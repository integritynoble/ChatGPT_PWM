"""
ChatGPT subscription auth — OAuth token storage, refresh, and login.

Authenticates to OpenAI with ChatGPT-plan OAuth tokens (the same scheme Codex
uses) instead of a billed API key. Tokens are stored in a Codex-style
``auth.json``. The login command runs the OAuth 2.0 PKCE flow against
``auth.openai.com`` with a local callback server, exactly like ``codex login``.

No token material is ever printed.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Optional

import httpx

# ── Constants (mirror Codex) ──────────────────────────────────────────────
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_ISSUER = "https://auth.openai.com"
OAUTH_AUTHORIZE_URL = f"{OAUTH_ISSUER}/oauth/authorize"
OAUTH_TOKEN_URL = f"{OAUTH_ISSUER}/oauth/token"
OAUTH_SCOPE = "openid profile email offline_access api.connectors.read api.connectors.invoke"
ORIGINATOR = "codex_cli_rs"
CALLBACK_PORT = 1455
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/auth/callback"

# Primary store for chatgpt-pwm; falls back to the Codex auth file if present.
AUTH_FILE = Path(
    os.environ.get("CHATGPT_AUTH_FILE", str(Path.home() / ".chatgpt-pwm" / "auth.json"))
)
CODEX_AUTH_FILE = Path.home() / ".codex" / "auth.json"


class AuthError(RuntimeError):
    """Raised when no usable ChatGPT subscription token is available."""


# ── JWT helpers (no signature verification; only claim extraction) ─────────
def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _jwt_claims(token: str) -> dict:
    try:
        return json.loads(_b64url_decode(token.split(".")[1]))
    except Exception:
        return {}


def _jwt_exp(token: str) -> Optional[int]:
    exp = _jwt_claims(token).get("exp")
    return int(exp) if exp else None


def _jwt_account_id(token: str) -> Optional[str]:
    auth = _jwt_claims(token).get("https://api.openai.com/auth", {})
    return auth.get("chatgpt_account_id") if isinstance(auth, dict) else None


# ── Storage ───────────────────────────────────────────────────────────────
def _active_auth_file() -> Optional[Path]:
    if AUTH_FILE.exists():
        return AUTH_FILE
    if CODEX_AUTH_FILE.exists():
        return CODEX_AUTH_FILE
    return None


def load_auth() -> dict:
    path = _active_auth_file()
    if not path:
        raise AuthError(
            "Not logged in. Run `chatgpt-pwm login` to sign in with your ChatGPT account."
        )
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        raise AuthError(f"Could not parse {path}: {e}") from e


def save_auth(auth: dict) -> None:
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTH_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(auth, indent=2))
    os.replace(tmp, AUTH_FILE)
    try:
        os.chmod(AUTH_FILE, 0o600)
    except OSError:
        pass


def logout() -> bool:
    if AUTH_FILE.exists():
        AUTH_FILE.unlink()
        return True
    return False


def is_logged_in() -> bool:
    return _active_auth_file() is not None


def account_email() -> Optional[str]:
    try:
        auth = load_auth()
    except AuthError:
        return None
    tokens = auth.get("tokens") or {}
    for tok in (tokens.get("id_token"), tokens.get("access_token")):
        if isinstance(tok, str):
            email = _jwt_claims(tok).get("email")
            if email:
                return email
    return None


# ── Token refresh ─────────────────────────────────────────────────────────
def _refresh(auth: dict) -> dict:
    tokens = auth.get("tokens") or {}
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise AuthError("Session expired. Run `chatgpt-pwm login` again.")
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/json"},
            json={
                "client_id": OAUTH_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid profile email",
            },
        )
    if resp.status_code != 200:
        raise AuthError("Session refresh failed. Run `chatgpt-pwm login` again.")
    data = resp.json()
    tokens["access_token"] = data.get("access_token", tokens.get("access_token"))
    if data.get("refresh_token"):
        tokens["refresh_token"] = data["refresh_token"]
    if data.get("id_token"):
        tokens["id_token"] = data["id_token"]
    auth["tokens"] = tokens
    auth["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_auth(auth)
    return auth


def get_access_token() -> tuple[str, str]:
    """Return (access_token, account_id), refreshing if near expiry."""
    auth = load_auth()
    tokens = auth.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise AuthError("Not logged in. Run `chatgpt-pwm login`.")

    exp = _jwt_exp(access_token)
    if exp is None or exp - time.time() < 300:
        auth = _refresh(auth)
        tokens = auth.get("tokens") or {}
        access_token = tokens["access_token"]

    account_id = (
        tokens.get("account_id")
        or _jwt_account_id(access_token)
        or _jwt_account_id(tokens.get("id_token", ""))
        or auth.get("account_id")
    )
    if not account_id:
        raise AuthError("Could not determine ChatGPT account id. Run `chatgpt-pwm login` again.")
    return access_token, account_id


# ── PKCE login flow ───────────────────────────────────────────────────────
def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


_SUCCESS_HTML = b"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Signed in</title><style>body{font-family:-apple-system,sans-serif;background:#212121;
color:#ececec;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.box{text-align:center}.c{color:#10a37f;font-size:48px}</style></head>
<body><div class="box"><div class="c">&#10003;</div><h2>Signed in to ChatGPT-PWM</h2>
<p>You can close this tab and return to your terminal.</p></div></body></html>"""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result = {
            "code": (params.get("code") or [None])[0],
            "state": (params.get("state") or [None])[0],
            "error": (params.get("error") or [None])[0],
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_SUCCESS_HTML)

    def log_message(self, *args):  # silence
        pass


def login(open_browser: bool = True, timeout: int = 300) -> str:
    """
    Run the OAuth PKCE flow. Returns the signed-in account email (or "").
    Raises AuthError on failure.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    params = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": OAUTH_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": ORIGINATOR,
    }
    auth_url = f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    try:
        server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    except OSError as e:
        raise AuthError(
            f"Could not bind callback port {CALLBACK_PORT} ({e}). "
            "Close anything using it (e.g. codex login) and retry."
        ) from e
    server.timeout = timeout
    _CallbackHandler.result = {}

    print("\nOpen this URL in your browser to sign in:\n")
    print(f"  {auth_url}\n")
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

    def _serve():
        while not _CallbackHandler.result:
            server.handle_request()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    t.join(timeout)
    server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise AuthError("Login timed out waiting for the browser callback.")
    if result.get("error"):
        raise AuthError(f"Login failed: {result['error']}")
    if result.get("state") != state:
        raise AuthError("Login failed: state mismatch (possible CSRF).")
    code = result.get("code")
    if not code:
        raise AuthError("Login failed: no authorization code returned.")

    # Exchange the code for tokens.
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urllib.parse.urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": OAUTH_CLIENT_ID,
                    "code_verifier": verifier,
                }
            ),
        )
    if resp.status_code != 200:
        raise AuthError(f"Token exchange failed ({resp.status_code}).")
    data = resp.json()
    id_token = data.get("id_token", "")
    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    account_id = _jwt_account_id(access_token) or _jwt_account_id(id_token)

    auth = {
        "auth_mode": "chatgpt",
        "tokens": {
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_auth(auth)

    email = _jwt_claims(id_token).get("email") or _jwt_claims(access_token).get("email") or ""
    return email
