"""Profile resolution and database helpers for multi-profile support."""
import re
import sqlite3
from fastapi import Request


def slugify(text: str) -> str:
    """Generate a clean URL/path-safe slug from a profile name."""
    s = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[-\s]+", "-", s) or "user"


def get_profile_id(request: Request, conn: sqlite3.Connection) -> int:
    """Extract and validate the active profile ID from headers, query params, or cookies."""
    raw = (
        request.headers.get("X-Profile-ID")
        or request.query_params.get("profile_id")
        or request.cookies.get("active_profile_id")
    )
    if raw:
        try:
            pid = int(raw)
            row = conn.execute("SELECT id FROM profiles WHERE id = ?", (pid,)).fetchone()
            if row:
                return row["id"]
        except (ValueError, TypeError):
            pass

    # Fallback to default profile, or lowest ID
    row = conn.execute("SELECT id FROM profiles WHERE is_default = 1 LIMIT 1").fetchone()
    if row:
        return row["id"]
    row = conn.execute("SELECT id FROM profiles ORDER BY id ASC LIMIT 1").fetchone()
    return row["id"] if row else 1


def get_profile(conn: sqlite3.Connection, profile_id: int) -> dict:
    """Fetch profile dict by id, with fallback to default."""
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM profiles WHERE is_default = 1 LIMIT 1").fetchone()
    if not row:
        row = conn.execute("SELECT * FROM profiles ORDER BY id ASC LIMIT 1").fetchone()
    return dict(row) if row else {}
