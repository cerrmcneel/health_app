"""Tests for target calculations (Mifflin-St Jeor, ISSN macros) and profile onboarding."""
import pytest
from fastapi.testclient import TestClient

from app.services.targets import compute_bmr, compute_tdee, compute_targets


def test_mifflin_st_jeor_bmr_male_worked_example():
    """Male, 80 kg, 180 cm, 30 years old:
    BMR = 10 * 80 + 6.25 * 180 - 5 * 30 + 5 = 800 + 1125 - 150 + 5 = 1780 kcal
    """
    bmr = compute_bmr(sex="male", weight_kg=80.0, height_cm=180.0, age=30)
    assert bmr == 1780.0


def test_mifflin_st_jeor_bmr_female_worked_example():
    """Female, 65 kg, 165 cm, 28 years old:
    BMR = 10 * 65 + 6.25 * 165 - 5 * 28 - 161 = 650 + 1031.25 - 140 - 161 = 1380.25 kcal
    """
    bmr = compute_bmr(sex="female", weight_kg=65.0, height_cm=165.0, age=28)
    assert bmr == 1380.25


def test_tdee_activity_multipliers():
    bmr = 1500.0
    assert compute_tdee(bmr, "sedentary") == pytest.approx(1500.0 * 1.2)
    assert compute_tdee(bmr, "light") == pytest.approx(1500.0 * 1.375)
    assert compute_tdee(bmr, "moderate") == pytest.approx(1500.0 * 1.55)
    assert compute_tdee(bmr, "active") == pytest.approx(1500.0 * 1.725)
    assert compute_tdee(bmr, "very_active") == pytest.approx(1500.0 * 1.9)


def test_protein_in_issn_optimal_range():
    """Protein must stay within the 1.6 - 2.2 g/kg ISSN recommendation for active individuals."""
    targets_cut = compute_targets("male", weight_kg=75.0, height_cm=175.0, age=25, goal="lose", goal_rate_kg_per_week=0.5)
    assert 1.6 <= targets_cut["protein_per_kg"] <= 2.2

    targets_bulk = compute_targets("male", weight_kg=75.0, height_cm=175.0, age=25, goal="gain", goal_rate_kg_per_week=0.25)
    assert 1.6 <= targets_bulk["protein_per_kg"] <= 2.2

    targets_maint = compute_targets("male", weight_kg=75.0, height_cm=175.0, age=25, goal="maintain")
    assert 1.6 <= targets_maint["protein_per_kg"] <= 2.2


def test_fat_never_falls_below_20_percent_energy_floor():
    """Dietary fat must protect the 20% endocrine floor."""
    for goal in ["lose", "maintain", "gain"]:
        targets = compute_targets("female", weight_kg=60.0, height_cm=160.0, age=30, goal=goal, goal_rate_kg_per_week=0.75)
        fat_pct = (targets["fat_target"] * 9.0) / targets["calorie_target"]
        assert fat_pct >= 0.199, f"Fat percentage {fat_pct} under 20% for goal {goal}"


def test_macros_sum_to_within_two_percent_of_calorie_target():
    """Sum of macronutrient energies must match total calorie target within rounding error (<= 2%)."""
    for goal in ["lose", "maintain", "gain"]:
        targets = compute_targets("male", weight_kg=82.0, height_cm=183.0, age=32, goal=goal)
        macro_cals = (targets["protein_target"] * 4.0) + (targets["carbs_target"] * 4.0) + (targets["fat_target"] * 9.0)
        cal_target = targets["calorie_target"]
        delta_pct = abs(macro_cals - cal_target) / cal_target
        assert delta_pct <= 0.02, f"Macro sum {macro_cals} deviates from calorie target {cal_target} by {delta_pct:.2%}"


def test_safe_caloric_floor_enforced():
    """Calorie targets must never drop below 1200 kcal (female) or 1400 kcal (male)."""
    female_cut = compute_targets("female", weight_kg=45.0, height_cm=150.0, age=40, goal="lose", goal_rate_kg_per_week=1.5)
    assert female_cut["calorie_target"] >= 1200

    male_cut = compute_targets("male", weight_kg=55.0, height_cm=160.0, age=40, goal="lose", goal_rate_kg_per_week=1.5)
    assert male_cut["calorie_target"] >= 1400


def test_preview_targets_api(client: TestClient):
    res = client.post("/api/profiles/preview-targets", json={
        "sex": "male",
        "weight_kg": 80.0,
        "height_cm": 180.0,
        "age": 30,
        "activity_level": "moderate",
        "goal": "maintain",
        "goal_rate_kg_per_week": 0.5,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["bmr"] == 1780
    assert data["calorie_target"] > 0
    assert "explanation" in data


def test_profile_onboarding_saves_stats_and_updates_inventory(client: TestClient):
    # 1. Create a fresh profile
    res = client.post("/api/profiles", json={"name": "NewUser"})
    assert res.status_code == 201
    profile = res.json()
    pid = profile["id"]
    assert profile.get("onboarded_at") is None

    # 2. Complete onboarding interview
    payload = {
        "sex": "male",
        "birth_year": 1996,
        "height_cm": 178.0,
        "current_weight_kg": 76.5,
        "activity_level": "moderate",
        "goal": "lose",
        "goal_rate_kg_per_week": 0.5,
        "equipment_keys": ["yoga_mat", "jump_rope", "dumbbells"],
        "preferred_duration_min": 30,
        "preferred_level": "intermediate",
        "workout_days_per_week": 4,
    }
    onboard_res = client.post(f"/api/profiles/{pid}/onboarding", json=payload)
    assert onboard_res.status_code == 200
    updated = onboard_res.json()

    assert updated["onboarded_at"] is not None
    assert updated["sex"] == "male"
    assert updated["birth_year"] == 1996
    assert updated["height_cm"] == 178.0
    assert updated["goal"] == "lose"
    assert updated["preferred_duration_min"] == 30
    assert updated["workout_days_per_week"] == 4

    # Calculated calorie target should reflect a deficit
    assert updated["calorie_target"] < 2500

    # Initial weigh-in must be saved into weights
    w_res = client.get("/api/weights", headers={"X-Profile-ID": str(pid)})
    assert w_res.status_code == 200
    w_data = w_res.json()
    assert len(w_data["weights"]) >= 1
    assert w_data["latest_weight"] == 76.5

    # Equipment inventory must be saved
    eq_res = client.get("/api/workouts/equipment", headers={"X-Profile-ID": str(pid)})
    assert eq_res.status_code == 200
    owned = eq_res.json()["owned_keys"]
    assert set(owned) == {"yoga_mat", "jump_rope", "dumbbells"}


def test_profile_onboarding_404_for_unknown_profile(client: TestClient):
    res = client.post("/api/profiles/99999/onboarding", json={"sex": "male"})
    assert res.status_code == 404


def test_backup_export_returns_valid_zip(client: TestClient):
    import io
    import zipfile

    res = client.get("/api/backup/export")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert "attachment; filename=" in res.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    assert "tracker.db" in names
    assert "manifest.json" in names

