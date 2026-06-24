"""Core chat session logic — streaming + non-streaming completions."""
from __future__ import annotations

import sys
from typing import Iterator, List, Optional, Tuple

import openai

from .config import get_api_key, get_base_url


def build_client(api_key: Optional[str] = None, base_url: Optional[str] = None) -> openai.OpenAI:
    key = api_key or get_api_key()
    if not key:
        raise ValueError(
            "No API key found. Set OPENAI_API_KEY (or PWM_API_KEY) environment variable.\n"
            "  export OPENAI_API_KEY=pwm_your_key_here"
        )
    url = base_url or get_base_url()
    return openai.OpenAI(api_key=key, base_url=url)


def stream_response(
    client: openai.OpenAI,
    messages: List[dict],
    model: str,
) -> Iterator[Tuple[str, Optional[dict]]]:
    """
    Yields (chunk_text, usage_dict) where usage_dict is None until the final chunk.
    """
    usage = None
    with client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    ) as stream:
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content, None
            if chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                }
    yield "", usage


def complete_response(
    client: openai.OpenAI,
    messages: List[dict],
    model: str,
) -> Tuple[str, Optional[dict]]:
    """Non-streaming completion — returns (text, usage)."""
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=False,
    )
    text = resp.choices[0].message.content or ""
    usage = None
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
    return text, usage


def build_messages(
    conversation: List[dict],
    user_input: str,
    system_prompt: Optional[str],
) -> List[dict]:
    messages: List[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(conversation)
    messages.append({"role": "user", "content": user_input})
    return messages
