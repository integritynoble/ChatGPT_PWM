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

## 2026-07-02 — Canvas (side-by-side collaborative editor)

**Request:** "Please build Canvas next."

**Built** (`web/index.html` only): ChatGPT's Canvas — a split-view editor where the
model writes/revises documents and code in a right-hand panel while chat continues on
the left. Backend unchanged; the protocol is marker-based: `systemContext()` (when the
Canvas tool is on **or** the convo already has a canvas) instructs the model to wrap
the ENTIRE artifact in `[[canvas: title="…" lang="…"]] … [[/canvas]]`, commentary
outside. The client:

- **Streams live** — `splitCanvas()` splits partial replies during `streamReply()`;
  canvas body paints into the panel as it streams (title bar shows "writing…"), the
  chat bubble gets a compact **canvas card** (icon + title + "Click to open canvas")
  instead of the raw block. Raw markers never render in chat; text outside markers
  shows normally. (Gotcha fixed: on very fast streams the pending rAF paint is
  cancelled in `finally` — the panel now also opens on commit.)
- **Versions** — each model rewrite pushes `c.canvas.versions[]` (v1/v2… with ‹ ›
  nav). Manual edits update the current version in place (debounced persist).
- **Panel** — editable title (rename re-titles the chat card), Edit↔Preview toggle
  (preview = rendered markdown; code renders as a highlighted fence; editor = plain
  textarea, mono for code), Copy, Download (extension from lang: py/js/…; md for
  prose), Close (card reopens). Quick-action chips by kind — doc: Polish/Shorter/
  Longer/Simplify/Add emojis; code: Add comments/Fix bugs/Code review/Optimize — each
  sends a normal user turn; the system context carries the current canvas content, so
  the model replies with a full updated artifact → new version.
- **Entry** — "Canvas — Collaborate on writing and code" row in the **+** menu, plus a
  composer pill while armed; auto-disarms once a canvas is committed (the follow-up
  instruction persists via `c.canvas`). One canvas per conversation, stored on the
  convo (`cg_convos`), survives reload. Mobile: panel goes full-screen.

**Verified:** `node --check` OK; headless (SSE stub streaming canvas markers in 40-char
chunks): 33/33 — parser, + menu/pill, live stream→panel, card in chat, no raw markers,
v1→v2 commit, version nav, edit/save/preview, rename, close/reopen, reload
persistence, code-canvas chips/mono, zero console errors. Regressions green: GPTs
16/16, archive+shortcuts 14/14, voice 20/20. Deployed to both live dirs; live smoke on
both domains (menu row, pill, panel render) clean.

---

## 2026-07-02 — Voice conversation mode

**Request:** "Please build voice conversation mode next."

**Built** (`web/index.html` only — no backend changes): a client-side voice loop in
ChatGPT's full-screen voice UI. Since the backend is a text SSE stream (no realtime
audio model), the loop is: **listen** (Web Speech `SpeechRecognition`, non-continuous
so silence ends the turn) → **send** through the normal `/api/chat` stream (message
persists into the active chat like a typed turn, incl. GPT persona / custom
instructions / memory) → **speak** the reply (`speechSynthesis`, markdown stripped:
code blocks → "code block omitted", links → text/"link") → **listen** again.

- **Entry:** a waveform **Voice mode** button in the composer (shown when the input is
  empty and both speech APIs exist, next to the dictate mic). Gated on a PWM key like
  send. `#voice-overlay`: blue radial-gradient orb with per-state animation
  (listening=pulse, thinking=dim, speaking=bounce, idle=faded), status line
  (Listening…/Thinking…/Speaking…/Muted), live interim transcript, and two round
  controls — **mute** (aborts recognition; unmute resumes) and red **✕ end**
  (also Esc). Recognition is deliberately NOT active while speaking, so the TTS
  audio can't feed back into the mic.
- Exiting re-renders the thread, so the spoken conversation is visible in the chat.

**Verified:** `node --check` OK; headless Chromium with mocked
SpeechRecognition/speechSynthesis + a real SSE `/api/chat` stub — 20/20 checks
(button→overlay→listen, interim transcript, Thinking→Speaking transitions, reply
spoken, auto re-listen, both turns persisted to the convo, mute/unmute, Esc + ✕ end,
zero console errors). GPTs (16) + archive/shortcuts (14) regressions still green.
Deployed to both live dirs; live smoke on both domains: button renders, overlay opens
to Listening…, Esc closes, zero console errors.

**Notes / limits:** needs a browser with `SpeechRecognition` (Chrome/Edge; the button
hides elsewhere); en-US recognition; voice is the browser's default TTS voice — not
OpenAI's neural voices; no barge-in while speaking.

---

## 2026-07-02 — Parity push: GPTs, archive chats, keyboard shortcuts

**Request:** "Make sure this ChatGPT based on PWM is the same as ChatGPT from OpenAI"
— the recurring parity directive. Finished the in-flight GPTs work and closed two more
gaps.

- **GPTs (custom versions of ChatGPT)** — the sidebar "GPTs" placeholder is now real:
  a grid of GPT cards (3 seeded examples: Code Copilot, Writing Coach, Chef) plus
  **+ Create a GPT** → modal with name / description / instructions (edit + delete via
  the card's pencil). Clicking a card starts a chat with that GPT: a pill above the
  composer shows *"Chatting with \<name\>"* (✕ to exit), the convo stores `gptId`, and
  `systemContext()` injects the persona (`You are "<name>", a custom GPT. <instructions>`)
  ahead of custom instructions + memory. Stored in `cg_gpts` (+ `cg_gpts_seeded`).
  (Prior session left this half-built and uncommitted — this session added the missing
  modal HTML, all GPTs CSS, and the `seedGpts()` init call.)
- **Archive chats** — chat ⋯ menu gains **Archive**; archived chats leave the sidebar
  (flag `convo.archived`) and appear in Settings under **"Archived chats"** with
  Unarchive / Delete. Archiving the active chat returns to the landing screen.
- **Keyboard shortcuts** — ChatGPT's set: **Ctrl/⌘+Shift+O** new chat,
  **Ctrl/⌘+Shift+S** toggle sidebar, **Shift+Esc** focus composer,
  **Ctrl/⌘+Shift+⌫** delete current chat (confirm), **Ctrl/⌘+/** shortcuts overlay
  (Esc closes; ⌘ shown on Mac).

**Verified:** `node --check` OK; headless Chromium (local): 16/16 GPTs checks
(seed/create/edit/persist/context-bar/systemContext/ensureConvo), 14/14
archive+shortcuts checks, zero console errors (only the expected `/api/balance` 404 on
the backend-less test server). **Deployed to both live dirs**; live smoke on
chatgpt.comparegpt.io + chatgpt.platformai.org: GPT grid renders, shortcuts open,
zero console errors.

**Still not at full parity** (larger lifts): voice conversation mode, Canvas, code
interpreter, connectors, Sora (placeholder), server-side cross-device sync, shareable
chat links (share uses Web Share/clipboard, no hosted URL).

---

## 2026-07-01 — Parity push: Custom instructions, real Library, real Projects

**Request:** Keep closing the gap to OpenAI's ChatGPT. Turned two decorative
placeholders into real features and added the most-requested missing one.

- **Custom instructions ("Customize ChatGPT")** — Settings gains two fields (what
  ChatGPT should know about you / how it should respond), stored in localStorage and
  sent as a leading **system** message. Backend (`openai_subscription._build_payload`)
  now **appends** a client system message to `_default_instructions()` instead of
  replacing it, so tone/date/formatting survive. Deployed to **both** backends (systemd
  `chatgpt-pwm` :8200 + `chatgpt-pwm-dev` :8201, both restarted).
- **Real Library** — images made with *Create image* now persist in **IndexedDB**
  (localStorage nulls them for quota) and render as a grid (newest first, prompt as
  caption) in the Library view; click → lightbox with Download/Delete. Saved on stream
  completion.
- **Real Projects** — create projects, add/move/remove chats via the chat ⋯ menu, open
  a project to see its chats + start chats scoped to it (sidebar Projects = list, click
  = detail with rename/delete). Persisted in `cg_projects` + `convo.projectId`.

**Verified** (headless, per feature): custom-instructions system message injected +
backend append; Library persist→grid→lightbox; Projects create→assign→list→detail;
zero console errors. Commits `6b5bcf9`, `7943a1a`, `91ecb11`; deployed to both live dirs.

**Still not at full parity** (larger lifts, documented): voice mode, Canvas, code
interpreter, cross-chat memory, connectors (OpenAI Platform/GitHub/Canva/Finances),
Sora/GPTs (still placeholders), server-side cross-device sync.

---

## 2026-06-29 — ChatGPT-style "+" tools menu (photos/files · image · web search · deep research)

**Request:** Replicate OpenAI ChatGPT's composer **+** menu. (Decisions: omit the
connectors — OpenAI Platform/GitHub/Canva/Finances — since they'd need real OAuth
integrations; Deep research = high-reasoning + web search.)

**Built** (`web/index.html`): the **+** button now opens a ChatGPT-style popup with four
rows (icon + title + description) and a bottom **"Type to search plugins, files & skills"**
filter box:
- **Add photos & files** → existing file picker.
- **Create image · "Visualize anything"** → toggles `imageGen` (image_generation tool).
- **Web search · "Find real-time news and info"** → toggles `webSearch` (web_search tool).
- **Deep research · "Multi-step web research"** → new: forces the request to
  `gpt-5.5-thinking` (effort=high) **and** `web_search=true`, with a "Researching…" status.
- Each tool row shows a live **checkmark**; the composer pills (Search/Image + a new
  **Deep research** pill that appears when active) stay in sync via `syncToolUI()`. The
  three tools are mutually exclusive. The bottom box filters rows by label/keywords
  (`filterPlusMenu`), with a "No matches" state. Clicks inside the menu no longer bubble
  to the document close-handler, so the search box is usable and checkmarks persist.

**Verified:** `node --check` OK; headless (local + live) — 4 items render with
descriptions, toggles + checkmarks + pills sync, mutual exclusivity holds, filter works
(`news` → Web search; `zzz` → No matches), zero console errors. Deployed to both live
dirs; confirmed live on chatgpt.comparegpt.io and chatgpt.platformai.org.

---

## 2026-06-29 — Three login methods on ChatGPT (Google / token.comparegpt.io / physicsworldmodel.org)

**Request:** "Make chatgpt.comparegpt.io log in by token.comparegpt.io or
physicsworldmodel.org or google." (Also reported the site "not available" — verified it
was actually up: 200, valid cert, renders, zero console errors; likely a transient
Cloudflare/network blip.)

**Built:** the login modal now shows **three** SSO buttons — *Continue with Google*
(with the Google "G" mark), *…with token.comparegpt.io*, *…with physicsworldmodel.org*
— above the manual `sk-pwm-…` field. All three funnel through the portal's app-login
bridge via `ssoLogin(method)`, which appends `&method=google|portal|pwm`. The portal
login page reads `method` and emphasizes the matching option (Google for google/pwm).
This reuses the portal's existing Google auth rather than duplicating it on ChatGPT.
Paired portal change: `token` branch `feat/app-login-sso` (commit `6ad9eac`).

**Verified:** JS syntax OK; headless — all three buttons render and navigate to the
correct `…/api/auth/app-login?redirect_uri=<origin>/&method=…` URLs.

**Still not deployed** (same ordering: portal endpoint must go live first). Live site
keeps the previous working behavior until then.

---

## 2026-06-29 — Automatic SSO: portal-side app-login endpoint (cross-repo)

**Request:** "Build the portal-side endpoint too" — complete the automatic key handoff
that the portal-login buttons couldn't do alone.

**Built** (spec: `docs/superpowers/specs/2026-06-29-pwm-sso-login-design.md`, REVISION 2).
Unblocking insight: the platform exchange already mints **`sk-pwm-`** keys
(`exchange_internal.py: KEY_PREFIX="sk-pwm-"`) — exactly what ChatGPT-PWM billing
validates — so the portal can mint one for a logged-in user and hand it back.

- **`token/` portal** (separate repo): new `GET /api/auth/app-login` — `redirect_uri`
  exact-match allowlist (→400 otherwise); not-authed → `302 /login?next=…`; authed →
  mint `sk-pwm-` consumer key (label "chatgpt") → `302 <redirect_uri>#pwm_key=…`; mint
  failure → `#sso_error=mint_failed`. Config `app_login_allowed_redirects` = the two
  ChatGPT origins. `Login.vue` `finishLogin()` now honors `?next=` (full nav for
  backend/absolute URLs). 3 new pytest tests, all green; full suite shows only the 11
  pre-existing cookie-over-http failures (unchanged from origin/main); frontend builds.
- **`chatgpt-pwm/`**: `web/index.html` `ssoLogin()` points the token.comparegpt.io
  button at `/api/auth/app-login?redirect_uri=<origin>/`; existing `captureKeyFromUrl()`
  consumes the returned `#pwm_key=`. JS syntax OK; headless click → navigates to the
  correct app-login URL.

**Not deployed / not pushed.** Both changes sit on feature branches. **Deploy order
matters:** the portal endpoint must be live *before* the ChatGPT button repoint (else
the button 404s). Portal deploy is director-gated. Until then, the live ChatGPT login
keeps the previous working behavior (portal buttons → portal root + manual key paste).

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
