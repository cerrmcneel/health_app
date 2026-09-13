"""Profile management for multi-user/multi-profile tracking."""
import sqlite3
from fastapi import APIRouter, HTTPException, Request, Response

from app import config
from app.db import get_conn
from app.data.exercises import STANDARD_EQUIPMENT
from app.deps import get_profile, get_profile_id, sanitize_profile, slugify
from app.models import OnboardingIn, ProfileIn, ProfileUpdate, TargetPreviewIn, VerifyPinIn
from app.services.profile_security import (
    check_rate_limit,
    hash_pin,
    record_failed_attempt,
    record_successful_attempt,
    sign_profile_token,
    verify_pin,
    verify_profile_token,
)
from app.services.targets import compute_targets

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
def list_profiles(request: Request):
    """List all available profiles without PIN obstruction."""
    with get_conn() as conn:
        active_id = get_profile_id(request, conn, check_pin=False)
        rows = conn.execute(
            "SELECT * FROM profiles ORDER BY is_default DESC, id ASC"
        ).fetchall()
        profiles = [sanitize_profile(dict(r)) for r in rows]
        for p in profiles:
            p["is_active"] = (p["id"] == active_id)
        return {"profiles": profiles, "active_profile_id": active_id}


@router.post("", status_code=201)
def create_profile(payload: ProfileIn):
    """Create a new profile."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name cannot be empty.")

    base_slug = slugify(name)
    when = config.now().isoformat()

    pin_hash, pin_salt = (hash_pin(payload.pin) if payload.pin else (None, None))

    with get_conn() as conn:
        # Check uniqueness of name
        existing = conn.execute("SELECT id FROM profiles WHERE name = ?", (name,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Profile '{name}' already exists.")

        # Ensure slug uniqueness
        slug = base_slug
        counter = 1
        while conn.execute("SELECT id FROM profiles WHERE slug = ?", (slug,)).fetchone():
            counter += 1
            slug = f"{base_slug}-{counter}"

        cur = conn.execute(
            """INSERT INTO profiles (name, slug, created_at, avatar_color,
                                     calorie_target, protein_target, carbs_target, fat_target,
                                     is_default, seeded_equipment, pin_hash, pin_salt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)""",
            (name, slug, when, payload.avatar_color,
             payload.calorie_target, payload.protein_target, payload.carbs_target, payload.fat_target,
             pin_hash, pin_salt),
        )
        profile_id = cur.lastrowid
        conn.execute(
            """INSERT OR IGNORE INTO profile_equipment (profile_id, item_key, name, acquired_at)
               VALUES (?, 'yoga_mat', 'Yoga Mat', ?),
                      (?, 'jump_rope', 'Jump Rope', ?)""",
            (profile_id, when, profile_id, when),
        )
        return sanitize_profile(dict(conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()))


@router.get("/{profile_id}")
def get_profile_by_id(profile_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found.")
        return sanitize_profile(dict(row))


@router.post("/{profile_id}/verify-pin")
def verify_profile_pin(profile_id: int, payload: VerifyPinIn, request: Request, response: Response):
    """Verify 4-digit PIN for profile and return signed token / set cookie."""
    with get_conn() as conn:
        row = conn.execute("SELECT id, pin_hash, pin_salt FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found.")

        if not row["pin_hash"]:
            token = sign_profile_token(profile_id)
            response.set_cookie(f"profile_token_{profile_id}", token, max_age=86400 * 7, httponly=False, samesite="lax", path="/")
            return {"token": token, "profile_id": profile_id, "has_pin": False}

        client_ip = request.client.host if request.client else "127.0.0.1"
        rate_key = f"{profile_id}:{client_ip}"
        check_rate_limit(rate_key)

        if not verify_pin(payload.pin, row["pin_hash"], row["pin_salt"]):
            record_failed_attempt(rate_key)
            raise HTTPException(status_code=401, detail="Incorrect PIN.")

        record_successful_attempt(rate_key)
        token = sign_profile_token(profile_id)
        response.set_cookie(f"profile_token_{profile_id}", token, max_age=86400 * 7, httponly=False, samesite="lax", path="/")
        return {"token": token, "profile_id": profile_id, "expires_in": 86400 * 7, "has_pin": True}


@router.post("/{profile_id}/lock")
def lock_profile(profile_id: int, response: Response):
    """Lock profile and clear browser unlock cookie."""
    response.delete_cookie(f"profile_token_{profile_id}", path="/")
    return {"locked": profile_id}


@router.patch("/{profile_id}")
def update_profile(profile_id: int, patch: ProfileUpdate, request: Request):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found.")

        has_pin = bool(row["pin_hash"])
        fields = patch.model_dump(exclude_unset=True)

        # Handle PIN configuration / changes / removal
        if fields.get("remove_pin"):
            if has_pin:
                cur_pin = fields.get("current_pin")
                if not cur_pin or not verify_pin(cur_pin, row["pin_hash"], row["pin_salt"]):
                    raise HTTPException(status_code=400, detail="Current PIN is incorrect.")
            fields["pin_hash"] = None
            fields["pin_salt"] = None
        elif "pin" in fields and fields["pin"] is not None:
            if has_pin:
                cur_pin = fields.get("current_pin")
                if not cur_pin or not verify_pin(cur_pin, row["pin_hash"], row["pin_salt"]):
                    raise HTTPException(status_code=400, detail="Current PIN is incorrect.")
            new_hash, new_salt = hash_pin(fields["pin"])
            fields["pin_hash"] = new_hash
            fields["pin_salt"] = new_salt
        elif has_pin:
            # Profile has a PIN and non-PIN fields are being updated; verify token or current_pin
            token = (
                request.headers.get("X-Profile-Token")
                or request.cookies.get(f"profile_token_{profile_id}")
            )
            is_authed = bool(token and verify_profile_token(token, profile_id))
            if not is_authed and fields.get("current_pin"):
                is_authed = verify_pin(fields["current_pin"], row["pin_hash"], row["pin_salt"])
            if not is_authed:
                raise HTTPException(status_code=403, detail="Profile is locked. PIN verification required.")

        fields.pop("current_pin", None)
        fields.pop("remove_pin", None)
        fields.pop("pin", None)

        if "name" in fields and fields["name"] is not None:
            name = fields["name"].strip()
            if not name:
                raise HTTPException(status_code=400, detail="Profile name cannot be empty.")
            dup = conn.execute("SELECT id FROM profiles WHERE name = ? AND id != ?", (name, profile_id)).fetchone()
            if dup:
                raise HTTPException(status_code=409, detail=f"Profile '{name}' already exists.")
            fields["name"] = name
            base_slug = slugify(name)
            slug = base_slug
            counter = 1
            while conn.execute("SELECT id FROM profiles WHERE slug = ? AND id != ?", (slug, profile_id)).fetchone():
                counter += 1
                slug = f"{base_slug}-{counter}"
            fields["slug"] = slug

        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE profiles SET {assignments} WHERE id = ?",
                (*fields.values(), profile_id),
            )

        return sanitize_profile(dict(conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()))


@router.delete("/{profile_id}")
def delete_profile(profile_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found.")
        if row["is_default"]:
            raise HTTPException(status_code=400, detail="Cannot delete the default profile.")

        count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        if count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the only remaining profile.")

        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        return {"deleted": profile_id}


@router.post("/{profile_id}/default")
def set_default_profile(profile_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found.")

        conn.execute("UPDATE profiles SET is_default = 0")
        conn.execute("UPDATE profiles SET is_default = 1 WHERE id = ?", (profile_id,))
        return {"default_profile_id": profile_id}


@router.post("/preview-targets")
def preview_targets(payload: TargetPreviewIn):
    """Compute and preview targets without saving."""
    return compute_targets(
        sex=payload.sex,
        weight_kg=payload.weight_kg,
        height_cm=payload.height_cm,
        age=payload.age,
        activity_level=payload.activity_level,
        goal=payload.goal,
        goal_rate_kg_per_week=payload.goal_rate_kg_per_week,
    )


@router.post("/{profile_id}/onboarding")
def complete_onboarding(profile_id: int, payload: OnboardingIn):
    """Save guided profile onboarding stats, update targets, log initial weight, and set inventory."""
    with get_conn() as conn:
        prof = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not prof:
            raise HTTPException(status_code=404, detail="Profile not found.")

        name = prof["name"]
        slug = prof["slug"]
        if payload.name and payload.name.strip():
            candidate_name = payload.name.strip()
            if candidate_name != prof["name"]:
                dup = conn.execute(
                    "SELECT id FROM profiles WHERE name = ? AND id != ?", (candidate_name, profile_id)
                ).fetchone()
                if dup:
                    raise HTTPException(status_code=409, detail=f"Profile '{candidate_name}' already exists.")
                name = candidate_name
                base_slug = slugify(name)
                slug = base_slug
                counter = 1
                while conn.execute("SELECT id FROM profiles WHERE slug = ? AND id != ?", (slug, profile_id)).fetchone():
                    counter += 1
                    slug = f"{base_slug}-{counter}"

        avatar_color = payload.avatar_color or prof["avatar_color"]

        calorie_target = payload.calorie_target or prof["calorie_target"]
        protein_target = payload.protein_target or prof["protein_target"]
        carbs_target = payload.carbs_target or prof["carbs_target"]
        fat_target = payload.fat_target or prof["fat_target"]

        now_dt = config.now()
        now_str = now_dt.isoformat()
        today_str = config.today_iso()

        age = None
        if payload.birth_year:
            age = max(10, min(120, now_dt.year - payload.birth_year))

        if payload.current_weight_kg and payload.height_cm and age:
            if not payload.calorie_target:
                calc = compute_targets(
                    sex=payload.sex,
                    weight_kg=payload.current_weight_kg,
                    height_cm=payload.height_cm,
                    age=age,
                    activity_level=payload.activity_level,
                    goal=payload.goal,
                    goal_rate_kg_per_week=payload.goal_rate_kg_per_week or 0.5,
                )
                calorie_target = calc["calorie_target"]
                protein_target = calc["protein_target"]
                carbs_target = calc["carbs_target"]
                fat_target = calc["fat_target"]

            conn.execute(
                """INSERT INTO weights (profile_id, day, logged_at, weight_kg, notes)
                   VALUES (?, ?, ?, ?, 'Initial onboarding weight')
                   ON CONFLICT(profile_id, day) DO UPDATE SET weight_kg = excluded.weight_kg, logged_at = excluded.logged_at""",
                (profile_id, today_str, now_str, payload.current_weight_kg),
            )

        if payload.equipment_keys is not None:
            eq_map = {item["key"]: item["name"] for item in STANDARD_EQUIPMENT}
            conn.execute("DELETE FROM profile_equipment WHERE profile_id = ?", (profile_id,))
            for key in payload.equipment_keys:
                k = key.strip().lower()
                if not k or k in ("none", "bodyweight"):
                    continue
                item_name = eq_map.get(k, k.replace("_", " ").title())
                conn.execute(
                    """INSERT OR IGNORE INTO profile_equipment (profile_id, item_key, name, acquired_at)
                       VALUES (?, ?, ?, ?)""",
                    (profile_id, k, item_name, now_str),
                )
            conn.execute("UPDATE profiles SET seeded_equipment = 1 WHERE id = ?", (profile_id,))

        onboarded_at = now_str

        conn.execute(
            """UPDATE profiles SET
                name = ?, slug = ?, avatar_color = ?,
                sex = ?, birth_year = ?, height_cm = ?,
                activity_level = ?, goal = ?, goal_rate_kg_per_week = ?,
                preferred_duration_min = ?, preferred_level = ?, workout_days_per_week = ?,
                calorie_target = ?, protein_target = ?, carbs_target = ?, fat_target = ?,
                onboarded_at = ?
               WHERE id = ?""",
            (
                name, slug, avatar_color,
                payload.sex, payload.birth_year, payload.height_cm,
                payload.activity_level, payload.goal, payload.goal_rate_kg_per_week,
                payload.preferred_duration_min or 25, payload.preferred_level or "intermediate", payload.workout_days_per_week or 3,
                calorie_target, protein_target, carbs_target, fat_target,
                onboarded_at, profile_id
            ),
        )

        return sanitize_profile(dict(conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()))

