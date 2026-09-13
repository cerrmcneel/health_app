"""Data portability & backup export: Zero-lock-in data export.

Provides clean standalone ZIP archives:
1. Per-profile export (default): Strictly isolated export containing only the
   requesting profile's records (meals, meal items, weights, workouts, equipment,
   and progress photos) and personal media files.
2. Full instance backup (?scope=all): Administrative complete instance backup
   including the entire SQLite database and storage directory. Requires
   APP_PASSWORD to be configured, and the active profile to be the default one.

The default-profile condition is a guard rail, not a security boundary. The
active profile comes from the client-supplied X-Profile-ID header, so anyone who
has already authenticated can present the default profile's id and reach the
full dump. That is acceptable today because APP_PASSWORD is a single secret
shared by the whole household -- everyone who can log in holds the same
credential -- but it stops being acceptable the moment two households share one
instance. Binding the profile to the signed session cookie is the fix; see
PLAN_WORKOUT_HARDENING.md Task 3.7 Layer 2.
"""
import io
import json
import sqlite3
import zipfile
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app import auth, config
from app.db import AFTER_MIGRATE_SCHEMA, SCHEMA, get_conn
from app.deps import get_profile_id

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _copy_table(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    table_name: str,
    query: str,
    params: tuple = (),
) -> list[dict]:
    """Copy matching rows from src to dst using identical column definitions."""
    rows = [dict(r) for r in src.execute(query, params).fetchall()]
    if not rows:
        return []
    cols = list(rows[0].keys())
    col_str = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))
    insert_sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders})"
    for r in rows:
        dst.execute(insert_sql, tuple(r[c] for c in cols))
    return rows


@router.get("/export")
def export_backup(request: Request, scope: str = Query(default="profile")):
    """Download a standalone ZIP backup of health data.

    - scope=profile (default): Exports ONLY the requesting profile's records and photos.
    - scope=all: Full instance backup. Restricted to default admin profile and requires
      APP_PASSWORD to be configured in the environment.
    """
    if scope not in ("profile", "all", "instance"):
        raise HTTPException(
            status_code=400,
            detail="Invalid scope. Supported scopes: 'profile', 'all'.",
        )

    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        prof = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not prof:
            raise HTTPException(status_code=404, detail="Profile not found.")

        zip_buffer = io.BytesIO()

        if scope in ("all", "instance"):
            # Task 7.1 (a): Administrative full-instance backup
            if not auth.is_auth_enabled():
                raise HTTPException(
                    status_code=403,
                    detail="Full-instance backup requires APP_PASSWORD to be configured in the environment.",
                )
            if not prof["is_default"]:
                raise HTTPException(
                    status_code=403,
                    detail="Full-instance backup is restricted to the default administrative profile.",
                )

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # Consistent WAL snapshot of entire database
                mem_db = sqlite3.connect(":memory:")
                conn.backup(mem_db)
                db_bytes = mem_db.serialize()
                mem_db.close()
                zf.writestr("tracker.db", db_bytes)

                # All media in storage
                storage_dir = config.STORAGE_DIR.resolve()
                media_files: list[str] = []
                if storage_dir.exists():
                    for file_path in storage_dir.rglob("*"):
                        if file_path.is_file():
                            if file_path.name.startswith("tracker.db"):
                                continue
                            rel_path = file_path.relative_to(storage_dir)
                            zf.write(file_path, arcname=f"storage/{rel_path.as_posix()}")
                            media_files.append(rel_path.as_posix())

                manifest = {
                    "version": "1.0",
                    "scope": "instance",
                    "exported_at": config.now().isoformat(),
                    "today": config.today_iso(),
                    "media_files_count": len(media_files),
                }
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            filename = f"health_tracker_instance_{config.today_iso()}.zip"

        else:
            # Task 7.1 (b): Isolated per-profile export
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                mem_db = sqlite3.connect(":memory:")
                mem_db.row_factory = sqlite3.Row
                mem_db.executescript(SCHEMA)
                mem_db.executescript(AFTER_MIGRATE_SCHEMA)

                # Copy only the requesting profile's rows
                _copy_table(conn, mem_db, "profiles", "SELECT * FROM profiles WHERE id = ?", (profile_id,))
                meals = _copy_table(conn, mem_db, "meals", "SELECT * FROM meals WHERE profile_id = ?", (profile_id,))
                meal_ids = [m["id"] for m in meals]
                meal_items: list[dict] = []
                if meal_ids:
                    placeholders = ", ".join(["?"] * len(meal_ids))
                    meal_items = _copy_table(
                        conn,
                        mem_db,
                        "meal_items",
                        f"SELECT * FROM meal_items WHERE meal_id IN ({placeholders})",
                        tuple(meal_ids),
                    )
                weights = _copy_table(conn, mem_db, "weights", "SELECT * FROM weights WHERE profile_id = ?", (profile_id,))
                photos = _copy_table(
                    conn,
                    mem_db,
                    "progress_photos",
                    "SELECT * FROM progress_photos WHERE profile_id = ?",
                    (profile_id,),
                )
                equipment = _copy_table(
                    conn,
                    mem_db,
                    "profile_equipment",
                    "SELECT * FROM profile_equipment WHERE profile_id = ?",
                    (profile_id,),
                )
                workouts = _copy_table(conn, mem_db, "workouts", "SELECT * FROM workouts WHERE profile_id = ?", (profile_id,))
                weekly_plans = _copy_table(conn, mem_db, "weekly_plans", "SELECT * FROM weekly_plans WHERE profile_id = ?", (profile_id,))

                mem_db.commit()
                db_bytes = mem_db.serialize()
                mem_db.close()
                zf.writestr("tracker.db", db_bytes)

                # Collect and copy strictly only this profile's media files
                storage_dir = config.STORAGE_DIR.resolve()
                profile_media_paths: set[str] = set()
                for p in photos:
                    if p.get("path"):
                        profile_media_paths.add(p["path"])
                for m in meals:
                    if m.get("image_path"):
                        profile_media_paths.add(m["image_path"])

                media_written: list[str] = []
                for rel_str in sorted(profile_media_paths):
                    file_path = (storage_dir / rel_str).resolve()
                    # Computed outside the f-string: a backslash inside a format
                    # expression is a SyntaxError before Python 3.12 (PEP 701),
                    # and the README supports 3.11+.
                    arc_rel = rel_str.replace("\\", "/")
                    try:
                        file_path.relative_to(storage_dir)
                        if file_path.is_file():
                            zf.write(file_path, arcname=f"storage/{arc_rel}")
                            media_written.append(arc_rel)
                    except ValueError:
                        continue

                manifest = {
                    "version": "1.0",
                    "scope": "profile",
                    "profile_id": profile_id,
                    "profile_name": prof["name"],
                    "profile_slug": prof["slug"],
                    "exported_at": config.now().isoformat(),
                    "today": config.today_iso(),
                    "counts": {
                        "meals": len(meals),
                        "meal_items": len(meal_items),
                        "weights": len(weights),
                        "workouts": len(workouts),
                        "progress_photos": len(photos),
                        "equipment": len(equipment),
                    },
                    "media_files_count": len(media_written),
                }
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            slug = prof["slug"] if "slug" in prof.keys() else f"profile_{profile_id}"
            filename = f"health_data_{slug}_{config.today_iso()}.zip"

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
