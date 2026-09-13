"""Automated test suite for weeklong workout planning and Upper/Lower split distribution."""
from datetime import date, timedelta
import io
import sqlite3
import zipfile
import pytest

from app.data.exercises import EXERCISE_CATALOG


def _get_profile_header(client, profile_name="WeekPlanner"):
    res = client.post(
        "/api/profiles",
        json={"name": profile_name, "calorie_target": 2200, "avatar_color": "#10b981"},
    )
    if res.status_code == 201:
        pid = res.json()["id"]
    else:
        profs = client.get("/api/profiles").json()["profiles"]
        pid = [p["id"] for p in profs if p["name"] == profile_name][0]
    return {"X-Profile-ID": str(pid)}, pid


def test_week_plan_auto_creation_and_defaults(client):
    headers, pid = _get_profile_header(client, "AutoCreateUser")

    res = client.get("/api/workouts/week-plan", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["profile_id"] == pid
    assert "week_start" in data
    assert "week_end" in data
    days = data["days"]
    assert len(days) == 7

    mon = date.fromisoformat(data["week_start"])
    assert mon.weekday() == 0

    workout_days = [d for d in days if not d["is_rest"]]
    rest_days = [d for d in days if d["is_rest"]]
    assert len(workout_days) == 3
    assert len(rest_days) == 4

    assert days[0]["focus"] == "upper"
    assert days[1]["focus"] == "rest"
    assert days[2]["focus"] == "lower"
    assert days[3]["focus"] == "rest"
    assert days[4]["focus"] == "full_body"
    assert days[5]["focus"] == "rest"
    assert days[6]["focus"] == "rest"

    for d in days:
        assert "routine" in d
        assert "title" in d["routine"]
        assert len(d["routine"]["phases"]) >= 3


def test_week_plan_splits_by_frequency(client):
    headers, pid = _get_profile_header(client, "SplitTester")

    res = client.post(
        "/api/workouts/week-plan/generate",
        headers=headers,
        json={"days_per_week": 4, "level": "intermediate", "duration_min": 30},
    )
    assert res.status_code == 200
    data = res.json()
    days = data["days"]
    assert len([d for d in days if not d["is_rest"]]) == 4
    assert days[0]["focus"] == "upper"
    assert days[1]["focus"] == "lower"
    assert days[2]["focus"] == "rest"
    assert days[3]["focus"] == "upper"
    assert days[4]["focus"] == "lower"
    assert days[5]["focus"] == "rest"
    assert days[6]["focus"] == "rest"

    res = client.post(
        "/api/workouts/week-plan/generate",
        headers=headers,
        json={"days_per_week": 5},
    )
    assert res.status_code == 200
    days5 = res.json()["days"]
    assert len([d for d in days5 if not d["is_rest"]]) == 5
    assert days5[0]["focus"] == "upper"
    assert days5[1]["focus"] == "lower"
    assert days5[2]["focus"] == "core_mobility"
    assert days5[3]["focus"] == "upper"
    assert days5[4]["focus"] == "lower"


def test_muscle_group_targeting_integrity(client):
    headers, pid = _get_profile_header(client, "TargetTester")

    res = client.get("/api/workouts/week-plan", headers=headers)
    assert res.status_code == 200
    days = res.json()["days"]

    upper_day = days[0]
    assert upper_day["focus"] == "upper"
    upper_main = upper_day["routine"]["main"]
    assert len(upper_main) > 0
    for ex in upper_main:
        assert ex["category"] in ("upper", "core"), f"Unexpected category {ex['category']} in upper day"

    lower_day = days[2]
    assert lower_day["focus"] == "lower"
    lower_main = lower_day["routine"]["main"]
    assert len(lower_main) > 0
    for ex in lower_main:
        assert ex["category"] in ("lower", "core"), f"Unexpected category {ex['category']} in lower day"


def test_equipment_strict_adherence_in_week_plan(client):
    headers, pid = _get_profile_header(client, "EquipCheckUser")

    eq_res = client.get("/api/workouts/equipment", headers=headers).json()
    owned_keys = set(eq_res["owned_keys"])
    owned_keys.add("none")

    plan_res = client.get("/api/workouts/week-plan", headers=headers).json()
    for d in plan_res["days"]:
        routine = d["routine"]
        for phase in routine["phases"]:
            for ex in phase["exercises"]:
                assert ex["equipment"] in owned_keys, (
                    f"Exercise '{ex['name']}' requires unowned equipment '{ex['equipment']}'"
                )


def test_workout_completion_tracking(client):
    headers, pid = _get_profile_header(client, "CompletionUser")

    plan = client.get("/api/workouts/week-plan", headers=headers).json()
    mon_str = plan["days"][0]["date"]

    assert plan["days"][0]["completed"] is False

    log_res = client.post(
        "/api/workouts",
        headers=headers,
        json={
            "day": mon_str,
            "title": "Strict Pushups and Core",
            "category": "upper",
            "duration_min": 25,
            "intensity": "intermediate",
            "equipment_used": ["yoga_mat"],
            "routine": [{"name": "Pushups"}],
            "notes": "Completed monday target",
        },
    )
    assert log_res.status_code == 201

    updated_plan = client.get("/api/workouts/week-plan", headers=headers).json()
    assert updated_plan["days"][0]["completed"] is True
    assert updated_plan["completed_days"] >= 1
    assert len(updated_plan["days"][0]["logged_workouts"]) >= 1
    assert updated_plan["days"][0]["logged_workouts"][0]["title"] == "Strict Pushups and Core"


def test_reroll_day(client):
    headers, pid = _get_profile_header(client, "RerollUser")

    plan1 = client.get("/api/workouts/week-plan", headers=headers).json()

    reroll_res = client.post(
        "/api/workouts/week-plan/reroll-day",
        headers=headers,
        json={"day_idx": 0, "focus": "hiit"},
    )
    assert reroll_res.status_code == 200
    plan2 = reroll_res.json()

    assert plan2["days"][0]["focus"] == "hiit"
    assert plan2["days"][0]["focus_label"] == "HIIT & Cardio"
    assert plan2["days"][0]["is_rest"] is False
    assert plan2["days"][1]["focus"] == plan1["days"][1]["focus"]
    assert plan2["days"][2]["focus"] == plan1["days"][2]["focus"]


def test_profile_isolation_in_week_plans(client):
    headersA, pidA = _get_profile_header(client, "ProfileA_User")
    headersB, pidB = _get_profile_header(client, "ProfileB_User")

    client.post(
        "/api/workouts/week-plan/generate",
        headers=headersA,
        json={"days_per_week": 5},
    )

    client.post(
        "/api/workouts/week-plan/generate",
        headers=headersB,
        json={"days_per_week": 3},
    )

    planA = client.get("/api/workouts/week-plan", headers=headersA).json()
    planB = client.get("/api/workouts/week-plan", headers=headersB).json()

    assert planA["profile_id"] == pidA
    assert planB["profile_id"] == pidB
    assert planA["days_per_week"] == 5
    assert planB["days_per_week"] == 3


def test_backup_export_includes_weekly_plans(client):
    headers, pid = _get_profile_header(client, "BackupPlanUser")

    # Generate a plan
    client.get("/api/workouts/week-plan", headers=headers)

    # Download backup
    res = client.get("/api/backup/export", headers=headers)
    assert res.status_code == 200

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert "tracker.db" in zf.namelist()

    db_bytes = zf.read("tracker.db")
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    mem.deserialize(db_bytes)

    rows = mem.execute("SELECT * FROM weekly_plans WHERE profile_id = ?", (pid,)).fetchall()
    assert len(rows) >= 1
