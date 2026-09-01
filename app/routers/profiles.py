"""Profile management for multi-user/multi-profile tracking."""
import sqlite3
from fastapi import APIRouter, HTTPException, Request

from app import config
from app.db import get_conn
from app.deps import get_profile, get_profile_id, slugify
from app.models import ProfileIn, ProfileUpdate

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
def list_profiles(request: Request):
    """List all available profiles."""
    with get_conn() as conn:
        active_id = get_profile_id(request, conn)
        rows = conn.execute(
            "SELECT * FROM profiles ORDER BY is_default DESC, id ASC"
        ).fetchall()
        profiles = [dict(r) for r in rows]
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
                                     calorie_target, protein_target, carbs_target, fat_target, is_default)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (name, slug, when, payload.avatar_color,
             payload.calorie_target, payload.protein_target, payload.carbs_target, payload.fat_target),
        )
        profile_id = cur.lastrowid
        return dict(conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone())


@router.get("/{profile_id}")
def get_profile_by_id(profile_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found.")
        return dict(row)


@router.patch("/{profile_id}")
def update_profile(profile_id: int, patch: ProfileUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found.")

        fields = patch.model_dump(exclude_unset=True)
        if "name" in fields and fields["name"] is not None:
            name = fields["name"].strip()
            if not name:
                raise HTTPException(status_code=400, detail="Profile name cannot be empty.")
            dup = conn.execute("SELECT id FROM profiles WHERE name = ? AND id != ?", (name, profile_id)).fetchone()
            if dup:
                raise HTTPException(status_code=409, detail=f"Profile '{name}' already exists.")
            fields["name"] = name
            fields["slug"] = slugify(name)

        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE profiles SET {assignments} WHERE id = ?",
                (*fields.values(), profile_id),
            )

        return dict(conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone())


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
