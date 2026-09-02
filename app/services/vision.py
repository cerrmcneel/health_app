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

TEXT_SYSTEM_PROMPT = """You are a nutrition estimation engine. You receive a natural language description of a meal or food intake and return structured macronutrient data. You output JSON only.

Follow this procedure for every meal description:

1. IDENTIFY each distinct edible component mentioned or implied (e.g. "cheeseburger with bacon and fries" -> burger bun, beef patty, cheddar cheese, bacon strips, french fries). Include condiments, butter, cooking oil, sauces, and milk/sugar in beverages.

2. ESTIMATE PORTIONS & MASS (grams):
- If quantities, counts, or measurements are given (e.g. "2 eggs", "1 cup rice", "150g salmon", "1 can coke", "large iced latte"), convert them accurately to mass in grams.
- If portions are NOT specified (e.g. "bowl of chili", "slice of pizza", "chicken breast with broccoli", "protein shake"), GUESS realistic, standard typical portion sizes (e.g. 1 standard slice pizza ~105g, 1 cooked chicken breast ~170g, 1 standard bowl chili ~300g, 1 scoop whey ~30g in 250ml milk/water) and clearly state your assumed standard serving in `basis`.

3. DERIVE MACROS from mass using nutritional values for the food as prepared.

4. CHECK ARITHMETIC: For each item, protein_g*4 + carbs_g*4 + fat_g*9 must land within 10% of its `calories`. If not, correct the numbers.

Rules:
- `dish` is a short, descriptive title for the overall meal (e.g. "Scrambled Eggs with Sourdough Toast & Latte").
- `grams` is the estimated edible mass for that component in grams.
- `basis` names the portion calculation or standard serving assumption, e.g. "assumed standard 1 cup cooked (~195g)" or "stated 2 large eggs (~100g)".
- `notes` is for assumptions or suggested adjustments, e.g. "Assumed standard medium portion with whole milk".
- Set `confidence` to "high" when quantities were specified, "medium" for standard recognizable dishes, or "low" for ambiguous items.
- Never refuse, never ask questions, never output empty items. Always return valid JSON matching the schema."""

MULTIMODAL_SYSTEM_PROMPT = """You are a precision nutrition estimation engine. You receive a photograph of a meal together with user notes and natural language context. You output JSON only.

Follow this procedure:

1. FUSE VISUAL EVIDENCE AND USER CONTEXT:
- Visual Evidence (Photo): Use the photo to scale plate size, observe three-dimensional portion depth and volume, verify item counts, and detect unmentioned visible foods (e.g. side salad, sauces, garnishes).
- User Context (Notes): Use the user's notes for ingredients invisible or ambiguous in the photo: specific cooking oils/butter, dressings, sauces, meat lean/fat percentages, dairy types (whole vs skim vs oat milk), sweeteners, or specified brand names and exact weights/counts.
- When the user specifies an exact count or measurement (e.g. "2 eggs", "6 oz steak", "1 pint beer"), prioritize their stated quantity while using the photo to verify the dish.

2. SEPARATE DISTINCT COMPONENTS: Identify each component separately (e.g. burger bun, patty, cheese, bacon, fries, mayo).

3. ESTIMATE MASS (grams) & MACROS: Provide edible portion weight in grams and accurate prepared macronutrients (protein, carbs, fat, calories).

4. CHECK ARITHMETIC: For each item, protein_g*4 + carbs_g*4 + fat_g*9 must land within 10% of its calories.

Rules:
- `dish` is a descriptive title for the overall meal (e.g. "Ribeye Steak with Roasted Potatoes and Asparagus").
- `grams` is edible mass in grams.
- `basis` combines the visual scale and the user's notes, e.g. "photo shows ~250g steak; user noted cooked in 1 tbsp olive oil".
- Set `confidence` to "high" when user notes clarify quantities/ingredients, otherwise "medium" or "low".
- Never refuse, never ask questions, never return empty items. Return valid JSON matching the schema."""

USER_PROMPT = (
    "Estimate the macronutrients in this meal. Break it into separate items, "
    "state your size reference in `basis` for each, and return JSON matching the schema."
)


class VisionError(RuntimeError):
    """Ollama was unreachable, timed out, or returned something unusable."""


async def _call_ollama(messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": NUTRITION_SCHEMA,
        "think": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 1500,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            if resp.status_code == 400 and "think" in resp.text.lower():
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
        raise VisionError(f"'{model}' returned an empty response.")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        if truncated:
            raise VisionError(
                f"'{model}' hit the token limit mid-JSON, so the estimate was cut off."
            ) from exc
        raise VisionError(f"Model output was not valid JSON: {content[:200]}") from exc

    return normalize(data, model=model, raw=content)


async def analyze_meal(image_b64: str, model: str | None = None) -> dict[str, Any]:
    """Send a base64 JPEG to Ollama and return the parsed, validated estimate."""
    model = model or config.VISION_MODEL
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT, "images": [image_b64]},
    ]
    return await _call_ollama(messages, model)


async def analyze_meal_text(description: str, model: str | None = None) -> dict[str, Any]:
    """Send a natural language meal description to Ollama and return structured macros."""
    model = model or config.VISION_MODEL
    user_content = f"Estimate the macronutrients for this meal description:\n\"{description.strip()}\"\nBreak it into items and guess standard serving sizes if not specified."
    messages = [
        {"role": "system", "content": TEXT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    return await _call_ollama(messages, model)


async def analyze_meal_multimodal(image_b64: str, text: str, model: str | None = None) -> dict[str, Any]:
    """Combine photo analysis with user notes/context for the most accurate estimate."""
    model = model or config.VISION_MODEL
    user_content = (
        f"Estimate the macronutrients in this meal photograph.\n\n"
        f"User notes & context:\n\"{text.strip()}\"\n\n"
        f"Combine the visual proof from the image with the user's notes to accurately identify components, portion sizes, and macros."
    )
    messages = [
        {"role": "system", "content": MULTIMODAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_content, "images": [image_b64]},
    ]
    return await _call_ollama(messages, model)


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
