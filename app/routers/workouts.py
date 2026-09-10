"""Workout generator, equipment inventory, and session logging."""
import json
import logging
import random
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from app import config
from app.db import get_conn
from app.deps import get_profile_id
from app.models import EquipmentIn, WorkoutGenerateIn, WorkoutLogIn

log = logging.getLogger("tracker")

router = APIRouter(prefix="/api/workouts", tags=["workouts"])

# Standard catalog of fitness equipment
STANDARD_EQUIPMENT = [
    {"key": "yoga_mat", "name": "Yoga Mat", "icon": "🧘", "desc": "Floor work, core, and stretching"},
    {"key": "jump_rope", "name": "Jump Rope", "icon": "🪢", "desc": "Cardio conditioning & HIIT intervals"},
    {"key": "pull_up_bar", "name": "Pull-up Bar", "icon": "🚪", "desc": "Back, lats & upper body pulling"},
    {"key": "resistance_bands", "name": "Resistance Bands", "icon": "🎗️", "desc": "Variable tension & joint-friendly strength"},
    {"key": "dumbbells", "name": "Dumbbells", "icon": "🏋️", "desc": "Free weights for full-body progressive overload"},
    {"key": "kettlebell", "name": "Kettlebell", "icon": "🔔", "desc": "Ballistics, power & functional strength"},
    {"key": "bench", "name": "Workout Bench", "icon": "🛋️", "desc": "Pressing, steps & elevation"},
    {"key": "barbell", "name": "Barbell & Plates", "icon": "🔩", "desc": "Heavy compound lifts"},
    {"key": "dip_station", "name": "Dip Station", "icon": "🪜", "desc": "Chest, triceps & core dips"},
    {"key": "ab_wheel", "name": "Ab Wheel", "icon": "⚙️", "desc": "Core rollout & anti-extension"},
    {"key": "foam_roller", "name": "Foam Roller", "icon": "🪵", "desc": "Mobility & myofascial release"},
]

# Comprehensive Exercise Library with strict equipment tags
EXERCISE_CATALOG = [
    # --- WARM-UP (phase: warmup) ---
    {
        "id": "arm_circles_chest_opener",
        "name": "Arm Circles & Chest Openers",
        "category": "upper",
        "equipment": "none",
        "phase": "warmup",
        "type": "time",
        "default_target": "45s",
        "target_muscles": "Shoulders, Chest",
        "instructions": "Big controlled arm circles, alternating forward and backward with chest expansion.",
    },
    {
        "id": "cat_cow_mat",
        "name": "Cat-Cow Flow",
        "category": "mobility",
        "equipment": "yoga_mat",
        "phase": "warmup",
        "type": "reps",
        "default_target": "10 reps",
        "target_muscles": "Spine, Core",
        "instructions": "Inhale arching back, exhale tucking chin and rounding spine.",
    },
    {
        "id": "worlds_greatest_stretch",
        "name": "World's Greatest Stretch",
        "category": "mobility",
        "equipment": "yoga_mat",
        "phase": "warmup",
        "type": "reps",
        "default_target": "5 / side",
        "target_muscles": "Hips, Thoracic Spine, Hamstrings",
        "instructions": "Deep lunge with elbow to inside of front ankle, then rotate torso reaching arm up.",
    },
    {
        "id": "jumping_jacks_warmup",
        "name": "Jumping Jacks",
        "category": "cardio",
        "equipment": "none",
        "phase": "warmup",
        "type": "time",
        "default_target": "45s",
        "target_muscles": "Full Body, Calves",
        "instructions": "Light on toes with rhythmic breathing to elevate heart rate.",
    },
    {
        "id": "jump_rope_easy_rhythm",
        "name": "Jump Rope Light Rhythm",
        "category": "cardio",
        "equipment": "jump_rope",
        "phase": "warmup",
        "type": "time",
        "default_target": "60s",
        "target_muscles": "Calves, Cardio, Coordination",
        "instructions": "Light continuous basic bounce, elbows tucked, rotating from wrists.",
    },
    {
        "id": "bird_dog_mat",
        "name": "Bird-Dog Core Warm-up",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "warmup",
        "type": "reps",
        "default_target": "8 / side",
        "target_muscles": "Lower Back, Glutes, Core",
        "instructions": "Opposite arm and leg reach, squeeze glute at top, keep hips square.",
    },
    {
        "id": "band_pull_aparts_warmup",
        "name": "Band Pull-Aparts",
        "category": "upper",
        "equipment": "resistance_bands",
        "phase": "warmup",
        "type": "reps",
        "default_target": "15 reps",
        "target_muscles": "Rear Delts, Rotator Cuff",
        "instructions": "Hold band with arms extended straight out, pull apart squeezing shoulder blades.",
    },

    # --- CARDIO & HIIT (phase: main) ---
    {
        "id": "jump_rope_intervals",
        "name": "Jump Rope Speed Intervals",
        "category": "cardio",
        "equipment": "jump_rope",
        "phase": "main",
        "type": "time",
        "default_target": "45s on / 15s rest",
        "target_muscles": "Calves, Cardio, Shoulders",
        "instructions": "High cadence basic bounce or boxer step. Stay on the balls of your feet.",
    },
    {
        "id": "jump_rope_high_knees",
        "name": "Jump Rope High Knee Sprints",
        "category": "cardio",
        "equipment": "jump_rope",
        "phase": "main",
        "type": "time",
        "default_target": "30s max effort",
        "target_muscles": "Hip Flexors, Quads, Core, Cardio",
        "instructions": "Drive knees up alternatively with each rope rotation. Explosive tempo.",
    },
    {
        "id": "jump_rope_boxer_step",
        "name": "Jump Rope Boxer Step",
        "category": "cardio",
        "equipment": "jump_rope",
        "phase": "main",
        "type": "time",
        "default_target": "60s",
        "target_muscles": "Coordination, Footwork, Cardio",
        "instructions": "Shift weight subtly from left to right foot each skip. Relaxed rhythm.",
    },
    {
        "id": "burpees_full_body",
        "name": "Full Body Burpees",
        "category": "cardio",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "10-12 reps",
        "target_muscles": "Full Body, Cardio",
        "instructions": "Drop chest to floor, kick back, explode up with jump and overhead clap.",
    },
    {
        "id": "mountain_climbers_mat",
        "name": "Mountain Climbers",
        "category": "cardio",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "time",
        "default_target": "40s",
        "target_muscles": "Core, Shoulders, Hip Flexors",
        "instructions": "Hands firmly on mat under shoulders, drive knees toward chest alternately at quick tempo.",
    },
    {
        "id": "skater_hops",
        "name": "Lateral Skater Hops",
        "category": "cardio",
        "equipment": "none",
        "phase": "main",
        "type": "time",
        "default_target": "45s",
        "target_muscles": "Glute Medius, Calves, Balance",
        "instructions": "Bound side to side, landing softly on one foot with opposite leg trailing behind.",
    },

    # --- UPPER BODY (phase: main) ---
    {
        "id": "push_ups_standard",
        "name": "Strict Push-ups",
        "category": "upper",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "10-15 reps",
        "target_muscles": "Chest, Front Deltoids, Triceps",
        "instructions": "Body straight as a plank, elbows at 45°, chest touches 2 inches above ground.",
    },
    {
        "id": "diamond_push_ups",
        "name": "Diamond Push-ups",
        "category": "upper",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "8-12 reps",
        "target_muscles": "Triceps, Inner Chest",
        "instructions": "Thumbs and index fingers touching under sternum. Lower chest to hands.",
    },
    {
        "id": "pike_push_ups",
        "name": "Pike Push-ups",
        "category": "upper",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "8-10 reps",
        "target_muscles": "Shoulders, Triceps, Traps",
        "instructions": "Hips pushed high into an inverted V. Lower forehead forward toward floor.",
    },
    {
        "id": "chair_dips",
        "name": "Chair / Bench Tricep Dips",
        "category": "upper",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "12-15 reps",
        "target_muscles": "Triceps, Anterior Shoulders",
        "instructions": "Palms on edge of chair/couch, lower hips bending elbows to 90°, press up.",
    },
    {
        "id": "pull_ups_bar",
        "name": "Pull-ups (Overhand)",
        "category": "upper",
        "equipment": "pull_up_bar",
        "phase": "main",
        "type": "reps",
        "default_target": "6-10 reps",
        "target_muscles": "Lats, Upper Back, Biceps",
        "instructions": "Full range from dead hang to chin clearly over bar without swinging.",
    },
    {
        "id": "chin_ups_bar",
        "name": "Chin-ups (Underhand)",
        "category": "upper",
        "equipment": "pull_up_bar",
        "phase": "main",
        "type": "reps",
        "default_target": "6-10 reps",
        "target_muscles": "Biceps, Lats",
        "instructions": "Supinated grip, pull elbows down into ribcage, chin over bar.",
    },
    {
        "id": "banded_bent_over_row",
        "name": "Banded Bent-over Row",
        "category": "upper",
        "equipment": "resistance_bands",
        "phase": "main",
        "type": "reps",
        "default_target": "12-15 reps",
        "target_muscles": "Lats, Rhomboids, Rear Delts",
        "instructions": "Stand on band, hinge hips 45°, pull handles to hips driving elbows back.",
    },
    {
        "id": "dumbbell_overhead_press",
        "name": "Dumbbell Overhead Press",
        "category": "upper",
        "equipment": "dumbbells",
        "phase": "main",
        "type": "reps",
        "default_target": "10-12 reps",
        "target_muscles": "Deltoids, Triceps",
        "instructions": "Press dumbbells overhead from ear level, locking arms out without arching back.",
    },
    {
        "id": "dumbbell_floor_press",
        "name": "Dumbbell Floor Press",
        "category": "upper",
        "equipment": "dumbbells",
        "phase": "main",
        "type": "reps",
        "default_target": "10-12 reps",
        "target_muscles": "Chest, Triceps",
        "instructions": "Lie on mat, knees bent, press dumbbells up until arms extend; elbows gently touch mat at bottom.",
    },

    # --- LOWER BODY (phase: main) ---
    {
        "id": "air_squats_cadence",
        "name": "Tempo Air Squats",
        "category": "lower",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "15-20 reps",
        "target_muscles": "Quads, Glutes, Hamstrings",
        "instructions": "Feet shoulder-width, break at hips and knees, descend below parallel, drive through whole foot.",
    },
    {
        "id": "walking_lunges",
        "name": "Walking Lunges",
        "category": "lower",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "10 / leg",
        "target_muscles": "Quads, Glutes, Core Stability",
        "instructions": "Step forward with chest upright, back knee gently kissing floor, push through front heel.",
    },
    {
        "id": "jump_squats_power",
        "name": "Explosive Jump Squats",
        "category": "lower",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "10-12 reps",
        "target_muscles": "Fast-Twitch Quads, Calves, Glutes",
        "instructions": "Descend into squat and explode vertically into air. Land softly absorbing impact.",
    },
    {
        "id": "bulgarian_split_squat",
        "name": "Bulgarian Split Squats",
        "category": "lower",
        "equipment": "none",
        "phase": "main",
        "type": "reps",
        "default_target": "8-10 / leg",
        "target_muscles": "Quads, Glutes",
        "instructions": "Rear foot elevated on couch or step. Lower front thigh to parallel, chest proud.",
    },
    {
        "id": "glute_bridge_mat",
        "name": "Glute Bridges on Mat",
        "category": "lower",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "reps",
        "default_target": "15-20 reps",
        "target_muscles": "Gluteus Maximus, Hamstrings",
        "instructions": "Lie on mat, heels near hips, bridge hips up squeezing glutes hard for 2 seconds at top.",
    },
    {
        "id": "single_leg_bridge_mat",
        "name": "Single-Leg Glute Bridge",
        "category": "lower",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "reps",
        "default_target": "10 / leg",
        "target_muscles": "Unilateral Glute & Hamstring",
        "instructions": "One leg extended in air, drive through planted heel to full hip extension.",
    },
    {
        "id": "wall_sit_isometric",
        "name": "Wall Sit",
        "category": "lower",
        "equipment": "none",
        "phase": "main",
        "type": "time",
        "default_target": "45s",
        "target_muscles": "Quad Isometric Endurance",
        "instructions": "Back flat against wall, thighs parallel to floor at 90°, arms at sides.",
    },
    {
        "id": "dumbbell_goblet_squat",
        "name": "Goblet Squats",
        "category": "lower",
        "equipment": "dumbbells",
        "phase": "main",
        "type": "reps",
        "default_target": "10-12 reps",
        "target_muscles": "Quads, Glutes, Core",
        "instructions": "Hold dumbbell vertical at chest level, elbows tucked, squat deep between knees.",
    },
    {
        "id": "kettlebell_swings",
        "name": "Kettlebell Swings",
        "category": "lower",
        "equipment": "kettlebell",
        "phase": "main",
        "type": "reps",
        "default_target": "15-20 reps",
        "target_muscles": "Posterior Chain, Glutes, Hamstrings",
        "instructions": "Powerful hip hinge, snap hips to project kettlebell to chest height. Never an arm raise.",
    },

    # --- CORE & MAT (phase: main) ---
    {
        "id": "forearm_plank_mat",
        "name": "Forearm Plank",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "time",
        "default_target": "45-60s",
        "target_muscles": "Rectus Abdominis, Transverse Abdominis",
        "instructions": "Elbows under shoulders on mat, tuck pelvis, squeeze glutes and quads tight.",
    },
    {
        "id": "side_plank_mat",
        "name": "Side Plank (Left & Right)",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "time",
        "default_target": "30s / side",
        "target_muscles": "Obliques, QL, Shoulder Stability",
        "instructions": "Stack feet, elevate hips in a straight diagonal line, hold steady.",
    },
    {
        "id": "hollow_body_hold_mat",
        "name": "Hollow Body Hold",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "time",
        "default_target": "30-40s",
        "target_muscles": "Deep Anterior Core",
        "instructions": "Press lower back completely into mat, lift shoulder blades and feet 6 inches off ground.",
    },
    {
        "id": "deadbug_mat",
        "name": "Deadbugs",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "reps",
        "default_target": "10 / side",
        "target_muscles": "Anti-Extension Core",
        "instructions": "Lower opposite arm and leg while pinning lower back glued firmly to mat.",
    },
    {
        "id": "bicycle_crunches_mat",
        "name": "Bicycle Crunches",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "reps",
        "default_target": "20 reps",
        "target_muscles": "Obliques, Rectus Abdominis",
        "instructions": "Slow controlled tempo, bring elbow to opposite knee rotating through upper torso.",
    },
    {
        "id": "russian_twists_mat",
        "name": "Russian Twists",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "reps",
        "default_target": "20 total",
        "target_muscles": "Obliques, Rotational Core",
        "instructions": "Sit in V position with heels elevated or on mat, rotate shoulders tapping side to side.",
    },
    {
        "id": "superman_hold_mat",
        "name": "Superman Arch Hold",
        "category": "core",
        "equipment": "yoga_mat",
        "phase": "main",
        "type": "time",
        "default_target": "30s",
        "target_muscles": "Erector Spinae, Glutes, Rhomboids",
        "instructions": "Lie face down, simultaneously lift chest and quads off mat squeezing posterior chain.",
    },
    {
        "id": "hanging_knee_raises",
        "name": "Hanging Knee Raises",
        "category": "core",
        "equipment": "pull_up_bar",
        "phase": "main",
        "type": "reps",
        "default_target": "10-12 reps",
        "target_muscles": "Lower Abs, Grip Strength",
        "instructions": "Dead hang on bar, curl knees up toward chest without swinging or arching.",
    },

    # --- COOL-DOWN & MOBILITY (phase: cooldown) ---
    {
        "id": "childs_pose_mat",
        "name": "Child's Pose",
        "category": "mobility",
        "equipment": "yoga_mat",
        "phase": "cooldown",
        "type": "time",
        "default_target": "60s",
        "target_muscles": "Lats, Lower Back, Hips",
        "instructions": "Knees wide on mat, sit hips back to heels, extend arms forward, deep belly breaths.",
    },
    {
        "id": "cobra_stretch_mat",
        "name": "Cobra / Upward Dog",
        "category": "mobility",
        "equipment": "yoga_mat",
        "phase": "cooldown",
        "type": "time",
        "default_target": "45s",
        "target_muscles": "Abdominals, Hip Flexors",
        "instructions": "Lie face down, press palms to extend arms, lift chest up while relaxing lower back.",
    },
    {
        "id": "pigeon_pose_mat",
        "name": "Pigeon Pose",
        "category": "mobility",
        "equipment": "yoga_mat",
        "phase": "cooldown",
        "type": "time",
        "default_target": "45s / side",
        "target_muscles": "Glute, Piriformis, Hip Capsule",
        "instructions": "Front shin across mat, rear leg extended straight back. Sink hips down.",
    },
    {
        "id": "seated_hamstring_mat",
        "name": "Seated Forward Fold",
        "category": "mobility",
        "equipment": "yoga_mat",
        "phase": "cooldown",
        "type": "time",
        "default_target": "60s",
        "target_muscles": "Hamstrings, Calves, Back",
        "instructions": "Legs straight on mat, reach chest forward toward toes without aggressively rounding.",
    },
    {
        "id": "standing_quad_stretch",
        "name": "Standing Quad Stretch",
        "category": "mobility",
        "equipment": "none",
        "phase": "cooldown",
        "type": "time",
        "default_target": "30s / leg",
        "target_muscles": "Quadriceps, Hip Flexors",
        "instructions": "Hold ankle behind glute, pull heel to buttocks while keeping knees together.",
    },
]


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


@router.post("/equipment", status_code=201)
def add_or_toggle_equipment(request: Request, payload: EquipmentIn):
    """Add or toggle an equipment item for the active profile."""
    key = payload.item_key.strip().lower()
    name = payload.name.strip()
    if not key or not name:
        raise HTTPException(status_code=400, detail="Invalid equipment key or name.")

    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        existing = conn.execute(
            "SELECT id FROM profile_equipment WHERE profile_id = ? AND item_key = ?",
            (profile_id, key),
        ).fetchone()

        now_str = config.now().isoformat()
        if existing:
            # If already exists, delete it (toggle off)
            conn.execute(
                "DELETE FROM profile_equipment WHERE id = ?", (existing["id"],)
            )
            return {"status": "removed", "item_key": key}
        else:
            conn.execute(
                """INSERT INTO profile_equipment (profile_id, item_key, name, acquired_at, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (profile_id, key, name, now_str, payload.notes),
            )
            return {"status": "added", "item_key": key, "name": name}


@router.delete("/equipment/{item_key}", status_code=204)
def remove_equipment(request: Request, item_key: str):
    """Remove an equipment item from the active profile."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        conn.execute(
            "DELETE FROM profile_equipment WHERE profile_id = ? AND item_key = ?",
            (profile_id, item_key.strip().lower()),
        )


@router.post("/generate")
def generate_workout(request: Request, params: WorkoutGenerateIn):
    """Generate a structured workout routine strictly tailored to available equipment."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        owned_keys = _get_profile_equipment_keys(conn, profile_id)

    # Filter exercises where user possesses the required equipment
    eligible = [e for e in EXERCISE_CATALOG if e["equipment"] in owned_keys]
    if not eligible:
        raise HTTPException(status_code=400, detail="No eligible exercises found for your equipment.")

    category = params.category
    duration = params.duration_min
    level = params.level

    # Pool separation by phase
    warmups_pool = [e for e in eligible if e["phase"] == "warmup"]
    main_pool = [e for e in eligible if e["phase"] == "main"]
    cooldowns_pool = [e for e in eligible if e["phase"] == "cooldown"]

    # Filter main pool by category if specific
    if category == "hiit":
        cat_main = [e for e in main_pool if e["category"] in ("cardio", "core")]
    elif category == "upper":
        cat_main = [e for e in main_pool if e["category"] in ("upper", "core")]
    elif category == "lower":
        cat_main = [e for e in main_pool if e["category"] in ("lower", "core")]
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

    routine = {
        "title": title,
        "category": category,
        "duration_min": duration,
        "rounds": rounds,
        "work_rest": work_rest_str,
        "level": level,
        "intensity": level,
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
                "desc": f"Perform consecutively with 1-2 min rest between full circuits.",
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

    return routine


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
            "options": {"temperature": 0.3, "num_predict": 1200},
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "{}")
                data = json.loads(content)
                data["equipment_used"] = equip_names
                data["estimated_calories"] = round(params.duration_min * 8)
                return data
    except Exception as exc:
        log.warning("Local AI workout generation fallback: %s", exc)

    # Seamless fallback to offline generator if Ollama is unavailable
    return generate_workout(request, params)


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
def list_workouts(request: Request, limit: int = 30):
    """List recent completed workouts for the active profile."""
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
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

        week_count = conn.execute(
            """SELECT COUNT(*) as cnt, COALESCE(SUM(duration_min), 0) as total_min
               FROM workouts WHERE profile_id = ? AND day >= date('now', '-7 days')""",
            (profile_id,),
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
