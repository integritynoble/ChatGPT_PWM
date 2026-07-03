"""
ChatGPT-PWM web service — FastAPI backend + embedded SPA frontend.

Generation is backed by an OpenAI ChatGPT subscription (OAuth tokens, the same
scheme Codex uses) — no per-token API key billing. Access is gated by a PWM key
and, when the PWM exchange is deployed, billed against the user's PWM balance.
"""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, List, Optional, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

import openai_subscription as subscription
import pwm_billing

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
    """Stream from the subscription backend, then bill PWM tokens on completion."""
    prompt_tokens = completion_tokens = 0
    async for chunk in subscription.stream_chat(messages, model, web_search, image_gen):
        # Capture usage from the final chunk for billing.
        text = chunk.decode(errors="replace")
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
    convo: dict


@app.post("/api/share")
async def create_share(req: Request, body: ShareRequest):
    user, pwm_key = _share_auth(req)
    check = await pwm_billing.check_balance(pwm_key)
    if not check.valid:
        raise HTTPException(status_code=401, detail=check.reason)
    convo_id = str(body.convo.get("id") or "")
    if not convo_id or not body.convo.get("messages"):
        raise HTTPException(status_code=400, detail="Nothing to share.")
    data = json.dumps(body.convo)
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
