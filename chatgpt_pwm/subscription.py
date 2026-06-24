"""
ChatGPT subscription chat backend (synchronous, for the CLI).

Proxies chat turns to the ChatGPT backend's responses API using the OAuth
access token, translating the responses-API event stream into plain text
deltas plus a final usage dict.
"""
from __future__ import annotations

import json
import uuid
from typing import Iterator, List, Optional, Tuple

import httpx

from . import auth

CHATGPT_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"

DEFAULT_MODEL = "gpt-5.5"
SUPPORTED_MODELS = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]

# Friendly aliases → real backend slug (account-served models only).
_MODEL_MAP = {
    "gpt-4o": "gpt-5.5",
    "gpt-4o-mini": "gpt-5.4-mini",
    "gpt-4-turbo": "gpt-5.4",
    "gpt-4": "gpt-5.4",
    "gpt-3.5-turbo": "gpt-5.4-mini",
    "o3": "gpt-5.5",
    "o3-mini": "gpt-5.4-mini",
    "o1": "gpt-5.5",
    "o1-mini": "gpt-5.4-mini",
    "gpt-5.5": "gpt-5.5",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-mini": "gpt-5.4-mini",
}


def resolve_model(model: str) -> str:
    return _MODEL_MAP.get(model, DEFAULT_MODEL)


def _to_responses_input(messages: List[dict]) -> Tuple[str, list]:
    instructions = ""
    items: list = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            instructions = f"{instructions}\n\n{content}".strip() if instructions else content
            continue
        text_type = "output_text" if role == "assistant" else "input_text"
        items.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": text_type, "text": content}],
            }
        )
    return instructions, items


def _payload(messages: List[dict], model: str) -> dict:
    instructions, items = _to_responses_input(messages)
    return {
        "model": resolve_model(model),
        "instructions": instructions or "You are a helpful assistant.",
        "input": items,
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "store": False,
        "stream": True,
        "prompt_cache_key": str(uuid.uuid4()),
    }


def _headers(access_token: str, account_id: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": auth.ORIGINATOR,
        "session_id": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "codex_cli_rs",
    }


class UpstreamError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"upstream {status}: {body[:300]}")


def stream_chat(
    messages: List[dict],
    model: str,
) -> Iterator[Tuple[str, Optional[dict]]]:
    """
    Yield (text_delta, usage). ``usage`` is None until the terminal chunk,
    which yields ("", usage_dict). Refreshes the token once on 401.
    """
    payload = _payload(messages, model)

    def _attempt(access_token: str, account_id: str) -> Iterator[Tuple[str, Optional[dict]]]:
        with httpx.Client(timeout=httpx.Timeout(300, connect=30)) as client:
            with client.stream(
                "POST",
                CHATGPT_RESPONSES_URL,
                headers=_headers(access_token, account_id),
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    raise UpstreamError(resp.status_code, resp.read().decode(errors="replace"))
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type", "")
                    if etype == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            yield delta, None
                    elif etype == "response.completed":
                        usage = (event.get("response") or {}).get("usage") or {}
                        yield "", {
                            "prompt_tokens": usage.get("input_tokens", 0),
                            "completion_tokens": usage.get("output_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                        }
                    elif etype in ("response.failed", "error"):
                        raise UpstreamError(502, json.dumps(event))

    access_token, account_id = auth.get_access_token()
    try:
        yield from _attempt(access_token, account_id)
    except UpstreamError as e:
        if e.status == 401:
            refreshed = auth._refresh(auth.load_auth())  # noqa: SLF001
            tokens = refreshed.get("tokens") or {}
            access_token = tokens["access_token"]
            account_id = (
                tokens.get("account_id")
                or auth._jwt_account_id(access_token)  # noqa: SLF001
                or account_id
            )
            yield from _attempt(access_token, account_id)
        else:
            raise
