"""Daily totals, history, targets, and a system health probe."""
from datetime import date, timedelta

from fastapi import APIRouter, Query, Request

from app import config
from app.db import get_conn
from app.deps import get_profile, get_profile_id
from app.models import Settings
from app.services import vision

router = APIRouter(prefix="/api", tags=["stats"])

EMPTY = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "meal_count": 0}


@router.get("/stats/daily")
def daily(request: Request, day: date | None = None):
    """Totals plus target progress for one day for the active profile."""
    target_day = (day or config.now().date()).isoformat()
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        prof = get_profile(conn, profile_id)
        row = conn.execute(
            "SELECT * FROM v_daily_totals WHERE profile_id = ? AND day = ?", (profile_id, target_day)
        ).fetchone()

    targets = {
        "calorie_target": prof.get("calorie_target", 2200.0),
        "protein_target": prof.get("protein_target", 160.0),
        "carbs_target": prof.get("carbs_target", 220.0),
        "fat_target": prof.get("fat_target", 70.0),
    }

    totals = {**EMPTY, **({k: v for k, v in dict(row).items() if k not in ("day", "profile_id")} if row else {})}
    return {
        "day": target_day,
        "profile": {
            "id": prof.get("id"),
            "name": prof.get("name"),
            "avatar_color": prof.get("avatar_color"),
        },
        "totals": totals,
        "targets": targets,
        "remaining": {
            "calories": round(targets["calorie_target"] - totals["calories"], 1),
            "protein_g": round(targets["protein_target"] - totals["protein_g"], 1),
            "carbs_g": round(targets["carbs_target"] - totals["carbs_g"], 1),
            "fat_g": round(targets["fat_target"] - totals["fat_g"], 1),
        },
    }


@router.get("/stats/range")
def range_stats(request: Request, days: int = Query(default=14, ge=1, le=365)):
    """A dense day-by-day series ending today for the active profile."""
    end = config.now().date()
    start = end - timedelta(days=days - 1)
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        prof = get_profile(conn, profile_id)
        rows = {
            r["day"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM v_daily_totals WHERE profile_id = ? AND day BETWEEN ? AND ?",
                (profile_id, start.isoformat(), end.isoformat()),
            )
        }

    targets = {
        "calorie_target": prof.get("calorie_target", 2200.0),
        "protein_target": prof.get("protein_target", 160.0),
        "carbs_target": prof.get("carbs_target", 220.0),
        "fat_target": prof.get("fat_target", 70.0),
    }

    series = []
    for offset in range(days):
        d = (start + timedelta(days=offset)).isoformat()
        row = rows.get(d)
        entry = {**EMPTY, "day": d}
        if row:
            entry.update({k: v or 0 for k, v in row.items() if k not in ("day", "profile_id")})
        series.append(entry)

    logged = [s["calories"] for s in series if s["meal_count"]]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "targets": targets,
        "series": series,
        "average_calories": round(sum(logged) / len(logged), 1) if logged else 0.0,
        "days_logged": len(logged),
    }


@router.get("/settings")
def get_settings(request: Request):
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        prof = get_profile(conn, profile_id)
    return {
        "calorie_target": prof.get("calorie_target", 2200.0),
        "protein_target": prof.get("protein_target", 160.0),
        "carbs_target": prof.get("carbs_target", 220.0),
        "fat_target": prof.get("fat_target", 70.0),
    }


@router.put("/settings")
def put_settings(request: Request, settings: Settings):
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        conn.execute(
            """UPDATE profiles SET calorie_target = ?, protein_target = ?,
                                  carbs_target = ?, fat_target = ? WHERE id = ?""",
            (settings.calorie_target, settings.protein_target,
             settings.carbs_target, settings.fat_target, profile_id),
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
        hint = (
            f"'{config.VISION_MODEL}' cannot process images. "
            f"Vision-capable models installed: {', '.join(vision_models) or 'none'}."
        )
        if "gemma" in config.VISION_MODEL.lower():
            hint += " Note: Gemma 4 requires Ollama >= 0.22 to enable vision (check `ollama --version`)."
        info["hint"] = hint
    return info


@router.get("/health/live")
def health_live():
    """Lightweight liveness probe for Docker HEALTHCHECK. Confirms process & SQLite are up."""
    with get_conn() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok"}
