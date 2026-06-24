"""Configuration management for chatgpt-pwm."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

PWM_BASE_URL = "https://physicsworldmodel.org/api/v1/exchange/openai"
DEFAULT_MODEL = "gpt-4o"
HISTORY_DIR = Path.home() / ".chatgpt-pwm" / "conversations"
CONFIG_FILE = Path.home() / ".chatgpt-pwm" / "config.json"

AVAILABLE_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
    "o3",
    "o3-mini",
    "o1",
    "o1-mini",
]

DEFAULT_SYSTEM_PROMPT = (
    "You are ChatGPT, a large language model trained by OpenAI. "
    "Be helpful, harmless, and honest."
)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {
        "model": DEFAULT_MODEL,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "base_url": None,
        "stream": True,
    }


def save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_api_key() -> Optional[str]:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("PWM_API_KEY")


def get_base_url() -> str:
    cfg = load_config()
    return (
        os.environ.get("OPENAI_BASE_URL")
        or cfg.get("base_url")
        or PWM_BASE_URL
    )
