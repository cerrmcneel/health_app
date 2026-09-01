"""Meal analysis and logging.

Analysis and logging are deliberately separate calls: /analyze never writes to the
database, so the user always gets an editable card to correct before anything is
committed. The photo is parked in _pending/ and claimed by token on confirm.
"""
from datetime import date, datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import config
from app.db import get_conn
from app.models import MealIn, MealUpdate
from app.services import images, vision

router = APIRouter(prefix="/api", tags=["meals"])


@router.post("/analyze")
async def analyze(image: UploadFile = File(...), model: str | None = Form(default=None)):
    """Estimate macros from a meal photo. Writes nothing to the database."""
    try:
        img = images.open_image(await image.read())
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    b64 = images.prepare_for_vision(img)
    try:
        result = await vision.analyze_meal(b64, model=model)
    except vision.VisionError as exc:
        # 502: the failure is in the upstream model, not in the client's request.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not result["items"]:
        raise HTTPException(
            status_code=422,
            detail="The model found no food in this photo. Try a clearer shot, or log it by hand.",
        )

    result["pending_image"] = images.save_pending(img)
    return result


@router.post("/meals", status_code=201)
def create_meal(meal: MealIn):
    """Commit a reviewed meal, claiming its pending photo if one was supplied."""
    when = config.now()
    day = (meal.day or when.date()).isoformat()

    image_path = None
    if meal.pending_image:
        image_path = images.commit_pending(meal.pending_image, when)

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO meals (day, logged_at, name, meal_type, source,
                                  image_path, model, notes, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (day, when.isoformat(), meal.name, meal.meal_type, meal.source,
             image_path, meal.model, meal.notes, meal.raw_json),
        )
        meal_id = cur.lastrowid
        _insert_items(conn, meal_id, meal.items)
        return _fetch_meal(conn, meal_id)


@router.get("/meals")
def list_meals(day: date | None = None, limit: int = 100):
    """Meals for a given day (defaults to today), newest first."""
    target = (day or config.now().date()).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM meals WHERE day = ? ORDER BY logged_at DESC LIMIT ?",
            (target, max(1, min(limit, 500))),
        ).fetchall()
        return {"day": target, "meals": [_fetch_meal(conn, r["id"]) for r in rows]}


@router.get("/meals/{meal_id}")
def get_meal(meal_id: int):
    with get_conn() as conn:
        meal = _fetch_meal(conn, meal_id)
        if meal is None:
            raise HTTPException(status_code=404, detail="Meal not found.")
        return meal


@router.patch("/meals/{meal_id}")
def update_meal(meal_id: int, patch: MealUpdate):
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM meals WHERE id = ?", (meal_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Meal not found.")

        fields = patch.model_dump(exclude_unset=True, exclude={"items"})
        if "day" in fields and fields["day"] is not None:
            fields["day"] = fields["day"].isoformat()
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE meals SET {assignments} WHERE id = ?",
                (*fields.values(), meal_id),
            )

        if patch.items is not None:
            if not patch.items:
                raise HTTPException(status_code=400, detail="A meal needs at least one item.")
            conn.execute("DELETE FROM meal_items WHERE meal_id = ?", (meal_id,))
            _insert_items(conn, meal_id, patch.items)

        return _fetch_meal(conn, meal_id)


@router.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int):
    """Remove a meal. The photo on disk is kept -- deleting a mislogged entry
    should not silently destroy the only copy of the picture."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Meal not found.")


def _insert_items(conn, meal_id: int, items) -> None:
    conn.executemany(
        """INSERT INTO meal_items
               (meal_id, name, grams, calories, protein_g, carbs_g, fat_g, confidence, position)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (meal_id, it.name, it.grams, it.calories, it.protein_g,
             it.carbs_g, it.fat_g, it.confidence, pos)
            for pos, it in enumerate(items)
        ],
    )


def _fetch_meal(conn, meal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if row is None:
        return None
    items = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM meal_items WHERE meal_id = ? ORDER BY position", (meal_id,)
        )
    ]
    meal = dict(row)
    meal["items"] = items
    meal["totals"] = vision.totals_for(items)
    meal["image_url"] = f"/media/{row['image_path']}" if row["image_path"] else None
    return meal
