"""Conversation history save/load."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .config import HISTORY_DIR


def _safe_filename(title: str) -> str:
    safe = re.sub(r'[^\w\s-]', '', title)
    safe = re.sub(r'\s+', '_', safe.strip())
    return safe[:50] or "conversation"


def save_conversation(messages: List[dict], title: Optional[str] = None) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not title and messages:
        first = next((m["content"] for m in messages if m["role"] == "user"), "")
        title = first[:40] if first else "conversation"
    fname = f"{ts}_{_safe_filename(title or 'conversation')}.json"
    path = HISTORY_DIR / fname
    payload = {
        "title": title or "Conversation",
        "created_at": datetime.now().isoformat(),
        "messages": messages,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_conversation(path: Path) -> tuple[str, List[dict]]:
    data = json.loads(path.read_text())
    return data.get("title", "Conversation"), data.get("messages", [])


def list_conversations() -> List[Path]:
    if not HISTORY_DIR.exists():
        return []
    return sorted(HISTORY_DIR.glob("*.json"), reverse=True)
