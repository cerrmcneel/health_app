"""Equipment inventory: catalog coverage and the generator's hard constraint."""
import pytest

from app.routers.workouts import EXERCISE_CATALOG, STANDARD_EQUIPMENT

MIN_EXERCISES_PER_ITEM = 3


def _keys_with_exercises():
    return {e["equipment"] for e in EXERCISE_CATALOG}


def test_catalog_ids_are_unique():
    ids = [e["id"] for e in EXERCISE_CATALOG]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate exercise ids: {sorted(dupes)}"


def test_every_exercise_declares_known_equipment():
    known = {item["key"] for item in STANDARD_EQUIPMENT} | {"none"}
    unknown = _keys_with_exercises() - known
    assert not unknown, f"exercises reference equipment not in the catalog: {sorted(unknown)}"


@pytest.mark.parametrize("item", STANDARD_EQUIPMENT, ids=lambda i: i["key"])
def test_advertised_equipment_unlocks_exercises(item):
    """Adding a piece of gear must actually change what the generator can produce.

    The inventory UI advertises each item with a promise ('Heavy compound lifts'),
    so a key with no exercises behind it is a broken promise, not a gap.
    """
    count = sum(1 for e in EXERCISE_CATALOG if e["equipment"] == item["key"])
    assert count >= MIN_EXERCISES_PER_ITEM, (
        f"'{item['name']}' ({item['key']}) unlocks {count} exercise(s); "
        f"owning it changes nothing about generated routines"
    )


def test_catalog_covers_all_three_phases():
    phases = {e["phase"] for e in EXERCISE_CATALOG}
    assert phases == {"warmup", "main", "cooldown"}


def test_generator_never_prescribes_unowned_equipment(client, second_profile):
    """The core promise of the feature, asserted rather than merely prompted."""
    headers = {"X-Profile-ID": str(second_profile["id"])}

    owned = client.get("/api/workouts/equipment", headers=headers).json()
    owned_keys = set(owned["owned_keys"]) | {"none"}

    for category in ("full_body", "hiit", "upper", "lower", "core_mobility"):
        routine = client.post(
            "/api/workouts/generate",
            json={"category": category, "duration_min": 40, "level": "advanced"},
            headers=headers,
        ).json()
        for ex in routine["warmup"] + routine["main"] + routine["cooldown"]:
            assert ex["equipment"] in owned_keys, (
                f"{category}: prescribed '{ex['name']}' requiring "
                f"'{ex['equipment']}', which this profile does not own"
            )


def test_adding_equipment_actually_reaches_generated_routines(client, second_profile):
    """Owning new gear must change what the generator produces, not just the DB.

    Generation samples randomly, so a single draw proves nothing; this repeats
    until the new equipment appears, and fails if it never does.
    """
    headers = {"X-Profile-ID": str(second_profile["id"])}

    client.post(
        "/api/workouts/equipment",
        json={"item_key": "pull_up_bar", "name": "Pull-up Bar"},
        headers=headers,
    )
    owned = client.get("/api/workouts/equipment", headers=headers).json()["owned_keys"]
    assert "pull_up_bar" in owned

    for _ in range(40):
        routine = client.post(
            "/api/workouts/generate",
            json={"category": "upper", "duration_min": 40, "level": "intermediate"},
            headers=headers,
        ).json()
        if any(e["equipment"] == "pull_up_bar" for e in routine["main"]):
            return

    pytest.fail(
        "40 upper-body routines were generated after adding a pull-up bar and not "
        "one prescribed a pull-up bar exercise"
    )


def test_post_equipment_twice_does_not_silently_remove_it(client, second_profile):
    """POST is an add, not a toggle.

    A double-tap on an inventory chip, or a retried request, must not delete gear
    the user just added.
    """
    headers = {"X-Profile-ID": str(second_profile["id"])}
    body = {"item_key": "kettlebell", "name": "Kettlebell"}

    client.post("/api/workouts/equipment", json=body, headers=headers)
    client.post("/api/workouts/equipment", json=body, headers=headers)

    owned = client.get("/api/workouts/equipment", headers=headers).json()["owned_keys"]
    assert "kettlebell" in owned, "second POST removed the equipment instead of being a no-op"
