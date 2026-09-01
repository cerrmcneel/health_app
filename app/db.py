"""SQLite access: WAL mode, foreign keys, idempotent schema."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    day       TEXT    NOT NULL,
    taken_at  TEXT    NOT NULL,
    pose      TEXT    NOT NULL CHECK (pose IN ('front','profile')),
    path      TEXT    NOT NULL,                -- relative to STORAGE_DIR
    width     INTEGER NOT NULL DEFAULT 0,
    height    INTEGER NOT NULL DEFAULT 0,
    bytes     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (day, pose)                         -- one shot per pose per day; re-shoot replaces
);
CREATE INDEX IF NOT EXISTS idx_photos_pose_day ON progress_photos(pose, day DESC);

CREATE TABLE IF NOT EXISTS settings (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    calorie_target REAL NOT NULL DEFAULT 2200,
    protein_target REAL NOT NULL DEFAULT 160,
    carbs_target   REAL NOT NULL DEFAULT 220,
    fat_target     REAL NOT NULL DEFAULT 70
);
INSERT OR IGNORE INTO settings (id) VALUES (1);

-- Daily totals are derived, never stored, so edits to a meal can never drift
-- out of sync with the day's headline number.
CREATE VIEW IF NOT EXISTS v_daily_totals AS
SELECT m.day                          AS day,
       COUNT(DISTINCT m.id)           AS meal_count,
       ROUND(SUM(i.calories), 1)      AS calories,
       ROUND(SUM(i.protein_g), 1)     AS protein_g,
       ROUND(SUM(i.carbs_g), 1)       AS carbs_g,
       ROUND(SUM(i.fat_g), 1)         AS fat_g
FROM meals m
JOIN meal_items i ON i.meal_id = m.id
GROUP BY m.day;
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


def init_db() -> None:
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
