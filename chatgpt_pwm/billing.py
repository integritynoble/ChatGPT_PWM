"""
PWM token billing for the CLI.

Generation runs on the ChatGPT subscription; this module meters each turn
against the user's PWM balance via the PWM platform's token API. The PWM key
is read from PWM_API_KEY or the local config file.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import httpx

from .config import load_config, save_config

PLATFORM_URL = os.environ.get("PWM_PLATFORM_URL", "https://physicsworldmodel.org").rstrip("/")
BALANCE_PATH = "/api/v1/pwm-token/balance"
SPEND_PATH = "/api/v1/pwm-token/spend"

# PWM tokens per 1K tokens. Override via env.
PWM_PER_1K_PROMPT = float(os.environ.get("PWM_PER_1K_PROMPT", "0.001"))
PWM_PER_1K_COMPLETION = float(os.environ.get("PWM_PER_1K_COMPLETION", "0.003"))


# ── Key storage ────────────────────────────────────────────────────────────
def get_pwm_key() -> Optional[str]:
    return os.environ.get("PWM_API_KEY") or load_config().get("pwm_key")


def set_pwm_key(key: str) -> None:
    cfg = load_config()
    cfg["pwm_key"] = key.strip()
    save_config(cfg)


def clear_pwm_key() -> None:
    cfg = load_config()
    cfg.pop("pwm_key", None)
    save_config(cfg)


def has_pwm_key() -> bool:
    return bool(get_pwm_key())


# ── Pricing ────────────────────────────────────────────────────────────────
def cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        (prompt_tokens / 1000.0) * PWM_PER_1K_PROMPT
        + (completion_tokens / 1000.0) * PWM_PER_1K_COMPLETION,
        6,
    )


# ── Platform calls ─────────────────────────────────────────────────────────
class BalanceResult:
    def __init__(self, valid: bool, balance: float = 0.0, reason: str = ""):
        self.valid = valid
        self.balance = balance
        self.reason = reason


def check_balance(key: str) -> BalanceResult:
    """Validate the PWM key and read its balance. Fails OPEN on platform error."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{PLATFORM_URL}{BALANCE_PATH}",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 401:
            return BalanceResult(False, reason="Invalid PWM key.")
        if resp.status_code != 200:
            return BalanceResult(True)  # fail open
        data = resp.json()
        bal = float(data.get("balance", 0.0))
        if bal <= 0:
            return BalanceResult(False, bal, "Insufficient PWM balance.")
        return BalanceResult(True, bal)
    except Exception:
        return BalanceResult(True)  # fail open on network error


def charge(
    key: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Tuple[bool, Optional[float], float]:
    """
    Deduct PWM tokens for one turn. Returns (billed, balance_after, amount).
    Never raises.
    """
    amount = cost(prompt_tokens, completion_tokens)
    if amount <= 0:
        return False, None, 0.0
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{PLATFORM_URL}{SPEND_PATH}",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"amount": amount, "purpose": f"chatgpt-cli:{model}"},
            )
        if resp.status_code == 200:
            data = resp.json()
            return True, data.get("balance_after"), amount
        return False, None, amount
    except Exception:
        return False, None, amount
