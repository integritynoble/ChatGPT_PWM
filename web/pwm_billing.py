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
import uuid

import httpx

logger = logging.getLogger("pwm_billing")

PLATFORM_BASE = os.environ.get("PWM_PLATFORM_URL", "http://127.0.0.1:8101")
SPEND_PATH = "/api/v1/pwm-token/spend"
BALANCE_PATH = "/api/v1/pwm-token/balance"

# Pricing: PWM tokens per 1K tokens. Override via env.
# Exchange-aligned pricing: charge = official-API USD cost x PWM_PER_OFFICIAL_USD.
# 0.02 PWM per official-$1 == $0.10 at the $5/PWM peg == 10x under official prices,
# matching the exchange's competitive rates (cheapest live nodes: 0.017-0.02).
# The old flat tariff (0.001/1K prompt + 0.003/1K completion) priced ABOVE the
# official API for gpt-5.5 — replaced 2026-07-07.
PWM_PER_OFFICIAL_USD = float(os.environ.get("PWM_PER_OFFICIAL_USD", "0.02"))
PWM_USD_PEG = float(os.environ.get("PWM_USD_PRICE", "5.0"))
# (input_usd_per_1M, output_usd_per_1M) — mirror of the platform's MODEL_PRICES
MODEL_PRICES = {
    "gpt-5-codex": (1.25, 10.0),
    "gpt-5": (1.25, 10.0),
    "gpt-4o": (2.5, 10.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}
DEFAULT_PRICE = (3.0, 15.0)


def _model_price(model: str):
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    matches = [n for n in MODEL_PRICES if model.startswith(n)]
    return MODEL_PRICES[max(matches, key=len)] if matches else DEFAULT_PRICE


def _usd_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, outp = _model_price(model)
    return round(prompt_tokens / 1e6 * inp + completion_tokens / 1e6 * outp, 6)


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
        # Zero balance is NOT a blocker: the exchange grants every consumer a
        # few free trial prompts and 402s cleanly after that. Let it decide.
        return BalanceCheck(True, balance)
    except Exception as e:  # noqa: BLE001
        logger.warning("PWM balance check skipped (%s)", e)
        return BalanceCheck(True)


def _cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    return round(_usd_cost(model, prompt_tokens, completion_tokens) * PWM_PER_OFFICIAL_USD, 6)


def _receipt_purpose(model: str, amount: float, usd: float, ref: str) -> str:
    """Cost-receipt description, same shape as the exchange settle lines —
    the portal activity feed parses it into a mini-receipt. Max 100 chars."""
    paid = amount * PWM_USD_PEG
    if usd > 0 and paid > 0 and usd / paid >= 1.05:
        p = f"chatgpt:{model} — {amount:.6f} PWM (≈${paid:.4f}) vs API ≈${usd:.4f} ({usd / paid:.1f}× cheaper) (ref:{ref})"
    elif usd > 0:
        p = f"chatgpt:{model} — {amount:.6f} PWM (≈${paid:.4f}); API ≈${usd:.4f} (ref:{ref})"
    else:
        p = f"chatgpt:{model} (ref:{ref})"
    if len(p) > 100:
        p = p[:100]
    return p


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
    amount = _cost(model, prompt_tokens, completion_tokens)
    if amount <= 0:
        return False
    usd = _usd_cost(model, prompt_tokens, completion_tokens)
    ref = uuid.uuid4().hex[:10]
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
                    "purpose": _receipt_purpose(model, amount, usd, ref),
                    "idempotency_key": f"chatgpt-{ref}",
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
