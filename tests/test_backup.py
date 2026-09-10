"""Tests for backup export and profile data boundary isolation."""
import io
import json
import sqlite3
import zipfile
from fastapi.testclient import TestClient

from app import config


def test_default_export_is_profile_isolated(client: TestClient):
    """Profile B's backup export must never include Profile A's photos or records."""
    from PIL import Image

    def _jpeg(color):
        buf = io.BytesIO()
        Image.new("RGB", (60, 60), color=color).save(buf, format="JPEG")
        return buf.getvalue()

    # 1. Profile 1 (Default) logs a photo and meal
    p1_res = client.post(
        "/api/photos",
        data={"day": "2026-09-10", "pose": "front"},
        files={"image": ("photo1.jpg", _jpeg("red"), "image/jpeg")},
        headers={"X-Profile-ID": "1"},
    )
    assert p1_res.status_code == 201
    p1_photo_url = p1_res.json()["photo"]["url"]
    p1_photo_path = p1_photo_url.replace("/media/", "")

    client.post(
        "/api/meals",
        json={"name": "Secret P1 Meal", "items": [{"name": "Steak", "calories": 500}]},
        headers={"X-Profile-ID": "1"},
    )

    # 2. Create Profile 2 and log distinct photo and meal
    p2_res = client.post("/api/profiles", json={"name": "Bob"})
    assert p2_res.status_code == 201
    pid2 = str(p2_res.json()["id"])

    p2_photo_res = client.post(
        "/api/photos",
        data={"day": "2026-09-10", "pose": "front"},
        files={"image": ("photo2.jpg", _jpeg("blue"), "image/jpeg")},
        headers={"X-Profile-ID": pid2},
    )
    assert p2_photo_res.status_code == 201
    p2_photo_url = p2_photo_res.json()["photo"]["url"]
    p2_photo_path = p2_photo_url.replace("/media/", "")

    client.post(
        "/api/meals",
        json={"name": "Bob Meal", "items": [{"name": "Salad", "calories": 200}]},
        headers={"X-Profile-ID": pid2},
    )

    # 3. Profile 2 downloads their data export
    res = client.get("/api/backup/export", headers={"X-Profile-ID": pid2})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    namelist = zf.namelist()

    # Manifest checks
    assert "manifest.json" in namelist
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["scope"] == "profile"
    assert manifest["profile_id"] == int(pid2)
    assert manifest["profile_name"] == "Bob"

    # Profile 1's photo must NOT exist in Profile 2's ZIP, but Profile 2's must
    assert f"storage/{p1_photo_path}" not in namelist, f"Profile 1 photo {p1_photo_path} found in Profile 2 export: {namelist}"
    assert f"storage/{p2_photo_path}" in namelist, f"Profile 2 photo {p2_photo_path} missing from Profile 2 export: {namelist}"

    # Embedded SQLite DB must contain only Profile 2's rows
    assert "tracker.db" in namelist
    db_bytes = zf.read("tracker.db")
    tmp_conn = sqlite3.connect(":memory:")
    tmp_conn.deserialize(db_bytes)

    # Profiles table must only have Profile 2
    profs = tmp_conn.execute("SELECT id, name FROM profiles").fetchall()
    assert len(profs) == 1
    assert profs[0][0] == int(pid2)
    assert profs[0][1] == "Bob"

    # Meals table must only have Bob's meal
    meals = tmp_conn.execute("SELECT name, profile_id FROM meals").fetchall()
    assert len(meals) == 1
    assert meals[0][0] == "Bob Meal"
    assert meals[0][1] == int(pid2)

    # Progress photos must only have Bob's photo
    photos = tmp_conn.execute("SELECT profile_id FROM progress_photos").fetchall()
    assert len(photos) == 1
    assert photos[0][0] == int(pid2)


def test_profile_b_cannot_export_full_instance(client: TestClient):
    """Non-default profile must be rejected with 403 on full instance export."""
    p2_res = client.post("/api/profiles", json={"name": "Charlie"})
    assert p2_res.status_code == 201
    pid2 = str(p2_res.json()["id"])

    res = client.get("/api/backup/export?scope=all", headers={"X-Profile-ID": pid2})
    assert res.status_code == 403
    assert "restricted to the default administrative profile" in res.json()["detail"] or "APP_PASSWORD" in res.json()["detail"]


def test_full_instance_export_rejected_when_auth_disabled(client: TestClient, monkeypatch):
    """Default profile is blocked from full-instance dump if APP_PASSWORD is not set."""
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    res = client.get("/api/backup/export?scope=all", headers={"X-Profile-ID": "1"})
    assert res.status_code == 403
    assert "APP_PASSWORD" in res.json()["detail"]


def test_full_instance_export_permitted_for_admin_with_auth(client: TestClient, monkeypatch):
    """Default profile can export full instance when APP_PASSWORD is configured."""
    monkeypatch.setenv("APP_PASSWORD", "secret123")
    from app import auth
    auth._failed_attempts.clear()
    auth._key_cache.clear()

    # Log in to get session cookie
    login_res = client.post("/login", json={"password": "secret123"})
    assert login_res.status_code == 200
    assert auth.COOKIE_NAME in client.cookies

    res = client.get("/api/backup/export?scope=all", headers={"X-Profile-ID": "1"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["scope"] == "instance"


def test_admin_scope_check_is_a_guard_rail_not_a_boundary(client: TestClient, monkeypatch):
    """Documents the real behaviour so the docs cannot drift back into overclaiming.

    The active profile comes from the client-supplied X-Profile-ID header, so an
    authenticated non-default profile can reach the full dump simply by naming
    the default profile's id. That is tolerable only because APP_PASSWORD is one
    secret shared by the whole household. If this test ever starts failing
    because the request is rejected, the profile has been bound to the session
    (Task 3.7 Layer 2) -- delete this test and tighten the docs to match.
    """
    monkeypatch.setenv("APP_PASSWORD", "household_secret")
    from app import auth
    auth._failed_attempts.clear()
    auth._key_cache.clear()

    login = client.post("/login", json={"password": "household_secret"})
    assert login.status_code == 200

    non_default = client.post("/api/profiles", json={"name": "Dana"})
    assert non_default.status_code == 201

    # Dana presents the default profile's id and receives the whole instance.
    res = client.get("/api/backup/export?scope=all", headers={"X-Profile-ID": "1"})
    assert res.status_code == 200
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(res.content)).read("manifest.json"))
    assert manifest["scope"] == "instance"
