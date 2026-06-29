# Design: PWM SSO login + "get a token first" chat gate

**Date:** 2026-06-29
**Component:** `chatgpt-pwm/web` (frontend `index.html` + backend `main.py`)
**Goal:** Let users log in to ChatGPT-PWM directly through the PWM platform
(`token.comparegpt.io` / `physicsworldmodel.org`) via an automatic SSO redirect-back,
instead of hand-pasting an `sk-pwm-…` key. When a logged-out user tries to chat,
send them to `token.comparegpt.io` to get a PWM token first.

## User decisions (captured in brainstorming)

1. **Login mechanism:** Automatic **SSO redirect-back** (no manual copy-paste).
2. **Chat gate:** When a user without a valid key presses send, **redirect the
   current tab** to `https://token.comparegpt.io/`.
3. **Destinations:** **Two buttons** — `token.comparegpt.io` and
   `physicsworldmodel.org`.
4. **Token exchange:** After SSO `validate`, **use the returned `access_token`
   directly** as the billing credential (Bearer token on the existing
   `/pwm-token/*` calls).
5. **Auto-redirect timing:** Only **on send / login-click** (do *not* auto-redirect
   logged-out users on page load — they still see the UI + modal first).

## Auth topology (discovered)

| Piece | Host | Notes |
|---|---|---|
| Token portal (SPA frontend) | `token.comparegpt.io` | Cloudflare; SPA catch-all (all paths → 200). Pages: `/login`, `/get_pwm`, `/token`, `/sso/callback`. Does **not** expose `/api/...`. |
| PWM platform API | `physicsworldmodel.org` → `172.17.0.1:8101` | Internal API reachable (openapi 286 KB). **Public host returns 502 right now.** |
| SSO issue | `GET /api/v1/auth/sso/issue?redirect_uri=…` | Issues an SSO token; redirects back (param `token`, possibly `access_token`). Requires a logged-in platform session. |
| Validate/exchange | `POST /api/v1/auth/validate {sso_token}` → `AuthResponse{success, access_token, valid, user}` | Exchanges the SSO token for a session `access_token`. |
| Billing gate (current) | `GET /api/v1/pwm-token/balance`, `POST /api/v1/pwm-token/spend`, `Authorization: Bearer <key>` | Today this `<key>` is an `sk-pwm-…` API key; per decision #4 we will pass the SSO `access_token` here instead. |

## Flow

```
[ChatGPT-PWM modal] --click "Continue with <portal>"-->
  <SSO_ISSUE_URL>?redirect_uri=https://<this-host>/sso/callback
    --(user already logged in at portal)-->
  https://<this-host>/sso/callback?token=<sso_token>
    --backend POST /api/v1/auth/validate {sso_token}-->
  AuthResponse{ access_token }
    --302--> https://<this-host>/#sso=<access_token>
  [SPA reads #sso, stores as active key, clears hash, refreshes balance]
```

Chat gate (decision #2 + #5): on **send** with no valid key →
`window.location.href = "https://token.comparegpt.io/"`.

## Changes

### Frontend (`index.html`)
- **Login modal:** above the existing "Access key" field, add two primary buttons:
  - "Continue with token.comparegpt.io" → `SSO_ISSUE_URL_COMPAREGPT`
  - "Continue with physicsworldmodel.org" → `SSO_ISSUE_URL_PWM`
  Keep the manual `sk-pwm-…` field below as a fallback ("or paste a key").
- **SSO return handler:** on load, if `location.hash` matches `#sso=<token>`, store it
  via the existing `setKey()` path, strip the hash, close the modal, refresh balance.
- **Chat gate:** in the send handler, if `!getKey()` (or balance invalid), set
  `window.location.href = COMPAREGPT_GET_TOKEN_URL` instead of just opening the modal.

### Backend (`main.py`)
- **New route `GET /sso/callback`:** read `token` (fallback `access_token`) from query;
  `POST {PWM_PLATFORM_URL}/api/v1/auth/validate {sso_token: token}`; on
  `success && access_token`, `RedirectResponse` to `/#sso=<access_token>`; on failure
  redirect to `/#sso_error=1`. Fail-closed to the modal on any exception.
- **Billing credential:** no code change required if the SSO `access_token` is accepted
  as `Authorization: Bearer` by `/pwm-token/balance` + `/pwm-token/spend`
  (`pwm_billing.py` already sends the stored key verbatim as the bearer).

### Config (new constants)
- Frontend: `SSO_ISSUE_URL_COMPAREGPT`, `SSO_ISSUE_URL_PWM`, `COMPAREGPT_GET_TOKEN_URL`
  (= `https://token.comparegpt.io/`).
- Backend: reuse `PWM_PLATFORM_URL` for the server-side `validate` call.

## Error handling
- `validate` returns `success:false` / non-200 / timeout → redirect `/#sso_error=1`;
  SPA shows a toast ("Login failed — try again or paste your key") and opens the modal.
- SSO `access_token` rejected by billing (401 on balance) → existing gate shows
  "Invalid PWM key"; user falls back to manual key or retries SSO.
- `pwm_billing.check_balance` already fails **open** on platform outages, so a 502 on
  `/pwm-token/*` never hard-blocks a chat (matches current behaviour).

## Verification plan
- `node --check` on extracted inline JS.
- Backend: unit-hit `/sso/callback?token=FAKE` → expect redirect to `/#sso_error=1`
  (validate rejects fake token).
- Manual round-trip once the public API is reachable + a logged-in portal session:
  click button → land back logged in → send a message → streams + bills.
- Headless screenshot of the modal with the two new buttons.

## Open external dependencies (BLOCKERS for a verified round-trip)
1. **Exact public SSO-issue URL + redirect param for each button.** The API path
   `/api/v1/auth/sso/issue` is only on the platform host; `token.comparegpt.io` is a
   SPA and may front it under a different route. Need the canonical entry URL(s).
2. **`physicsworldmodel.org` currently 502s publicly** — must be healthy for the
   server-side `validate` call and the issue redirect to work end-to-end.
3. **Confirm `/pwm-token/*` accepts the SSO `access_token`** as a bearer (decision #4
   assumes yes; if no, switch to minting an `sk-pwm-…` key via
   `/api/v1/auth/api-key/generate`).

These are captured as constants/config so the buildable parts (UI, callback route,
chat-gate redirect, SSO return handler) can ship and be unit-verified now, with the
three values filled in to complete the live round-trip.

---

## REVISION (2026-06-29, after reading platform + portal source)

Reading `pwm_nonprofit_dev/platform/.../routers/auth.py` and `token/backend/app/...`
changed the picture. The fully-automatic redirect-back is **not implementable from
`chatgpt-pwm` alone**:

- **`/sso/issue` allowlists exactly one `redirect_uri`** — `token.comparegpt.io/api/auth/pwm-sso`
  (`config.py: SSO_TOKEN_PORTAL_REDIRECT_URI`); any other `redirect_uri` → 400. So
  ChatGPT-PWM cannot be the SSO target. The **token portal** is the sole SSO consumer.
- **The portal session cookie is host-scoped to `token.comparegpt.io`**
  (`token/backend/app/config.py: cookie_domain = "token.comparegpt.io"`, not
  `.comparegpt.io`), so `chatgpt.comparegpt.io` cannot read it cross-subdomain.

A true auto-handoff would therefore require changes to **other deployed services**
(broaden the cookie to `.comparegpt.io` + a CORS key endpoint, OR add an app-login
redirect endpoint to the portal + allowlist our `redirect_uri` on the platform).
That is out of scope for a self-contained `chatgpt-pwm` change and touches production
auth, so it is deferred.

### Implemented scope (self-contained, satisfies the original request)
1. **Login modal — two portal buttons:** "Log in / get token at token.comparegpt.io"
   → opens `https://token.comparegpt.io/`; "physicsworldmodel.org" → opens
   `https://physicsworldmodel.org/`. Helper line: log in there, copy your `sk-pwm-…`
   key, paste below. Manual key field retained as the primary entry.
2. **Chat gate:** send with no stored key → `window.location.href =
   "https://token.comparegpt.io/"` (current-tab redirect, per decision #2).
3. **Forward-compatible return handler:** on load, if the URL carries
   `#pwm_key=…`/`#key=…`/`?pwm_key=…` (an `sk-pwm-…` value), store it via `setKey()`,
   strip it from the URL, and refresh balance — so if the portal later adds an
   app-callback that redirects back with the key, it works with no further change here.

Backend `/sso/callback` route and the access_token-as-credential path are **deferred**
until the portal/platform expose an app-login; they are not built now.

---

## REVISION 2 (2026-06-29) — portal-side app-login BUILT

Built the missing portal endpoint so the handoff is now genuinely automatic. The key
insight that unblocked it: the platform's exchange already mints **`sk-pwm-`** keys
(`exchange_internal.py`: `KEY_PREFIX = "sk-pwm-"`) — exactly what ChatGPT-PWM billing
validates — so the portal can mint one for a logged-in user and hand it back.

**Flow (implemented):**
```
[ChatGPT modal] "Continue with token.comparegpt.io" → ssoLogin()
  → https://token.comparegpt.io/api/auth/app-login?redirect_uri=<chatgpt-origin>/
    ├─ logged in  → mint sk-pwm- key (consumer_api_key, label "chatgpt")
    │               → 302 <chatgpt-origin>/#pwm_key=sk-pwm-…
    │               → captureKeyFromUrl() stores it, scrubs the URL → logged in
    └─ not logged → 302 /login?next=<app-login-url> → SPA login → finishLogin()
                    follows next back to /api/auth/app-login → mint → back to ChatGPT
```

**Changes by repo:**
- `token/` (portal) — `routers/auth.py`: new `GET /api/auth/app-login` (redirect_uri
  allowlist → 400; not-authed → `/login?next=`; authed → mint + `#pwm_key=`; mint
  failure → `#sso_error=mint_failed`). `config.py`:
  `app_login_allowed_redirects` (the two ChatGPT origins). `frontend/src/views/Login.vue`:
  `finishLogin()` honors `?next=` (full nav for backend/absolute URLs, SPA router
  otherwise). Tests: 3 new in `tests/test_auth_routes.py`, all green.
- `chatgpt-pwm/` — `web/index.html`: `ssoLogin()` points the token.comparegpt.io
  button at `/api/auth/app-login?redirect_uri=<origin>/`. The existing
  `captureKeyFromUrl()` already consumes the returned `#pwm_key=`.

**Security:** the minted key rides in the URL **fragment** (not query — not sent to
servers/logs) and is scrubbed on arrival. The `redirect_uri` exact-match allowlist is
the control preventing key delivery to an attacker origin.

**Deploy ordering (IMPORTANT):** the portal endpoint must go live **before** the
ChatGPT button repoint, or the button 404s. Portal deploy is director-gated (per
`token/SESSION_HISTORY.md`). Both changes are committed on feature branches, unpushed
and not deployed, pending that sequence. Known limitation: each app-login mints a fresh
`sk-pwm-` key (the platform mint isn't idempotent); keys are labelled "chatgpt" and
revocable in the portal Use tab.
