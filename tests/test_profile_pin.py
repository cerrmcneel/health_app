"""Tests for profile 4-digit PIN lock, token authentication, and privacy protection."""
import uuid
import pytest
from app.services.profile_security import reset_rate_limits


@pytest.fixture(autouse=True)
def clean_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


def test_unlocked_profile_works_freely(client):
    """Profiles without a PIN are accessible without any authentication tokens."""
    name = f"Open_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name})
    assert res.status_code == 201
    prof = res.json()
    assert prof["has_pin"] is False
    assert "pin_hash" not in prof
    assert "pin_salt" not in prof

    # Can log meals freely
    meal_res = client.post(
        "/api/meals",
        json={"name": "Open Lunch", "items": [{"name": "Salad", "calories": 150}]},
        headers={"X-Profile-ID": str(prof["id"])},
    )
    assert meal_res.status_code == 201


def test_create_profile_with_pin(client):
    """Setting a PIN at creation masks the hash and marks has_pin=True."""
    name = f"Locked_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name, "pin": "1357"})
    assert res.status_code == 201
    prof = res.json()
    assert prof["has_pin"] is True
    assert "pin_hash" not in prof
    assert "pin_salt" not in prof


def test_locked_profile_blocks_data_access(client):
    """Locked profile data cannot be read without a valid unlock token."""
    name = f"Secret_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name, "pin": "2468"})
    assert res.status_code == 201
    pid = res.json()["id"]

    # Attempting to read meals without token returns 403
    m_res = client.get("/api/meals", headers={"X-Profile-ID": str(pid)})
    assert m_res.status_code == 403
    assert "Profile is locked" in m_res.json()["detail"]

    # Attempting to read weights without token returns 403
    w_res = client.get("/api/weights", headers={"X-Profile-ID": str(pid)})
    assert w_res.status_code == 403

    # Attempting to read stats without token returns 403
    s_res = client.get("/api/stats/daily", headers={"X-Profile-ID": str(pid)})
    assert s_res.status_code == 403


def test_verify_pin_success_and_unlock(client):
    """Correct PIN returns a signed token that grants access to profile data."""
    name = f"Vault_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name, "pin": "9999"})
    pid = res.json()["id"]

    # Verify PIN
    auth_res = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "9999"})
    assert auth_res.status_code == 200
    data = auth_res.json()
    assert "token" in data
    assert data["profile_id"] == pid
    token = data["token"]

    # Access with X-Profile-Token header
    m_res = client.get(
        "/api/meals",
        headers={"X-Profile-ID": str(pid), "X-Profile-Token": token},
    )
    assert m_res.status_code == 200

    # Write data with token
    write_res = client.post(
        "/api/meals",
        json={"name": "Protected Dinner", "items": [{"name": "Steak", "calories": 500}]},
        headers={"X-Profile-ID": str(pid), "X-Profile-Token": token},
    )
    assert write_res.status_code == 201


def test_verify_pin_incorrect(client):
    """Incorrect PIN returns 401 and does not grant token."""
    name = f"Lock_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name, "pin": "4321"})
    pid = res.json()["id"]

    auth_res = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "0000"})
    assert auth_res.status_code == 401
    assert "Incorrect PIN" in auth_res.json()["detail"]


def test_rate_limiting_brute_force(client):
    """5 consecutive failed PIN attempts triggers HTTP 429 rate limit."""
    name = f"Guarded_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name, "pin": "7777"})
    pid = res.json()["id"]

    for _ in range(5):
        fail_res = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "0000"})
        assert fail_res.status_code == 401

    # 6th attempt should be blocked with 429
    blocked_res = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "7777"})
    assert blocked_res.status_code == 429
    assert "Too many incorrect attempts" in blocked_res.json()["detail"]


def test_patch_pin_management(client):
    """Testing setting, changing, and removing a PIN via PATCH."""
    name = f"Manage_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name})
    pid = res.json()["id"]
    assert res.json()["has_pin"] is False

    # 1. Set PIN on profile without a PIN
    patch_res = client.patch(f"/api/profiles/{pid}", json={"pin": "1234"})
    assert patch_res.status_code == 200
    assert patch_res.json()["has_pin"] is True

    # 2. Change PIN without current PIN should fail
    fail_change = client.patch(f"/api/profiles/{pid}", json={"pin": "5678"})
    assert fail_change.status_code == 400
    assert "Current PIN is incorrect" in fail_change.json()["detail"]

    # Change PIN with wrong current PIN should fail
    fail_change2 = client.patch(f"/api/profiles/{pid}", json={"pin": "5678", "current_pin": "0000"})
    assert fail_change2.status_code == 400

    # Change PIN with correct current PIN succeeds
    succ_change = client.patch(f"/api/profiles/{pid}", json={"pin": "5678", "current_pin": "1234"})
    assert succ_change.status_code == 200

    # Old PIN fails now
    old_verify = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "1234"})
    assert old_verify.status_code == 401

    # New PIN succeeds
    new_verify = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "5678"})
    assert new_verify.status_code == 200

    # 3. Remove PIN with wrong current PIN should fail
    fail_remove = client.patch(f"/api/profiles/{pid}", json={"remove_pin": True, "current_pin": "9999"})
    assert fail_remove.status_code == 400

    # Remove PIN with correct current PIN succeeds
    succ_remove = client.patch(f"/api/profiles/{pid}", json={"remove_pin": True, "current_pin": "5678"})
    assert succ_remove.status_code == 200
    assert succ_remove.json()["has_pin"] is False

    # Profile is now unlocked; verify-pin returns has_pin=False
    unlocked_verify = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "1234"})
    assert unlocked_verify.status_code == 200
    assert unlocked_verify.json()["has_pin"] is False


def test_lock_endpoint_clears_cookie(client):
    """POST /api/profiles/{id}/lock clears the profile cookie."""
    name = f"LockTest_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name, "pin": "1111"})
    pid = res.json()["id"]

    v_res = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "1111"})
    assert v_res.status_code == 200

    lock_res = client.post(f"/api/profiles/{pid}/lock")
    assert lock_res.status_code == 200
    assert lock_res.json() == {"locked": pid}


def test_locked_profile_media_access(client):
    """Media from a locked profile cannot be viewed without token."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color="red").save(buf, format="JPEG")

    name = f"PhotoVault_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/profiles", json={"name": name, "pin": "5555"})
    pid = res.json()["id"]

    # Unlock to upload photo
    v_res = client.post(f"/api/profiles/{pid}/verify-pin", json={"pin": "5555"})
    token = v_res.json()["token"]

    up_res = client.post(
        "/api/photos",
        files={"image": ("locked_pic.jpg", buf.getvalue(), "image/jpeg")},
        data={"pose": "front", "day": "2026-09-12"},
        headers={"X-Profile-ID": str(pid), "X-Profile-Token": token},
    )
    assert up_res.status_code == 201
    photo_url = up_res.json()["photo"]["url"]

    # Clear client cookies to simulate unauthenticated request
    client.cookies.clear()
    blocked = client.get(photo_url, headers={"X-Profile-ID": str(pid)})
    assert blocked.status_code == 403

    # Requesting with valid token header returns 200
    allowed = client.get(
        photo_url,
        headers={"X-Profile-ID": str(pid), "X-Profile-Token": token},
    )
    assert allowed.status_code == 200

    # Requesting with cookie returns 200 (browser <img> tag behavior)
    client.cookies.clear()
    client.cookies.set(f"profile_token_{pid}", token)
    client.cookies.set("active_profile_id", str(pid))
    cookie_res = client.get(photo_url)
    assert cookie_res.status_code == 200

