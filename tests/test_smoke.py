"""Durable no-network smoke test for the chatgpt-pwm web app.

The regression 'sweeps' referenced in SESSION_HISTORY.md were ad-hoc scripts that
were never committed. This is the first checked-in test: it boots the FastAPI app
with a TestClient (no network, no real ChatGPT calls) and asserts the surface is
intact — the app imports, key routes are registered, health is green, and the
generation endpoint is auth-gated.

Run:  cd chatgpt-pwm && PYTHONPATH=web:. python3 -m pytest tests/test_smoke.py -v
"""
import os, sys, pathlib
# Force the auth gate ON *before* importing the app (PWM_KEY_REQUIRED is read at
# import time). This keeps the smoke test fully offline: a keyless /api/chat is
# rejected with 401 and never reaches the real ChatGPT subscription. Production
# runs with PWM_KEY_REQUIRED=1; local/dev defaults to 0 (open access).
os.environ["PWM_KEY_REQUIRED"] = "1"

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
sys.path.insert(0, str(WEB))
sys.path.insert(0, str(WEB.parent))

import pytest
from fastapi.testclient import TestClient
import main as webmain

client = TestClient(webmain.app)

KEY_ROUTES = ["/health", "/api/chat", "/api/models", "/api/run", "/api/tasks", "/api/files"]


def test_app_imports():
    assert webmain.app.title == "ChatGPT-PWM"


@pytest.mark.parametrize("path", KEY_ROUTES)
def test_key_route_registered(path):
    assert path in {r.path for r in webmain.app.routes}, f"{path} not registered"


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200


def test_models_ok():
    r = client.get("/api/models")
    assert r.status_code == 200


def test_chat_requires_auth():
    # With PWM_KEY_REQUIRED=1 (set above), a keyless request is rejected with 401
    # and never reaches the subscription -> no network, deterministic.
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"
