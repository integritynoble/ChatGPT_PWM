"""
ChatGPT-PWM web service — FastAPI backend + embedded SPA frontend.

Generation is backed by an OpenAI ChatGPT subscription (OAuth tokens, the same
scheme Codex uses) — no per-token API key billing. Access is gated by a PWM key
and, when the PWM exchange is deployed, billed against the user's PWM balance.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, List, Optional, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

import openai_subscription as subscription
import pwm_billing

logger = logging.getLogger("chatgpt-pwm")

# Require a PWM key to use the service (set PWM_KEY_REQUIRED=0 to open access).
PWM_KEY_REQUIRED = os.environ.get("PWM_KEY_REQUIRED", "0") == "1"

AVAILABLE_MODELS = subscription.SUPPORTED_MODELS

app = FastAPI(title="ChatGPT-PWM", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str
    # str for plain text, or a list of parts ({type:"text",text} / {type:"image_url",image_url})
    content: Union[str, List[Any]]


class ChatRequest(BaseModel):
    messages: List[Message]
    model: str = subscription.DEFAULT_MODEL
    stream: bool = True
    web_search: bool = False
    image_gen: bool = False


# Image-input limits (data-URL length; base64 is ~1.33x the binary size).
MAX_IMAGES = 6
MAX_IMAGE_CHARS = 9_000_000  # ~6.7 MB binary


def _validate_images(messages: List[dict]) -> None:
    """Reject oversized / too-many image parts before hitting the backend."""
    count = 0
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("image_url", "image", "input_image"):
                count += 1
                url = part.get("image_url") or part.get("image") or part.get("url") or ""
                if isinstance(url, dict):
                    url = url.get("url", "")
                if isinstance(url, str) and len(url) > MAX_IMAGE_CHARS:
                    raise HTTPException(status_code=413, detail="Image too large (max ~6 MB each).")
    if count > MAX_IMAGES:
        raise HTTPException(status_code=413, detail=f"Too many images (max {MAX_IMAGES}).")


async def _stream_with_billing(
    pwm_key: Optional[str],
    messages: List[dict],
    model: str,
    web_search: bool = False,
    image_gen: bool = False,
) -> AsyncIterator[bytes]:
    """Stream from the subscription backend, then bill PWM tokens on completion.

    Diagnosability: failures here travel INSIDE a "200 OK" SSE stream and never
    show in access logs — so log in-stream error events, streams that end with
    no content (the UI's "No response." case), and mid-stream exceptions
    (surfaced to the client as an SSE error event instead of a dead stream).
    """
    prompt_tokens = completion_tokens = 0
    saw_content = False
    try:
        async for chunk in subscription.stream_chat(messages, model, web_search, image_gen):
            text = chunk.decode(errors="replace")
            if '"error":' in text:
                logger.error("chat in-stream error (model=%s): %s", model, text.strip()[:500])
            if '"content"' in text:
                saw_content = True
            # Capture usage from the final chunk for billing.
            if '"usage"' in text:
                for line in text.splitlines():
                    if line.startswith("data:"):
                        try:
                            obj = json.loads(line[5:].strip())
                            usage = obj.get("usage")
                            if usage:
                                prompt_tokens = usage.get("prompt_tokens", 0)
                                completion_tokens = usage.get("completion_tokens", 0)
                        except Exception:
                            pass
            yield chunk
    except (GeneratorExit, asyncio.CancelledError):
        raise  # client went away (stop/barge-in) — not an upstream failure
    except Exception as e:  # noqa: BLE001
        logger.error("chat stream aborted mid-stream (model=%s): %r", model, e)
        try:
            msg = f"Generation failed mid-stream: {e}"[:300]
            yield ("data: " + json.dumps({"error": {"message": msg}}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"
        except Exception:
            pass
        return
    if not saw_content:
        logger.warning(
            "chat stream ended with NO content (model=%s, web_search=%s, image_gen=%s)",
            model, web_search, image_gen,
        )
    # Best-effort billing — never blocks or fails the response.
    if pwm_key:
        await pwm_billing.charge(pwm_key, model, prompt_tokens, completion_tokens)


@app.post("/api/chat")
async def chat(req: Request, body: ChatRequest):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None

    if PWM_KEY_REQUIRED and not pwm_key:
        raise HTTPException(status_code=401, detail="Missing PWM key. Set X-PWM-Key header.")

    # Pre-flight: validate key + balance before serving (fails open on outage).
    if pwm_key:
        check = await pwm_billing.check_balance(pwm_key)
        if not check.valid:
            code = 402 if "balance" in check.reason.lower() else 401
            raise HTTPException(status_code=code, detail=check.reason)

    messages = [m.model_dump() for m in body.messages]
    _validate_images(messages)

    try:
        # Validate auth availability up front so errors surface as JSON, not a broken stream.
        await subscription.get_access_token()
    except subscription.SubscriptionAuthError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return StreamingResponse(
        _stream_with_billing(pwm_key, messages, body.model, body.web_search, body.image_gen),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/models")
async def models():
    return {"models": AVAILABLE_MODELS}


# ── Server-side sync (cross-device chat history) ─────────────────────────
# Per-item newest-wins merge keyed by the PWM key. Both live backends point
# at the same SQLite file (WAL), so the two public domains stay in sync too.

import hashlib
import sqlite3

SYNC_DB_PATH = os.environ.get(
    "CHATGPT_SYNC_DB", os.path.expanduser("~/pwm/chatgpt-sync/sync.db")
)
SYNC_KINDS = {"convo", "project", "gpt", "kv"}
SYNC_MAX_ITEM_BYTES = 400_000     # one chat / one kv blob
SYNC_MAX_TOTAL_BYTES = 8_000_000  # whole push
SYNC_MAX_ITEMS = 1200


def _sync_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SYNC_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SYNC_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS items(
            user TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
            ts INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, data TEXT,
            PRIMARY KEY(user, kind, id))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS shares(
            id TEXT PRIMARY KEY, user TEXT NOT NULL, convo_id TEXT NOT NULL,
            data TEXT NOT NULL, created INTEGER NOT NULL)"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS shares_user ON shares(user, convo_id)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, user TEXT NOT NULL, pwm_key TEXT,
            title TEXT NOT NULL, prompt TEXT NOT NULL, schedule TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            next_run INTEGER, last_run INTEGER, created INTEGER NOT NULL)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS tasks_user ON tasks(user)")
    conn.execute("CREATE INDEX IF NOT EXISTS tasks_due ON tasks(status, next_run)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS groups(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
            invite TEXT NOT NULL UNIQUE, ai_busy_until INTEGER,
            created INTEGER NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS group_members(
            group_id TEXT NOT NULL, user TEXT NOT NULL, name TEXT NOT NULL,
            joined INTEGER NOT NULL, PRIMARY KEY(group_id, user))"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS group_msgs(
            group_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL,
            author TEXT, author_user TEXT, content TEXT NOT NULL, ts INTEGER NOT NULL,
            PRIMARY KEY(group_id, seq))"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS gm_user ON group_members(user)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS files(
            id TEXT PRIMARY KEY, user TEXT NOT NULL, name TEXT NOT NULL,
            kind TEXT NOT NULL, content TEXT NOT NULL, size INTEGER NOT NULL,
            ts INTEGER NOT NULL, project TEXT)"""
    )
    # Migrate older DBs that created `files` before the project column existed.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(files)")]
    if "project" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN project TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS files_user ON files(user, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS files_proj ON files(user, project)")
    return conn


class SyncItem(BaseModel):
    kind: str
    id: str
    ts: int
    deleted: int = 0
    data: Optional[str] = None  # JSON-encoded payload; None for tombstones


class SyncRequest(BaseModel):
    items: List[SyncItem] = []


@app.post("/api/sync")
async def sync(req: Request, body: SyncRequest):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if not pwm_key:
        raise HTTPException(status_code=401, detail="Sync requires a PWM key.")
    check = await pwm_billing.check_balance(pwm_key)
    if not check.valid:
        raise HTTPException(status_code=401, detail=check.reason)
    user = hashlib.sha256(pwm_key.encode()).hexdigest()

    if len(body.items) > SYNC_MAX_ITEMS:
        raise HTTPException(status_code=413, detail="Too many sync items.")
    total = sum(len(it.data or "") for it in body.items)
    if total > SYNC_MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail="Sync payload too large.")

    conn = _sync_db()
    try:
        for it in body.items:
            if it.kind not in SYNC_KINDS or not it.id:
                continue
            if it.data and len(it.data) > SYNC_MAX_ITEM_BYTES:
                continue  # skip oversize items rather than failing the sync
            row = conn.execute(
                "SELECT ts FROM items WHERE user=? AND kind=? AND id=?",
                (user, it.kind, it.id),
            ).fetchone()
            if row is None or it.ts > row[0]:
                conn.execute(
                    "INSERT INTO items(user,kind,id,ts,deleted,data) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(user,kind,id) DO UPDATE SET "
                    "ts=excluded.ts, deleted=excluded.deleted, data=excluded.data",
                    (user, it.kind, it.id, it.ts, 1 if it.deleted else 0,
                     None if it.deleted else it.data),
                )
        conn.commit()
        rows = conn.execute(
            "SELECT kind,id,ts,deleted,data FROM items WHERE user=?", (user,)
        ).fetchall()
    finally:
        conn.close()

    return {
        "items": [
            {"kind": k, "id": i, "ts": t, "deleted": d, "data": (None if d else data)}
            for (k, i, t, d, data) in rows
        ]
    }


# ── Code interpreter (Docker-sandboxed Python execution) ─────────────────

import asyncio
import base64
import glob
import shutil
import subprocess
import tempfile
import uuid

from starlette.concurrency import run_in_threadpool

CI_IMAGE = os.environ.get("CHATGPT_CI_IMAGE", "chatgpt-pwm-ci:latest")
CI_TIMEOUT = int(os.environ.get("CHATGPT_CI_TIMEOUT", "30"))
CI_ENABLED = os.environ.get("CHATGPT_CI_ENABLED", "1") == "1"
CI_MAX_CODE = 100_000
CI_MAX_OUTPUT = 40_000
CI_MAX_IMAGES = 6
CI_MAX_IMAGE_BYTES = 4_000_000
_ci_sema = asyncio.Semaphore(int(os.environ.get("CHATGPT_CI_CONCURRENCY", "4")))


class RunRequest(BaseModel):
    code: str


def _run_sandboxed(code: str) -> dict:
    """Run Python in a locked-down, network-less Docker container. Blocking."""
    workdir = tempfile.mkdtemp(prefix="ci_")
    name = "ci_" + uuid.uuid4().hex[:12]
    try:
        os.chmod(workdir, 0o755)
        outdir = os.path.join(workdir, "out")
        os.makedirs(outdir, exist_ok=True)
        os.chmod(outdir, 0o777)
        script = os.path.join(workdir, "script.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(code)
        os.chmod(script, 0o644)

        cmd = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            "--memory", "512m", "--memory-swap", "512m",
            "--cpus", "1", "--pids-limit", "128",
            "--user", "65534:65534",
            "--read-only", "--tmpfs", "/tmp:size=64m,exec",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{workdir}:/work:rw", "-w", "/work",
            CI_IMAGE, "python", "/work/script.py",
        ]
        timed_out = False
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CI_TIMEOUT)
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            timed_out = True
            subprocess.run(["docker", "kill", name], capture_output=True)
            stdout = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            rc = -1

        images = []
        for p in sorted(glob.glob(os.path.join(outdir, "*"))):
            if len(images) >= CI_MAX_IMAGES:
                break
            low = p.lower()
            if not low.endswith((".png", ".jpg", ".jpeg", ".gif")):
                continue
            try:
                with open(p, "rb") as im:
                    raw = im.read()
                if len(raw) <= CI_MAX_IMAGE_BYTES:
                    mime = "image/png" if low.endswith(".png") else (
                        "image/gif" if low.endswith(".gif") else "image/jpeg")
                    images.append(f"data:{mime};base64," + base64.b64encode(raw).decode())
            except Exception:  # noqa: BLE001
                pass

        return {
            "stdout": stdout[:CI_MAX_OUTPUT],
            "stderr": stderr[:CI_MAX_OUTPUT],
            "images": images,
            "timed_out": timed_out,
            "exit_code": rc,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/api/run")
async def run_code(req: Request, body: RunRequest):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if PWM_KEY_REQUIRED and not pwm_key:
        raise HTTPException(status_code=401, detail="Missing PWM key. Set X-PWM-Key header.")
    if pwm_key:
        check = await pwm_billing.check_balance(pwm_key)
        if not check.valid:
            code = 402 if "balance" in check.reason.lower() else 401
            raise HTTPException(status_code=code, detail=check.reason)

    if not CI_ENABLED or shutil.which("docker") is None:
        raise HTTPException(status_code=503, detail="Code execution is not available on this server.")
    code = (body.code or "")[:CI_MAX_CODE]
    if not code.strip():
        raise HTTPException(status_code=400, detail="No code to run.")

    async with _ci_sema:
        return await run_in_threadpool(_run_sandboxed, code)


# ── Scheduled tasks (ChatGPT Tasks) ──────────────────────────────────────
# Tasks are created from chat (a [[task]] marker handled like other tools) and
# run server-side on a scheduler. Results are written into the user's sync
# store as a conversation ("⏰ <title>"), so they appear in the sidebar on the
# next sync pull — on any device. The PWM key is stored with the task so runs
# can be balance-checked and billed like interactive turns.

import asyncio
import datetime as _dt
import time as _time
import uuid as _uuid

TASK_TICK = int(os.environ.get("CHATGPT_TASK_TICK", "30"))
TASK_MAX_PER_USER = 10
TASK_MAX_OUTPUT = 20_000
TASK_TYPES = {"once", "daily", "weekly"}


class TaskCreateRequest(BaseModel):
    title: str
    prompt: str
    schedule: dict


class TaskPatchRequest(BaseModel):
    status: str


def _task_next_run(sched: dict, after_ms: int) -> Optional[int]:
    """Next run (epoch ms, UTC) strictly after `after_ms`; None when exhausted."""
    t = sched.get("type")
    if t == "once":
        at = int(sched.get("at") or 0)
        return at if at > after_ms else None
    tzmin = int(sched.get("tz") or 0)  # minutes to ADD to UTC for local wall time
    try:
        hh, mm = [int(x) for x in str(sched.get("time") or "09:00").split(":")[:2]]
    except ValueError:
        hh, mm = 9, 0
    local = _dt.datetime.fromtimestamp(after_ms / 1000, _dt.timezone.utc) + _dt.timedelta(minutes=tzmin)
    cand = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t == "weekly":
        day = int(sched.get("day") or 0)  # 0=Monday … 6=Sunday
        cand += _dt.timedelta(days=(day - cand.weekday()) % 7)
    step = _dt.timedelta(days=7 if t == "weekly" else 1)
    while cand <= local:
        cand += step
    return int((cand - _dt.timedelta(minutes=tzmin)).timestamp() * 1000)


def _task_auth_sync(req: Request):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if not pwm_key:
        raise HTTPException(status_code=401, detail="Tasks require a PWM key.")
    return hashlib.sha256(pwm_key.encode()).hexdigest(), pwm_key


def _task_row_public(r) -> dict:
    (tid, title, prompt, schedule, status, next_run, last_run, created) = r
    return {"id": tid, "title": title, "prompt": prompt,
            "schedule": json.loads(schedule), "status": status,
            "next_run": next_run, "last_run": last_run, "created": created}


@app.post("/api/tasks")
async def create_task(req: Request, body: TaskCreateRequest):
    user, pwm_key = _task_auth_sync(req)
    check = await pwm_billing.check_balance(pwm_key)
    if not check.valid:
        raise HTTPException(status_code=401, detail=check.reason)
    title = (body.title or "").strip()[:80]
    prompt = (body.prompt or "").strip()[:4000]
    sched = body.schedule or {}
    if not title or not prompt:
        raise HTTPException(status_code=400, detail="Task needs a title and a prompt.")
    if sched.get("type") not in TASK_TYPES:
        raise HTTPException(status_code=400, detail="Schedule type must be once, daily, or weekly.")
    now_ms = int(_time.time() * 1000)
    next_run = _task_next_run(sched, now_ms)
    if next_run is None:
        raise HTTPException(status_code=400, detail="That time is already in the past.")
    conn = _sync_db()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user=? AND status IN ('active','paused')", (user,)
        ).fetchone()[0]
        if count >= TASK_MAX_PER_USER:
            raise HTTPException(status_code=409, detail=f"Task limit reached ({TASK_MAX_PER_USER}). Delete one first.")
        tid = _uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO tasks(id,user,pwm_key,title,prompt,schedule,status,next_run,created) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (tid, user, pwm_key, title, prompt, json.dumps(sched), "active", next_run, now_ms))
        conn.commit()
    finally:
        conn.close()
    return {"id": tid, "title": title, "next_run": next_run, "status": "active"}


@app.get("/api/tasks")
async def list_tasks(req: Request):
    user, _ = _task_auth_sync(req)
    conn = _sync_db()
    try:
        rows = conn.execute(
            "SELECT id,title,prompt,schedule,status,next_run,last_run,created "
            "FROM tasks WHERE user=? ORDER BY created DESC", (user,)).fetchall()
    finally:
        conn.close()
    return {"tasks": [_task_row_public(r) for r in rows]}


@app.patch("/api/tasks/{tid}")
async def patch_task(req: Request, tid: str, body: TaskPatchRequest):
    user, _ = _task_auth_sync(req)
    if body.status not in ("active", "paused"):
        raise HTTPException(status_code=400, detail="Status must be active or paused.")
    conn = _sync_db()
    try:
        row = conn.execute("SELECT user, schedule FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No such task.")
        if row[0] != user:
            raise HTTPException(status_code=403, detail="Not your task.")
        next_run = None
        if body.status == "active":
            next_run = _task_next_run(json.loads(row[1]), int(_time.time() * 1000))
            if next_run is None:
                raise HTTPException(status_code=400, detail="This one-time task is already in the past.")
        conn.execute("UPDATE tasks SET status=?, next_run=? WHERE id=?",
                     (body.status, next_run, tid))
        conn.commit()
    finally:
        conn.close()
    return {"id": tid, "status": body.status}


@app.delete("/api/tasks/{tid}")
async def delete_task(req: Request, tid: str):
    user, _ = _task_auth_sync(req)
    conn = _sync_db()
    try:
        row = conn.execute("SELECT user FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No such task.")
        if row[0] != user:
            raise HTTPException(status_code=403, detail="Not your task.")
        conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        conn.commit()
    finally:
        conn.close()
    return {"deleted": tid}


def _append_task_result(user: str, tid: str, title: str, prompt: str, text: str) -> None:
    """Write a run's output into the user's sync store as a '⏰ <title>' conversation."""
    cid = f"task_{tid}"
    now_ms = int(_time.time() * 1000)
    conn = _sync_db()
    try:
        row = conn.execute(
            "SELECT data FROM items WHERE user=? AND kind='convo' AND id=? AND deleted=0",
            (user, cid)).fetchone()
        convo = None
        if row:
            try:
                convo = json.loads(row[0])
            except Exception:  # noqa: BLE001
                convo = None
        if not convo:
            convo = {"id": cid, "title": ("⏰ " + title)[:48], "taskId": tid,
                     "messages": [{"role": "user", "content": prompt, "ts": now_ms}], "ts": now_ms}
        convo.setdefault("messages", []).append(
            {"role": "assistant", "variants": [{"content": text, "ts": now_ms}], "vi": 0})
        convo["ts"] = now_ms
        convo["taskId"] = tid
        conn.execute(
            "INSERT INTO items(user,kind,id,ts,deleted,data) VALUES(?,?,?,?,0,?) "
            "ON CONFLICT(user,kind,id) DO UPDATE SET ts=excluded.ts, deleted=0, data=excluded.data",
            (user, "convo", cid, now_ms, json.dumps(convo)))
        conn.commit()
    finally:
        conn.close()


async def _run_task(tid: str, user: str, pwm_key: Optional[str], title: str, prompt: str) -> None:
    try:
        if pwm_key:
            check = await pwm_billing.check_balance(pwm_key)
            if not check.valid:  # invalid key / no balance → pause instead of burning runs
                conn = _sync_db()
                try:
                    conn.execute("UPDATE tasks SET status='paused', next_run=NULL WHERE id=?", (tid,))
                    conn.commit()
                finally:
                    conn.close()
                _append_task_result(user, tid, title, prompt,
                                    "⚠️ Task paused: " + (check.reason or "PWM key/balance check failed."))
                return
        # Give the run the user's memories + custom instructions from the sync store.
        msgs = []
        conn = _sync_db()
        try:
            kv = dict(conn.execute(
                "SELECT id, data FROM items WHERE user=? AND kind='kv' AND deleted=0", (user,)).fetchall())
        finally:
            conn.close()
        try:
            mem = json.loads(kv.get("memories") or "{}")
            if not mem.get("off") and mem.get("list"):
                msgs.append({"role": "system", "content": "Known facts about the user:\n" +
                             "\n".join("- " + (m.get("text") or "") for m in mem["list"][-50:])})
        except Exception:  # noqa: BLE001
            pass
        try:
            ci = json.loads(kv.get("ci") or "{}")
            parts = []
            if ci.get("about"):
                parts.append("About the user:\n" + ci["about"])
            if ci.get("style"):
                parts.append("How the user wants responses:\n" + ci["style"])
            if parts:
                msgs.append({"role": "system", "content": "\n\n".join(parts)})
        except Exception:  # noqa: BLE001
            pass
        now_str = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        msgs.append({"role": "system", "content":
                     f"This is the automated scheduled task {title!r} running at {now_str}. "
                     "Produce the deliverable directly — no preamble about being a scheduled task."})
        msgs.append({"role": "user", "content": prompt})

        full = ""
        ptoks = ctoks = 0
        async for chunk in subscription.stream_chat(msgs, subscription.DEFAULT_MODEL, False, False):
            for line in chunk.decode(errors="replace").splitlines():
                if not line.startswith("data:"):
                    continue
                d = line[5:].strip()
                if not d or d == "[DONE]":
                    continue
                try:
                    obj = json.loads(d)
                except Exception:  # noqa: BLE001
                    continue
                delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    full += delta
                usage = obj.get("usage")
                if usage:
                    ptoks = usage.get("prompt_tokens", 0)
                    ctoks = usage.get("completion_tokens", 0)
        _append_task_result(user, tid, title, prompt, full.strip()[:TASK_MAX_OUTPUT] or "(no output)")
        if pwm_key and (ptoks or ctoks):
            await pwm_billing.charge(pwm_key, subscription.DEFAULT_MODEL, ptoks, ctoks)
    except Exception as e:  # noqa: BLE001
        try:
            _append_task_result(user, tid, title, prompt,
                                f"⚠️ Task run failed: {type(e).__name__}: {str(e)[:200]}")
        except Exception:  # noqa: BLE001
            pass


async def _task_scheduler() -> None:
    """Claim-and-run loop. Every worker/backend runs one; the atomic UPDATE on
    next_run guarantees each due task fires exactly once across all of them."""
    while True:
        try:
            await asyncio.sleep(TASK_TICK)
            now_ms = int(_time.time() * 1000)
            conn = _sync_db()
            claimed = []
            try:
                rows = conn.execute(
                    "SELECT id,user,pwm_key,title,prompt,schedule FROM tasks "
                    "WHERE status='active' AND next_run IS NOT NULL AND next_run<=?",
                    (now_ms,)).fetchall()
                for (tid, user, key, title, prompt, sched_json) in rows:
                    try:
                        nxt = _task_next_run(json.loads(sched_json), now_ms)
                    except Exception:  # noqa: BLE001
                        nxt = None
                    cur = conn.execute(
                        "UPDATE tasks SET last_run=?, next_run=?, status=? WHERE id=? AND next_run<=?",
                        (now_ms, nxt, ("active" if nxt else "done"), tid, now_ms))
                    if cur.rowcount == 1:
                        claimed.append((tid, user, key, title, prompt))
                conn.commit()
            finally:
                conn.close()
            for c in claimed:
                asyncio.create_task(_run_task(*c))
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            pass  # never let the scheduler die


@app.on_event("startup")
async def _start_task_scheduler():
    asyncio.create_task(_task_scheduler())


# ── Persistent file library ──────────────────────────────────────────────
# Files uploaded once and reusable across any conversation, stored server-side
# (in the shared DB) so they follow the user across devices. Text files hold
# their extracted text; images hold a data URL. The client attaches a stored
# file to a chat exactly like a fresh upload.

FILES_MAX_COUNT = 100
FILES_MAX_ONE = 8_000_000          # one file (data-URL images run large)
FILES_MAX_TOTAL = 60_000_000       # per user
PROJECT_MAX_FILES = 40             # ChatGPT's per-project cap
PROJECT_CTX_MAX = 200_000          # cap the text injected into a project chat


class FileUploadRequest(BaseModel):
    name: str
    kind: str                      # "text" | "image"
    content: str                   # extracted text, or a data: URL for images
    project: Optional[str] = None  # None → general library; else project id


def _files_auth(req: Request):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if not pwm_key:
        raise HTTPException(status_code=401, detail="File library requires a PWM key.")
    return hashlib.sha256(pwm_key.encode()).hexdigest()


@app.post("/api/files")
async def file_upload(req: Request, body: FileUploadRequest):
    user = _files_auth(req)
    name = (body.name or "file").strip()[:200]
    kind = body.kind if body.kind in ("text", "image") else "text"
    content = body.content or ""
    if not content.strip():
        raise HTTPException(status_code=400, detail="Empty file.")
    size = len(content)
    if size > FILES_MAX_ONE:
        raise HTTPException(status_code=413, detail="File too large (max ~8 MB).")
    project = (body.project or "").strip() or None
    conn = _sync_db()
    try:
        count, total = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size),0) FROM files WHERE user=?", (user,)).fetchone()
        if count >= FILES_MAX_COUNT:
            raise HTTPException(status_code=409, detail=f"Library is full ({FILES_MAX_COUNT} files). Delete some first.")
        if total + size > FILES_MAX_TOTAL:
            raise HTTPException(status_code=413, detail="Library storage is full. Delete some files first.")
        if project:
            pcount = conn.execute(
                "SELECT COUNT(*) FROM files WHERE user=? AND project=?", (user, project)).fetchone()[0]
            if pcount >= PROJECT_MAX_FILES:
                raise HTTPException(status_code=409, detail=f"This project already has {PROJECT_MAX_FILES} files (the max).")
        fid = _uuid.uuid4().hex[:16]
        now_ms = int(_time.time() * 1000)
        conn.execute(
            "INSERT INTO files(id,user,name,kind,content,size,ts,project) VALUES(?,?,?,?,?,?,?,?)",
            (fid, user, name, kind, content, size, now_ms, project))
        conn.commit()
    finally:
        conn.close()
    return {"id": fid, "name": name, "kind": kind, "size": size, "ts": now_ms, "project": project}


@app.get("/api/files")
async def file_list(req: Request, project: Optional[str] = None):
    user = _files_auth(req)
    conn = _sync_db()
    try:
        if project:
            rows = conn.execute(
                "SELECT id,name,kind,size,ts FROM files WHERE user=? AND project=? ORDER BY ts DESC",
                (user, project)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,name,kind,size,ts FROM files WHERE user=? AND project IS NULL ORDER BY ts DESC",
                (user,)).fetchall()
    finally:
        conn.close()
    return {"files": [{"id": r[0], "name": r[1], "kind": r[2], "size": r[3], "ts": r[4]} for r in rows]}


@app.get("/api/project-files/{pid}")
async def project_files_content(req: Request, pid: str):
    """Project files WITH text content, for injecting as context into project chats."""
    user = _files_auth(req)
    conn = _sync_db()
    try:
        rows = conn.execute(
            "SELECT name,kind,content FROM files WHERE user=? AND project=? ORDER BY ts", (user, pid)).fetchall()
    finally:
        conn.close()
    out = []
    budget = PROJECT_CTX_MAX
    for (name, kind, content) in rows:
        if kind != "text":
            out.append({"name": name, "kind": kind, "content": ""})
            continue
        chunk = content[:budget]
        budget -= len(chunk)
        out.append({"name": name, "kind": "text", "content": chunk})
        if budget <= 0:
            break
    return {"files": out}


@app.get("/api/files/{fid}")
async def file_get(req: Request, fid: str):
    user = _files_auth(req)
    conn = _sync_db()
    try:
        row = conn.execute(
            "SELECT name,kind,content FROM files WHERE id=? AND user=?", (fid, user)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No such file.")
    return {"id": fid, "name": row[0], "kind": row[1], "content": row[2]}


@app.delete("/api/files/{fid}")
async def file_delete(req: Request, fid: str):
    user = _files_auth(req)
    conn = _sync_db()
    try:
        row = conn.execute("SELECT user FROM files WHERE id=?", (fid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No such file.")
        if row[0] != user:
            raise HTTPException(status_code=403, detail="Not your file.")
        conn.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
    finally:
        conn.close()
    return {"deleted": fid}


# ── Group chats ───────────────────────────────────────────────────────────
# Unlike personal chats (client-side + sync), a group chat is one canonical
# server-side conversation shared by up to 20 PWM users. Members join via an
# invite link (/g/<token>) with a display name; clients poll for messages.
# ChatGPT replies when mentioned (@chatgpt); generation is claimed atomically
# so only one worker/backend answers, and is billed to the summoner's key.

import re as _re
import secrets

GROUP_MAX_MEMBERS = 20
GROUP_MSG_MAX = 8_000
GROUP_FETCH_WINDOW = 200
GROUP_AI_CONTEXT = 40
_GROUP_SUMMON_RE = _re.compile(r"(^|\W)@?(chatgpt|gpt|ai)(\W|$)", _re.I)


class GroupCreateRequest(BaseModel):
    title: str
    name: str          # creator's display name in the group


class GroupJoinRequest(BaseModel):
    name: str


class GroupMessageRequest(BaseModel):
    content: str


def _group_auth(req: Request):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if not pwm_key:
        raise HTTPException(status_code=401, detail="Group chats require a PWM key.")
    return hashlib.sha256(pwm_key.encode()).hexdigest(), pwm_key


def _group_member(conn, gid: str, user: str) -> Optional[str]:
    row = conn.execute(
        "SELECT name FROM group_members WHERE group_id=? AND user=?", (gid, user)
    ).fetchone()
    return row[0] if row else None


def _group_info(conn, gid: str, user: str) -> dict:
    g = conn.execute(
        "SELECT id,title,owner,invite,ai_busy_until,created FROM groups WHERE id=?", (gid,)
    ).fetchone()
    if not g:
        raise HTTPException(status_code=404, detail="No such group.")
    members = [r[0] for r in conn.execute(
        "SELECT name FROM group_members WHERE group_id=? ORDER BY joined", (gid,)).fetchall()]
    last = conn.execute(
        "SELECT MAX(seq), MAX(ts) FROM group_msgs WHERE group_id=?", (gid,)).fetchone()
    return {"id": g[0], "title": g[1], "invite": g[3], "members": members,
            "me": _group_member(conn, gid, user),
            "is_owner": g[2] == user, "last_seq": last[0] or 0, "last_ts": last[1] or g[5],
            "typing": bool(g[4] and g[4] > int(_time.time() * 1000))}


@app.post("/api/groups")
async def group_create(req: Request, body: GroupCreateRequest):
    user, pwm_key = _group_auth(req)
    check = await pwm_billing.check_balance(pwm_key)
    if not check.valid:
        raise HTTPException(status_code=401, detail=check.reason)
    title = (body.title or "").strip()[:60] or "Group chat"
    name = (body.name or "").strip()[:40] or "Member"
    gid = _uuid.uuid4().hex[:12]
    now_ms = int(_time.time() * 1000)
    conn = _sync_db()
    try:
        conn.execute("INSERT INTO groups(id,title,owner,invite,created) VALUES(?,?,?,?,?)",
                     (gid, title, user, secrets.token_urlsafe(12), now_ms))
        conn.execute("INSERT INTO group_members(group_id,user,name,joined) VALUES(?,?,?,?)",
                     (gid, user, name, now_ms))
        conn.commit()
        info = _group_info(conn, gid, user)
    finally:
        conn.close()
    return info


@app.get("/api/groups")
async def group_list(req: Request):
    user, _ = _group_auth(req)
    conn = _sync_db()
    try:
        gids = [r[0] for r in conn.execute(
            "SELECT group_id FROM group_members WHERE user=?", (user,)).fetchall()]
        out = [_group_info(conn, g, user) for g in gids]
    finally:
        conn.close()
    out.sort(key=lambda g: -(g["last_ts"] or 0))
    for g in out:
        g.pop("invite", None)   # invite links only via the detail endpoint
    return {"groups": out}


@app.get("/api/group/{gid}")
async def group_detail(req: Request, gid: str):
    user, _ = _group_auth(req)
    conn = _sync_db()
    try:
        if not _group_member(conn, gid, user):
            raise HTTPException(status_code=403, detail="Not a member of this group.")
        return _group_info(conn, gid, user)
    finally:
        conn.close()


@app.get("/api/group-invite/{token}")
async def group_invite_info(token: str):
    """Public: what a visitor sees before joining."""
    conn = _sync_db()
    try:
        g = conn.execute("SELECT id,title FROM groups WHERE invite=?", (token,)).fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="This invite link is invalid.")
        members = [r[0] for r in conn.execute(
            "SELECT name FROM group_members WHERE group_id=? ORDER BY joined", (g[0],)).fetchall()]
    finally:
        conn.close()
    return {"title": g[1], "members": members}


@app.post("/api/group-join/{token}")
async def group_join(req: Request, token: str, body: GroupJoinRequest):
    user, pwm_key = _group_auth(req)
    check = await pwm_billing.check_balance(pwm_key)
    if not check.valid:
        raise HTTPException(status_code=401, detail=check.reason)
    name = (body.name or "").strip()[:40] or "Member"
    now_ms = int(_time.time() * 1000)
    conn = _sync_db()
    try:
        g = conn.execute("SELECT id FROM groups WHERE invite=?", (token,)).fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="This invite link is invalid.")
        gid = g[0]
        if _group_member(conn, gid, user):
            return _group_info(conn, gid, user)   # already in — idempotent
        count = conn.execute(
            "SELECT COUNT(*) FROM group_members WHERE group_id=?", (gid,)).fetchone()[0]
        if count >= GROUP_MAX_MEMBERS:
            raise HTTPException(status_code=409, detail=f"This group is full ({GROUP_MAX_MEMBERS} members).")
        conn.execute("INSERT INTO group_members(group_id,user,name,joined) VALUES(?,?,?,?)",
                     (gid, user, name, now_ms))
        seq = (conn.execute("SELECT MAX(seq) FROM group_msgs WHERE group_id=?", (gid,)).fetchone()[0] or 0) + 1
        conn.execute(
            "INSERT INTO group_msgs(group_id,seq,role,author,author_user,content,ts) VALUES(?,?,?,?,?,?,?)",
            (gid, seq, "system", None, None, f"{name} joined the group", now_ms))
        conn.commit()
        return _group_info(conn, gid, user)
    finally:
        conn.close()


@app.post("/api/group/{gid}/leave")
async def group_leave(req: Request, gid: str):
    user, _ = _group_auth(req)
    now_ms = int(_time.time() * 1000)
    conn = _sync_db()
    try:
        name = _group_member(conn, gid, user)
        if not name:
            raise HTTPException(status_code=403, detail="Not a member of this group.")
        conn.execute("DELETE FROM group_members WHERE group_id=? AND user=?", (gid, user))
        remaining = conn.execute(
            "SELECT COUNT(*) FROM group_members WHERE group_id=?", (gid,)).fetchone()[0]
        if remaining == 0:
            conn.execute("DELETE FROM groups WHERE id=?", (gid,))
            conn.execute("DELETE FROM group_msgs WHERE group_id=?", (gid,))
        else:
            seq = (conn.execute("SELECT MAX(seq) FROM group_msgs WHERE group_id=?", (gid,)).fetchone()[0] or 0) + 1
            conn.execute(
                "INSERT INTO group_msgs(group_id,seq,role,author,author_user,content,ts) VALUES(?,?,?,?,?,?,?)",
                (gid, seq, "system", None, None, f"{name} left the group", now_ms))
        conn.commit()
    finally:
        conn.close()
    return {"left": gid}


@app.get("/api/group/{gid}/messages")
async def group_messages(req: Request, gid: str, after: int = 0):
    user, _ = _group_auth(req)
    conn = _sync_db()
    try:
        if not _group_member(conn, gid, user):
            raise HTTPException(status_code=403, detail="Not a member of this group.")
        rows = conn.execute(
            "SELECT seq,role,author,content,ts FROM group_msgs "
            "WHERE group_id=? AND seq>? ORDER BY seq LIMIT ?",
            (gid, after, GROUP_FETCH_WINDOW)).fetchall()
        info = _group_info(conn, gid, user)
    finally:
        conn.close()
    return {"messages": [{"seq": r[0], "role": r[1], "author": r[2], "content": r[3], "ts": r[4]}
                         for r in rows],
            "typing": info["typing"], "members": info["members"], "title": info["title"]}


async def _group_ai_reply(gid: str, pwm_key: str) -> None:
    """Generate ChatGPT's reply to a group; the caller already claimed the lock."""
    try:
        conn = _sync_db()
        try:
            g = conn.execute("SELECT title FROM groups WHERE id=?", (gid,)).fetchone()
            members = [r[0] for r in conn.execute(
                "SELECT name FROM group_members WHERE group_id=? ORDER BY joined", (gid,)).fetchall()]
            rows = conn.execute(
                "SELECT role,author,content FROM group_msgs WHERE group_id=? "
                "ORDER BY seq DESC LIMIT ?", (gid, GROUP_AI_CONTEXT)).fetchall()
        finally:
            conn.close()
        rows.reverse()
        msgs = [{"role": "system", "content":
                 f"You are ChatGPT participating in a group chat titled {g[0]!r} with members: "
                 + ", ".join(members) +
                 ". Each user message is prefixed with the sender's name. Reply naturally to the "
                 "conversation, addressing people by name when helpful. Keep replies concise and "
                 "conversational — this is a group discussion, not an essay."}]
        for (role, author, content) in rows:
            if role == "assistant":
                msgs.append({"role": "assistant", "content": content})
            elif role == "user":
                msgs.append({"role": "user", "content": f"{author or 'Someone'}: {content}"})
        full = ""
        ptoks = ctoks = 0
        async for chunk in subscription.stream_chat(msgs, subscription.DEFAULT_MODEL, False, False):
            for line in chunk.decode(errors="replace").splitlines():
                if not line.startswith("data:"):
                    continue
                d = line[5:].strip()
                if not d or d == "[DONE]":
                    continue
                try:
                    obj = json.loads(d)
                except Exception:  # noqa: BLE001
                    continue
                delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    full += delta
                usage = obj.get("usage")
                if usage:
                    ptoks = usage.get("prompt_tokens", 0)
                    ctoks = usage.get("completion_tokens", 0)
        full = full.strip()[:GROUP_MSG_MAX] or "(no response)"
        now_ms = int(_time.time() * 1000)
        conn = _sync_db()
        try:
            seq = (conn.execute("SELECT MAX(seq) FROM group_msgs WHERE group_id=?", (gid,)).fetchone()[0] or 0) + 1
            conn.execute(
                "INSERT INTO group_msgs(group_id,seq,role,author,author_user,content,ts) VALUES(?,?,?,?,?,?,?)",
                (gid, seq, "assistant", "ChatGPT", None, full, now_ms))
            conn.execute("UPDATE groups SET ai_busy_until=NULL WHERE id=?", (gid,))
            conn.commit()
        finally:
            conn.close()
        if pwm_key and (ptoks or ctoks):
            await pwm_billing.charge(pwm_key, subscription.DEFAULT_MODEL, ptoks, ctoks)
    except Exception:  # noqa: BLE001
        conn = _sync_db()
        try:
            conn.execute("UPDATE groups SET ai_busy_until=NULL WHERE id=?", (gid,))
            conn.commit()
        finally:
            conn.close()


@app.post("/api/group/{gid}/messages")
async def group_send(req: Request, gid: str, body: GroupMessageRequest):
    user, pwm_key = _group_auth(req)
    content = (body.content or "").strip()[:GROUP_MSG_MAX]
    if not content:
        raise HTTPException(status_code=400, detail="Empty message.")
    now_ms = int(_time.time() * 1000)
    conn = _sync_db()
    try:
        name = _group_member(conn, gid, user)
        if not name:
            raise HTTPException(status_code=403, detail="Not a member of this group.")
        seq = (conn.execute("SELECT MAX(seq) FROM group_msgs WHERE group_id=?", (gid,)).fetchone()[0] or 0) + 1
        conn.execute(
            "INSERT INTO group_msgs(group_id,seq,role,author,author_user,content,ts) VALUES(?,?,?,?,?,?,?)",
            (gid, seq, "user", name, user, content, now_ms))
        summoned = bool(_GROUP_SUMMON_RE.search(content))
        claimed = False
        if summoned:
            check = await pwm_billing.check_balance(pwm_key)
            if check.valid:
                cur = conn.execute(
                    "UPDATE groups SET ai_busy_until=? WHERE id=? AND "
                    "(ai_busy_until IS NULL OR ai_busy_until<?)",
                    (now_ms + 120_000, gid, now_ms))
                claimed = cur.rowcount == 1
        conn.commit()
    finally:
        conn.close()
    if claimed:
        asyncio.create_task(_group_ai_reply(gid, pwm_key))
    return {"seq": seq, "ai": claimed}


@app.get("/g/{token}", response_class=HTMLResponse)
async def group_invite_page(token: str):
    # The SPA detects /g/<token> and shows the join screen.
    return _INDEX_FILE.read_text(encoding="utf-8")


# ── Connectors (server-side proxy: GitHub, Finances) ─────────────────────
# Token-light by design: GitHub works unauthenticated for public data (a
# user-supplied PAT unlocks code search / private repos and higher limits);
# Finances uses Yahoo's public chart API. Tokens are passed per-request from
# the client and never stored server-side.

import httpx

CONN_TIMEOUT = 15
CONN_MAX_FILE = 50_000
_YF_HEADERS = {"User-Agent": "Mozilla/5.0 (chatgpt-pwm connector)"}


class ConnectorRequest(BaseModel):
    service: str
    action: str
    params: dict = {}
    token: Optional[str] = None


def _gh_headers(token: Optional[str]) -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "chatgpt-pwm-connector"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _connector_github(action: str, p: dict, token: Optional[str]) -> dict:
    async with httpx.AsyncClient(timeout=CONN_TIMEOUT, headers=_gh_headers(token)) as cx:
        if action == "search_repos":
            r = await cx.get("https://api.github.com/search/repositories",
                             params={"q": p.get("q", ""), "per_page": 5})
            r.raise_for_status()
            return {"repos": [{"repo": it["full_name"], "stars": it["stargazers_count"],
                               "description": (it.get("description") or "")[:200],
                               "url": it["html_url"]} for it in r.json().get("items", [])]}
        if action == "repo_info":
            r = await cx.get(f"https://api.github.com/repos/{p.get('repo','')}")
            r.raise_for_status()
            it = r.json()
            return {"repo": it["full_name"], "description": it.get("description"),
                    "stars": it["stargazers_count"], "forks": it["forks_count"],
                    "open_issues": it["open_issues_count"], "language": it.get("language"),
                    "default_branch": it.get("default_branch"), "url": it["html_url"]}
        if action == "read_file":
            r = await cx.get(f"https://api.github.com/repos/{p.get('repo','')}/contents/{p.get('path','')}",
                             params=({"ref": p["ref"]} if p.get("ref") else None))
            r.raise_for_status()
            it = r.json()
            if isinstance(it, list):
                return {"directory": [e["name"] + ("/" if e["type"] == "dir" else "") for e in it][:100]}
            content = base64.b64decode(it.get("content", "") or "").decode(errors="replace")
            truncated = len(content) > CONN_MAX_FILE
            return {"path": it.get("path"), "content": content[:CONN_MAX_FILE], "truncated": truncated}
        if action == "list_issues":
            r = await cx.get(f"https://api.github.com/repos/{p.get('repo','')}/issues",
                             params={"state": p.get("state", "open"), "per_page": 10})
            r.raise_for_status()
            return {"issues": [{"number": it["number"], "title": it["title"], "state": it["state"],
                                "user": it["user"]["login"], "is_pr": "pull_request" in it}
                               for it in r.json()]}
        if action == "search_code":
            if not token:
                return {"error": "GitHub code search requires a personal access token (add one in Settings → Connectors)."}
            r = await cx.get("https://api.github.com/search/code",
                             params={"q": p.get("q", ""), "per_page": 5})
            r.raise_for_status()
            return {"matches": [{"repo": it["repository"]["full_name"], "path": it["path"],
                                 "url": it["html_url"]} for it in r.json().get("items", [])]}
    return {"error": f"Unknown github action '{action}'."}


async def _connector_finance(action: str, p: dict) -> dict:
    symbol = (p.get("symbol") or "").upper().strip()
    if not symbol:
        return {"error": "Missing symbol."}
    rng = {"quote": "5d", "history": p.get("range", "6mo")}.get(action, "5d")
    async with httpx.AsyncClient(timeout=CONN_TIMEOUT, headers=_YF_HEADERS) as cx:
        r = await cx.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                         params={"range": rng, "interval": "1d" if action == "history" else "1d"})
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        meta = res["meta"]
        if action == "quote":
            return {"symbol": meta.get("symbol"), "price": meta.get("regularMarketPrice"),
                    "currency": meta.get("currency"), "previous_close": meta.get("chartPreviousClose"),
                    "exchange": meta.get("exchangeName"),
                    "day_high": meta.get("regularMarketDayHigh"), "day_low": meta.get("regularMarketDayLow")}
        ts = res.get("timestamp", [])
        closes = res["indicators"]["quote"][0].get("close", [])
        import datetime as _dt
        hist = [{"date": _dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), "close": round(c, 4)}
                for t, c in zip(ts, closes) if c is not None][-120:]
        return {"symbol": meta.get("symbol"), "currency": meta.get("currency"), "history": hist}
    return {"error": f"Unknown finance action '{action}'."}


@app.post("/api/connector")
async def connector(req: Request, body: ConnectorRequest):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if PWM_KEY_REQUIRED and not pwm_key:
        raise HTTPException(status_code=401, detail="Missing PWM key. Set X-PWM-Key header.")
    if pwm_key:
        check = await pwm_billing.check_balance(pwm_key)
        if not check.valid:
            code = 402 if "balance" in check.reason.lower() else 401
            raise HTTPException(status_code=code, detail=check.reason)

    try:
        if body.service == "github":
            result = await _connector_github(body.action, body.params or {}, body.token)
        elif body.service == "finance":
            result = await _connector_finance(body.action, body.params or {})
        else:
            return {"ok": False, "error": f"Unknown service '{body.service}'."}
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", "")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"{body.service} API error {e.response.status_code}: {detail or e.response.reason_phrase}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Connector failed: {type(e).__name__}"}
    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "result": result}


# ── Hosted share links (public read-only chat snapshots) ─────────────────

import secrets
import time as _time


def _share_auth(req: Request):
    """Require a PWM key; returns (user_hash, key) for share create/list/delete."""
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if not pwm_key:
        raise HTTPException(status_code=401, detail="Sharing requires a PWM key.")
    return hashlib.sha256(pwm_key.encode()).hexdigest(), pwm_key


class ShareRequest(BaseModel):
    convo: dict | None = None
    gpt: dict | None = None


@app.post("/api/share")
async def create_share(req: Request, body: ShareRequest):
    user, pwm_key = _share_auth(req)
    check = await pwm_billing.check_balance(pwm_key)
    if not check.valid:
        raise HTTPException(status_code=401, detail=check.reason)
    # A GPT share carries its config under a "_gpt" wrapper in the same store.
    if body.gpt is not None:
        gid = str(body.gpt.get("id") or "")
        if not gid or not body.gpt.get("name"):
            raise HTTPException(status_code=400, detail="Nothing to share.")
        convo_id = "gpt:" + gid
        payload = {"_gpt": body.gpt}
    elif body.convo is not None and body.convo.get("id") and body.convo.get("messages"):
        convo_id = str(body.convo.get("id"))
        payload = body.convo
    else:
        raise HTTPException(status_code=400, detail="Nothing to share.")
    data = json.dumps(payload)
    if len(data) > SYNC_MAX_ITEM_BYTES:
        raise HTTPException(status_code=413, detail="Conversation too large to share.")
    conn = _sync_db()
    try:
        # Re-sharing the same chat updates the existing link (ChatGPT's "Update link").
        row = conn.execute(
            "SELECT id FROM shares WHERE user=? AND convo_id=?", (user, convo_id)
        ).fetchone()
        sid = row[0] if row else secrets.token_urlsafe(12)
        conn.execute(
            "INSERT INTO shares(id,user,convo_id,data,created) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, created=excluded.created",
            (sid, user, convo_id, data, int(_time.time() * 1000)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": sid, "url": f"/share/{sid}"}


@app.get("/api/share/{sid}")
async def get_share(sid: str):
    conn = _sync_db()
    try:
        row = conn.execute(
            "SELECT data, created FROM shares WHERE id=?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Shared link not found.")
    return {"convo": json.loads(row[0]), "created": row[1]}


@app.get("/api/shares")
async def list_shares(req: Request):
    user, _ = _share_auth(req)
    conn = _sync_db()
    try:
        rows = conn.execute(
            "SELECT id, convo_id, created, data FROM shares WHERE user=? ORDER BY created DESC",
            (user,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for (sid, cid, created, data) in rows:
        try:
            title = json.loads(data).get("title") or "Untitled"
        except Exception:
            title = "Untitled"
        out.append({"id": sid, "convo_id": cid, "created": created, "title": title})
    return {"shares": out}


@app.delete("/api/share/{sid}")
async def delete_share(req: Request, sid: str):
    user, _ = _share_auth(req)
    conn = _sync_db()
    try:
        row = conn.execute("SELECT user FROM shares WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Shared link not found.")
        if row[0] != user:
            raise HTTPException(status_code=403, detail="Not your shared link.")
        conn.execute("DELETE FROM shares WHERE id=?", (sid,))
        conn.commit()
    finally:
        conn.close()
    return {"deleted": sid}


@app.get("/share/{sid}", response_class=HTMLResponse)
async def share_page(sid: str):
    # The SPA detects /share/<id> and renders the read-only shared view.
    return _INDEX_FILE.read_text(encoding="utf-8")


# ── Text-to-speech (neural voices via edge-tts; used by voice mode / read-aloud) ──

try:
    import edge_tts as _edge_tts
except ImportError:  # endpoint degrades to 503; the UI falls back to browser TTS
    _edge_tts = None

TTS_VOICES = {
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-US-AriaNeural",
    "en-GB-SoniaNeural",
}
TTS_DEFAULT_VOICE = "en-US-JennyNeural"
TTS_MAX_CHARS = 6000


class TTSRequest(BaseModel):
    text: str
    voice: str = TTS_DEFAULT_VOICE


@app.post("/api/tts")
async def tts(req: Request, body: TTSRequest):
    if _edge_tts is None:
        raise HTTPException(status_code=503, detail="TTS engine not available on the server.")

    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if PWM_KEY_REQUIRED and not pwm_key:
        raise HTTPException(status_code=401, detail="Missing PWM key. Set X-PWM-Key header.")
    if pwm_key:
        check = await pwm_billing.check_balance(pwm_key)
        if not check.valid:
            code = 402 if "balance" in check.reason.lower() else 401
            raise HTTPException(status_code=code, detail=check.reason)

    text = body.text.strip()[:TTS_MAX_CHARS]
    if not text:
        raise HTTPException(status_code=400, detail="No text to speak.")
    voice = body.voice if body.voice in TTS_VOICES else TTS_DEFAULT_VOICE

    async def gen() -> AsyncIterator[bytes]:
        communicate = _edge_tts.Communicate(text, voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(
        gen(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/balance")
async def balance(req: Request):
    pwm_key = (
        req.headers.get("X-PWM-Key")
        or req.headers.get("Authorization", "").removeprefix("Bearer ")
    ).strip() or None
    if not pwm_key:
        return {"valid": False, "reason": "No PWM key provided."}
    check = await pwm_billing.check_balance(pwm_key)
    return {"valid": check.valid, "balance": check.balance, "reason": check.reason}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ChatGPT logomark favicon (app-icon: white mark on a black rounded square).
# Served as a real file so browsers render it as the tab icon reliably
# (SVG data-URI favicons are flaky across browsers/Cloudflare).
_FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
    "<rect width='24' height='24' rx='5' fill='#000'/>"
    "<g transform='translate(3.5 3.5) scale(0.708)'>"
    "<path fill='#fff' d='M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zM13.2599 22.43a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4751zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.1419.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6456zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.1419.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.5093-2.6067-1.4997z'/></g></svg>"
)


@app.get("/favicon.svg")
async def favicon_svg():
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


@app.get("/favicon.ico")
async def favicon_ico():
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


# ── Frontend ─────────────────────────────────────────────────────────────

from pathlib import Path as _Path

_INDEX_FILE = _Path(__file__).parent / "index.html"


@app.get("/", response_class=HTMLResponse)
async def index():
    return _INDEX_FILE.read_text(encoding="utf-8")
