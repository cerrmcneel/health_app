"""Meal photo -> macros, via a local Ollama vision model with structured output."""
import json
from typing import Any

import httpx

from app import config

# Ollama's `format` field accepts a JSON Schema and constrains decoding to it.
# This is what makes the output parseable without regex-scraping a code fence.
NUTRITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dish": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "grams": {"type": "number"},
                    "calories": {"type": "number"},
                    "protein_g": {"type": "number"},
                    "carbs_g": {"type": "number"},
                    "fat_g": {"type": "number"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "basis": {"type": "string"},
                },
                "required": [
                    "name", "grams", "calories",
                    "protein_g", "carbs_g", "fat_g", "confidence",
                ],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["dish", "items"],
}

SYSTEM_PROMPT = """You are a nutrition estimation engine. You receive one photograph of a meal and return structured macronutrient data. You output JSON only.

Follow this procedure for every photo:

1. IDENTIFY each distinct edible component separately. A burger with fries is two items, not one. Count visible sauces, dressings, oil sheen and butter as their own items -- they are the single most common source of underestimation. Ignore non-food objects (cutlery, napkins, packaging, garnish that is not eaten).

2. SCALE the scene before estimating any weight. Find a reference object of known size and state it in `basis`. In descending order of reliability: a standard dinner plate is 26-28 cm across, a side plate 19-21 cm, a fork 18-20 cm long, a soda can 6.6 cm wide, a chicken egg 5.7 cm long, an adult thumb 6 cm. If nothing usable is in frame, assume a 27 cm plate and say so in `basis`.

3. ESTIMATE VOLUME from that scale, then convert to mass. Judge depth, not just the outline: food photographed from above hides its own height, and a mound is roughly half the mass of the cylinder that would enclose it. Apply approximate densities -- cooked rice/pasta 1.0 g/ml, leafy salad 0.2, dense meat 1.05, bread 0.3, soup 1.0, cheese 1.1, nuts 0.6, fried potato 0.55.

4. DERIVE macros from mass using per-100g values for the food as prepared, not raw. Cooking method changes this substantially: deep-frying adds roughly 8-12 g of fat per 100 g of food, pan-frying 3-6 g. Reflect that in the fat figure.

5. CHECK your arithmetic before answering. For each item, protein_g*4 + carbs_g*4 + fat_g*9 must land within 10% of its `calories`. If it does not, correct the numbers -- do not report the inconsistency.

Rules:
- `grams` is edible mass for that item only, excluding bone, shell, rind and pit.
- Set `confidence` to "low" when the food is obscured, when the dish is mixed or homemade so its recipe is unknowable, or when you had no size reference.
- `basis` is one short clause naming the reference object and the portion judgement, e.g. "27cm plate; rice covers a third of it, ~2cm deep".
- `notes` is for what would most change the estimate if you knew it, e.g. "cannot tell if the dressing is oil-based or yoghurt-based; +/- 90 kcal".
- Prefer a realistic central estimate over a cautious low one. Restaurant and takeaway portions run larger than home-cooked equivalents.
- Never refuse, never ask a question, never return an empty item list. If the photo is unclear, give your best estimate with confidence "low"."""

USER_PROMPT = (
    "Estimate the macronutrients in this meal. Break it into separate items, "
    "state your size reference in `basis` for each, and return JSON matching the schema."
)


class VisionError(RuntimeError):
    """Ollama was unreachable, timed out, or returned something unusable."""


async def analyze_meal(image_b64: str, model: str | None = None) -> dict[str, Any]:
    """Send a base64 JPEG to Ollama and return the parsed, validated estimate."""
    model = model or config.VISION_MODEL
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT, "images": [image_b64]},
        ],
        "stream": False,
        "format": NUTRITION_SCHEMA,
        # Thinking models (gemma4, deepseek-r1, qwen3...) otherwise spend the whole
        # token budget in `message.thinking` and return an empty `content`. The
        # schema already forces the structure, so the reasoning pass buys nothing.
        "think": False,
        "options": {
            # Low but non-zero: greedy decoding makes this model class repeat a
            # single memorised portion size across visibly different photos.
            "temperature": 0.2,
            "num_predict": 1500,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            if resp.status_code == 400 and "think" in resp.text.lower():
                # Model has no thinking mode and rejects the field outright.
                payload.pop("think")
                resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
    except httpx.TimeoutException as exc:
        raise VisionError(
            f"{model} did not respond within {config.OLLAMA_TIMEOUT:.0f}s. "
            "A cold model load can exceed this; raise OLLAMA_TIMEOUT or pre-warm it."
        ) from exc
    except httpx.RequestError as exc:
        raise VisionError(f"Cannot reach Ollama at {config.OLLAMA_URL}: {exc}") from exc

    if resp.status_code != 200:
        if resp.status_code == 404:
            raise VisionError(f"Model '{model}' is not pulled. Run: ollama pull {model}")
        raise VisionError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    message = body.get("message") or {}
    content = (message.get("content") or "").strip()
    truncated = body.get("done_reason") == "length"

    if not content:
        if message.get("thinking"):
            raise VisionError(
                f"'{model}' spent its whole token budget reasoning and returned no answer. "
                "Ollama ignored think=false; upgrade Ollama or pick a non-thinking model."
            )
        raise VisionError(
            f"'{model}' returned an empty response. Confirm it is vision-capable "
            "(GET /api/health lists which installed models can see images)."
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        if truncated:
            raise VisionError(
                f"'{model}' hit the token limit mid-JSON, so the estimate was cut off. "
                "This usually means the photo has a very large number of items."
            ) from exc
        raise VisionError(f"Model output was not valid JSON: {content[:200]}") from exc

    return normalize(data, model=model, raw=content)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return max(0.0, round(out, 1))


def normalize(data: dict[str, Any], model: str, raw: str = "") -> dict[str, Any]:
    """Coerce model output into the exact shape the frontend and DB expect.

    A schema-constrained model still emits nonsense values (negatives, strings,
    macros that contradict the calorie count), so every field is re-checked here.
    """
    items: list[dict[str, Any]] = []
    for idx, item in enumerate(data.get("items") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip() or f"Item {idx + 1}"
        protein = _num(item.get("protein_g"))
        carbs = _num(item.get("carbs_g"))
        fat = _num(item.get("fat_g"))
        calories = _num(item.get("calories"))

        # Rule 5 is advisory to the model; enforce it here. If the stated calories
        # disagree with the macros by >15%, trust the macros -- they are estimated
        # per-component, whereas the calorie figure tends to be recalled wholesale.
        derived = protein * 4 + carbs * 4 + fat * 9
        if derived > 0 and (calories <= 0 or abs(calories - derived) / derived > 0.15):
            calories = round(derived, 1)
        elif derived <= 0 and calories <= 0:
            continue  # no nutrition at all: a hallucinated garnish, drop it

        conf = str(item.get("confidence") or "medium").lower()
        items.append({
            "name": name[:120],
            "grams": _num(item.get("grams")),
            "calories": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
            "confidence": conf if conf in ("low", "medium", "high") else "medium",
            "basis": str(item.get("basis") or "")[:300],
        })

    return {
        "dish": str(data.get("dish") or "").strip()[:160] or "Meal",
        "items": items,
        "notes": str(data.get("notes") or "").strip()[:500],
        "model": model,
        "totals": totals_for(items),
        "raw": raw,
    }


def totals_for(items: list[dict[str, Any]]) -> dict[str, float]:
    keys = ("calories", "protein_g", "carbs_g", "fat_g", "grams")
    return {k: round(sum(_num(i.get(k)) for i in items), 1) for k in keys}


async def list_models() -> list[dict[str, Any]]:
    """Installed models, with a flag for whether each can actually see images."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{config.OLLAMA_URL}/api/tags")
        resp.raise_for_status()
        models = resp.json().get("models", [])
    return [
        {
            "name": m.get("name", ""),
            "size": m.get("size", 0),
            "vision": "vision" in (m.get("capabilities") or []),
        }
        for m in models
    ]
