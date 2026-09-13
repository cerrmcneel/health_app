"""Workout generator, equipment inventory, and session logging."""
from datetime import date, timedelta
import json
import logging
import random
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from app import config
from app.db import get_conn
from app.deps import get_profile_id
from app.models import (
    EquipmentIn,
    WeekPlanGenerateIn,
    WeekPlanRerollDayIn,
    WorkoutGenerateIn,
    WorkoutLogIn,
)

log = logging.getLogger("tracker")

router = APIRouter(prefix="/api/workouts", tags=["workouts"])

from app.data.exercises import EXERCISE_CATALOG, HIGH_IMPACT_IDS, STANDARD_EQUIPMENT


def _get_profile_equipment_keys(conn, profile_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT item_key FROM profile_equipment WHERE profile_id = ?", (profile_id,)
    ).fetchall()
    keys = {r["item_key"] for r in rows}
    keys.add("none")  # bodyweight is always available
    return keys


@router.get("/equipment")
def get_equipment(request: Request):
    """List available catalog and active profile's owned equipment."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        rows = conn.execute(
            "SELECT * FROM profile_equipment WHERE profile_id = ? ORDER BY id ASC",
            (profile_id,),
        ).fetchall()
        owned = [dict(r) for r in rows]
        owned_keys = {r["item_key"] for r in rows}

        catalog = []
        for item in STANDARD_EQUIPMENT:
            catalog.append({
                **item,
                "owned": item["key"] in owned_keys,
            })

        return {
            "owned": owned,
            "equipment": owned,
            "catalog": catalog,
            "standard_catalog": catalog,
            "owned_keys": sorted(list(owned_keys)),
        }


@router.post("/equipment")
def add_equipment(request: Request, payload: EquipmentIn):
    """Add an equipment item for the active profile (idempotent add-only)."""
    key = payload.item_key.strip().lower()
    name = payload.name.strip()
    if not key or not name:
        raise HTTPException(status_code=400, detail="Invalid equipment key or name.")

    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        now_str = config.now().isoformat()
        conn.execute(
            """INSERT INTO profile_equipment (profile_id, item_key, name, acquired_at, notes)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, item_key) DO UPDATE SET name = excluded.name""",
            (profile_id, key, name, now_str, payload.notes),
        )
        return {"status": "added", "item_key": key, "name": name}


@router.delete("/equipment/{item_key}", status_code=204)
def remove_equipment(request: Request, item_key: str):
    """Remove an equipment item from the active profile."""
    key = item_key.strip().lower()
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        cur = conn.execute(
            "DELETE FROM profile_equipment WHERE profile_id = ? AND item_key = ?",
            (profile_id, key),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Equipment '{key}' not found in inventory.")


def generate_catalog_routine(
    category: str = "full_body",
    duration: int = 25,
    level: str = "intermediate",
    owned_keys: set[str] | None = None,
) -> dict:
    """Generate a structured workout routine strictly tailored to available equipment."""
    if owned_keys is None:
        owned_keys = {"none"}

    # Filter exercises where user possesses the required equipment
    eligible = [e for e in EXERCISE_CATALOG if e["equipment"] in owned_keys]
    if not eligible:
        eligible = [e for e in EXERCISE_CATALOG if e["equipment"] == "none"]

    if category == "rest":
        warmups_pool = [e for e in eligible if e["phase"] == "warmup"]
        mobility_pool = [e for e in eligible if e["category"] in ("mobility", "core")]
        cooldowns_pool = [e for e in eligible if e["phase"] == "cooldown"]
        if not mobility_pool:
            mobility_pool = cooldowns_pool or warmups_pool

        selected_warmups = random.sample(warmups_pool, min(2, len(warmups_pool)))
        selected_main = random.sample(mobility_pool, min(3, len(mobility_pool)))
        selected_cooldowns = random.sample(cooldowns_pool, min(2, len(cooldowns_pool)))

        used_keys = set()
        for ex in selected_warmups + selected_main + selected_cooldowns:
            if ex["equipment"] != "none":
                used_keys.add(ex["equipment"])

        return {
            "title": f"Active Recovery & Mobility Flow ({duration} min)",
            "category": "rest",
            "duration_min": duration,
            "rounds": 1,
            "work_rest": "Continuous relaxed flow",
            "level": level,
            "intensity": "recovery",
            "generator": "catalog",
            "estimated_calories": round(duration * 2.5),
            "equipment_used": list(used_keys),
            "warmup": selected_warmups,
            "main": selected_main,
            "cooldown": selected_cooldowns,
            "phases": [
                {
                    "phase_key": "warmup",
                    "name": "Phase 1: Dynamic Warm-Up & Joint Prep",
                    "desc": "Gentle rotations to lubricate joints and awaken muscles.",
                    "exercises": selected_warmups,
                },
                {
                    "phase_key": "main",
                    "name": "Phase 2: Active Mobility & Flow",
                    "desc": "Gentle range-of-motion work for recovery and tension release.",
                    "exercises": selected_main,
                },
                {
                    "phase_key": "cooldown",
                    "name": "Phase 3: Deep Mat Stretches",
                    "desc": "Relaxing stretches to down-regulate the nervous system.",
                    "exercises": selected_cooldowns,
                },
            ],
        }

    # Pool separation by phase
    warmups_pool = [e for e in eligible if e["phase"] == "warmup"]
    main_pool = [e for e in eligible if e["phase"] == "main"]
    cooldowns_pool = [e for e in eligible if e["phase"] == "cooldown"]

    # Filter main pool by category if specific
    if category == "hiit":
        cat_main = [e for e in main_pool if e["category"] in ("cardio", "core")]
    elif category == "upper":
        upper_items = [e for e in main_pool if e["category"] == "upper"]
        core_items = [e for e in main_pool if e["category"] == "core"]
        cat_main = upper_items if len(upper_items) >= 4 else (upper_items + core_items)
    elif category == "lower":
        lower_items = [e for e in main_pool if e["category"] == "lower"]
        core_items = [e for e in main_pool if e["category"] == "core"]
        cat_main = lower_items if len(lower_items) >= 4 else (lower_items + core_items)
    elif category == "core_mobility":
        cat_main = [e for e in main_pool if e["category"] in ("core", "mobility")]
    else:  # full_body
        cat_main = main_pool

    # If specific pool is small, backfill with main pool
    if len(cat_main) < 3:
        cat_main = main_pool

    # Determine structure based on target duration
    if duration <= 18:
        warmup_count = 2
        main_count = 3
        cooldown_count = 1
        rounds = 3
        work_rest_str = "40s work / 20s rest" if category == "hiit" else "3 rounds"
    elif duration <= 30:
        warmup_count = 3
        main_count = 4
        cooldown_count = 2
        rounds = 3
        work_rest_str = "45s work / 15s rest" if category == "hiit" else "3-4 rounds"
    else:  # 40+ min
        warmup_count = 3
        main_count = 6
        cooldown_count = 2
        rounds = 4
        work_rest_str = "45s work / 15s rest" if category == "hiit" else "4 rounds"

    # Level changes the dose, not just the label. Beginners get fewer rounds and
    # longer rest; advanced athletes get more rounds and shorter rest.
    if level == "beginner":
        rounds = max(2, rounds - 1)
        work_rest_str = "30s work / 30s rest" if category == "hiit" else f"{rounds} rounds"
    elif level == "advanced":
        rounds = rounds + 1
        main_count += 1
        work_rest_str = "50s work / 10s rest" if category == "hiit" else f"{rounds} rounds"

    # High-impact movements are excluded for beginners: they are the ones most
    # likely to be done badly and hurt someone on their first session.
    if level == "beginner":
        gentler = [e for e in cat_main if e["id"] not in HIGH_IMPACT_IDS]
        if len(gentler) >= 3:
            cat_main = gentler

    # Sample without duplicates
    selected_warmups = random.sample(warmups_pool, min(warmup_count, len(warmups_pool)))
    selected_main = random.sample(cat_main, min(main_count, len(cat_main)))
    selected_cooldowns = random.sample(cooldowns_pool, min(cooldown_count, len(cooldowns_pool)))

    # Title naming
    titles_by_cat = {
        "full_body": "Full Body Calisthenics & Strength",
        "hiit": "Jump Rope & Bodyweight HIIT Circuit",
        "upper": "Upper Body & Core Sculpt",
        "lower": "Lower Body Power & Leg Burn",
        "core_mobility": "Mat Core & Dynamic Mobility Flow",
        "rest": "Active Recovery & Mobility Flow",
    }
    title = f"{titles_by_cat.get(category, 'Functional Workout')} ({duration} min)"

    # Identify equipment actually used
    used_keys = set()
    for ex in selected_warmups + selected_main + selected_cooldowns:
        if ex["equipment"] != "none":
            used_keys.add(ex["equipment"])

    # Estimated calories burned
    rate = 9.5 if category == "hiit" else 7.5
    est_calories = round(duration * rate)

    return {
        "title": title,
        "category": category,
        "duration_min": duration,
        "rounds": rounds,
        "work_rest": work_rest_str,
        "level": level,
        "intensity": level,
        "generator": "catalog",
        "estimated_calories": est_calories,
        "equipment_used": list(used_keys),
        "warmup": selected_warmups,
        "main": selected_main,
        "cooldown": selected_cooldowns,
        "phases": [
            {
                "phase_key": "warmup",
                "name": "Phase 1: Dynamic Warm-Up",
                "desc": "3-5 minutes to elevate core temperature and lubricate joints.",
                "exercises": selected_warmups,
            },
            {
                "phase_key": "main",
                "name": f"Phase 2: Main Circuit ({rounds} Rounds)",
                "desc": "Perform consecutively with 1-2 min rest between full circuits.",
                "exercises": selected_main,
            },
            {
                "phase_key": "cooldown",
                "name": "Phase 3: Cool-Down & Flexibility",
                "desc": "Deep stretching on the mat to down-regulate nervous system.",
                "exercises": selected_cooldowns,
            },
        ],
    }


@router.post("/generate")
def generate_workout(request: Request, params: WorkoutGenerateIn):
    """Generate a structured workout routine strictly tailored to available equipment."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        owned_keys = _get_profile_equipment_keys(conn, profile_id)

    eligible = [e for e in EXERCISE_CATALOG if e["equipment"] in owned_keys]
    if not eligible:
        raise HTTPException(status_code=400, detail="No eligible exercises found for your equipment.")

    return generate_catalog_routine(
        category=params.category,
        duration=params.duration_min,
        level=params.level,
        owned_keys=owned_keys,
    )


@router.post("/ai-generate")
async def ai_generate_workout(request: Request, params: WorkoutGenerateIn):
    """Generate a custom personalized workout using the local Ollama model."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        owned_keys = _get_profile_equipment_keys(conn, profile_id)
        prof = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        name = prof["name"] if prof else "User"

    equip_names = []
    for item in STANDARD_EQUIPMENT:
        if item["key"] in owned_keys and item["key"] != "none":
            equip_names.append(item["name"])
    equip_str = ", ".join(equip_names) if equip_names else "Bodyweight only (no equipment)"

    custom_note = f"User Request: {params.custom_prompt}" if params.custom_prompt else ""

    system_prompt = f"""You are an expert fitness coach and movement specialist.
You prescribe structured workout routines. You must strictly follow these rules:
1. EQUIPMENT CONSTRAINT: The user possesses ONLY this equipment: [{equip_str}]. You MUST NEVER prescribe any movement requiring any equipment not in this list. (Bodyweight/floor exercises are always allowed).
2. STRUCTURE: Break the session into Warm-Up, Main Circuit (3-4 rounds), and Cool-Down.
3. OUTPUT: Output JSON only matching the schema."""

    user_prompt = f"""Design a {params.duration_min}-minute {params.category.replace('_', ' ')} workout for {name} ({params.level} level).
Available Equipment: {equip_str}
{custom_note}
Include clear exercise names, target reps or seconds, and a brief coaching cue."""

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "category": {"type": "string"},
            "duration_min": {"type": "integer"},
            "coaching_advice": {"type": "string"},
            "phases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "exercises": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "target": {"type": "string"},
                                    "instructions": {"type": "string"},
                                    "equipment": {"type": "string"},
                                },
                                "required": ["name", "target", "instructions"],
                            },
                        },
                    },
                    "required": ["name", "exercises"],
                },
            },
        },
        "required": ["title", "phases"],
    }

    try:
        payload = {
            "model": config.VISION_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": schema,
            "stream": False,
            # gemma4 and other reasoning-capable models will otherwise spend the
            # whole num_predict budget thinking and return empty content --
            # app/services/vision.py sends this for the same reason.
            "think": False,
            "options": {"temperature": 0.3, "num_predict": 2000},
        }
        # A cold 12B load routinely exceeds 45s, which made the first AI
        # generation of every session time out and silently fall back.
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            if resp.status_code == 400 and "think" in resp.text.lower():
                # Older Ollama builds reject the field outright.
                payload.pop("think")
                resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            if resp.status_code == 200:
                message = resp.json().get("message") or {}
                content = (message.get("content") or "").strip()
                if not content:
                    raise ValueError(
                        "model returned no content"
                        + (" (it reasoned instead of answering)" if message.get("thinking") else "")
                    )
                data = _canonicalize_ai_routine(json.loads(content), params, owned_keys)
                if data is not None:
                    data["equipment_used"] = equip_names
                    data["estimated_calories"] = round(params.duration_min * 8)
                    data["generator"] = "ai"
                    return data
                log.warning("AI routine had no usable main-circuit exercises; falling back")
            else:
                log.warning("Ollama returned HTTP %s for workout generation", resp.status_code)
    except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        log.warning("Local AI workout generation fallback: %s", exc)

    # Seamless fallback to the offline generator if Ollama is unavailable. The
    # marker lets the UI say so rather than passing this off as the AI's work.
    fallback = generate_workout(request, params)
    fallback["generator"] = "offline-fallback"
    return fallback


def _canonicalize_ai_routine(
    data: dict[str, Any], params: WorkoutGenerateIn, owned_keys: set[str]
) -> dict[str, Any] | None:
    """Reshape free-form model output into the contract the UI renders.

    The model returns arbitrarily-named `phases`; the frontend reads
    `warmup`/`main`/`cooldown` lists of exercises with the same field names the
    catalog generator emits. Returns None when nothing usable survives, so the
    caller can fall back.

    Exercises requiring equipment the profile does not own are dropped here. The
    system prompt asks the model to respect the inventory, but a prompt is a
    request, not a constraint -- this is the constraint.
    """
    buckets: dict[str, list[dict[str, Any]]] = {"warmup": [], "main": [], "cooldown": []}

    for phase in data.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        label = str(phase.get("name") or "").lower()
        if "warm" in label:
            key = "warmup"
        elif "cool" in label or "stretch" in label or "down" in label:
            key = "cooldown"
        else:
            key = "main"

        for ex in phase.get("exercises") or []:
            if not isinstance(ex, dict):
                continue
            name = str(ex.get("name") or "").strip()
            if not name:
                continue
            equipment = str(ex.get("equipment") or "none").strip().lower().replace(" ", "_")
            if equipment in ("", "bodyweight", "none", "no_equipment"):
                equipment = "none"
            if equipment not in owned_keys:
                log.info("dropped AI exercise '%s' requiring unowned '%s'", name, equipment)
                continue

            target = str(ex.get("target") or "").strip()
            buckets[key].append({
                "id": "",
                "name": name[:120],
                "category": str(ex.get("category") or params.category),
                "equipment": equipment,
                "phase": key,
                "type": "time" if _looks_timed(target) else "reps",
                "default_target": target or "10 reps",
                "target_muscles": str(ex.get("target_muscles") or ""),
                "instructions": str(ex.get("instructions") or "")[:500],
            })

    if not buckets["main"]:
        return None

    data.update(buckets)
    data.setdefault("category", params.category)
    data.setdefault("duration_min", params.duration_min)
    data.setdefault("level", params.level)
    data.setdefault("intensity", params.level)
    data.setdefault("rounds", 3)
    data.setdefault("work_rest", f"{data['rounds']} rounds")
    return data


def _looks_timed(target: str) -> bool:
    """'45s' / '30 sec' / '1 min' are time-based; '10 reps' is not."""
    low = target.lower()
    return any(unit in low for unit in ("s", "sec", "min")) and "rep" not in low


@router.post("", status_code=201)
def log_workout(request: Request, payload: WorkoutLogIn):
    """Log a completed workout session to the active profile."""
    day = (payload.day or config.now().date()).isoformat()
    now_str = config.now().isoformat()
    routine_val = payload.routine_json if payload.routine_json is not None else payload.routine
    routine_str = json.dumps(routine_val)
    equip_str = json.dumps(payload.equipment_used)

    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        cur = conn.execute(
            """INSERT INTO workouts (profile_id, day, logged_at, title, category,
                                     duration_min, intensity, equipment_used, routine_json, completed, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (profile_id, day, now_str, payload.title, payload.category,
             payload.duration_min, payload.intensity, equip_str, routine_str, payload.notes),
        )
        row = conn.execute("SELECT * FROM workouts WHERE id = ?", (cur.lastrowid,)).fetchone()
        item = dict(row)
        item["equipment_used"] = json.loads(item["equipment_used"] or "[]")
        item["routine"] = json.loads(item["routine_json"] or "[]")
        return item


@router.get("")
def list_workouts(request: Request, day: date | None = None, limit: int = 30):
    """List recent completed workouts for the active profile."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        if day is not None:
            rows = conn.execute(
                """SELECT * FROM workouts
                   WHERE profile_id = ? AND day = ?
                   ORDER BY id DESC LIMIT ?""",
                (profile_id, day.isoformat(), min(max(limit, 1), 100)),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM workouts
                   WHERE profile_id = ?
                   ORDER BY day DESC, id DESC LIMIT ?""",
                (profile_id, min(max(limit, 1), 100)),
            ).fetchall()

        results = []
        for r in rows:
            item = dict(r)
            item["equipment_used"] = json.loads(item["equipment_used"] or "[]")
            item["routine"] = json.loads(item["routine_json"] or "[]")
            results.append(item)

        cutoff = (config.now().date() - timedelta(days=6)).isoformat()
        week_count = conn.execute(
            """SELECT COUNT(*) as cnt, COALESCE(SUM(duration_min), 0) as total_min
               FROM workouts WHERE profile_id = ? AND day >= ?""",
            (profile_id, cutoff),
        ).fetchone()

        return {
            "workouts": results,
            "this_week": {
                "sessions": week_count["cnt"] if week_count else 0,
                "total_minutes": week_count["total_min"] if week_count else 0,
            },
        }


@router.delete("/{workout_id}", status_code=204)
def delete_workout(request: Request, workout_id: int):
    """Delete a logged workout."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        row = conn.execute(
            "SELECT id FROM workouts WHERE id = ? AND profile_id = ?",
            (workout_id, profile_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Workout not found.")
        conn.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))


# --- Weeklong Training Plan (Upper / Lower / Full Body Splits) ---

FOCUS_LABELS: dict[str, str] = {
    "upper": "Upper Body & Core",
    "lower": "Lower Body & Legs",
    "full_body": "Full Body Strength",
    "core_mobility": "Core & Mobility",
    "hiit": "HIIT & Cardio",
    "rest": "Rest & Active Recovery",
}

FOCUS_MUSCLES: dict[str, list[str]] = {
    "upper": ["Chest", "Back", "Shoulders", "Arms", "Core"],
    "lower": ["Quads", "Hamstrings", "Glutes", "Calves"],
    "full_body": ["Full Body", "Chest", "Legs", "Back", "Core"],
    "core_mobility": ["Core", "Spine", "Hips", "Flexibility"],
    "hiit": ["Cardio", "Agility", "Core", "Endurance"],
    "rest": ["Recovery", "Mobility", "Joint Health"],
}

# Systematic sports-science splits mapping 7 days (Monday=0 to Sunday=6)
# designed to avoid consecutive muscle clashes while ensuring balanced upper/lower targeting.
WEEK_SPLIT_TEMPLATES: dict[int, list[str]] = {
    1: ["rest", "rest", "full_body", "rest", "rest", "rest", "rest"],
    2: ["rest", "upper", "rest", "rest", "lower", "rest", "rest"],
    3: ["upper", "rest", "lower", "rest", "full_body", "rest", "rest"],
    4: ["upper", "lower", "rest", "upper", "lower", "rest", "rest"],
    5: ["upper", "lower", "core_mobility", "upper", "lower", "rest", "rest"],
    6: ["upper", "lower", "core_mobility", "upper", "lower", "hiit", "rest"],
    7: ["upper", "lower", "core_mobility", "upper", "lower", "hiit", "core_mobility"],
}


def _get_monday(d: date) -> date:
    """Return the Monday of the ISO week containing date d."""
    return d - timedelta(days=d.weekday())


def _build_week_split(
    days_per_week: int,
    week_start: str,
    level: str,
    duration_min: int,
    owned_keys: set[str],
) -> list[dict]:
    """Generate a structured 7-day schedule with targeted Upper/Lower/Full routines."""
    monday = _get_monday(date.fromisoformat(week_start))
    clamped_days = max(1, min(7, days_per_week))
    split = WEEK_SPLIT_TEMPLATES.get(clamped_days, WEEK_SPLIT_TEMPLATES[3])

    days: list[dict] = []
    for day_idx in range(7):
        day_date = monday + timedelta(days=day_idx)
        focus = split[day_idx]
        is_rest = (focus == "rest")
        dur = 15 if is_rest else duration_min
        routine = generate_catalog_routine(
            category=focus,
            duration=dur,
            level=level,
            owned_keys=owned_keys,
        )
        days.append({
            "day_idx": day_idx,
            "date": day_date.isoformat(),
            "day_name": day_date.strftime("%A"),
            "day_short": day_date.strftime("%a"),
            "focus": focus,
            "focus_label": FOCUS_LABELS.get(focus, "Workout"),
            "is_rest": is_rest,
            "title": routine["title"],
            "duration_min": routine["duration_min"],
            "level": level,
            "target_muscles": FOCUS_MUSCLES.get(focus, []),
            "routine": routine,
        })
    return days


def _enrich_plan_with_logs(conn, profile_id: int, week_start: str, days: list[dict]) -> dict:
    """Attach live logged workout completion status and today flag to week plan days."""
    today_iso = config.now().date().isoformat()
    monday = date.fromisoformat(week_start)
    sunday = monday + timedelta(days=6)

    rows = conn.execute(
        """SELECT id, day, title, category, duration_min, logged_at
           FROM workouts
           WHERE profile_id = ? AND day >= ? AND day <= ? AND completed = 1
           ORDER BY day ASC, id ASC""",
        (profile_id, monday.isoformat(), sunday.isoformat()),
    ).fetchall()

    logged_by_day: dict[str, list[dict]] = {}
    for r in rows:
        d_str = r["day"]
        if d_str not in logged_by_day:
            logged_by_day[d_str] = []
        logged_by_day[d_str].append(dict(r))

    for d in days:
        d_iso = d["date"]
        logged = logged_by_day.get(d_iso, [])
        d["completed"] = len(logged) > 0
        d["logged_workouts"] = logged
        d["is_today"] = (d_iso == today_iso)

    completed_days = sum(1 for d in days if d.get("completed"))
    total_workout_days = sum(1 for d in days if not d.get("is_rest"))

    return {
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "days_per_week": total_workout_days,
        "completed_days": completed_days,
        "total_workout_days": total_workout_days,
        "days": days,
    }


@router.get("/week-plan")
def get_week_plan(request: Request, week_start: str | None = None):
    """Get the 7-day structured training plan for the active profile (auto-creates if missing)."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        today = config.now().date()
        if week_start:
            try:
                mon = _get_monday(date.fromisoformat(week_start))
            except ValueError:
                mon = _get_monday(today)
        else:
            mon = _get_monday(today)
        mon_str = mon.isoformat()

        row = conn.execute(
            "SELECT * FROM weekly_plans WHERE profile_id = ? AND week_start = ?",
            (profile_id, mon_str),
        ).fetchone()

        if row:
            days = json.loads(row["days_json"])
            plan_id = row["id"]
        else:
            prof = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            days_per_week = prof["workout_days_per_week"] if prof and prof["workout_days_per_week"] else 3
            level = prof["preferred_level"] if prof and prof["preferred_level"] else "intermediate"
            duration = prof["preferred_duration_min"] if prof and prof["preferred_duration_min"] else 25
            owned_keys = _get_profile_equipment_keys(conn, profile_id)

            days = _build_week_split(days_per_week, mon_str, level, duration, owned_keys)
            now_str = config.now().isoformat()
            cur = conn.execute(
                """INSERT INTO weekly_plans (profile_id, week_start, created_at, days_json)
                   VALUES (?, ?, ?, ?)""",
                (profile_id, mon_str, now_str, json.dumps(days)),
            )
            plan_id = cur.lastrowid

        res = _enrich_plan_with_logs(conn, profile_id, mon_str, days)
        res["id"] = plan_id
        res["profile_id"] = profile_id
        return res


@router.post("/week-plan/generate")
def generate_week_plan(request: Request, payload: WeekPlanGenerateIn):
    """(Re)generate a full 7-day structured training plan with updated settings."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        prof = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()

        today = config.now().date()
        if payload.week_start:
            try:
                mon = _get_monday(date.fromisoformat(payload.week_start))
            except ValueError:
                mon = _get_monday(today)
        else:
            mon = _get_monday(today)
        mon_str = mon.isoformat()

        days_per_week = payload.days_per_week or (prof["workout_days_per_week"] if prof and prof["workout_days_per_week"] else 3)
        level = payload.level or (prof["preferred_level"] if prof and prof["preferred_level"] else "intermediate")
        duration = payload.duration_min or (prof["preferred_duration_min"] if prof and prof["preferred_duration_min"] else 25)

        updates = []
        params = []
        if payload.days_per_week is not None:
            updates.append("workout_days_per_week = ?")
            params.append(payload.days_per_week)
        if payload.level is not None:
            updates.append("preferred_level = ?")
            params.append(payload.level)
        if payload.duration_min is not None:
            updates.append("preferred_duration_min = ?")
            params.append(payload.duration_min)
        if updates:
            params.append(profile_id)
            conn.execute(f"UPDATE profiles SET {', '.join(updates)} WHERE id = ?", tuple(params))

        owned_keys = _get_profile_equipment_keys(conn, profile_id)
        days = _build_week_split(days_per_week, mon_str, level, duration, owned_keys)
        now_str = config.now().isoformat()

        conn.execute(
            """INSERT INTO weekly_plans (profile_id, week_start, created_at, days_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(profile_id, week_start) DO UPDATE SET
                 days_json = excluded.days_json,
                 created_at = excluded.created_at""",
            (profile_id, mon_str, now_str, json.dumps(days)),
        )

        row = conn.execute(
            "SELECT id FROM weekly_plans WHERE profile_id = ? AND week_start = ?",
            (profile_id, mon_str),
        ).fetchone()

        res = _enrich_plan_with_logs(conn, profile_id, mon_str, days)
        res["id"] = row["id"] if row else None
        res["profile_id"] = profile_id
        return res


@router.post("/week-plan/reroll-day")
def reroll_week_plan_day(request: Request, payload: WeekPlanRerollDayIn):
    """Reroll a single day's routine within the active week plan."""
    if payload.day_idx < 0 or payload.day_idx > 6:
        raise HTTPException(status_code=400, detail="Invalid day_idx (must be 0 to 6).")

    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        today = config.now().date()
        if payload.week_start:
            try:
                mon = _get_monday(date.fromisoformat(payload.week_start))
            except ValueError:
                mon = _get_monday(today)
        else:
            mon = _get_monday(today)
        mon_str = mon.isoformat()

        row = conn.execute(
            "SELECT * FROM weekly_plans WHERE profile_id = ? AND week_start = ?",
            (profile_id, mon_str),
        ).fetchone()

        prof = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        owned_keys = _get_profile_equipment_keys(conn, profile_id)

        if row:
            days = json.loads(row["days_json"])
            plan_id = row["id"]
        else:
            days_per_week = prof["workout_days_per_week"] if prof and prof["workout_days_per_week"] else 3
            level = prof["preferred_level"] if prof and prof["preferred_level"] else "intermediate"
            duration = prof["preferred_duration_min"] if prof and prof["preferred_duration_min"] else 25
            days = _build_week_split(days_per_week, mon_str, level, duration, owned_keys)
            now_str = config.now().isoformat()
            cur = conn.execute(
                """INSERT INTO weekly_plans (profile_id, week_start, created_at, days_json)
                   VALUES (?, ?, ?, ?)""",
                (profile_id, mon_str, now_str, json.dumps(days)),
            )
            plan_id = cur.lastrowid

        target_day = days[payload.day_idx]
        if payload.focus:
            target_day["focus"] = payload.focus
            target_day["focus_label"] = FOCUS_LABELS.get(payload.focus, "Workout")
            target_day["is_rest"] = (payload.focus == "rest")
            target_day["target_muscles"] = FOCUS_MUSCLES.get(payload.focus, [])

        focus = target_day["focus"]
        is_rest = target_day.get("is_rest", focus == "rest")
        dur = target_day.get("duration_min", 25)
        if is_rest:
            dur = 15
        level = target_day.get("level", "intermediate")

        new_routine = generate_catalog_routine(
            category=focus,
            duration=dur,
            level=level,
            owned_keys=owned_keys,
        )
        target_day["routine"] = new_routine
        target_day["title"] = new_routine["title"]
        target_day["duration_min"] = new_routine["duration_min"]

        conn.execute(
            "UPDATE weekly_plans SET days_json = ? WHERE id = ?",
            (json.dumps(days), plan_id),
        )

        res = _enrich_plan_with_logs(conn, profile_id, mon_str, days)
        res["id"] = plan_id
        res["profile_id"] = profile_id
        return res

