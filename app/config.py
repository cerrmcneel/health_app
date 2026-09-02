"""Runtime configuration, loaded from .env with sane defaults."""
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _resolve(value: str) -> Path:
    """Relative paths in .env are resolved against the project root, not cwd."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else (BASE_DIR / p).resolve()


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
VISION_MODEL = os.getenv("VISION_MODEL", "gemma4:12b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))
VISION_MAX_EDGE = int(os.getenv("VISION_MAX_EDGE", "1024"))

STORAGE_DIR = _resolve(os.getenv("STORAGE_DIR", "./storage/fitness_tracker"))
DB_PATH = _resolve(os.getenv("DB_PATH", "./storage/fitness_tracker/tracker.db"))

FRONT_DIR = STORAGE_DIR / "front"
PROFILE_DIR = STORAGE_DIR / "profile"
MEALS_DIR = STORAGE_DIR / "meals"
PENDING_DIR = STORAGE_DIR / "_pending"

POSES = ("front", "profile")
POSE_DIRS = {"front": FRONT_DIR, "profile": PROFILE_DIR}

STATIC_DIR = BASE_DIR / "static"

def _load_tz() -> ZoneInfo | timezone:
    """Resolve the configured timezone, degrading rather than refusing to boot.

    Windows ships no system zoneinfo database, so `zoneinfo` depends on the
    `tzdata` package being installed. Falling back to ZoneInfo("UTC") is not
    safe there: with no database present that raises too, and the app dies at
    import time. datetime.timezone.utc needs no database and always works.
    """
    name = os.getenv("TZ", "UTC")
    try:
        return ZoneInfo(name)
    except Exception:
        pass
    try:
        return ZoneInfo("UTC")
    except Exception:
        # No tz database at all. Day boundaries fall at UTC midnight, which is
        # wrong for most users but keeps the app usable; install `tzdata`.
        return timezone.utc


TZ = _load_tz()


def now() -> datetime:
    """Timezone-aware 'now' in the configured local zone."""
    return datetime.now(TZ)


def today_iso() -> str:
    return now().date().isoformat()


def ensure_dirs() -> None:
    for d in (STORAGE_DIR, FRONT_DIR, PROFILE_DIR, MEALS_DIR, PENDING_DIR, DB_PATH.parent):
        d.mkdir(parents=True, exist_ok=True)
