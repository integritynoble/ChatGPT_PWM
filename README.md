# chatgpt-pwm

ChatGPT CLI powered by your **ChatGPT subscription** — the same conversation
experience as ChatGPT from OpenAI, running in your terminal. Generation uses your
ChatGPT plan via OAuth (the same subscription auth Codex uses), so there is **no
API key and no per-token billing**.

## Features

- **Sign in with your ChatGPT account** — OAuth login, no API key
- **Streaming responses** with real-time output
- **Syntax-highlighted code blocks** via Rich markdown rendering
- **Multi-turn conversations** with full history context
- **Conversation save/load** — resume any previous chat
- **Model switching** — GPT-5.5, GPT-5.4, GPT-5.4 mini
- **Custom system prompts**
- **Multiline input** — end a line with `\` to continue
- **Input history** — Up/Down arrows navigate past prompts
- **Token usage display** per turn and session total
- **No Python required** — download a single pre-built binary

## Install

### One-liner (macOS / Linux)
```bash
curl -fsSL https://raw.githubusercontent.com/integritynoble/ChatGPT_PWM/main/install.sh | bash
```

### macOS (Apple Silicon)
```bash
curl -L https://github.com/integritynoble/ChatGPT_PWM/releases/latest/download/chatgpt-pwm-macos-arm64 \
  -o /usr/local/bin/chatgpt-pwm && chmod +x /usr/local/bin/chatgpt-pwm
```

### Linux (x86\_64)
```bash
curl -L https://github.com/integritynoble/ChatGPT_PWM/releases/latest/download/chatgpt-pwm-linux-x86_64 \
  -o /usr/local/bin/chatgpt-pwm && chmod +x /usr/local/bin/chatgpt-pwm
```

### Linux (arm64)
```bash
curl -L https://github.com/integritynoble/ChatGPT_PWM/releases/latest/download/chatgpt-pwm-linux-arm64 \
  -o /usr/local/bin/chatgpt-pwm && chmod +x /usr/local/bin/chatgpt-pwm
```

### Windows
Download [chatgpt-pwm-windows-x86_64.exe](https://github.com/integritynoble/ChatGPT_PWM/releases/latest/download/chatgpt-pwm-windows-x86_64.exe) and add it to your PATH.

### Via pip (any platform with Python 3.9+)
```bash
pip install chatgpt-pwm
```

## Quickstart

Sign in once with your ChatGPT account, then chat:

```bash
chatgpt-pwm login     # opens your browser to sign in with ChatGPT
chatgpt-pwm           # start chatting
```

The `login` command runs the OAuth flow against `auth.openai.com` and stores
your session in `~/.chatgpt-pwm/auth.json`. If you already use Codex, your
existing `~/.codex/auth.json` session is picked up automatically — no separate
login needed.

## Usage

```
chatgpt-pwm [OPTIONS]            # start an interactive chat
chatgpt-pwm login               # sign in with your ChatGPT account
chatgpt-pwm logout              # sign out
chatgpt-pwm whoami              # show the signed-in account

Options:
  -m, --model TEXT      Model to use (default: gpt-5.5)
  -s, --system TEXT     System prompt
  --no-stream           Disable streaming output
  --load PATH           Load a saved conversation file
  -h, --help            Show help
  --version             Show version
```

## In-session commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/clear` | Clear conversation history |
| `/save` | Save current conversation to disk |
| `/load [n]` | Load a saved conversation |
| `/history` | List saved conversations |
| `/model [name]` | Switch model (e.g. `/model gpt-5.4-mini`) |
| `/models` | List all available models |
| `/system [text]` | Set or show system prompt |
| `/tokens` | Show total token usage for this session |
| `/login` | Sign in with your ChatGPT account |
| `/logout` | Sign out |
| `/whoami` | Show signed-in account |
| `/copy` | Copy last response to clipboard |
| `/quit` | Exit |

## Available models

| Model | Description |
|-------|-------------|
| `gpt-5.5` | Default — highest quality |
| `gpt-5.4` | Fast, high quality |
| `gpt-5.4-mini` | Fastest, most economical |

The exact models available depend on your ChatGPT plan.

## How it works

```
chatgpt-pwm  ──►  chatgpt.com/backend-api  ──►  your ChatGPT subscription
             (OAuth access token, refreshed automatically)
```

On `login`, an OAuth 2.0 PKCE flow authenticates you with your ChatGPT account
and stores access/refresh tokens locally. Each chat turn is sent to the ChatGPT
backend with your access token (auto-refreshed when it nears expiry). Your
ChatGPT plan covers usage — there is no API key and no per-token charge.

## Configuration

Model and system-prompt defaults are saved in `~/.chatgpt-pwm/config.json`.
Saved conversations live in `~/.chatgpt-pwm/conversations/`. Auth tokens are in
`~/.chatgpt-pwm/auth.json` (mode `0600`).

## Comparison with Claude and Codex

| | **chatgpt-pwm** | **claude-pwm** | **codex** |
|---|---|---|---|
| Version | v1.2.1 | — | — |
| Provider | OpenAI | Anthropic | OpenAI |
| Models | GPT-5.5 / 5.4 | Claude | GPT-5 family |
| Interface | Conversational chat | Coding agent | Coding agent |
| Auth | ChatGPT subscription (OAuth) | `ANTHROPIC_AUTH_TOKEN=pwm_...` | ChatGPT subscription (OAuth) |
| Billing | PWM balance (`sk-pwm-…` key) | PWM balance | ChatGPT plan |
