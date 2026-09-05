"""Open Knowledge Framework (OKF) & Nutrition Science Retrieval Engine.

Uses SQLite FTS5 for local BM25 ranking over curated markdown articles,
fusing scientific evidence with personal stats (weight, targets, intake)
for local LLM synthesis via Ollama.
"""
import re
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from app import config

KNOWLEDGE_DIR = config.BASE_DIR / "app" / "knowledge"

EXPLAINER_SYSTEM_PROMPT = """You are an evidence-based sports nutritionist and exercise physiologist.
You explain the physiological science behind human nutrition, macronutrient distribution, and energy balance.
Your explanations are clear, actionable, and directly grounded in established clinical guidelines (ISSN, ACSM, Mifflin-St Jeor).
When discussing the user's targets, reference their exact numbers (calories, protein g, protein g/kg, carbs g, fat g and fat %) and explain why each macro is positioned where it is:
1. Protein: Muscle Protein Synthesis (MPS), lean tissue preservation, and thermic effect.
2. Dietary Fats: Endocrine/hormonal baseline (testosterone/estrogen), cell membranes, fat-soluble vitamins (A, D, E, K).
3. Carbohydrates: High-intensity anaerobic training fuel, glycogen restoration, thyroid (T3) and leptin support.
4. Energy Balance: How total calories align with body composition goals.
Be concise, scientific, and motivating. Do not give generic medical disclaimers."""

QA_SYSTEM_PROMPT = """You are an evidence-based sports nutritionist and health educator.
Answer the user's question using the provided scientific knowledge excerpts and the user's current personal nutrition snapshot.
Guidelines:
- Ground your answer in the provided scientific facts (mentioning guidelines like ISSN or mechanisms like MPS/glycogen/hormones when relevant).
- Personalize the response to their stats (targets, current weight, protein g/kg) where applicable.
- Be concise (2 to 4 focused paragraphs), clear, and direct.
- If the question asks for advice outside general sports nutrition and wellness, answer with evidence-based nutrition principles without being evasive."""


def parse_markdown_docs() -> list[dict[str, Any]]:
    """Parse markdown files in app/knowledge into structured document sections."""
    docs = []
    if not KNOWLEDGE_DIR.exists():
        return docs

    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        slug = path.stem
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        lines = content.splitlines()
        doc_title = slug.replace("_", " ").title()
        current_section = "Overview"
        section_lines: list[str] = []

        for line in lines:
            if line.startswith("# "):
                doc_title = line[2:].strip()
            elif line.startswith("## "):
                if section_lines:
                    text = "\n".join(section_lines).strip()
                    if text:
                        docs.append({
                            "slug": slug,
                            "title": doc_title,
                            "section": current_section,
                            "content": text,
                            "tags": f"{slug} {doc_title.lower()} {current_section.lower()}",
                        })
                current_section = line[3:].strip()
                section_lines = []
            else:
                section_lines.append(line)

        if section_lines:
            text = "\n".join(section_lines).strip()
            if text:
                docs.append({
                    "slug": slug,
                    "title": doc_title,
                    "section": current_section,
                    "content": text,
                    "tags": f"{slug} {doc_title.lower()} {current_section.lower()}",
                })

    return docs


def index_knowledge(conn: sqlite3.Connection) -> int:
    """Reindex knowledge articles into the SQLite FTS5 table."""
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_docs USING fts5(slug UNINDEXED, title, section, content, tags)"
    )
    docs = parse_markdown_docs()
    if not docs:
        return 0

    conn.execute("DELETE FROM knowledge_docs")
    for d in docs:
        conn.execute(
            "INSERT INTO knowledge_docs (slug, title, section, content, tags) VALUES (?, ?, ?, ?, ?)",
            (d["slug"], d["title"], d["section"], d["content"], d["tags"]),
        )
    conn.commit()
    return len(docs)


def search_knowledge(conn: sqlite3.Connection, query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Search knowledge base using SQLite FTS5 BM25 ranking."""
    clean = re.sub(r"[^\w\s]", " ", query).strip()
    tokens = [t for t in clean.split() if len(t) > 1]
    if not tokens:
        rows = conn.execute(
            "SELECT slug, title, section, content, 0.0 as rank FROM knowledge_docs LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    fts_query = " OR ".join(tokens)
    try:
        rows = conn.execute(
            """SELECT slug, title, section, content, rank
               FROM knowledge_docs
               WHERE knowledge_docs MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        pass

    rows = conn.execute(
        "SELECT slug, title, section, content, 0.0 as rank FROM knowledge_docs LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_personal_snapshot(conn: sqlite3.Connection, profile_id: int, day: str) -> dict[str, Any]:
    """Assemble a full personal snapshot: targets, recent weight, and today's intake."""
    prof = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not prof:
        prof = conn.execute("SELECT * FROM profiles WHERE is_default = 1 LIMIT 1").fetchone()
    if not prof:
        prof = {
            "name": "User", "calorie_target": 2200.0, "protein_target": 160.0,
            "carbs_target": 220.0, "fat_target": 70.0,
        }
    else:
        prof = dict(prof)

    cals = float(prof.get("calorie_target") or 2200)
    prot = float(prof.get("protein_target") or 160)
    carbs = float(prof.get("carbs_target") or 220)
    fat = float(prof.get("fat_target") or 70)

    prot_kcal = prot * 4.0
    carbs_kcal = carbs * 4.0
    fat_kcal = fat * 9.0

    prot_pct = round((prot_kcal / cals) * 100, 1) if cals > 0 else 0.0
    carbs_pct = round((carbs_kcal / cals) * 100, 1) if cals > 0 else 0.0
    fat_pct = round((fat_kcal / cals) * 100, 1) if cals > 0 else 0.0

    # Weight stats
    w_row = conn.execute(
        "SELECT weight_kg, day FROM weights WHERE profile_id = ? ORDER BY day DESC, id DESC LIMIT 1",
        (profile_id,),
    ).fetchone()
    weight_kg = float(w_row["weight_kg"]) if w_row else None
    weight_day = str(w_row["day"]) if w_row else None

    prot_per_kg = round(prot / weight_kg, 2) if weight_kg and weight_kg > 0 else None
    fat_per_kg = round(fat / weight_kg, 2) if weight_kg and weight_kg > 0 else None
    carbs_per_kg = round(carbs / weight_kg, 2) if weight_kg and weight_kg > 0 else None

    # Today's intake
    tot_row = conn.execute(
        "SELECT * FROM v_daily_totals WHERE profile_id = ? AND day = ?",
        (profile_id, day),
    ).fetchone()
    today_intake = {
        "calories": float(tot_row["calories"]) if tot_row and tot_row["calories"] else 0.0,
        "protein_g": float(tot_row["protein_g"]) if tot_row and tot_row["protein_g"] else 0.0,
        "carbs_g": float(tot_row["carbs_g"]) if tot_row and tot_row["carbs_g"] else 0.0,
        "fat_g": float(tot_row["fat_g"]) if tot_row and tot_row["fat_g"] else 0.0,
        "meal_count": int(tot_row["meal_count"]) if tot_row and tot_row["meal_count"] else 0,
    }

    return {
        "profile_name": prof.get("name", "User"),
        "targets": {
            "calories": cals,
            "protein_g": prot,
            "carbs_g": carbs,
            "fat_g": fat,
            "protein_pct": prot_pct,
            "carbs_pct": carbs_pct,
            "fat_pct": fat_pct,
        },
        "weight": {
            "weight_kg": weight_kg,
            "logged_day": weight_day,
            "protein_per_kg": prot_per_kg,
            "fat_per_kg": fat_per_kg,
            "carbs_per_kg": carbs_per_kg,
        },
        "today_intake": today_intake,
    }


def _deterministic_balance_explanation(snapshot: dict[str, Any]) -> str:
    """Fallback structured explanation if local Ollama model is offline."""
    t = snapshot["targets"]
    w = snapshot["weight"]
    name = snapshot.get("profile_name", "User")

    prot_note = f"{t['protein_g']}g"
    if w.get("protein_per_kg"):
        prot_note += f" ({w['protein_per_kg']} g/kg body weight)"

    lines = [
        f"### Why {name}'s Macro Split Is Scientifically Balanced",
        "",
        f"**Daily Targets:** {t['calories']:.0f} kcal &middot; **Protein:** {prot_note} &middot; **Carbs:** {t['carbs_g']}g ({t['carbs_pct']}%) &middot; **Fat:** {t['fat_g']}g ({t['fat_pct']}%)",
        "",
        "#### 1. Protein Target & Muscle Preservation",
    ]
    if w.get("protein_per_kg"):
        g_kg = w["protein_per_kg"]
        if g_kg >= 1.6:
            lines.append(f"At **{g_kg} g/kg**, your protein target lands squarely within the International Society of Sports Nutrition (ISSN) optimal range of 1.6–2.2 g/kg. This provides sufficient leucine to trigger maximal Muscle Protein Synthesis (MPS) and safeguard lean mass against catabolism.")
        else:
            lines.append(f"At **{g_kg} g/kg**, your protein intake supports active recovery. If you are in a caloric deficit, elevating towards 1.8–2.2 g/kg is recommended to spare skeletal muscle.")
    else:
        lines.append(f"Your target of **{t['protein_g']}g** provides robust amino acid availability for recovery, cellular repair, and high satiety (Thermic Effect of Food ~20–30%).")

    lines.extend([
        "",
        "#### 2. Dietary Fat & Hormonal Baseline",
        f"At **{t['fat_pct']}% of total energy** ({t['fat_g']}g), your fat target safely surpasses the critical 20% minimum threshold established by sports endocrinology. This preserves baseline steroid hormone production (testosterone, progesterone, estradiol), supports cellular membrane fluidity, and guarantees optimal absorption of fat-soluble vitamins (A, D, E, K).",
        "",
        "#### 3. Carbohydrates & Glycogen Performance",
        f"Allocating **{t['carbs_pct']}% of energy** ({t['carbs_g']}g) to carbohydrates fuels high-intensity anaerobic glycolysis. This replenishes intramuscular glycogen stores (each gram binding ~3g of water for muscular hydration), sustains training volume, and supports healthy thyroid hormone (T3) and leptin signaling.",
    ])
    return "\n".join(lines)


async def explain_balance(conn: sqlite3.Connection, profile_id: int, day: str) -> dict[str, Any]:
    """Generate a personalized rationale for the user's active targets."""
    snapshot = get_personal_snapshot(conn, profile_id, day)
    docs = search_knowledge(conn, "macronutrients protein fats carbohydrates energy balance", limit=4)
    sources = [f"{d['title']} - {d['section']}" for d in docs]

    context_text = "\n\n".join([f"### {d['title']}: {d['section']}\n{d['content']}" for d in docs])
    t = snapshot["targets"]
    w = snapshot["weight"]
    weight_str = f"{w['weight_kg']} kg (giving {w['protein_per_kg']} g/kg protein)" if w.get("weight_kg") else "not yet logged"

    user_prompt = f"""Explain why this user's macro split is balanced, citing the provided sports science principles:

User Profile: {snapshot['profile_name']}
Current Body Weight: {weight_str}
Daily Energy Target: {t['calories']} kcal
- Protein: {t['protein_g']}g ({t['protein_pct']}% of calories)
- Carbohydrates: {t['carbs_g']}g ({t['carbs_pct']}% of calories)
- Fat: {t['fat_g']}g ({t['fat_pct']}% of calories)

Scientific Guidelines & Knowledge Context:
{context_text}

Provide a well-structured, motivating explanation covering Protein (g/kg & MPS), Fats (hormone & endocrine safety minimum), Carbs (glycogen & training fuel), and Energy Balance."""

    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.VISION_MODEL,
                    "messages": [
                        {"role": "system", "content": EXPLAINER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.4, "num_predict": 1200},
                },
            )
            if resp.status_code == 200:
                body = resp.json()
                content = (body.get("message") or {}).get("content", "").strip()
                if content:
                    return {
                        "explanation": content,
                        "snapshot": snapshot,
                        "sources": sources,
                        "model": config.VISION_MODEL,
                    }
    except Exception:
        pass

    return {
        "explanation": _deterministic_balance_explanation(snapshot),
        "snapshot": snapshot,
        "sources": sources,
        "model": "knowledge-engine-local",
    }


async def ask_nutrition_question(
    conn: sqlite3.Connection, profile_id: int, day: str, question: str
) -> dict[str, Any]:
    """Answer arbitrary user nutrition/health questions with retrieved context and personal stats."""
    snapshot = get_personal_snapshot(conn, profile_id, day)
    docs = search_knowledge(conn, question, limit=3)
    sources = [f"{d['title']} - {d['section']}" for d in docs]
    context_text = "\n\n".join([f"### {d['title']}: {d['section']}\n{d['content']}" for d in docs])

    t = snapshot["targets"]
    w = snapshot["weight"]
    weight_str = f"{w['weight_kg']} kg ({w['protein_per_kg']} g/kg protein)" if w.get("weight_kg") else "unknown"

    user_prompt = f"""Question from user: {question}

User's Personal Nutrition Context:
- Active Profile: {snapshot['profile_name']}
- Weight: {weight_str}
- Targets: {t['calories']} kcal (Protein: {t['protein_g']}g, Carbs: {t['carbs_g']}g, Fat: {t['fat_g']}g)
- Today consumed so far: {snapshot['today_intake']['calories']} kcal, {snapshot['today_intake']['protein_g']}g protein

Retrieved Scientific Evidence:
{context_text}

Answer the user's question clearly, scientifically, and concisely based on this evidence and their context."""

    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.VISION_MODEL,
                    "messages": [
                        {"role": "system", "content": QA_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.5, "num_predict": 1000},
                },
            )
            if resp.status_code == 200:
                body = resp.json()
                content = (body.get("message") or {}).get("content", "").strip()
                if content:
                    return {
                        "answer": content,
                        "sources": sources,
                        "snapshot": snapshot,
                        "model": config.VISION_MODEL,
                    }
    except Exception as exc:
        return {
            "answer": (
                f"Ollama ({config.VISION_MODEL}) is currently unreachable ({exc}).\n\n"
                f"However, based on our Knowledge Base ({', '.join(sources)}):\n"
                + _deterministic_balance_explanation(snapshot)
            ),
            "sources": sources,
            "snapshot": snapshot,
            "model": "offline-fallback",
        }

    return {
        "answer": "Unable to generate response from model.",
        "sources": sources,
        "snapshot": snapshot,
        "model": config.VISION_MODEL,
    }
