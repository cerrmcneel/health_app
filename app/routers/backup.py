"""Data portability & backup export: Zero-lock-in data export.

Provides a clean standalone ZIP archive containing:
- Consistent, WAL-safe snapshot of tracker.db
- All progress photos and meal images in storage/
- Export metadata manifest
"""
import io
import json
import sqlite3
import zipfile
from fastapi import APIRouter
from fastapi.responses import Response

from app import config
from app.db import get_conn

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("/export")
def export_backup():
    """Download a complete standalone ZIP backup of all health data and media."""
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Consistent in-memory WAL checkpoint backup of SQLite DB
        mem_db = sqlite3.connect(":memory:")
        with get_conn() as live_conn:
            live_conn.backup(mem_db)
        db_bytes = mem_db.serialize()
        mem_db.close()
        zf.writestr("tracker.db", db_bytes)

        # 2. Archive all stored media (progress photos, meal images)
        storage_dir = config.STORAGE_DIR.resolve()
        media_files: list[str] = []
        if storage_dir.exists():
            for file_path in storage_dir.rglob("*"):
                if file_path.is_file():
                    # Skip the live database and its WAL files from the filesystem pass
                    # (they are already safely captured in tracker.db above)
                    if file_path.name.startswith("tracker.db"):
                        continue
                    rel_path = file_path.relative_to(storage_dir)
                    zf.write(file_path, arcname=f"storage/{rel_path.as_posix()}")
                    media_files.append(rel_path.as_posix())

        # 3. Export Manifest
        manifest = {
            "version": "1.0",
            "exported_at": config.now().isoformat(),
            "today": config.today_iso(),
            "media_files_count": len(media_files),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    filename = f"health_tracker_backup_{config.today_iso()}.zip"
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
