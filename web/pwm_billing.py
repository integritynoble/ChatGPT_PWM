"""
PWM token billing — best-effort deduction against the PWM platform.

Charges a user's PWM balance for a chat turn by calling the platform's
``/api/v1/pwm-token/spend`` endpoint with their PWM key. Designed to fail
open: if the platform endpoint is not deployed or the call errors, the chat
response is never affected (it has already streamed). When the platform
exchange goes live, this starts billing automatically — no code change needed.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("pwm_billing")

PLATFORM_BASE = os.environ.get("PWM_PLATFORM_URL", "http://127.0.0.1:8101")
SPEND_PATH = "/api/v1/pwm-token/spend"
BALANCE_PATH = "/api/v1/pwm-token/balance"

# Pricing: PWM tokens per 1K tokens. Override via env.
PWM_PER_1K_PROMPT = float(os.environ.get("PWM_PER_1K_PROMPT", "0.001"))
PWM_PER_1K_COMPLETION = float(os.environ.get("PWM_PER_1K_COMPLETION", "0.003"))


class BalanceCheck:
    """Result of a pre-flight balance check."""

    def __init__(self, valid: bool, balance: float = 0.0, reason: str = ""):
        self.valid = valid
        self.balance = balance
        self.reason = reason


async def check_balance(pwm_key: str) -> BalanceCheck:
    """
    Validate a PWM key and confirm a positive balance before serving a turn.
    Returns BalanceCheck(valid, balance, reason). On platform errors, fails
    OPEN (valid=True) so an outage never blocks chat.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{PLATFORM_BASE}{BALANCE_PATH}",
                headers={"Authorization": f"Bearer {pwm_key}"},
            )
        if resp.status_code == 401:
            return BalanceCheck(False, reason="Invalid PWM key.")
        if resp.status_code == 404:
            # Token router not deployed here — fail open.
            return BalanceCheck(True)
        if resp.status_code != 200:
            return BalanceCheck(True)  # fail open on unexpected errors
        data = resp.json()
        balance = float(data.get("balance", 0.0))
        if balance <= 0:
            return BalanceCheck(False, balance, "Insufficient PWM balance.")
        return BalanceCheck(True, balance)
    except Exception as e:  # noqa: BLE001
        logger.warning("PWM balance check skipped (%s)", e)
        return BalanceCheck(True)


def _cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        (prompt_tokens / 1000.0) * PWM_PER_1K_PROMPT
        + (completion_tokens / 1000.0) * PWM_PER_1K_COMPLETION,
        6,
    )


async def charge(
    pwm_key: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> bool:
    """
    Attempt to deduct PWM tokens for one chat turn. Returns True if billed,
    False if skipped/failed. Never raises.
    """
    amount = _cost(prompt_tokens, completion_tokens)
    if amount <= 0:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PLATFORM_BASE}{SPEND_PATH}",
                headers={
                    "Authorization": f"Bearer {pwm_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "amount": amount,
                    "purpose": f"chatgpt:{model}",
                },
            )
        if resp.status_code == 200:
            logger.info("Billed %.6f PWM for %s (%d+%d tok)", amount, model,
                        prompt_tokens, completion_tokens)
            return True
        # 404 → exchange/token router not deployed yet; fail open silently.
        if resp.status_code != 404:
            logger.warning("PWM billing returned %s: %s", resp.status_code,
                           resp.text[:200])
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("PWM billing skipped (%s)", e)
        return False
