"""Tests for the optional APP_PASSWORD shared-secret authentication layer."""
import os
import pytest
from starlette.testclient import TestClient

from app.auth import COOKIE_NAME, sign_session
from app.main import app


def test_auth_disabled_by_default(client):
    """When APP_PASSWORD is not set in environment, all endpoints work without auth."""
    res = client.get("/api/stats/daily")
    assert res.status_code == 200


def test_auth_blocks_unauthenticated_requests(monkeypatch):
    """When APP_PASSWORD is set, unauthenticated API calls return 401 and pages redirect to /login."""
    monkeypatch.setenv("APP_PASSWORD", "secret_pass_123")
    client = TestClient(app)

    # API calls return 401
    res = client.get("/api/stats/daily")
    assert res.status_code == 401
    assert res.json()["detail"] == "Authentication required."

    # Liveness probe is exempt for container health checks
    live_res = client.get("/api/health/live")
    assert live_res.status_code == 200

    # HTML page navigation redirects to /login
    page_res = client.get("/", follow_redirects=False)
    assert page_res.status_code == 303
    assert "/login" in page_res.headers["location"]


def test_login_flow_and_cookie_verification(monkeypatch):
    """Logging in with the correct password issues a signed cookie that grants access."""
    monkeypatch.setenv("APP_PASSWORD", "supersecret")
    client = TestClient(app)

    # Wrong password fails
    fail_res = client.post("/login", json={"password": "wrongpassword"})
    assert fail_res.status_code == 401
    assert COOKIE_NAME not in client.cookies

    # Right password succeeds and sets session cookie
    success_res = client.post("/login", json={"password": "supersecret"})
    assert success_res.status_code == 200
    assert COOKIE_NAME in client.cookies

    # Authenticated client can now access API
    api_res = client.get("/api/stats/daily")
    assert api_res.status_code == 200

    # Logout clears the cookie
    logout_res = client.get("/logout", follow_redirects=False)
    assert logout_res.status_code == 303
    # Cookie is removed or expired
    assert not client.cookies.get(COOKIE_NAME)


def test_tampered_cookie_is_rejected(monkeypatch):
    """A forged or tampered session cookie must be rejected."""
    monkeypatch.setenv("APP_PASSWORD", "supersecret")
    client = TestClient(app)

    # Set forged cookie
    client.cookies.set(COOKIE_NAME, "9999999999.fake_signature_abc123")
    res = client.get("/api/stats/daily")
    assert res.status_code == 401


def _auth_client(monkeypatch, password="supersecret"):
    monkeypatch.setenv("APP_PASSWORD", password)
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    return TestClient(app)


def test_login_page_escapes_the_error_message(monkeypatch):
    """`error` arrives from the query string, so it is attacker-controlled."""
    client = _auth_client(monkeypatch)
    res = client.get("/login?error=<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in res.text
    assert "&lt;script&gt;" in res.text


def test_login_page_escapes_the_next_parameter(monkeypatch):
    """Unescaped, this broke out of the hidden input's value attribute."""
    client = _auth_client(monkeypatch)
    res = client.get('/login?next=" onfocus=alert(1) x="')
    assert '" onfocus=alert(1) x="' not in res.text


@pytest.mark.parametrize("hostile", [
    "https://evil.example.com/phish",
    "//evil.example.com",
    "http://evil.example.com",
])
def test_login_does_not_redirect_off_site(monkeypatch, hostile):
    """An open redirect here is a phishing link that passes through the real login."""
    client = _auth_client(monkeypatch)
    res = client.post("/login", data={"password": "supersecret", "next": hostile},
                      follow_redirects=False)
    assert res.status_code == 303
    location = res.headers["location"]
    assert "evil.example.com" not in location
    assert location.startswith("/")


def test_login_still_honours_a_local_next(monkeypatch):
    client = _auth_client(monkeypatch)
    res = client.post("/login", data={"password": "supersecret", "next": "/progress"},
                      follow_redirects=False)
    assert res.headers["location"] == "/progress"


def test_rate_limit_survives_spoofed_forwarded_for(monkeypatch):
    """Trusting X-Forwarded-For unconditionally made the limit a no-op."""
    client = _auth_client(monkeypatch, password="rate_limit_pw")
    statuses = [
        client.post("/login", json={"password": "wrong"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
        for i in range(20)
    ]
    assert 429 in statuses, "rotating X-Forwarded-For bypassed the login rate limit"


def test_derived_key_is_cached(monkeypatch):
    """verify_session runs per request; scrypt costs ~50ms uncached."""
    import time as _time
    from app import auth
    monkeypatch.setenv("APP_PASSWORD", "cache_probe_password")
    auth._key_cache.clear()

    start = _time.perf_counter()
    auth._get_derived_key()
    cold = _time.perf_counter() - start

    start = _time.perf_counter()
    for _ in range(50):
        auth._get_derived_key()
    warm_each = (_time.perf_counter() - start) / 50

    assert warm_each < cold / 10, (
        f"key derivation is not cached: {warm_each*1000:.2f}ms per call vs {cold*1000:.1f}ms cold"
    )
