# chatgpt-pwm

ChatGPT CLI powered by PWM tokens — the same conversation experience as ChatGPT from OpenAI, running in your terminal and authenticated with your PWM key.

## Features

- **Streaming responses** with real-time output
- **Syntax-highlighted code blocks** via Rich markdown rendering
- **Multi-turn conversations** with full history context
- **Conversation save/load** — resume any previous chat
- **Model switching** — gpt-4o, gpt-4o-mini, o3, o3-mini, and more
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

### macOS (Intel)
```bash
curl -L https://github.com/integritynoble/ChatGPT_PWM/releases/latest/download/chatgpt-pwm-macos-x86_64 \
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
Download [chatgpt-pwm-windows-x86_64.exe](https://github.com/integritynoble/ChatGPT_PWM/releases/latest/download/chatgpt-pwm-windows-x86_64.exe) and add it to your PATH. Rename to `chatgpt-pwm.exe` for convenience.

### Via pip (any platform with Python 3.9+)
```bash
pip install chatgpt-pwm
```

## Use with PWM exchange

```bash
export OPENAI_API_KEY=pwm_your_key_here
chatgpt-pwm
```

The tool automatically routes through the PWM exchange at `https://physicsworldmodel.org/api/v1/exchange/openai`, which bills your PWM token balance and forwards requests to OpenAI.

You can also use a direct OpenAI API key:
```bash
export OPENAI_API_KEY=sk-...
chatgpt-pwm
```

## Usage

```
chatgpt-pwm [OPTIONS]

Options:
  -m, --model TEXT      Model to use (default: gpt-4o)
  -s, --system TEXT     System prompt
  --no-stream           Disable streaming output
  --api-key TEXT        API key (or set OPENAI_API_KEY)
  --base-url TEXT       Override API base URL (or set OPENAI_BASE_URL)
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
| `/model [name]` | Switch model (e.g. `/model gpt-4o-mini`) |
| `/models` | List all available models |
| `/system [text]` | Set or show system prompt |
| `/tokens` | Show total token usage for this session |
| `/copy` | Copy last response to clipboard |
| `/quit` | Exit |

## Available models

| Model | Description |
|-------|-------------|
| `gpt-4o` | Default — fast, multimodal, best quality |
| `gpt-4o-mini` | Fast and affordable |
| `gpt-4-turbo` | GPT-4 Turbo |
| `gpt-4` | GPT-4 classic |
| `gpt-3.5-turbo` | Fastest, most economical |
| `o3` | Reasoning model |
| `o3-mini` | Compact reasoning model |
| `o1` | First-gen reasoning model |
| `o1-mini` | Compact o1 |

## Configuration

Settings are saved in `~/.chatgpt-pwm/config.json`:

```json
{
  "model": "gpt-4o",
  "system_prompt": "You are ChatGPT...",
  "stream": true
}
```

Saved conversations are stored in `~/.chatgpt-pwm/conversations/`.

## How PWM exchange works

```
chatgpt-pwm  ──►  physicsworldmodel.org/api/v1/exchange/openai  ──►  api.openai.com
                  (deducts PWM tokens from your balance)
```

Your PWM token (`pwm_...`) is passed as the `Authorization` header. The exchange verifies your balance, deducts the cost, and forwards the request to OpenAI with the platform's API key. Response streams back end-to-end.

## Comparison with Claude and Codex

| | **chatgpt-pwm** | **claude-pwm** | **codex** (fork) |
|---|---|---|---|
| Provider | OpenAI | Anthropic | OpenAI |
| Models | GPT-4o, o3, ... | Claude 3.5/4 | codex-1, o3 |
| Interface | Conversational chat | Coding agent | Coding agent |
| Auth | `OPENAI_API_KEY=pwm_...` | `ANTHROPIC_AUTH_TOKEN=pwm_...` | `OPENAI_API_KEY=pwm_...` |
| Exchange URL | `.../exchange/openai` | `.../exchange/anthropic` | `.../exchange/openai` |
