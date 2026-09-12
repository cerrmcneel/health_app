"""Lightweight shared-secret authentication layer (APP_PASSWORD).

When APP_PASSWORD is not configured in the environment, authentication is
disabled entirely, preserving zero-friction local and single-user LAN deployments.
When configured, requests are gated by a constant-time HMAC-signed session cookie.
"""
import hashlib
import hmac
import html
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

log = logging.getLogger("tracker")

COOKIE_NAME = "auth_session"
SESSION_MAX_AGE = 30 * 86400  # 30 days
_RATE_LIMIT_WINDOW = 15 * 60   # 15 minutes
_MAX_FAILED_ATTEMPTS = 10

_failed_attempts: dict[str, list[float]] = {}

router = APIRouter(tags=["auth"])


def is_auth_enabled() -> bool:
    """True if an access password is set in the runtime environment."""
    return bool(os.getenv("APP_PASSWORD", "").strip())


_key_cache: dict[str, bytes] = {}


def _get_derived_key() -> bytes:
    """Derive the HMAC key from APP_PASSWORD, memoised.

    scrypt at n=16384 costs ~50ms and 16MB. verify_session() runs on every single
    request, so deriving it each time added ~50ms to every API call -- a page load
    makes several -- and handed anyone a trivial CPU-exhaustion lever. The password
    only changes on restart, so the derived key is cached against it.
    """
    pwd = os.getenv("APP_PASSWORD", "").strip()
    if not pwd:
        return b""
    cached = _key_cache.get(pwd)
    if cached is None:
        salt = hashlib.sha256(b"tracker_salt:" + pwd.encode("utf-8")).digest()
        cached = hashlib.scrypt(pwd.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
        _key_cache[pwd] = cached
    return cached


def safe_next(target: str | None) -> str:
    """Constrain a post-login redirect to a path on this site.

    Without this, /login?next=https://evil.example.com turns the login form into
    an open redirect: a convincing phishing link that genuinely lands on the real
    app's login page before bouncing the user off-site. Protocol-relative "//host"
    is rejected too -- browsers treat it as absolute.
    """
    if not target or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


def sign_session(expiry: int) -> str:
    key = _get_derived_key()
    sig = hmac.new(key, str(expiry).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def verify_session(token: str | None) -> bool:
    if not is_auth_enabled():
        return True
    if not token or "." not in token:
        return False
    parts = token.split(".", 1)
    try:
        expiry = int(parts[0])
    except (ValueError, TypeError):
        return False
    if time.time() > expiry:
        return False
    key = _get_derived_key()
    expected_sig = hmac.new(key, str(expiry).encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(parts[1], expected_sig)


def _trust_proxy_headers() -> bool:
    return os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes")


def _client_ip(request: Request) -> str:
    """Identify the caller for rate limiting.

    X-Forwarded-For is only honoured when TRUST_PROXY_HEADERS says a reverse proxy
    is actually in front. Trusting it unconditionally let an attacker defeat the
    login rate limit entirely just by incrementing the header on each attempt --
    every request looked like a different client.
    """
    if _trust_proxy_headers():
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def is_rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _failed_attempts.get(ip, []) if now - t < _RATE_LIMIT_WINDOW]
    _failed_attempts[ip] = attempts
    return len(attempts) >= _MAX_FAILED_ATTEMPTS


def record_failed_attempt(ip: str):
    now = time.time()
    attempts = [t for t in _failed_attempts.get(ip, []) if now - t < _RATE_LIMIT_WINDOW]
    attempts.append(now)
    _failed_attempts[ip] = attempts


def reset_rate_limit(ip: str):
    _failed_attempts.pop(ip, None)


def _is_secure(request: Request) -> bool:
    return (
        request.headers.get("x-forwarded-proto") == "https"
        or request.url.scheme == "https"
    )


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login &middot; LocalPulse</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --line: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #22c55e;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .login-card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 32px;
      width: 100%;
      max-width: 380px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.3);
    }
    h1 { font-size: 20px; margin-bottom: 8px; text-align: center; }
    p { font-size: 13px; color: var(--muted); margin-bottom: 24px; text-align: center; }
    .form-group { margin-bottom: 20px; }
    label { display: block; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); margin-bottom: 6px; }
    input[type="password"] {
      width: 100%;
      padding: 12px 14px;
      background: #0f172a;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: #fff;
      font-size: 16px;
    }
    input[type="password"]:focus {
      outline: none;
      border-color: var(--accent);
    }
    button {
      width: 100%;
      padding: 12px;
      background: var(--accent);
      color: #052e16;
      font-weight: 700;
      font-size: 15px;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: opacity 0.2s;
    }
    button:hover { opacity: 0.9; }
    .err-msg {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid var(--danger);
      color: #fca5a5;
      font-size: 13px;
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 16px;
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="login-card">
    <h1>LocalPulse</h1>
    <p>Enter your household password to access your health data</p>
    __ERROR__
    <form method="POST" action="/login">
      <input type="hidden" name="next" value="__NEXT__">
      <div class="form-group">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" required autofocus placeholder="Enter password...">
      </div>
      <button type="submit">Log In</button>
    </form>
  </div>
</body>
</html>"""


@router.get("/login", include_in_schema=False)
def login_page(request: Request, error: str | None = None, next: str = "/"):
    if not is_auth_enabled():
        return RedirectResponse(next or "/", status_code=303)
    if verify_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(safe_next(next), status_code=303)

    # Both values reach this page from the query string, so both are attacker
    # controlled: unescaped, `?error=<script>` was reflected XSS and `?next="...`
    # broke out of the hidden input's value attribute.
    err_html = f'<div class="err-msg">{html.escape(error)}</div>' if error else ""
    page = (
        LOGIN_HTML
        .replace("__ERROR__", err_html)
        .replace("__NEXT__", html.escape(safe_next(next), quote=True))
    )
    return HTMLResponse(content=page)


@router.post("/login", include_in_schema=False)
async def login(request: Request):
    if not is_auth_enabled():
        return RedirectResponse("/", status_code=303)

    ip = _client_ip(request)
    if is_rate_limited(ip):
        msg = "Too many failed attempts. Please try again in 15 minutes."
        if request.headers.get("accept", "").startswith("application/json") or "application/json" in request.headers.get("content-type", ""):
            return JSONResponse(status_code=429, content={"detail": msg})
        return login_page(request, error=msg)

    # Parse form or JSON body
    provided_password = ""
    next_url = "/"
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            provided_password = str(body.get("password") or "")
            next_url = safe_next(str(body.get("next") or "/"))
        except Exception:
            pass
    else:
        form = await request.form()
        provided_password = str(form.get("password") or "")
        next_url = safe_next(str(form.get("next") or "/"))

    expected_password = os.getenv("APP_PASSWORD", "").strip()
    if not hmac.compare_digest(provided_password.encode("utf-8"), expected_password.encode("utf-8")):
        record_failed_attempt(ip)
        log.warning("Failed login attempt from %s", ip)
        msg = "Incorrect password."
        if "application/json" in content_type or request.headers.get("accept", "").startswith("application/json"):
            return JSONResponse(status_code=401, content={"detail": msg})
        return login_page(request, error=msg, next=next_url)

    reset_rate_limit(ip)
    expiry = int(time.time()) + SESSION_MAX_AGE
    token = sign_session(expiry)

    is_json = "application/json" in content_type or request.headers.get("accept", "").startswith("application/json")
    if is_json:
        resp = JSONResponse(content={"status": "ok", "message": "Authenticated"})
    else:
        resp = RedirectResponse(url=safe_next(next_url), status_code=303)

    resp.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
    )
    return resp


@router.get("/logout", include_in_schema=False)
@router.post("/logout", include_in_schema=False)
def logout(request: Request):
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )
    return resp

