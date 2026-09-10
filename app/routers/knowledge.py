"""Router for the Open Knowledge Framework (OKF) & Nutrition Explainer."""
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app import config
from app.db import get_conn
from app.deps import get_profile_id
from app.services import knowledge

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    day: str | None = None


@router.get("/balance-explanation")
async def get_balance_explanation(
    request: Request,
    day: str | None = None,
):
    """Generate a personalized scientific rationale for the active profile's macro targets."""
    day_str = day or config.today_iso()
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        snapshot = knowledge.get_personal_snapshot(conn, profile_id, day_str)
        docs = knowledge.search_knowledge(conn, "macronutrients protein fats carbohydrates energy balance", limit=4)
    return await knowledge.explain_balance(snapshot, docs)


@router.post("/ask")
async def ask_nutrition_question(
    request: Request,
    body: QuestionIn,
):
    """Answer a user question about nutrition/health grounded in scientific knowledge and personal stats."""
    day_str = body.day or config.today_iso()
    with get_conn() as conn:
        profile_id = get_profile_id(request, conn)
        snapshot = knowledge.get_personal_snapshot(conn, profile_id, day_str)
        docs = knowledge.search_knowledge(conn, body.question, limit=3)
    return await knowledge.ask_nutrition_question(snapshot, docs, body.question)


@router.get("/sources")
def get_knowledge_sources():
    """List all available scientific articles and sections in the local knowledge base."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slug, title, section, tags FROM knowledge_docs ORDER BY slug, section"
        ).fetchall()
        return {"sources": [dict(r) for r in rows]}
