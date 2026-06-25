"""
ChatGPT-PWM web service — FastAPI backend + embedded SPA frontend.

Generation is backed by an OpenAI ChatGPT subscription (OAuth tokens, the same
scheme Codex uses) — no per-token API key billing. Access is gated by a PWM key
and, when the PWM exchange is deployed, billed against the user's PWM balance.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
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
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    model: str = subscription.DEFAULT_MODEL
    stream: bool = True


async def _stream_with_billing(
    pwm_key: Optional[str],
    messages: List[dict],
    model: str,
) -> AsyncIterator[bytes]:
    """Stream from the subscription backend, then bill PWM tokens on completion."""
    prompt_tokens = completion_tokens = 0
    async for chunk in subscription.stream_chat(messages, model):
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

    try:
        # Validate auth availability up front so errors surface as JSON, not a broken stream.
        await subscription.get_access_token()
    except subscription.SubscriptionAuthError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return StreamingResponse(
        _stream_with_billing(pwm_key, messages, body.model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/models")
async def models():
    return {"models": AVAILABLE_MODELS}


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


# ── Frontend ─────────────────────────────────────────────────────────────

from pathlib import Path as _Path

_INDEX_FILE = _Path(__file__).parent / "index.html"


@app.get("/", response_class=HTMLResponse)
async def index():
    return _INDEX_FILE.read_text(encoding="utf-8")
