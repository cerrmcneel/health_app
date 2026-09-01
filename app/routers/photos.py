"""Progress photo capture, ghost-reference lookup, and media serving."""
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app import config
from app.db import get_conn
from app.services import images

router = APIRouter(tags=["photos"])


@router.get("/api/photos/ghost")
def ghost(pose: str = Query(..., pattern="^(front|profile)$")):
    """The most recent photo for a pose, to overlay on the live viewfinder.

    Excludes today's own shot: re-taking a pose should align against the last
    session, not against the attempt just replaced.
    """
    today = config.now().date().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM progress_photos
               WHERE pose = ? AND day < ?
               ORDER BY day DESC LIMIT 1""",
            (pose, today),
        ).fetchone()
    if row is None:
        return {"pose": pose, "photo": None}
    return {"pose": pose, "photo": _serialize(row)}


@router.get("/api/photos")
def list_photos(
    pose: str | None = Query(default=None, pattern="^(front|profile)$"),
    limit: int = 60,
):
    limit = max(1, min(limit, 400))
    sql = "SELECT * FROM progress_photos"
    params: list = []
    if pose:
        sql += " WHERE pose = ?"
        params.append(pose)
    sql += " ORDER BY day DESC, pose LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"photos": [_serialize(r) for r in rows]}


@router.get("/api/photos/status")
def status():
    """Which poses are already captured today -- drives the capture flow's state."""
    today = config.now().date().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pose FROM progress_photos WHERE day = ?", (today,)
        ).fetchall()
    done = {r["pose"] for r in rows}
    return {
        "day": today,
        "done": sorted(done),
        "remaining": [p for p in config.POSES if p not in done],
    }


@router.post("/api/photos", status_code=201)
async def create_photo(
    image: UploadFile = File(...),
    pose: str = Form(...),
    day: date | None = Form(default=None),
):
    if pose not in config.POSES:
        raise HTTPException(status_code=400, detail=f"pose must be one of {config.POSES}")

    try:
        img = images.open_image(await image.read())
        target_day = (day or config.now().date()).isoformat()
        rel, w, h, size = images.save_progress_photo(img, pose, target_day)
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO progress_photos (day, taken_at, pose, path, width, height, bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(day, pose) DO UPDATE SET
                   taken_at = excluded.taken_at, path = excluded.path,
                   width = excluded.width, height = excluded.height,
                   bytes = excluded.bytes""",
            (target_day, config.now().isoformat(), pose, rel, w, h, size),
        )
        row = conn.execute(
            "SELECT * FROM progress_photos WHERE day = ? AND pose = ?", (target_day, pose)
        ).fetchone()

    nxt = next((p for p in config.POSES if p != pose), None)
    return {"photo": _serialize(row), "next_pose": nxt}


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
