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
    seeded_equipment INTEGER NOT NULL DEFAULT 0,
    is_default     INTEGER NOT NULL DEFAULT 0,
    sex            TEXT,
    birth_year     INTEGER,
    height_cm      REAL,
    activity_level TEXT,
    goal           TEXT,
    goal_rate_kg_per_week REAL,
    preferred_duration_min INTEGER DEFAULT 25,
    preferred_level TEXT DEFAULT 'intermediate',
    workout_days_per_week INTEGER DEFAULT 3,
    onboarded_at   TEXT,
    track_back_photo INTEGER NOT NULL DEFAULT 0,
    pin_hash       TEXT,
    pin_salt       TEXT
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
    pose        TEXT    NOT NULL CHECK (pose IN ('front','profile','back')),
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


CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_docs USING fts5(
    slug UNINDEXED,
    title,
    section,
    content,
    tags
);

CREATE TABLE IF NOT EXISTS profile_equipment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    item_key    TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    acquired_at TEXT    NOT NULL,
    notes       TEXT    NOT NULL DEFAULT '',
    UNIQUE (profile_id, item_key)
);
CREATE INDEX IF NOT EXISTS idx_equip_profile ON profile_equipment(profile_id);

CREATE TABLE IF NOT EXISTS workouts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id     INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    day            TEXT    NOT NULL,
    logged_at      TEXT    NOT NULL,
    title          TEXT    NOT NULL,
    category       TEXT    NOT NULL DEFAULT 'full_body',
    duration_min   INTEGER NOT NULL DEFAULT 20,
    intensity      TEXT    NOT NULL DEFAULT 'medium',
    equipment_used TEXT    NOT NULL DEFAULT '',
    routine_json   TEXT    NOT NULL DEFAULT '[]',
    completed      INTEGER NOT NULL DEFAULT 1,
    notes          TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_workouts_profile_day ON workouts(profile_id, day DESC);

CREATE TABLE IF NOT EXISTS weekly_plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    week_start  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    days_json   TEXT    NOT NULL,
    UNIQUE(profile_id, week_start)
);
CREATE INDEX IF NOT EXISTS idx_weekly_plans_prof_week ON weekly_plans(profile_id, week_start);
"""

AFTER_MIGRATE_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_meals_profile_day ON meals(profile_id, day);
CREATE INDEX IF NOT EXISTS idx_photos_profile_pose_day ON progress_photos(profile_id, pose, day DESC);
CREATE INDEX IF NOT EXISTS idx_equip_profile ON profile_equipment(profile_id);
CREATE INDEX IF NOT EXISTS idx_workouts_profile_day ON workouts(profile_id, day DESC);
CREATE INDEX IF NOT EXISTS idx_weekly_plans_prof_week ON weekly_plans(profile_id, week_start);

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


PHOTOS_TABLE_V2 = """
CREATE TABLE progress_photos__new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL DEFAULT 1 REFERENCES profiles(id) ON DELETE CASCADE,
    day         TEXT    NOT NULL,
    taken_at    TEXT    NOT NULL,
    pose        TEXT    NOT NULL CHECK (pose IN ('front','profile','back')),
    path        TEXT    NOT NULL,
    width       INTEGER NOT NULL DEFAULT 0,
    height      INTEGER NOT NULL DEFAULT 0,
    bytes       INTEGER NOT NULL DEFAULT 0
)
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return (row["sql"] or "") if row else ""


def _migrate(conn: sqlite3.Connection) -> None:
    # Ensure default profile exists
    conn.execute(
        """INSERT OR IGNORE INTO profiles (id, name, slug, created_at, avatar_color,
                                           calorie_target, protein_target, carbs_target, fat_target, is_default)
           VALUES (1, 'Default', 'default', ?, '#3b82f6', 2200, 160, 220, 70, 1)""",
        (config.now().isoformat(),),
    )

    # SQLite rejects ADD COLUMN when it carries both REFERENCES and a non-NULL
    # default ("Cannot add a REFERENCES column with non-NULL default value"), so
    # the column is added plain. Every pre-profiles row belongs to the default
    # profile by definition, which is exactly what DEFAULT 1 gives.
    if "profile_id" not in _columns(conn, "meals"):
        conn.execute("ALTER TABLE meals ADD COLUMN profile_id INTEGER NOT NULL DEFAULT 1")

    # A v1 progress_photos carries a table-level UNIQUE(day, pose). That would
    # stop a second profile ever storing its own photo for a day the first
    # profile already used. A table constraint cannot be dropped in place, so
    # the table is rebuilt when the legacy shape is detected or when 'back' pose is not yet allowed.
    photo_sql = " ".join(_table_sql(conn, "progress_photos").split()).lower()
    legacy_unique = "unique (day, pose)" in photo_sql or "unique(day, pose)" in photo_sql
    needs_back_pose = "'back'" not in photo_sql
    if "profile_id" not in _columns(conn, "progress_photos") or legacy_unique or needs_back_pose:
        has_pid = "profile_id" in _columns(conn, "progress_photos")
        pid_expr = "profile_id" if has_pid else "1"
        conn.execute("DROP TABLE IF EXISTS progress_photos__new")
        conn.execute(PHOTOS_TABLE_V2)
        conn.execute(
            f"""INSERT INTO progress_photos__new
                    (id, profile_id, day, taken_at, pose, path, width, height, bytes)
                SELECT id, COALESCE({pid_expr}, 1), day, taken_at, pose, path,
                       COALESCE(width, 0), COALESCE(height, 0), COALESCE(bytes, 0)
                FROM progress_photos"""
        )
        conn.execute("DROP TABLE progress_photos")
        conn.execute("ALTER TABLE progress_photos__new RENAME TO progress_photos")

    # Enforce one photo per profile/day/pose. This is an index rather than a
    # table constraint so it can also be applied to databases already created
    # with the profile-aware schema, which shipped without any constraint at
    # all. Duplicates must go first or the index cannot be built.
    conn.execute(
        """DELETE FROM progress_photos
           WHERE id NOT IN (SELECT MAX(id) FROM progress_photos
                            GROUP BY profile_id, day, pose)"""
    )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_photos_profile_day_pose
           ON progress_photos(profile_id, day, pose)"""
    )

    # Drop the legacy write-only settings table
    conn.execute("DROP TABLE IF EXISTS settings")

    # Track equipment seeding per-profile so deleting gear is respected across boots
    profile_cols = {r["name"] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()}
    if "seeded_equipment" not in profile_cols:
        conn.execute("ALTER TABLE profiles ADD COLUMN seeded_equipment INTEGER NOT NULL DEFAULT 0")

    # Ensure profile onboarding and preference columns exist on existing databases
    new_profile_cols = {
        "sex": "TEXT",
        "birth_year": "INTEGER",
        "height_cm": "REAL",
        "activity_level": "TEXT",
        "goal": "TEXT",
        "goal_rate_kg_per_week": "REAL",
        "preferred_duration_min": "INTEGER DEFAULT 25",
        "preferred_level": "TEXT DEFAULT 'intermediate'",
        "workout_days_per_week": "INTEGER DEFAULT 3",
        "onboarded_at": "TEXT",
        "track_back_photo": "INTEGER NOT NULL DEFAULT 0",
        "pin_hash": "TEXT",
        "pin_salt": "TEXT",
    }
    for col_name, col_def in new_profile_cols.items():
        if col_name not in profile_cols:
            conn.execute(f"ALTER TABLE profiles ADD COLUMN {col_name} {col_def}")

    # One-time initial equipment seed (Yoga Mat, Jump Rope) for unseeded profiles
    now_str = config.now().isoformat()
    profiles = conn.execute("SELECT id FROM profiles WHERE seeded_equipment = 0").fetchall()
    for p in profiles:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM profile_equipment WHERE profile_id = ?", (p["id"],)
        ).fetchone()["c"]
        if count == 0:
            conn.execute(
                """INSERT OR IGNORE INTO profile_equipment (profile_id, item_key, name, acquired_at)
                   VALUES (?, 'yoga_mat', 'Yoga Mat', ?),
                          (?, 'jump_rope', 'Jump Rope', ?)""",
                (p["id"], now_str, p["id"], now_str),
            )
        conn.execute("UPDATE profiles SET seeded_equipment = 1 WHERE id = ?", (p["id"],))

    # Ensure weekly_plans table exists on existing databases
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weekly_plans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            week_start  TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            days_json   TEXT    NOT NULL,
            UNIQUE(profile_id, week_start)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_weekly_plans_prof_week ON weekly_plans(profile_id, week_start)")



def init_db() -> None:
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(AFTER_MIGRATE_SCHEMA)
        try:
            from app.services import knowledge
            knowledge.index_knowledge(conn)
        except Exception as exc:
            import logging
            logging.getLogger("tracker").warning("knowledge indexing failed: %s", exc)


