"""Body weight tracking and moving average trends."""
from datetime import date
from fastapi import APIRouter, HTTPException, Query, Request

from app import config
from app.db import get_conn
from app.deps import get_profile_id
from app.models import WeightIn

router = APIRouter(prefix="/api/weights", tags=["weights"])


@router.get("")
def list_weights(request: Request, limit: int = Query(default=30, ge=1, le=365)):
    """List weights newest-first for the active profile, with 7-day moving averages."""
    limit = max(1, min(limit, 365))
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        rows = conn.execute(
            """SELECT * FROM weights
               WHERE profile_id = ?
               ORDER BY day DESC LIMIT ?""",
            (profile_id, limit),
        ).fetchall()

        entries = [dict(r) for r in rows]

        # Calculate 7-day trailing average for each entry (chronological pass)
        chron = list(reversed(entries))
        weights_by_day = {e["day"]: e["weight_kg"] for e in chron}

        results = []
        for e in entries:
            day_iso = e["day"]
            # Look back 7 days
            window = [
                v for d, v in weights_by_day.items()
                if 0 <= (date.fromisoformat(day_iso) - date.fromisoformat(d)).days < 7
            ]
            avg_7d = round(sum(window) / len(window), 2) if window else e["weight_kg"]
            results.append({
                **e,
                "moving_avg_7d": avg_7d,
            })

        latest = entries[0] if entries else None
        prior = entries[6] if len(entries) >= 7 else (entries[-1] if len(entries) > 1 else None)
        change_7d = round(latest["weight_kg"] - prior["weight_kg"], 2) if (latest and prior and latest != prior) else None

        return {
            "weights": results,
            "latest_weight": latest["weight_kg"] if latest else None,
            "change_7d": change_7d,
        }


@router.post("", status_code=201)
def log_weight(request: Request, payload: WeightIn):
    """Log or update body weight for a day (defaults to today)."""
    when = config.now()
    day = (payload.day or when.date()).isoformat()

    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        conn.execute(
            """INSERT INTO weights (profile_id, day, logged_at, weight_kg, notes)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, day) DO UPDATE SET
                   logged_at = excluded.logged_at,
                   weight_kg = excluded.weight_kg,
                   notes = excluded.notes""",
            (profile_id, day, when.isoformat(), payload.weight_kg, payload.notes),
        )
        row = conn.execute(
            "SELECT * FROM weights WHERE profile_id = ? AND day = ?", (profile_id, day)
        ).fetchone()
        return dict(row)


@router.delete("/{weight_id}")
def delete_weight(request: Request, weight_id: int):
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        row = conn.execute(
            "SELECT id FROM weights WHERE id = ? AND profile_id = ?", (weight_id, profile_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Weight record not found.")
        conn.execute("DELETE FROM weights WHERE id = ?", (weight_id,))
        return {"deleted": weight_id}
