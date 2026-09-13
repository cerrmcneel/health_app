"""Profile resolution and database helpers for multi-profile support."""
import re
import sqlite3
from fastapi import HTTPException, Request

from app.services.profile_security import verify_profile_token


def slugify(text: str) -> str:
    """Generate a clean URL/path-safe slug from a profile name."""
    s = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[-\s]+", "-", s) or "user"


def sanitize_profile(prof: dict) -> dict:
    """Strip secret hash/salt and add has_pin boolean."""
    data = dict(prof)
    data["has_pin"] = bool(data.get("pin_hash"))
    data.pop("pin_hash", None)
    data.pop("pin_salt", None)
    return data


def get_profile_id(request: Request, conn: sqlite3.Connection, check_pin: bool = True) -> int:
    """Extract and validate the active profile ID from headers, query params, or cookies.
    If check_pin is True and the profile has a PIN configured, verifies the unlock token.
    """
    raw = (
        request.headers.get("X-Profile-ID")
        or request.query_params.get("profile_id")
        or request.cookies.get("active_profile_id")
    )
    pid = None
    pin_hash = None

    if raw:
        try:
            candidate_id = int(raw)
            row = conn.execute("SELECT id, pin_hash FROM profiles WHERE id = ?", (candidate_id,)).fetchone()
            if row:
                pid = row["id"]
                pin_hash = row["pin_hash"]
        except (ValueError, TypeError):
            pass

    if pid is None:
        # Fallback to default profile, or lowest ID
        row = conn.execute("SELECT id, pin_hash FROM profiles WHERE is_default = 1 LIMIT 1").fetchone()
        if not row:
            row = conn.execute("SELECT id, pin_hash FROM profiles ORDER BY id ASC LIMIT 1").fetchone()
        if row:
            pid = row["id"]
            pin_hash = row["pin_hash"]
        else:
            return 1

    if check_pin and pin_hash:
        token = (
            request.headers.get("X-Profile-Token")
            or request.cookies.get(f"profile_token_{pid}")
            or request.query_params.get("profile_token")
        )
        if not token or not verify_profile_token(token, pid):
            raise HTTPException(status_code=403, detail="Profile is locked. PIN verification required.")

    return pid


def get_profile(conn: sqlite3.Connection, profile_id: int) -> dict:
    """Fetch profile dict by id, with fallback to default, sanitized of PIN secrets."""
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM profiles WHERE is_default = 1 LIMIT 1").fetchone()
    if not row:
        row = conn.execute("SELECT * FROM profiles ORDER BY id ASC LIMIT 1").fetchone()
    return sanitize_profile(dict(row)) if row else {}
