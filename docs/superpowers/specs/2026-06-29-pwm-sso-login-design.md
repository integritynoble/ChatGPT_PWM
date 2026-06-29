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
