"""Test fixtures.

The environment must be pointed at a throwaway storage directory *before*
`app.config` is imported, because config reads os.environ at import time and
`load_dotenv` does not override variables that are already set. Every import of
application code therefore happens inside the fixtures below, never at module
scope.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# This MUST happen at conftest import time, not inside a fixture.
#
# `app.config` reads os.environ once, at import. Test modules import application
# code at module scope (e.g. `from app.routers.workouts import EXERCISE_CATALOG`),
# and pytest imports those modules during collection -- long before any fixture
# runs. Setting these in a fixture was therefore too late: config had already
# frozen the real DB_PATH and OLLAMA_URL from .env, and the suite quietly ran
# against the developer's live database and live Ollama.
#
# load_dotenv() does not override variables that are already set, so assigning
# them here wins over .env.
# ---------------------------------------------------------------------------
_TMP = Path(tempfile.mkdtemp(prefix="tracker-tests-")).resolve()
os.environ["STORAGE_DIR"] = str(_TMP)
os.environ["DB_PATH"] = str(_TMP / "tracker.db")
os.environ["TZ"] = "Europe/Madrid"
# A closed port, so any accidental model call fails fast and deterministically
# instead of reaching a real Ollama and making the suite depend on it.
os.environ["OLLAMA_URL"] = "http://127.0.0.1:1"
os.environ["OLLAMA_TIMEOUT"] = "2"

atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))


@pytest.fixture(scope="session")
def storage_dir() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def app(storage_dir):
    from app import config
    # Fail loudly rather than silently mutating real data if the ordering above
    # ever breaks again.
    assert config.DB_PATH == storage_dir / "tracker.db", (
        f"tests are pointed at {config.DB_PATH}, not the temp database. "
        f"app.config was imported before conftest set the environment."
    )
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def second_profile(client):
    """A profile other than the default, for isolation tests."""
    import uuid
    name = f"Isolation {uuid.uuid4().hex[:8]}"
    res = client.post("/api/profiles", json={"name": name})
    assert res.status_code == 201, res.text
    profile = res.json()
    yield profile
    client.delete(f"/api/profiles/{profile['id']}")


@pytest.fixture()
def default_profile_id(client):
    res = client.get("/api/profiles")
    assert res.status_code == 200
    profiles = res.json()["profiles"]
    default = next((p for p in profiles if p["is_default"]), profiles[0])
    return default["id"]
