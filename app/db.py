"""SQLite access: WAL mode, foreign keys, idempotent schema."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL UNIQUE,
    slug           TEXT    NOT NULL UNIQUE,
    created_at     TEXT    NOT NULL,
    avatar_color   TEXT    NOT NULL DEFAULT '#3b82f6',
    calorie_target REAL    NOT NULL DEFAULT 2200,
    protein_target REAL    NOT NULL DEFAULT 160,
    carbs_target   REAL    NOT NULL DEFAULT 220,
    fat_target     REAL    NOT NULL DEFAULT 70,
    is_default     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL DEFAULT 1 REFERENCES profiles(id) ON DELETE CASCADE,
    day         TEXT    NOT NULL,              -- local YYYY-MM-DD, the grouping key
    logged_at   TEXT    NOT NULL,              -- ISO8601 with offset
    name        TEXT    NOT NULL DEFAULT '',
    meal_type   TEXT    NOT NULL DEFAULT 'other',
    source      TEXT    NOT NULL DEFAULT 'manual',  -- 'photo' | 'manual'
    image_path  TEXT,                          -- relative to STORAGE_DIR
    model       TEXT,                          -- vision model used, if any
    notes       TEXT    NOT NULL DEFAULT '',
    raw_json    TEXT                           -- unedited model output, for auditing
);
CREATE INDEX IF NOT EXISTS idx_meals_day ON meals(day);

CREATE TABLE IF NOT EXISTS meal_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id     INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    grams       REAL    NOT NULL DEFAULT 0,
    calories    REAL    NOT NULL DEFAULT 0,
    protein_g   REAL    NOT NULL DEFAULT 0,
    carbs_g     REAL    NOT NULL DEFAULT 0,
    fat_g       REAL    NOT NULL DEFAULT 0,
    confidence  TEXT    NOT NULL DEFAULT 'medium',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_meal ON meal_items(meal_id);

CREATE TABLE IF NOT EXISTS progress_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL DEFAULT 1 REFERENCES profiles(id) ON DELETE CASCADE,
    day         TEXT    NOT NULL,
    taken_at    TEXT    NOT NULL,
    pose        TEXT    NOT NULL CHECK (pose IN ('front','profile')),
    path        TEXT    NOT NULL,                -- relative to STORAGE_DIR
    width       INTEGER NOT NULL DEFAULT 0,
    height      INTEGER NOT NULL DEFAULT 0,
    bytes       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_photos_pose_day ON progress_photos(pose, day DESC);

CREATE TABLE IF NOT EXISTS weights (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    day        TEXT    NOT NULL,
    logged_at  TEXT    NOT NULL,
    weight_kg  REAL    NOT NULL,
    notes      TEXT    NOT NULL DEFAULT '',
    UNIQUE (profile_id, day)
);
CREATE INDEX IF NOT EXISTS idx_weights_profile_day ON weights(profile_id, day DESC);

CREATE TABLE IF NOT EXISTS settings (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    calorie_target REAL NOT NULL DEFAULT 2200,
    protein_target REAL NOT NULL DEFAULT 160,
    carbs_target   REAL NOT NULL DEFAULT 220,
    fat_target     REAL NOT NULL DEFAULT 70
);
INSERT OR IGNORE INTO settings (id) VALUES (1);
"""

AFTER_MIGRATE_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_meals_profile_day ON meals(profile_id, day);
CREATE INDEX IF NOT EXISTS idx_photos_profile_pose_day ON progress_photos(profile_id, pose, day DESC);

-- Daily totals are derived, never stored, so edits to a meal can never drift
-- out of sync with the day's headline number.
DROP VIEW IF EXISTS v_daily_totals;
CREATE VIEW v_daily_totals AS
SELECT m.profile_id                   AS profile_id,
       m.day                          AS day,
       COUNT(DISTINCT m.id)           AS meal_count,
       ROUND(SUM(i.calories), 1)      AS calories,
       ROUND(SUM(i.protein_g), 1)     AS protein_g,
       ROUND(SUM(i.carbs_g), 1)       AS carbs_g,
       ROUND(SUM(i.fat_g), 1)         AS fat_g
FROM meals m
JOIN meal_items i ON i.meal_id = m.id
GROUP BY m.profile_id, m.day;
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Per-call connection. Commits on clean exit, rolls back on exception."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    # Ensure default profile exists
    conn.execute(
        """INSERT OR IGNORE INTO profiles (id, name, slug, created_at, avatar_color,
                                           calorie_target, protein_target, carbs_target, fat_target, is_default)
           VALUES (1, 'Default', 'default', ?, '#3b82f6', 2200, 160, 220, 70, 1)""",
        (config.now().isoformat(),),
    )

    # Migrate columns if migrating an older database
    meal_cols = {r["name"] for r in conn.execute("PRAGMA table_info(meals)").fetchall()}
    if "profile_id" not in meal_cols:
        conn.execute("ALTER TABLE meals ADD COLUMN profile_id INTEGER DEFAULT 1 REFERENCES profiles(id) ON DELETE CASCADE")

    photo_cols = {r["name"] for r in conn.execute("PRAGMA table_info(progress_photos)").fetchall()}
    if "profile_id" not in photo_cols:
        conn.execute("ALTER TABLE progress_photos ADD COLUMN profile_id INTEGER DEFAULT 1 REFERENCES profiles(id) ON DELETE CASCADE")


def init_db() -> None:
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(AFTER_MIGRATE_SCHEMA)


