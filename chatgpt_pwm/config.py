"""Configuration management for chatgpt-pwm."""
from __future__ import annotations

import json
from pathlib import Path

from .subscription import DEFAULT_MODEL, SUPPORTED_MODELS  # re-export

HISTORY_DIR = Path.home() / ".chatgpt-pwm" / "conversations"
CONFIG_FILE = Path.home() / ".chatgpt-pwm" / "config.json"

AVAILABLE_MODELS = SUPPORTED_MODELS

DEFAULT_SYSTEM_PROMPT = (
    "You are ChatGPT, a large language model. "
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
        "stream": True,
    }


def save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
