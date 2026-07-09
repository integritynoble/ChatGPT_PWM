"""
OpenAI ChatGPT subscription auth + responses-API proxy.

Authenticates to OpenAI using ChatGPT-plan OAuth tokens (the same scheme Codex
uses) instead of a billed API key. Reads/refreshes tokens from a Codex-style
``auth.json`` and proxies chat requests to the ChatGPT backend's responses API,
translating to/from the chat-completions shape the frontend speaks.

No token material is ever logged.
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, List, Optional

import httpx

# ── Constants (mirror Codex) ──────────────────────────────────────────────
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CHATGPT_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"

# PWM exchange routing: when a request carries a PWM key, the turn is served by
# a POOL PROVIDER via the exchange (provider earns PWM, the key's wallet is
# billed by exchange settlement) instead of this host's own subscription.
_PLATFORM = os.environ.get("PWM_PLATFORM_URL", "https://physicsworldmodel.org").rstrip("/")
EXCHANGE_RESPONSES_URL = os.environ.get(
    "PWM_EXCHANGE_RESPONSES_URL",
    f"{_PLATFORM}/api/v1/exchange/openai/v1/responses")
ORIGINATOR = "codex_cli_rs"

# Where the ChatGPT-plan OAuth tokens live. Override with CHATGPT_AUTH_FILE.
AUTH_FILE = Path(
    os.environ.get("CHATGPT_AUTH_FILE", str(Path.home() / ".codex" / "auth.json"))
)

# The ChatGPT-account backend only accepts the plan's own model slugs.
# Map UI choices onto the models this subscription actually serves.
# GPT-5.6 (GA 2026-07-09): the number is the generation; Sol/Terra/Luna are
# durable capability tiers. Verified the subscription serves gpt-5.6-{sol,terra,
# luna} (bare "gpt-5.6" and bogus slugs 400). The simplified picker's effort
# levels map onto tiers: Instant→Terra (fast), Medium/High→Sol (top tier, with
# low/default/high reasoning effort set from the -instant/-thinking suffix).
DEFAULT_MODEL = "gpt-5.6-sol"
SUPPORTED_MODELS = ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"]
_MODEL_MAP = {
    # Friendly aliases → real backend slug
    "gpt-4o": "gpt-5.6-sol",
    "gpt-4o-mini": "gpt-5.6-terra",
    "gpt-4-turbo": "gpt-5.6-sol",
    "gpt-4": "gpt-5.6-sol",
    "gpt-3.5-turbo": "gpt-5.6-terra",
    "o3": "gpt-5.6-sol",
    "o3-mini": "gpt-5.6-terra",
    "o1": "gpt-5.6-sol",
    "o1-mini": "gpt-5.6-terra",
    # 5.6 tier slugs pass through
    "gpt-5.6-sol": "gpt-5.6-sol",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "gpt-5.6-luna": "gpt-5.6-luna",
    # Simplified picker → 5.6 tier + effort (effort from the suffix, below)
    "gpt-5.5": "gpt-5.6-sol",            # Medium → Sol (default effort)
    "gpt-5.5-thinking": "gpt-5.6-sol",   # High → Sol (high effort)
    "gpt-5.5-instant": "gpt-5.6-terra",  # Instant → Terra (fast; low effort)
    # Legacy 5.4/5.5 native slugs still resolve (older synced prefs)
    "gpt-5.4": "gpt-5.6-terra",
    "gpt-5.4-mini": "gpt-5.6-terra",
}


class SubscriptionAuthError(RuntimeError):
    """Raised when no usable ChatGPT subscription token is available."""


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _jwt_exp(token: str) -> Optional[int]:
    try:
        payload = json.loads(_b64url_decode(token.split(".")[1]))
        return int(payload.get("exp")) if payload.get("exp") else None
    except Exception:
        return None


def _jwt_account_id(token: str) -> Optional[str]:
    try:
        payload = json.loads(_b64url_decode(token.split(".")[1]))
        auth = payload.get("https://api.openai.com/auth", {})
        return auth.get("chatgpt_account_id")
    except Exception:
        return None


def _load_auth() -> dict:
    if not AUTH_FILE.exists():
        raise SubscriptionAuthError(
            f"No ChatGPT subscription auth found at {AUTH_FILE}. "
            "Run `codex login` (or set CHATGPT_AUTH_FILE)."
        )
    try:
        return json.loads(AUTH_FILE.read_text())
    except Exception as e:  # noqa: BLE001
        raise SubscriptionAuthError(f"Could not parse {AUTH_FILE}: {e}") from e


def _save_auth(auth: dict) -> None:
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTH_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(auth, indent=2))
    os.replace(tmp, AUTH_FILE)
    try:
        os.chmod(AUTH_FILE, 0o600)
    except OSError:
        pass


async def _refresh_tokens(auth: dict) -> dict:
    """Refresh the access token via the OAuth refresh-token grant."""
    tokens = auth.get("tokens") or {}
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise SubscriptionAuthError("No refresh_token available; run `codex login` again.")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/json"},
            json={
                "client_id": OAUTH_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid profile email",
            },
        )
    if resp.status_code != 200:
        raise SubscriptionAuthError(
            f"Token refresh failed ({resp.status_code}); run `codex login` again."
        )
    data = resp.json()
    tokens["access_token"] = data.get("access_token", tokens.get("access_token"))
    if data.get("refresh_token"):
        tokens["refresh_token"] = data["refresh_token"]
    if data.get("id_token"):
        tokens["id_token"] = data["id_token"]
    auth["tokens"] = tokens
    auth["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_auth(auth)
    return auth


async def get_access_token() -> tuple[str, str]:
    """Return (access_token, account_id), refreshing if the token is near expiry."""
    auth = _load_auth()
    tokens = auth.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise SubscriptionAuthError("No access_token in auth file; run `codex login`.")

    exp = _jwt_exp(access_token)
    # Refresh if expired or expiring within 5 minutes.
    if exp is None or exp - time.time() < 300:
        auth = await _refresh_tokens(auth)
        tokens = auth.get("tokens") or {}
        access_token = tokens["access_token"]

    account_id = (
        tokens.get("account_id")
        or _jwt_account_id(access_token)
        or auth.get("account_id")
    )
    if not account_id:
        raise SubscriptionAuthError("Could not determine chatgpt-account-id.")
    return access_token, account_id


# ── Request/response translation ──────────────────────────────────────────

def _text_of(content) -> str:
    """Flatten a content value (str or parts list) to plain text."""
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, dict) and p.get("type") in ("text", "input_text", "output_text"):
                out.append(p.get("text", ""))
        return " ".join(out).strip()
    return content or ""


def _content_parts(role: str, content) -> list:
    """Build responses-API content parts from a str or a list of parts."""
    text_type = "output_text" if role == "assistant" else "input_text"
    if not isinstance(content, list):
        return [{"type": text_type, "text": content or ""}]
    parts: list = []
    for p in content:
        if not isinstance(p, dict):
            parts.append({"type": text_type, "text": str(p)})
            continue
        t = p.get("type")
        if t in ("text", "input_text", "output_text"):
            parts.append({"type": text_type, "text": p.get("text", "")})
        elif t in ("image_url", "image", "input_image"):
            url = p.get("image_url") or p.get("image") or p.get("url")
            if isinstance(url, dict):
                url = url.get("url")
            if url:  # images only make sense as input
                parts.append({"type": "input_image", "image_url": url})
    return parts or [{"type": text_type, "text": ""}]


def _to_responses_input(messages: List[dict]) -> tuple[str, list]:
    """Split chat messages into (instructions, responses-input items)."""
    instructions = ""
    items: list = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            text = _text_of(content)
            instructions = (instructions + "\n\n" + text).strip() if instructions else text
            continue
        items.append(
            {
                "type": "message",
                "role": role,
                "content": _content_parts(role, content),
            }
        )
    return instructions, items


def _default_instructions() -> str:
    """A ChatGPT-style system prompt so answers match chatgpt.com's tone/formatting."""
    today = datetime.date.today().isoformat()
    return (
        "You are ChatGPT, a large language model trained by OpenAI. "
        f"The current date is {today}. "
        "Respond helpfully, accurately, and conversationally. Use Markdown formatting—"
        "headings, bold, bulleted/numbered lists, tables, and fenced code blocks with a "
        "language tag—when it improves clarity. Keep answers concise unless the user asks "
        "for depth."
    )


def _build_payload(messages: List[dict], model: str, web_search: bool = False,
                   image_gen: bool = False) -> dict:
    instructions, items = _to_responses_input(messages)
    # A leading system message from the client (e.g. the user's "custom instructions")
    # is APPENDED to the ChatGPT-style default, not used in its place — so tone, date,
    # and formatting guidance are preserved alongside the user's preferences.
    base = _default_instructions()
    instructions = (base + "\n\n" + instructions).strip() if instructions else base
    if web_search:
        instructions += ("\n\nYou can search the web. Search when it helps, and cite the "
                         "sources you use with inline citations.")
    if image_gen:
        tools, tool_choice = [{"type": "image_generation"}], {"type": "image_generation"}
    elif web_search:
        tools, tool_choice = [{"type": "web_search"}], {"type": "web_search"}
    else:
        tools, tool_choice = [], "auto"
    reasoning = {"summary": "auto"}
    if str(model).endswith("-thinking"):
        reasoning["effort"] = "high"
    elif str(model).endswith("-instant"):
        reasoning["effort"] = "low"   # fastest first token; voice mode uses this
    return {
        "model": _MODEL_MAP.get(model, DEFAULT_MODEL),
        "instructions": instructions,
        "input": items,
        "tools": tools,
        "tool_choice": tool_choice,
        "parallel_tool_calls": False,
        "store": False,
        "stream": True,
        "reasoning": reasoning,   # "Thinking" summary; higher effort for the Thinking model
        "prompt_cache_key": str(uuid.uuid4()),
    }


def _headers(access_token: str, account_id: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": ORIGINATOR,
        "session_id": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "codex_cli_rs",
    }


async def stream_chat(messages: List[dict], model: str, web_search: bool = False,
                      image_gen: bool = False,
                      pwm_key: "Optional[str]" = None) -> AsyncIterator[bytes]:
    """
    Proxy a chat request and yield chat-completions-style SSE lines
    (``data: {...}``) the frontend understands. With a ``pwm_key`` the turn is
    routed through the PWM EXCHANGE (pool provider serves & earns; the key's
    wallet is billed); without one it falls back to this host's subscription.
    """
    payload = _build_payload(messages, model, web_search, image_gen)

    if pwm_key:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
            async with client.stream(
                "POST",
                EXCHANGE_RESPONSES_URL,
                headers={"Authorization": f"Bearer {pwm_key}",
                         "Content-Type": "application/json"},
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")
                    raise _UpstreamError(resp.status_code, body)
                async for line in resp.aiter_lines():
                    async for chunk in _translate_line(line, model):
                        yield chunk
        return

    async def _attempt(access_token: str, account_id: str):
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
            async with client.stream(
                "POST",
                CHATGPT_RESPONSES_URL,
                headers=_headers(access_token, account_id),
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")
                    raise _UpstreamError(resp.status_code, body)
                async for line in resp.aiter_lines():
                    yield line

    access_token, account_id = await get_access_token()
    out_index = 0
    try:
        gen = _attempt(access_token, account_id)
        async for line in gen:
            async for chunk in _translate_line(line, model):
                yield chunk
    except _UpstreamError as e:
        if e.status == 401:
            # Force a refresh and retry once.
            auth = await _refresh_tokens(_load_auth())
            access_token = auth["tokens"]["access_token"]
            account_id = (
                auth["tokens"].get("account_id")
                or _jwt_account_id(access_token)
                or account_id
            )
            async for line in _attempt(access_token, account_id):
                async for chunk in _translate_line(line, model):
                    yield chunk
        else:
            raise


class _UpstreamError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"upstream {status}: {body[:200]}")


async def _translate_line(line: str, model: str) -> AsyncIterator[bytes]:
    """Translate one responses-API SSE line into a chat-completions delta line."""
    if not line or not line.startswith("data:"):
        return
    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return
    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        return

    etype = event.get("type", "")

    if etype == "response.output_text.delta":
        delta = event.get("delta", "")
        if delta:
            yield _chat_chunk(model, delta).encode()
    elif etype.startswith("response.reasoning") and isinstance(event.get("delta"), str) and event.get("delta"):
        yield ("data: " + json.dumps({"reasoning": event["delta"]}) + "\n\n").encode()
    elif etype in ("response.image_generation_call.in_progress", "response.image_generation_call.generating"):
        yield ("data: " + json.dumps({"status": "generating_image"}) + "\n\n").encode()
    elif etype in ("response.image_generation_call.partial_image", "response.image_generation_call.completed"):
        b64 = event.get("partial_image_b64") or event.get("result") or event.get("image_b64")
        if isinstance(b64, str) and len(b64) > 100:
            yield ("data: " + json.dumps({"image": "data:image/png;base64," + b64}) + "\n\n").encode()
    elif etype in ("response.web_search_call.in_progress", "response.web_search_call.searching"):
        yield ("data: " + json.dumps({"status": "searching"}) + "\n\n").encode()
    elif etype == "response.web_search_call.completed":
        yield ("data: " + json.dumps({"status": "searched"}) + "\n\n").encode()
    elif etype == "response.output_text.annotation.added":
        anno = event.get("annotation") or {}
        if anno.get("type") == "url_citation" and anno.get("url"):
            yield ("data: " + json.dumps(
                {"source": {"title": anno.get("title") or anno.get("url"), "url": anno.get("url")}}
            ) + "\n\n").encode()
    elif etype == "response.completed":
        usage = (event.get("response") or {}).get("usage") or {}
        final = {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "model": model,
        }
        if usage:
            final["usage"] = {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
        yield ("data: " + json.dumps(final) + "\n\n").encode()
        yield b"data: [DONE]\n\n"
    elif etype in ("response.failed", "error"):
        msg = json.dumps(event)[:300]
        yield ("data: " + json.dumps({"error": {"message": msg}}) + "\n\n").encode()


def _chat_chunk(model: str, delta_text: str) -> str:
    obj = {
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
    }
    return "data: " + json.dumps(obj) + "\n\n"
