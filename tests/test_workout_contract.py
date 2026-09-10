"""The API/UI contract for generated workout routines.

Commit 4dc8413 shipped a backend and a frontend that disagreed about the shape of
an exercise object, so `Generate Workout` threw a TypeError on every click and no
routine ever rendered. Nothing caught it because the two halves were only ever
exercised together by a human clicking the button.

These tests pin the contract from both directions:
  - the backend keeps emitting the fields the UI reads (test_generate_*)
  - the UI only reads fields the backend actually emits (test_frontend_*)
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKOUT_JS = ROOT / "static" / "js" / "workout.js"

# Fields `static/js/workout.js` reads off a routine object.
ROUTINE_FIELDS = ("title", "category", "duration_min", "intensity",
                  "equipment_used", "warmup", "main", "cooldown")


def _generate(client, **overrides):
    payload = {"category": "full_body", "duration_min": 25, "level": "intermediate"}
    payload.update(overrides)
    res = client.post("/api/workouts/generate", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _all_exercises(routine):
    return routine["warmup"] + routine["main"] + routine["cooldown"]


def test_generate_returns_every_routine_field_the_ui_reads(client):
    routine = _generate(client)
    missing = [f for f in ROUTINE_FIELDS if f not in routine]
    assert not missing, f"UI reads routine.{{{','.join(missing)}}} but the API omits them"


def test_generate_fills_all_three_phases_with_default_equipment(client):
    """A brand-new profile owns only a yoga mat and a jump rope.

    That is the most common real-world case, and it must still yield a complete
    session rather than an empty warm-up or cool-down.
    """
    routine = _generate(client)
    assert routine["warmup"], "no warm-up exercises for a default-equipment profile"
    assert routine["main"], "no main exercises for a default-equipment profile"
    assert routine["cooldown"], "no cool-down exercises for a default-equipment profile"


@pytest.mark.parametrize("category", ["full_body", "hiit", "upper", "lower", "core_mobility"])
def test_every_category_generates_a_usable_routine(client, category):
    routine = _generate(client, category=category)
    assert len(_all_exercises(routine)) >= 4


def test_exercise_scalar_fields_are_strings_not_lists(client):
    """The UI renders these directly; a list here reintroduces the 4dc8413 crash.

    `ex.equipment.map(...)` and `ex.target_muscles.join(...)` were written against
    an array shape that the backend never produced.
    """
    for ex in _all_exercises(_generate(client)):
        assert isinstance(ex["equipment"], str), f"{ex['name']}: equipment must be a str"
        assert isinstance(ex["target_muscles"], str), f"{ex['name']}: target_muscles must be a str"
        assert isinstance(ex["name"], str) and ex["name"]
        assert isinstance(ex["instructions"], str)


def test_every_exercise_carries_a_prescription(client):
    """`default_target` is the only prescription the API sends.

    The UI must render it; there are no `sets` / `reps` / `duration_sec` fields.
    """
    for ex in _all_exercises(_generate(client)):
        assert ex.get("default_target"), f"{ex['name']} has no default_target to display"
        assert ex.get("type") in ("time", "reps"), f"{ex['name']} has an unknown type"


def test_frontend_only_reads_exercise_fields_the_api_sends(client):
    """Static check that workout.js has not drifted away from the API again.

    Scrapes every `ex.<field>` access out of the renderer and asserts the API
    actually supplies it. This is the check that would have caught 4dc8413.
    """
    source = WORKOUT_JS.read_text(encoding="utf-8")
    read_fields = set(re.findall(r"\bex\.([a-zA-Z_][a-zA-Z0-9_]*)", source))
    # Ignore JS builtins reached through optional chaining on a string/array.
    read_fields -= {"length", "map", "join", "replace", "toString"}

    available = set(_all_exercises(_generate(client))[0].keys())
    unknown = sorted(read_fields - available)
    assert not unknown, (
        f"static/js/workout.js reads ex.{{{','.join(unknown)}}}, which "
        f"/api/workouts/generate never sends. Available fields: {sorted(available)}"
    )


def test_level_changes_the_dose_not_just_the_label(client):
    """The Beginner/Intermediate/Advanced pills must actually do something.

    The UI used to post `intensity`, which the API ignores in favour of `level`,
    so every routine came out at the default difficulty.
    """
    by_level = {
        lvl: _generate(client, category="hiit", duration_min=40, level=lvl)
        for lvl in ("beginner", "intermediate", "advanced")
    }
    rounds = {lvl: r["rounds"] for lvl, r in by_level.items()}
    assert rounds["beginner"] < rounds["intermediate"] < rounds["advanced"], rounds

    work_rest = {lvl: r["work_rest"] for lvl, r in by_level.items()}
    assert len(set(work_rest.values())) == 3, f"work/rest identical across levels: {work_rest}"


def test_beginner_routines_exclude_high_impact_movements(client):
    """Plyometrics are the movements most likely to hurt an untrained beginner."""
    from app.routers.workouts import HIGH_IMPACT_IDS

    for _ in range(15):
        routine = _generate(client, category="hiit", duration_min=40, level="beginner")
        offending = [e["name"] for e in routine["main"] if e["id"] in HIGH_IMPACT_IDS]
        assert not offending, f"beginner routine prescribed {offending}"


def test_ai_generate_falls_back_visibly_when_ollama_is_unreachable(client):
    """A silent fallback after a long wait looks like the AI produced this.

    The fixture points OLLAMA_URL at a closed port, so this always takes the
    fallback path.
    """
    res = client.post("/api/workouts/ai-generate",
                      json={"category": "full_body", "duration_min": 25, "level": "intermediate"})
    assert res.status_code == 200
    body = res.json()
    assert body["generator"] == "offline-fallback", (
        "the UI cannot tell the user the AI was unavailable without this marker"
    )
    # A fallback is still a complete, renderable routine.
    assert body["warmup"] and body["main"] and body["cooldown"]


def test_generate_marks_itself_as_the_catalog_generator(client):
    assert _generate(client)["generator"] == "catalog"


def test_rounds_is_present_for_set_tracking(client):
    """The set buttons must be driven by the routine's round count.

    Deriving them from a per-exercise `sets` field is what produced 'Set 1/2/3'
    against a cool-down stretch.
    """
    routine = _generate(client)
    assert isinstance(routine.get("rounds"), int) and routine["rounds"] >= 1
