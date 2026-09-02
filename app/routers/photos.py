"""Progress photo capture, ghost-reference lookup, and media serving."""
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app import config
from app.db import get_conn
from app.deps import get_profile, get_profile_id
from app.services import images

router = APIRouter(tags=["photos"])


@router.get("/api/photos/ghost")
def ghost(request: Request, pose: str = Query(..., pattern="^(front|profile)$")):
    """The most recent photo for a pose for the active profile, to overlay on the live viewfinder.

    Excludes today's own shot: re-taking a pose should align against the last
    session, not against the attempt just replaced.
    """
    today = config.now().date().isoformat()
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        row = conn.execute(
            """SELECT * FROM progress_photos
               WHERE profile_id = ? AND pose = ? AND day < ?
               ORDER BY day DESC LIMIT 1""",
            (profile_id, pose, today),
        ).fetchone()
    if row is None:
        return {"pose": pose, "photo": None}
    return {"pose": pose, "photo": _serialize(row)}


@router.get("/api/photos")
def list_photos(
    request: Request,
    pose: str | None = Query(default=None, pattern="^(front|profile)$"),
    limit: int = 60,
):
    limit = max(1, min(limit, 400))
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        sql = "SELECT * FROM progress_photos WHERE profile_id = ?"
        params: list = [profile_id]
        if pose:
            sql += " AND pose = ?"
            params.append(pose)
        sql += " ORDER BY day DESC, pose LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    return {"photos": [_serialize(r) for r in rows]}


@router.get("/api/photos/status")
def status(request: Request):
    """Which poses are already captured today for the active profile -- drives the capture flow's state."""
    today = config.now().date().isoformat()
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        rows = conn.execute(
            "SELECT pose FROM progress_photos WHERE profile_id = ? AND day = ?",
            (profile_id, today),
        ).fetchall()
    done = {r["pose"] for r in rows}
    return {
        "day": today,
        "done": sorted(done),
        "remaining": [p for p in config.POSES if p not in done],
    }


@router.post("/api/photos", status_code=201)
async def create_photo(
    request: Request,
    image: UploadFile = File(...),
    pose: str = Form(...),
    day: date | None = Form(default=None),
):
    if pose not in config.POSES:
        raise HTTPException(status_code=400, detail=f"pose must be one of {config.POSES}")

    target_day = (day or config.now().date()).isoformat()

    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)

    try:
        img = images.open_image(await image.read())
        rel, w, h, size = images.save_progress_photo(img, pose, target_day, profile_id=profile_id)
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM progress_photos WHERE profile_id = ? AND day = ? AND pose = ?",
            (profile_id, target_day, pose),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE progress_photos SET taken_at = ?, path = ?, width = ?, height = ?, bytes = ?
                   WHERE id = ?""",
                (config.now().isoformat(), rel, w, h, size, existing["id"]),
            )
            photo_id = existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO progress_photos (profile_id, day, taken_at, pose, path, width, height, bytes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (profile_id, target_day, config.now().isoformat(), pose, rel, w, h, size),
            )
            photo_id = cur.lastrowid

        row = conn.execute(
            "SELECT * FROM progress_photos WHERE id = ?", (photo_id,)
        ).fetchone()

    nxt = next((p for p in config.POSES if p != pose), None)
    return {"photo": _serialize(row), "next_pose": nxt}


@router.delete("/api/photos/{photo_id}", status_code=204)
def delete_photo(request: Request, photo_id: int):
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        row = conn.execute(
            "SELECT * FROM progress_photos WHERE id = ? AND profile_id = ?",
            (photo_id, profile_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Photo not found.")
        conn.execute("DELETE FROM progress_photos WHERE id = ?", (photo_id,))
        try:
            target = images.resolve_media(row["path"])
            if target.is_file():
                target.unlink()
        except Exception:
            pass


@router.get("/media/{path:path}")
def media(path: str):
    """Serve a stored image. Paths are validated against traversal."""
    try:
        target = images.resolve_media(path)
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(target, media_type="image/jpeg")


def _serialize(row) -> dict:
    photo = dict(row)
    photo["url"] = f"/media/{row['path']}"
    return photo
