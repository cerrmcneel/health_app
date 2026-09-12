"""Tests for optional back progress photo feature."""
import io
import json
import sqlite3
import zipfile
from fastapi.testclient import TestClient
from PIL import Image


def _jpeg(color="green"):
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), color=color).save(buf, format="JPEG")
    return buf.getvalue()


def test_back_photo_upload_and_ghost(client: TestClient, default_profile_id: int):
    headers = {"X-Profile-ID": str(default_profile_id)}

    # Upload back photo
    res = client.post(
        "/api/photos",
        data={"day": "2026-09-10", "pose": "back"},
        files={"image": ("back1.jpg", _jpeg("blue"), "image/jpeg")},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    photo = res.json()["photo"]
    assert photo["pose"] == "back"
    assert "back/" in photo["url"]

    # Ghost overlay for back pose
    ghost_res = client.get("/api/photos/ghost?pose=back", headers=headers)
    assert ghost_res.status_code == 200
    assert ghost_res.json()["photo"]["id"] == photo["id"]

    # Retaking on same day replaces it
    res2 = client.post(
        "/api/photos",
        data={"day": "2026-09-10", "pose": "back"},
        files={"image": ("back2.jpg", _jpeg("yellow"), "image/jpeg")},
        headers=headers,
    )
    assert res2.status_code == 201
    listing = client.get("/api/photos?pose=back", headers=headers).json()["photos"]
    assert len([p for p in listing if p["day"] == "2026-09-10"]) == 1


def test_profile_track_back_photo_toggle(client: TestClient, default_profile_id: int):
    headers = {"X-Profile-ID": str(default_profile_id)}

    # Default is 0 / off
    status = client.get("/api/photos/status", headers=headers).json()
    assert status["track_back_photo"] is False
    assert status["expected_poses"] == ["front", "profile"]

    # Toggle on
    patch_res = client.patch(
        f"/api/profiles/{default_profile_id}",
        json={"track_back_photo": 1},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["track_back_photo"] == 1

    # Verify status reflects toggle
    status = client.get("/api/photos/status", headers=headers).json()
    assert status["track_back_photo"] is True
    assert status["expected_poses"] == ["front", "profile", "back"]

    # Toggle off
    patch_res = client.patch(
        f"/api/profiles/{default_profile_id}",
        json={"track_back_photo": 0},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["track_back_photo"] == 0

    status = client.get("/api/photos/status", headers=headers).json()
    assert status["track_back_photo"] is False
    assert status["expected_poses"] == ["front", "profile"]


def test_back_photo_status_remaining_flow(client: TestClient, second_profile):
    pid = second_profile["id"]
    headers = {"X-Profile-ID": str(pid)}

    # Enable back photo tracking
    client.patch(f"/api/profiles/{pid}", json={"track_back_photo": 1}, headers=headers)

    status = client.get("/api/photos/status", headers=headers).json()
    assert status["remaining"] == ["front", "profile", "back"]
    assert status["done"] == []

    # Shoot front
    client.post(
        "/api/photos",
        data={"pose": "front"},
        files={"image": ("f.jpg", _jpeg("red"), "image/jpeg")},
        headers=headers,
    )
    status = client.get("/api/photos/status", headers=headers).json()
    assert status["done"] == ["front"]
    assert status["remaining"] == ["profile", "back"]

    # Shoot profile
    client.post(
        "/api/photos",
        data={"pose": "profile"},
        files={"image": ("p.jpg", _jpeg("green"), "image/jpeg")},
        headers=headers,
    )
    status = client.get("/api/photos/status", headers=headers).json()
    assert set(status["done"]) == {"front", "profile"}
    assert status["remaining"] == ["back"]

    # Shoot back
    client.post(
        "/api/photos",
        data={"pose": "back"},
        files={"image": ("b.jpg", _jpeg("blue"), "image/jpeg")},
        headers=headers,
    )
    status = client.get("/api/photos/status", headers=headers).json()
    assert set(status["done"]) == {"front", "profile", "back"}
    assert status["remaining"] == []


def test_back_photo_profile_isolation(client: TestClient, second_profile, default_profile_id: int):
    # Profile 2 uploads a back photo
    res = client.post(
        "/api/photos",
        files={"image": ("back.jpg", _jpeg("purple"), "image/jpeg")},
        data={"pose": "back", "day": "2026-09-11"},
        headers={"X-Profile-ID": str(second_profile["id"])},
    )
    assert res.status_code == 201
    photo_url = res.json()["photo"]["url"]
    assert "/media/back/" in photo_url

    # Owner can access photo
    client.cookies.set("active_profile_id", str(second_profile["id"]))
    owner_res = client.get(photo_url)
    assert owner_res.status_code == 200

    # Default profile cannot access Profile 2's back photo
    client.cookies.set("active_profile_id", str(default_profile_id))
    blocked_res = client.get(photo_url)
    assert blocked_res.status_code == 404
    client.cookies.clear()


def test_back_photo_backup_export(client: TestClient, second_profile, default_profile_id: int):
    # Default profile logs back photo
    p1_res = client.post(
        "/api/photos",
        data={"day": "2026-09-10", "pose": "back"},
        files={"image": ("p1_back.jpg", _jpeg("orange"), "image/jpeg")},
        headers={"X-Profile-ID": str(default_profile_id)},
    )
    assert p1_res.status_code == 201
    p1_photo_url = p1_res.json()["photo"]["url"]
    p1_rel = p1_photo_url.replace("/media/", "")

    # Export for default profile
    res1 = client.get("/api/backup/export", headers={"X-Profile-ID": str(default_profile_id)})
    assert res1.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res1.content)) as zf:
        names = zf.namelist()
        assert f"storage/{p1_rel}" in names

        # Verify DB in backup has the back photo
        db_bytes = zf.read("tracker.db")
        con = sqlite3.connect(":memory:")
        con.deserialize(db_bytes)
        row = con.execute("SELECT pose FROM progress_photos WHERE pose = 'back'").fetchone()
        assert row is not None and row[0] == "back"
        con.close()

    # Export for second profile must NOT contain p1's back photo
    res2 = client.get("/api/backup/export", headers={"X-Profile-ID": str(second_profile["id"])})
    assert res2.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res2.content)) as zf:
        assert f"storage/{p1_rel}" not in zf.namelist()


def test_next_pose_skips_poses_already_captured(client: TestClient, second_profile):
    """With three poses, "any pose except this one" pointed back at a done pose."""
    headers = {"X-Profile-ID": str(second_profile["id"])}
    client.patch(f"/api/profiles/{second_profile['id']}", json={"track_back_photo": 1}, headers=headers)

    def shoot(pose):
        res = client.post("/api/photos", data={"pose": pose, "day": "2026-09-12"},
                          files={"image": (f"{pose}.jpg", _jpeg(), "image/jpeg")}, headers=headers)
        assert res.status_code == 201, res.text
        return res.json()["next_pose"]

    assert shoot("front") == "profile"
    assert shoot("profile") == "back"
    assert shoot("back") is None


def test_track_back_photo_rejects_values_other_than_0_or_1(client: TestClient, second_profile):
    res = client.patch(f"/api/profiles/{second_profile['id']}", json={"track_back_photo": 5},
                       headers={"X-Profile-ID": str(second_profile["id"])})
    assert res.status_code == 422
