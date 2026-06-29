# Session history

A running log of working sessions on **chatgpt-pwm** (the ChatGPT experience for the
PWM exchange — CLI + web replica). Newest entries first. Modeled on the sibling
`claude-pwm` reference repo.

---

## Deploy targets (IMPORTANT — there are TWO live web backends)

The web UI (`chatgpt-pwm/web/index.html`) is served by **two independent backends**
behind nginx. A deploy must copy `index.html` to **both** live dirs or the two public
domains will drift out of sync (this bit us on 2026-06-29).

| Public domain | nginx → port | Live dir (deploy here) | Backend |
|---|---|---|---|
| `chatgpt.comparegpt.io` | `127.0.0.1:8200` | `/home/spiritai/pwm/chatgpt-web` | `chatgpt-pwm.service` (systemd, `WorkingDirectory=…/chatgpt-web`) |
| `chatgpt.platformai.org` | `127.0.0.1:8201` | `/home/spiritai/pwm/chatgpt-web-dev` | standalone `uvicorn main:app … --port 8201` (cwd `…/chatgpt-web-dev`) |

Canonical git source is `chatgpt-pwm/web/`. To deploy a UI change to both domains:

```bash
cp chatgpt-pwm/web/index.html /home/spiritai/pwm/chatgpt-web/index.html       # → chatgpt.comparegpt.io
cp chatgpt-pwm/web/index.html /home/spiritai/pwm/chatgpt-web-dev/index.html   # → chatgpt.platformai.org
```

No restart needed for `index.html` changes — `main.py` re-reads the file on every
`GET /`. **Backend** (`main.py` / `*.py`) changes still need a restart:
`systemctl restart chatgpt-pwm` for the 8200 backend; the 8201 uvicorn must be
restarted by its own process manager. nginx for both domains sets `proxy_buffering off`
/ `proxy_cache off` (SSE-friendly), so there's no edge cache to bust.

---

## 2026-06-29 — Portal login buttons + "get a token first" chat gate

**Request:** Let ChatGPT-PWM users log in directly via `token.comparegpt.io` /
`physicsworldmodel.org`; and when a logged-out user tries to chat, send them to
`https://token.comparegpt.io/` to get a PWM token first.

**Design + investigation** (spec: `docs/superpowers/specs/2026-06-29-pwm-sso-login-design.md`).
Read the platform (`pwm_nonprofit_dev`) and portal (`token/`) source to ground the
flow. Key constraints discovered: the platform's `/api/v1/auth/sso/issue` allowlists a
**single** `redirect_uri` (`token.comparegpt.io/api/auth/pwm-sso`), and the portal's
session cookie is host-scoped to `token.comparegpt.io` (not `.comparegpt.io`). So a
**fully-automatic** key handoff can't be done from `chatgpt-pwm` alone — it needs a
portal-side app-callback (deferred, would touch production auth in another repo).

**What shipped** (self-contained, `web/index.html` only — satisfies the request):
- **Login modal:** two portal buttons — *Continue with token.comparegpt.io* and
  *Continue with physicsworldmodel.org* — above an "or paste your key" divider and the
  existing `sk-pwm-…` field. Buttons redirect to the portal with a forward-compat
  `?return=<chatgpt-url>`. Hidden in full **Settings** mode.
- **Chat gate:** pressing send with no stored key now redirects the current tab to
  `https://token.comparegpt.io/` (toast: "Get a PWM token first…") instead of just
  reopening the modal. (Other entry points unchanged; no auto-redirect on page load.)
- **Forward-compatible return handler:** on load, a key arriving as
  `#pwm_key=…`/`#key=…`/`?pwm_key=…` (must match `sk-pwm-`) is stored and scrubbed from
  the URL — so if the portal later adds an app-callback, login completes with no
  further change here.

**Deploy / verify**
- `node --check` → OK; headless Chromium against a temp server: both buttons render,
  return-handler captures + scrubs both hash and query forms, chat-gate redirect hits
  `token.comparegpt.io/?return=…`, portal buttons hidden in Settings, zero console errors.
- Deployed to **both** live dirs (`chatgpt-web` + `chatgpt-web-dev`); verified the two
  buttons render live on `chatgpt.comparegpt.io` and `chatgpt.platformai.org`.

---

## 2026-06-29 — PWM-token onboarding reminder in the login modal

**Request:** Resume the ChatGPT session, record history here, and keep PWM ChatGPT at
parity with the real OpenAI ChatGPT. New ask this session: when users enter ChatGPT of
PWM, remind them to go to **token.comparegpt.io** to get a PWM token first.

**Starting state**
- Service healthy: `chatgpt-pwm.service` active, `GET /` → 200 on `127.0.0.1:8200`
  (`WorkingDirectory=/home/spiritai/pwm/chatgpt-web`); canonical git source is
  `chatgpt-pwm/web/index.html`.
- UI already at strong parity (landing layout, model menu incl. "ChatGPT Thinking",
  search/image tools, reasoning display, vision/PDF/DOCX upload, mobile polish — see
  recent commits). The login modal placeholder is `sk-pwm-…`.

**What changed**
- **Login modal now onboards new users to the PWM token.** The "Log in to ChatGPT"
  description (shown whenever no key is set) reads:
  *"Don't have a PWM token? Get one at **token.comparegpt.io**. Then enter your access
  key below to start chatting."* — with `token.comparegpt.io` as a clickable link
  (opens in a new tab). Applied in two places so it survives a re-render:
  the static `#settings-desc` markup and the login branch of `openSettingsModal()`
  (the full **Settings** view keeps its own "Manage your account…" copy).

**Deploy / verify**
- `node --check` on the extracted inline script → syntax OK.
- **Discovered there are TWO live web backends** (see the "Deploy targets" reference
  block at the top of this file). The first deploy only updated `chatgpt-web` (port
  8200 → `chatgpt.comparegpt.io`); `chatgpt.platformai.org` kept showing the old copy
  because it's a *separate* uvicorn on port 8201 serving `chatgpt-web-dev`. Confirmed
  that dev copy was byte-identical to the new file except for the reminder edit, then
  synced `index.html` to **both** live dirs.
- Headless Chromium against **both** public domains: login modal shows the new copy and
  `#settings-desc a` resolves to `https://token.comparegpt.io`. Screenshots captured.
- Shipped as commit `5893770` (pushed to `origin/main`,
  integritynoble/ChatGPT_PWM); this deploy-targets note is a follow-up commit.

---

## 2026-06-26 — Web UI brought to real-ChatGPT parity

**Request:** "Resume the chatgpt session, refer to claude-pwm, record the history here,
and make the PWM ChatGPT the same as the real ChatGPT from OpenAI." Plus: use
`sk-pwm-…` as the PWM-key placeholder/reminder.

**Starting state**
- Web service live: `chatgpt-pwm.service` → `uvicorn main:app` on `127.0.0.1:8200`,
  fronted by nginx at **https://chatgpt.platformai.org** (Certbot TLS, SSE-friendly
  proxy: `proxy_buffering off`).
- systemd `WorkingDirectory=/home/spiritai/pwm/chatgpt-web` (the **live deploy copy**).
  Git-tracked canonical source is `chatgpt-pwm/web/`. The two `index.html` /
  `main.py` / `openai_subscription.py` were identical at session start.
- Backend generation confirmed working: streamed real **GPT-5.5** from the pooled
  **ChatGPT subscription** (OAuth in `~/.codex/auth.json`). Billing gated by a PWM key
  (`PWM_KEY_REQUIRED=1`) checked against the PWM platform at `127.0.0.1:8101`.
- UI was already a solid dark-mode replica (sidebar+history, model dropdown, streaming
  markdown, code copy, KaTeX, regenerate, PWM-key modal).

**What changed (this session)** — full rewrite of `web/index.html` (pure client-side
SPA; backend `main.py` / API contract unchanged). Closed the gap to chatgpt.com across
all four areas:

- *Chat UX:* real in-sidebar **search** (filters by title + message text), **edit a
  user message** (truncates the thread at that turn and re-streams), **rename / delete**
  chats via a per-item ⋯ menu, auto chat titles from the first message, floating
  **scroll-to-bottom** button, stop-generation button.
- *Account / auth:* bottom-left **account menu** (key state + live balance, Settings,
  theme toggle, Log out) and a top-right avatar that opens it; a real **Settings** modal
  (PWM key, appearance, default model, delete-all-chats). PWM-key placeholder is now
  **`sk-pwm-…`** (matches prod, which mints `sk-pwm-` keys).
- *Reasoning & richness:* animated **thinking** dots before the first token,
  **regenerate-with-model-picker** dropdown, per-message **timestamps**, graceful
  empty/error states ("No response.", toast on stream error).
- *Visual polish:* **light + dark + system theme** (CSS-variable palettes, follows
  `prefers-color-scheme`), and the iconic **landing layout** — greeting + composer +
  suggestion chips vertically centered on an empty chat, composer drops to the bottom
  once the conversation starts.

State persists in `localStorage` (`cg_convos`, `cg_model`, `cg_theme`, `cg_pwm_key`).

**Deploy mechanic (important):** `main.py` reads `index.html` fresh on every `GET /`,
so deploying the UI is just copying the file to the live dir — **no service restart**:

```bash
cp chatgpt-pwm/web/index.html /home/spiritai/pwm/chatgpt-web/index.html
```

(Backend/`main.py` changes still need `systemctl restart chatgpt-pwm`.)

**Verification**
- `node --check` on the extracted inline script → syntax OK.
- Live `GET /` serves the new markup (theme/edit/scroll/`sk-pwm` markers present);
  `<title>ChatGPT</title>` intact.
- Backend streaming path intact: live `/api/chat` returns the PWM-key gate as designed
  (`Invalid PWM key` for a fake key); raw subscription generation re-confirmed.
- Headless Chromium (Playwright) render: **zero console errors**; model menu opens,
  Settings modal opens, search filters to the right count + shows "No chats found",
  light/dark themes render, KaTeX + code-block copy render. Screenshots captured.

**Known limits / deviations**
- Auth is a PWM key (billed to PWM balance), not an OpenAI account login — by design.
- Attachments / image input are stubbed (toast); voice not implemented.
- Chat titles are derived client-side from the first message (no model-generated title).
- History is per-browser `localStorage` (no server-side sync across devices).
