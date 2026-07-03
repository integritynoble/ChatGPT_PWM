# chatgpt-pwm

A faithful **ChatGPT experience powered by your ChatGPT subscription** — as a full web
app and a terminal CLI. Generation runs on a pooled ChatGPT plan over OAuth (the same
subscription auth Codex uses) — **no OpenAI API key, no per-token API charge**. Access
is gated by a **PWM account**; usage is metered against your PWM balance.

Two ways to use it:

- **Web app** — a complete ChatGPT-web replica (below). Live at
  **[chatgpt.comparegpt.io](https://chatgpt.comparegpt.io)** and
  **[chatgpt.platformai.org](https://chatgpt.platformai.org)**.
- **Terminal CLI** — `chatgpt-pwm`, the same conversation in your shell ([jump](#terminal-cli)).

<p align="center">
  <img src="https://raw.githubusercontent.com/integritynoble/ChatGPT_PWM/main/docs/screenshots/web-app.png" alt="chatgpt-pwm web app — the ChatGPT landing screen with sidebar and composer" width="860">
</p>

---

## Web app

A single-page ChatGPT replica (FastAPI backend + embedded SPA) that covers essentially
the whole ChatGPT feature surface. **Log in with your PWM account** — click *Continue
with token.comparegpt.io / physicsworldmodel.org / Google*; the portal mints your access
key and signs you in automatically (no key to paste).

<p align="center">
  <img src="https://raw.githubusercontent.com/integritynoble/ChatGPT_PWM/main/docs/screenshots/login.png" alt="chatgpt-pwm login screen with Google / token.comparegpt.io / physicsworldmodel.org SSO" width="560">
</p>

### Chat & models
- **Streaming replies** with live Markdown, syntax-highlighted code, and KaTeX math
- **Models:** ChatGPT 5.5 (default), 5.4, 5.4 mini, and **ChatGPT Thinking** (extended reasoning, with a visible thought process)
- **Edit a message** (re-runs the thread), **regenerate** with a model picker, **branch** between versions, **👍/👎 ratings**, per-message copy & timestamps
- **Temporary chats** that are never saved
- **Search** your whole history; **archive** chats; **keyboard shortcuts** (⌘/Ctrl+Shift+O new chat, ⌘/Ctrl+/ shortcuts, …)

### Tools (the `+` menu)
- **Web search** — real-time answers with cited sources
- **Deep research** — multi-step, high-reasoning research
- **Create image** — image generation, saved to your **Library**
- **Code interpreter** — the model writes and **runs Python in a sandbox** (numpy / pandas / matplotlib / scipy / sympy, no network), shows stdout & charts inline, and iterates on the results
- **Canvas** — a side-by-side editor for documents and code, with version history, inline editing, and quick actions (polish / shorter / fix bugs / …)
- **Connectors** — pull live data from **GitHub** (repos, files, issues, code search) and **Finances** (live stock quotes & history)

### Files & knowledge
- **Upload** images, PDFs, DOCX, and text — with **vision** for images and text extraction for documents
- **Persistent file library** — upload a file once, reuse it in any chat (cross-device)
- **Per-project files** — attach up to 40 reference files to a Project; they become shared context for every chat in it
- **Library** — a gallery of every image you generate

### Organization
- **Projects** — group related chats, with their own files
- **GPTs** — custom versions of ChatGPT with their own name and instructions

### Voice
- **Voice conversation mode** — full-screen, hands-free: it listens, thinks, and speaks back, then listens again
- **Neural voices** (server-side TTS) for voice mode and **read-aloud**, with a browser-voice fallback and a voice picker in Settings
- **Dictation** into the composer

### Personalization & memory
- **Memory across chats** — remembers durable facts you share; **time-aware**, so elapsed plans are treated as past
- **Custom instructions** — what ChatGPT should know about you and how it should respond

### Collaboration & continuity
- **Cross-device sync** — chats, projects, GPTs, memory, and custom instructions follow your account across devices (and both domains)
- **Hosted share links** — publish a read-only snapshot of a chat at `/share/<id>`; visitors can "Continue this conversation"
- **Group chats** — shared conversations for up to 20 people via an invite link; mention **@ChatGPT** to bring the AI into the discussion
- **Scheduled tasks** — ask ChatGPT to run something later or on a schedule (daily/weekly); results arrive as a chat, generated server-side even while you're away

### Look & feel
- Light / dark / system themes, a mobile-optimized layout, the ChatGPT landing screen, model picker, and account/settings menus

### Run the web app locally
```bash
cd web
pip install -r requirements.txt
# ChatGPT subscription tokens are read from ~/.codex/auth.json (or CHATGPT_AUTH_FILE)
uvicorn main:app --host 127.0.0.1 --port 8200
```

| Env var | Default | Meaning |
|---|---|---|
| `PWM_KEY_REQUIRED` | `0` | Require a PWM key to use the service |
| `PWM_PLATFORM_URL` | `http://127.0.0.1:8101` | PWM platform base for balance / spend |
| `CHATGPT_AUTH_FILE` | `~/.codex/auth.json` | ChatGPT subscription token store |
| `CHATGPT_SYNC_DB` | `~/pwm/chatgpt-sync/sync.db` | SQLite store for sync, shares, tasks, groups, files |
| `CHATGPT_CI_IMAGE` | `chatgpt-pwm-ci:latest` | Docker image for the code-interpreter sandbox |
| `CHATGPT_TASK_TICK` | `30` | Scheduled-task poll interval (seconds) |

Optional dependencies: the **code interpreter** needs Docker and a one-time build of the
sandbox image `chatgpt-pwm-ci:latest` (from `python:3.11-slim` +
numpy/pandas/matplotlib/scipy/sympy); **neural TTS** needs `edge-tts`. Both degrade
gracefully (503 / browser-voice fallback) when absent.

### Web architecture
| File | Purpose |
|---|---|
| `web/index.html` | The entire SPA (marked.js + highlight.js + DOMPurify + KaTeX) |
| `web/main.py` | FastAPI app + all API endpoints |
| `web/openai_subscription.py` | ChatGPT subscription auth + Responses-API proxy (async, SSE) |
| `web/pwm_billing.py` | PWM balance check + per-turn token deduction |

**API surface:** `/api/chat` (SSE) · `/api/models` · `/api/balance` · `/api/sync` ·
`/api/tasks` · `/api/groups` + `/api/group/*` + `/g/<token>` · `/api/files` +
`/api/project-files` · `/api/share` + `/share/<id>` · `/api/connector` · `/api/run` ·
`/api/tts`. Server-side state (sync, shares, tasks, groups, files) lives in one shared
SQLite DB keyed by a hash of your PWM key, so it works across devices and both domains.

---

## Terminal CLI

The same conversation experience in your terminal.

### Features
- **Sign in with your ChatGPT account** — OAuth login, no API key
- **Streaming responses** with syntax-highlighted code (Rich markdown)
- **Multi-turn conversations** with full history context
- **Conversation save/load** — resume any previous chat
- **Model switching** — GPT-5.5, GPT-5.4, GPT-5.4 mini
- **Custom system prompts**, multiline input (`\` to continue), input history
- **Token usage** per turn and session total
- **No Python required** — a single pre-built binary

### Install

One-liner (macOS / Linux):
```bash
curl -fsSL https://raw.githubusercontent.com/integritynoble/ChatGPT_PWM/main/install.sh | bash
```

Or grab a binary for your platform from
[Releases](https://github.com/integritynoble/ChatGPT_PWM/releases/latest)
(`chatgpt-pwm-macos-arm64`, `chatgpt-pwm-linux-x86_64`, `chatgpt-pwm-linux-arm64`,
`chatgpt-pwm-windows-x86_64.exe`), or via pip:
```bash
pip install chatgpt-pwm
```

### Quickstart
```bash
chatgpt-pwm login     # opens your browser to sign in with ChatGPT
chatgpt-pwm           # start chatting
```

`login` runs the OAuth (PKCE) flow against `auth.openai.com` and stores your session in
`~/.chatgpt-pwm/auth.json`. If you already use Codex, your existing `~/.codex/auth.json`
session is picked up automatically.

### Usage
```
chatgpt-pwm [OPTIONS]            # start an interactive chat
chatgpt-pwm login | logout | whoami

Options:
  -m, --model TEXT      Model to use (default: gpt-5.5)
  -s, --system TEXT     System prompt
  --no-stream           Disable streaming output
  --load PATH           Load a saved conversation file
  -h, --help            Show help
  --version             Show version
```

### In-session commands
| Command | Description |
|---|---|
| `/help` | Show all commands |
| `/clear` | Clear conversation history |
| `/save` · `/load [n]` · `/history` | Save / load / list conversations |
| `/model [name]` · `/models` | Switch model / list models |
| `/system [text]` | Set or show the system prompt |
| `/tokens` | Session token usage |
| `/login` · `/logout` · `/whoami` | Account |
| `/copy` | Copy last response |
| `/quit` | Exit |

### CLI config
Defaults in `~/.chatgpt-pwm/config.json`; saved conversations in
`~/.chatgpt-pwm/conversations/`; auth in `~/.chatgpt-pwm/auth.json` (`0600`).

---

## Models
| Model | Description |
|---|---|
| `gpt-5.5` | Default — highest quality |
| `gpt-5.5-thinking` | Extended reasoning for hard problems (web app: "ChatGPT Thinking") |
| `gpt-5.4` | Fast, high quality |
| `gpt-5.4-mini` | Fastest, most economical |

The exact models available depend on the pooled ChatGPT plan.

## How it works
```
you ──► chatgpt-pwm (web or CLI) ──► ChatGPT subscription (OAuth, auto-refreshed)
                    └──► PWM platform (balance check + per-turn metering)
```
Generation is served by the shared ChatGPT plan (no API key, no per-token API charge);
your **PWM balance** covers access, checked and metered per turn. Web login is via PWM
SSO; the CLI uses your own ChatGPT OAuth session.

## Comparison
| | **chatgpt-pwm** | **claude-pwm** | **codex** |
|---|---|---|---|
| Provider | OpenAI | Anthropic | OpenAI |
| Models | GPT-5.5 / 5.4 family | Claude | GPT-5 family |
| Interface | Web app + conversational CLI | Coding agent | Coding agent |
| Auth | ChatGPT subscription (OAuth) + PWM SSO | `ANTHROPIC_AUTH_TOKEN=pwm_…` | ChatGPT subscription (OAuth) |
| Billing | PWM balance | PWM balance | ChatGPT plan |
