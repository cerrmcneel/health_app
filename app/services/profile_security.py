"""Profile security: PIN hashing, HMAC unlock tokens, and brute-force protection."""
import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import defaultdict

from fastapi import HTTPException

from app import config

# Cached signing secret
_SECRET: bytes | None = None
_SECRET_LOCK = threading.Lock()

# In-memory rate limiting: {key: [timestamp, ...]}
_RATE_LOCK = threading.Lock()
_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 600  # 10 minutes


def get_profile_secret() -> bytes:
    """Retrieve or generate the persistent HMAC secret for profile tokens."""
    global _SECRET
    if _SECRET is not None:
        return _SECRET

    with _SECRET_LOCK:
        if _SECRET is not None:
            return _SECRET

        secret_path = config.STORAGE_DIR / ".profile_secret"
        if secret_path.is_file():
            try:
                secret = secret_path.read_bytes().strip()
                if len(secret) >= 16:
                    _SECRET = secret
                    return _SECRET
            except Exception:
                pass

        # Generate fresh 32-byte secret
        config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_bytes(32)
        try:
            secret_path.write_bytes(secret)
        except Exception:
            pass
        _SECRET = secret
        return _SECRET


def hash_pin(pin: str) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256 hash for 4-digit PIN. Returns (hash_hex, salt_hex)."""
    pin_str = str(pin).strip()
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", pin_str.encode("utf-8"), bytes.fromhex(salt), 100_000)
    return key.hex(), salt


def verify_pin(pin: str, pin_hash: str | None, pin_salt: str | None) -> bool:
    """Verify PIN against PBKDF2 hash using constant-time comparison."""
    if not pin or not pin_hash or not pin_salt:
        return False
    pin_str = str(pin).strip()
    try:
        salt_bytes = bytes.fromhex(pin_salt)
        key = hashlib.pbkdf2_hmac("sha256", pin_str.encode("utf-8"), salt_bytes, 100_000)
        return hmac.compare_digest(key.hex(), pin_hash)
    except Exception:
        return False


def sign_profile_token(profile_id: int, expiry_seconds: int = 86400 * 7) -> str:
    """Generate a cryptographically signed unlock token for a profile."""
    expires_at = int(time.time()) + expiry_seconds
    payload = f"{profile_id}.{expires_at}"
    secret = get_profile_secret()
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_profile_token(token: str | None, profile_id: int) -> bool:
    """Validate token format, profile ID, expiration, and HMAC signature."""
    if not token or not isinstance(token, str):
        return False

    parts = token.strip().split(".")
    if len(parts) != 3:
        return False

    pid_str, exp_str, sig = parts
    if not pid_str.isdigit() or not exp_str.isdigit():
        return False

    if int(pid_str) != profile_id:
        return False

    now = int(time.time())
    if int(exp_str) < now:
        return False

    secret = get_profile_secret()
    payload = f"{pid_str}.{exp_str}"
    expected_sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


def check_rate_limit(key: str) -> None:
    """Check if attempts for key exceed limit within window; raises HTTP 429 if exceeded."""
    now = time.time()
    with _RATE_LOCK:
        attempts = [t for t in _FAILED_ATTEMPTS.get(key, []) if now - t < WINDOW_SECONDS]
        _FAILED_ATTEMPTS[key] = attempts
        if len(attempts) >= MAX_ATTEMPTS:
            oldest = attempts[0]
            retry_after = max(1, int(WINDOW_SECONDS - (now - oldest)))
            mins = max(1, math.ceil(retry_after / 60))
            raise HTTPException(
                status_code=429,
                detail=f"Too many incorrect attempts. Please wait {mins} minute(s).",
                headers={"Retry-After": str(retry_after)},
            )


def record_failed_attempt(key: str) -> None:
    """Record a failed PIN attempt."""
    now = time.time()
    with _RATE_LOCK:
        _FAILED_ATTEMPTS[key].append(now)


def record_successful_attempt(key: str) -> None:
    """Clear failed attempts upon successful verification."""
    with _RATE_LOCK:
        _FAILED_ATTEMPTS.pop(key, None)


def reset_rate_limits() -> None:
    """Helper to clear rate limit state (primarily for test isolation)."""
    with _RATE_LOCK:
        _FAILED_ATTEMPTS.clear()
