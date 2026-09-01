"""Runtime configuration, loaded from .env with sane defaults."""
import os
from datetime import datetime
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

try:
    TZ = ZoneInfo(os.getenv("TZ", "UTC"))
except Exception:  # bad/unknown zone name should not stop the app booting
    TZ = ZoneInfo("UTC")


def now() -> datetime:
    """Timezone-aware 'now' in the configured local zone."""
    return datetime.now(TZ)


def today_iso() -> str:
    return now().date().isoformat()


def ensure_dirs() -> None:
    for d in (STORAGE_DIR, FRONT_DIR, PROFILE_DIR, MEALS_DIR, PENDING_DIR, DB_PATH.parent):
        d.mkdir(parents=True, exist_ok=True)
