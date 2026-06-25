# ChatGPT-PWM Web

A faithful ChatGPT web UI, served by FastAPI. Generation runs on a ChatGPT
subscription (OAuth, like Codex); usage is metered against the user's PWM
balance. Deployed at **https://chatgpt.platformai.org**.

## Components

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app — `/api/chat` (SSE stream), `/api/balance`, `/api/models`, serves `index.html` |
| `index.html` | Single-page ChatGPT-replica UI (marked.js + highlight.js + DOMPurify + KaTeX) |
| `openai_subscription.py` | ChatGPT subscription auth + responses-API proxy (async) |
| `pwm_billing.py` | PWM balance check + per-turn token deduction via the PWM platform |

## Run

```bash
pip install -r requirements.txt
# ChatGPT subscription tokens are read from ~/.codex/auth.json (or CHATGPT_AUTH_FILE)
uvicorn main:app --host 127.0.0.1 --port 8200
```

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `PWM_KEY_REQUIRED` | `0` | Require a PWM key to chat |
| `PWM_PLATFORM_URL` | `http://127.0.0.1:8101` | PWM platform base for balance/spend |
| `CHATGPT_AUTH_FILE` | `~/.codex/auth.json` | ChatGPT subscription token store |
| `PWM_PER_1K_PROMPT` | `0.001` | PWM tokens per 1K prompt tokens |
| `PWM_PER_1K_COMPLETION` | `0.003` | PWM tokens per 1K completion tokens |

The user's PWM key is sent per request as the `X-PWM-Key` header and is stored
only in the browser. No API keys or subscription tokens live in this repo.
