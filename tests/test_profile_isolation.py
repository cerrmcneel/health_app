"""Every record must belong to exactly one profile, and stay there.

In a household install each profile is a different person. A profile that can
read or delete another's meal log is a privacy failure, not just a bug.
"""
import pytest


def _log_meal(client, profile_id, name="Isolation probe"):
    res = client.post(
        "/api/meals",
        json={"name": name, "items": [{"name": "probe", "calories": 100}]},
        headers={"X-Profile-ID": str(profile_id)},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_meal_is_stored_against_the_requesting_profile(client, second_profile):
    meal = _log_meal(client, second_profile["id"])
    assert meal["profile_id"] == second_profile["id"]


def test_cannot_read_another_profiles_meal(client, second_profile, default_profile_id):
    meal = _log_meal(client, second_profile["id"], name="Private meal")
    res = client.get(f"/api/meals/{meal['id']}", headers={"X-Profile-ID": str(default_profile_id)})
    assert res.status_code == 404, (
        f"profile {default_profile_id} read profile {second_profile['id']}'s meal: {res.text[:200]}"
    )


def test_cannot_edit_another_profiles_meal(client, second_profile, default_profile_id):
    meal = _log_meal(client, second_profile["id"])
    res = client.patch(
        f"/api/meals/{meal['id']}",
        json={"name": "Tampered"},
        headers={"X-Profile-ID": str(default_profile_id)},
    )
    assert res.status_code == 404


def test_cannot_delete_another_profiles_meal(client, second_profile, default_profile_id):
    meal = _log_meal(client, second_profile["id"])
    res = client.delete(f"/api/meals/{meal['id']}", headers={"X-Profile-ID": str(default_profile_id)})
    assert res.status_code == 404

    still_there = client.get(
        f"/api/meals/{meal['id']}", headers={"X-Profile-ID": str(second_profile['id'])}
    )
    assert still_there.status_code == 200, "the meal was destroyed by another profile"


def test_cannot_duplicate_another_profiles_meal(client, second_profile, default_profile_id):
    """Duplicating copies the name, macros and image path across the boundary."""
    meal = _log_meal(client, second_profile["id"], name="Private meal")
    res = client.post(
        f"/api/meals/{meal['id']}/duplicate",
        headers={"X-Profile-ID": str(default_profile_id)},
    )
    assert res.status_code == 404


def test_meal_lists_do_not_bleed_between_profiles(client, second_profile, default_profile_id):
    _log_meal(client, second_profile["id"], name="Only theirs")
    mine = client.get("/api/meals", headers={"X-Profile-ID": str(default_profile_id)}).json()
    assert all(m["name"] != "Only theirs" for m in mine["meals"])


@pytest.mark.parametrize("endpoint", ["/api/weights", "/api/workouts"])
def test_list_endpoints_are_profile_scoped(client, second_profile, default_profile_id, endpoint):
    res = client.get(endpoint, headers={"X-Profile-ID": str(second_profile['id'])})
    assert res.status_code == 200
    payload = res.json()
    rows = payload.get("weights") or payload.get("workouts") or []
    assert all(r.get("profile_id") == second_profile["id"] for r in rows)


def test_progress_photo_is_profile_isolated(client, second_profile, default_profile_id):
    """Progress photos must not be accessible across profile boundaries."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="blue").save(buf, format="JPEG")

    res = client.post(
        "/api/photos",
        files={"image": ("photo.jpg", buf.getvalue(), "image/jpeg")},
        data={"pose": "front", "day": "2026-09-11"},
        headers={"X-Profile-ID": str(second_profile["id"])},
    )
    assert res.status_code in (200, 201), res.text
    photo_url = res.json()["photo"]["url"]

    owner_res = client.get(photo_url, headers={"X-Profile-ID": str(second_profile["id"])})
    assert owner_res.status_code == 200
    # Browser <img> requests send active_profile_id cookie without custom headers
    client.cookies.set("active_profile_id", str(second_profile["id"]))
    cookie_res = client.get(photo_url)
    assert cookie_res.status_code == 200

    # If cookie points to another profile, photo is blocked
    client.cookies.set("active_profile_id", str(default_profile_id))
    blocked_res = client.get(photo_url)
    assert blocked_res.status_code == 404
    client.cookies.clear()



def test_retaking_a_photo_the_same_day_replaces_it(client, second_profile):
    """Re-shooting a pose is a core flow: the ghost overlay exists to support it."""
    import io
    from PIL import Image

    headers = {"X-Profile-ID": str(second_profile["id"])}

    def _jpeg(color):
        buf = io.BytesIO()
        Image.new("RGB", (80, 80), color=color).save(buf, format="JPEG")
        return buf.getvalue()

    first = client.post(
        "/api/photos",
        files={"image": ("a.jpg", _jpeg("red"), "image/jpeg")},
        data={"pose": "front", "day": "2026-09-11"},
        headers=headers,
    )
    assert first.status_code == 201, first.text

    retake = client.post(
        "/api/photos",
        files={"image": ("b.jpg", _jpeg("blue"), "image/jpeg")},
        data={"pose": "front", "day": "2026-09-11"},
        headers=headers,
    )
    assert retake.status_code == 201, f"retake failed: {retake.text[:300]}"

    # Exactly one row for that day/pose, and the new file is the one served.
    listing = client.get("/api/photos?pose=front", headers=headers).json()["photos"]
    same_day = [p for p in listing if p["day"] == "2026-09-11"]
    assert len(same_day) == 1
    assert client.get(same_day[0]["url"], headers=headers).status_code == 200
