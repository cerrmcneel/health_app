"""Daily totals, history, targets, and a system health probe."""
from datetime import date, timedelta

from fastapi import APIRouter, Query

from app import config
from app.db import get_conn
from app.models import Settings
from app.services import vision

router = APIRouter(prefix="/api", tags=["stats"])

EMPTY = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "meal_count": 0}


@router.get("/stats/daily")
def daily(day: date | None = None):
    """Totals plus target progress for one day."""
    target_day = (day or config.now().date()).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM v_daily_totals WHERE day = ?", (target_day,)
        ).fetchone()
        settings = dict(conn.execute("SELECT * FROM settings WHERE id = 1").fetchone())

    totals = {**EMPTY, **({k: v for k, v in dict(row).items() if k != "day"} if row else {})}
    settings.pop("id", None)
    return {
        "day": target_day,
        "totals": totals,
        "targets": settings,
        "remaining": {
            "calories": round(settings["calorie_target"] - totals["calories"], 1),
            "protein_g": round(settings["protein_target"] - totals["protein_g"], 1),
            "carbs_g": round(settings["carbs_target"] - totals["carbs_g"], 1),
            "fat_g": round(settings["fat_target"] - totals["fat_g"], 1),
        },
    }


@router.get("/stats/range")
def range_stats(days: int = Query(default=14, ge=1, le=365)):
    """A dense day-by-day series ending today.

    Days with no meals are emitted as zeros rather than omitted, so the chart
    shows the gaps instead of silently compressing them.
    """
    end = config.now().date()
    start = end - timedelta(days=days - 1)
    with get_conn() as conn:
        rows = {
            r["day"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM v_daily_totals WHERE day BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat()),
            )
        }
        settings = dict(conn.execute("SELECT * FROM settings WHERE id = 1").fetchone())
    settings.pop("id", None)

    series = []
    for offset in range(days):
        d = (start + timedelta(days=offset)).isoformat()
        row = rows.get(d)
        entry = {**EMPTY, "day": d}
        if row:
            entry.update({k: v or 0 for k, v in row.items() if k != "day"})
        series.append(entry)

    logged = [s["calories"] for s in series if s["meal_count"]]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "targets": settings,
        "series": series,
        "average_calories": round(sum(logged) / len(logged), 1) if logged else 0.0,
        "days_logged": len(logged),
    }


@router.get("/settings")
def get_settings():
    with get_conn() as conn:
        row = dict(conn.execute("SELECT * FROM settings WHERE id = 1").fetchone())
    row.pop("id", None)
    return row


@router.put("/settings")
def put_settings(settings: Settings):
    with get_conn() as conn:
        conn.execute(
            """UPDATE settings SET calorie_target = ?, protein_target = ?,
                                   carbs_target = ?, fat_target = ? WHERE id = 1""",
            (settings.calorie_target, settings.protein_target,
             settings.carbs_target, settings.fat_target),
        )
    return settings.model_dump()


@router.get("/health")
async def health():
    """Reports whether Ollama is up and the configured model is usable.

    The UI calls this on load so a missing or non-vision model surfaces as a
    banner, rather than as a 502 after the user has already taken a photo.
    """
    info: dict = {
        "ollama_url": config.OLLAMA_URL,
        "configured_model": config.VISION_MODEL,
        "timezone": str(config.TZ),
        "storage_dir": str(config.STORAGE_DIR),
        "today": config.today_iso(),
    }
    try:
        models = await vision.list_models()
    except Exception as exc:
        return {**info, "ollama": "unreachable", "error": str(exc),
                "model_ready": False, "models": []}

    names = [m["name"] for m in models]
    match = next((m for m in models if m["name"] == config.VISION_MODEL), None)
    info["models"] = models
    info["ollama"] = "ok"
    info["model_installed"] = match is not None
    info["model_vision_capable"] = bool(match and match["vision"])
    info["model_ready"] = bool(match and match["vision"])
    if match is None:
        info["hint"] = (
            f"'{config.VISION_MODEL}' is not installed. Installed: {', '.join(names) or 'none'}. "
            f"Run `ollama pull {config.VISION_MODEL}` or set VISION_MODEL in .env."
        )
    elif not match["vision"]:
        vision_models = [m["name"] for m in models if m["vision"]]
        info["hint"] = (
            f"'{config.VISION_MODEL}' cannot process images. "
            f"Vision-capable models installed: {', '.join(vision_models) or 'none'}."
        )
    return info
