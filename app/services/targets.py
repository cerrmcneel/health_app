"""Evidence-based macro target calculation via Mifflin-St Jeor & ISSN guidelines.

Provides pure functions for BMR, TDEE, and macro distribution based on the
clinical consensus (Mifflin-St Jeor BMR, ISSN protein recommendations, and
endocrine minimum fat thresholds).
"""
from typing import Any

ACTIVITY_MULTIPLIERS: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# Caloric density of 1 kg human adipose tissue
KCAL_PER_KG_FAT = 7700.0


def compute_bmr(sex: str | None, weight_kg: float, height_cm: float, age: int) -> float:
    """Calculate Basal Metabolic Rate (BMR) via the Mifflin-St Jeor equation.

    Men:   10 * weight(kg) + 6.25 * height(cm) - 5 * age + 5
    Women: 10 * weight(kg) + 6.25 * height(cm) - 5 * age - 161
    """
    base = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * age)
    normalized_sex = (sex or "").strip().lower()
    if normalized_sex in ("male", "man", "m"):
        return base + 5.0
    elif normalized_sex in ("female", "woman", "f"):
        return base - 161.0
    else:
        # Non-binary or unspecified: neutral midpoint (-78)
        return base - 78.0


def compute_tdee(bmr: float, activity_level: str | None) -> float:
    """Compute Total Daily Energy Expenditure (TDEE) from BMR and activity multiplier."""
    level = (activity_level or "moderate").strip().lower().replace(" ", "_")
    multiplier = ACTIVITY_MULTIPLIERS.get(level, 1.55)
    return bmr * multiplier


def compute_targets(
    sex: str | None,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity_level: str | None = "moderate",
    goal: str | None = "maintain",
    goal_rate_kg_per_week: float = 0.5,
) -> dict[str, Any]:
    """Derive calorie and macronutrient targets grounded in sports nutrition science.

    - Protein: 1.6-2.2 g/kg body weight (ISSN optimal range; higher during deficit).
    - Fat: Minimum 20% of energy floor to protect endocrine and hormonal health.
    - Carbohydrates: Remainder of energy to replenish glycogen and fuel training.
    """
    bmr = compute_bmr(sex, weight_kg, height_cm, age)
    tdee = compute_tdee(bmr, activity_level)

    norm_goal = (goal or "maintain").strip().lower()
    rate = max(0.0, min(float(goal_rate_kg_per_week or 0.0), 1.5))
    daily_delta = (rate * KCAL_PER_KG_FAT) / 7.0

    if "lose" in norm_goal or "cut" in norm_goal:
        target_calories = round(tdee - daily_delta)
        protein_g_per_kg = 2.0  # Elevate toward 2.0 g/kg during caloric deficit to preserve lean mass
    elif "gain" in norm_goal or "bulk" in norm_goal:
        target_calories = round(tdee + daily_delta)
        protein_g_per_kg = 1.8
    else:
        target_calories = round(tdee)
        protein_g_per_kg = 1.8

    # Safe physiological floors
    floor = 1200 if (sex or "").lower() in ("female", "woman", "f") else 1400
    target_calories = max(floor, target_calories)

    # 1. Protein Target
    protein_g = round(weight_kg * protein_g_per_kg)
    protein_kcal = protein_g * 4.0

    # 2. Dietary Fat Target (safety floor of 20%, baseline 25% of energy)
    fat_kcal = max(target_calories * 0.20, target_calories * 0.25)
    fat_g = round(fat_kcal / 9.0)
    fat_kcal = fat_g * 9.0

    # 3. Carbohydrates Target (remainder of calories)
    rem_kcal = max(0.0, target_calories - (protein_kcal + fat_kcal))
    carbs_g = round(rem_kcal / 4.0)

    # Effective macros sum
    actual_kcal = round((protein_g * 4.0) + (carbs_g * 4.0) + (fat_g * 9.0))

    result = {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "calorie_target": target_calories,
        "protein_target": protein_g,
        "carbs_target": carbs_g,
        "fat_target": fat_g,
        "protein_per_kg": protein_g_per_kg,
        "protein_pct": round((protein_g * 4.0 / target_calories) * 100, 1),
        "carbs_pct": round((carbs_g * 4.0 / target_calories) * 100, 1),
        "fat_pct": round((fat_g * 9.0 / target_calories) * 100, 1),
    }
    result["explanation"] = explain_targets(result, weight_kg, norm_goal)
    return result


def explain_targets(targets: dict[str, Any], weight_kg: float, goal: str | None = "maintain") -> str:
    """Generate evidence-based clinical reasoning for the macro recommendation."""
    norm_goal = (goal or "maintain").lower()
    if "lose" in norm_goal or "cut" in norm_goal:
        goal_label = "caloric deficit for steady fat loss"
    elif "gain" in norm_goal or "bulk" in norm_goal:
        goal_label = "caloric surplus for lean hypertrophy"
    else:
        goal_label = "energy balance for weight maintenance"

    return (
        f"**Energy**: {targets['calorie_target']} kcal ({goal_label}, TDEE: {targets['tdee']} kcal, BMR: {targets['bmr']} kcal).\n"
        f"• **Protein ({targets['protein_target']}g / {targets['protein_pct']}%)**: {targets['protein_per_kg']} g/kg body weight. "
        f"Aligned with the International Society of Sports Nutrition (ISSN) 1.6–2.2 g/kg standard to optimize muscle protein synthesis.\n"
        f"• **Dietary Fat ({targets['fat_target']}g / {targets['fat_pct']}%)**: Set at {targets['fat_pct']}% of energy, above the 20% endocrine minimum to support hormone regulation.\n"
        f"• **Carbohydrates ({targets['carbs_target']}g / {targets['carbs_pct']}%)**: Remainder of calories to replenish glycogen stores and power training."
    )

