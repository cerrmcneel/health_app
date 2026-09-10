# Remediation & Improvement Plan — Health App

**Author:** Claude Opus 5 (review pass, 2026-09-10)
**Executor:** Gemini 3.8 in Antigravity
**Scope reviewed:** commits `4dc8413` (equipment + workout designer) and `5646c04` (docker/README alignment), plus the surrounding codebase.


---

## STATUS — Phase 1 is DONE (Claude, 2026-09-10)

**Phase 1 has been implemented and verified in a browser. Do not redo it.**
`python -m pytest tests/ -q` → **56 pass, 8 fail**, and all 8 remaining failures are
Phase 3 tasks (3.1 catalog coverage, 3.3 POST toggle semantics).

Verified live at `http://127.0.0.1:8077/workout`:
- Generate Workout renders a full routine on first click, no console error
- The main circuit shows one Set button per round; warm-up and cool-down show one
- Beginner → 3 rounds / 30s rest / no plyometrics; Advanced → 5 rounds / 10s rest
- AI Coach returned a model-authored routine (`generator: "ai"`) that rendered correctly
- With Ollama unreachable the API returns `generator: "offline-fallback"` and the UI
  toasts *"AI coach unavailable — used the offline designer."*

**Two fixes beyond the original Phase 1 scope were required to ship it:**

1. **`Cache-Control` on static assets** (`app/main.py`, `RevalidatingStaticFiles`).
   Starlette sent ETag/Last-Modified but no `Cache-Control`, so browsers applied
   heuristic freshness and kept serving the old `workout.js`. Without this, the fix
   would not have reached any client that had already loaded the broken file — I hit
   exactly that while verifying. The service worker's build-id versioning cannot help,
   because the HTTP cache sits underneath it.

2. **`"think": false` on `/ai-generate`** (`app/routers/workouts.py`). `gemma4:12b`
   advertises a `thinking` capability. Without this flag it spent its whole
   `num_predict` budget reasoning and returned empty content, so *every* AI generation
   failed with `JSONDecodeError` and fell back. `app/services/vision.py` already sent
   this; the workout endpoint did not. `num_predict` also raised 1200 → 2000.

**Also fixed: `tests/conftest.py` was not actually isolating the database.** Test
modules import application code at module scope, which pytest executes during
collection — before fixtures run. `app.config` had therefore already frozen the real
`DB_PATH` and `OLLAMA_URL` from `.env`, so the suite ran against the live database and
live Ollama. Environment setup now happens at conftest import time, and the `app`
fixture asserts `config.DB_PATH` points at the temp directory rather than failing
silently. If you add a test module, keep application imports inside functions or at
least never rely on a fixture to set the environment.

---

## 0. How to use this document

Work the phases **in order**. Phase 1 is a live production bug that makes the newest
feature unusable; do not start Phase 3 polish before Phase 1 is verified working in a
browser.

Every task below has: **Where** (file + line), **What's wrong**, **Change**, **Verify**.
Do not mark a task done until the Verify step passes.

**Non-negotiable project constraints** (from `HANDOFF.md`, still binding):
no cloud dependency, no CDN, no telemetry, no hosted AI API, no npm build step.
Everything stays vanilla ES modules + FastAPI + SQLite + optional local Ollama.

**Before you start:**
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8077
```
Keep this running and re-check the browser after each phase.

---

## Phase 1 — ✅ DONE: the workout generator (kept for the record)

### Evidence

I ran the app and clicked **Generate Workout**. Every single generation fails:

```
POST /api/workouts/generate  → 200 OK (backend is fine)
renderRoutine(res)           → TypeError: ex.equipment.map is not a function
Result: toast "Generation error: ex.equipment.map is not a function"
        #routine-card stays class="card hidden" — no routine EVER renders
```

The backend is correct. `static/js/workout.js` was written against a **different data
shape than the one `app/routers/workouts.py` actually returns**. The two halves of
commit `4dc8413` do not agree with each other, so the headline feature of that commit
has never worked.

### The actual contract

`/api/workouts/generate` returns exercise objects shaped like this:

```json
{
  "id": "jump_rope_easy_rhythm",
  "name": "Jump Rope Light Rhythm",
  "category": "cardio",
  "equipment": "jump_rope",                      // STRING, not array
  "phase": "warmup",
  "type": "time",                                // "time" | "reps"
  "default_target": "60s",                       // STRING, not sets/reps numbers
  "target_muscles": "Calves, Cardio, Coordination",  // STRING, not array
  "instructions": "Light continuous basic bounce..."
}
```

The frontend expects `ex.equipment: string[]`, `ex.target_muscles: string[]`,
`ex.sets: number`, `ex.reps: number`, `ex.duration_sec: number`. None of those exist.

### Task 1.1 — Fix `renderExercisePhase` to the real shape

**Where:** `static/js/workout.js:302-345`

**Change:**

- **Line 305-307** — `equipment` is a single string key (`"none"` for bodyweight):
  ```js
  const equipLabel = (ex.equipment && ex.equipment !== 'none')
    ? `${EQUIP_ICONS[ex.equipment] || '📦'} ${ex.equipment.replace(/_/g, ' ')}`
    : '🤸 Bodyweight';
  ```

- **Line 309-311** — there is no `sets`/`reps`/`duration_sec`. Use `default_target`:
  ```js
  const prescription = ex.default_target || (ex.type === 'time' ? '45s' : '10 reps');
  ```

- **Line 313** — `totalSets` must come from the routine, not the exercise. The backend
  returns `routine.rounds` (3 or 4). Pass it into `renderExercisePhase` as a third
  argument and default to 3:
  ```js
  function renderExercisePhase(phase, exercises, rounds = 3) { ... }
  const totalSets = phase === 'main' ? rounds : 1;
  ```
  Warm-up and cool-down movements are done once, not for 3 rounds — rendering "Set 1
  Set 2 Set 3" against a cool-down hamstring stretch is wrong.

- **Line 326** — `target_muscles` is already a comma-joined string; do not `.join()`,
  and **do escape it**:
  ```js
  ${ex.target_muscles ? `<span>&bull; ${esc(ex.target_muscles)}</span>` : ''}
  ```

- **Line 322** — `prescription` and `equipLabel` are interpolated raw into `innerHTML`.
  Wrap both in `esc()`. See Task 3.6 for why this matters.

**Verify:** click Generate Workout with the default gear (Yoga Mat + Jump Rope). The
routine card must appear with 3 warm-up, 4 main and 2 cool-down exercises, each showing
a real target like `60s` or `10-15 reps`, and no console error.

### Task 1.2 — Make `renderRoutine` tolerate a missing `category`

**Where:** `static/js/workout.js:277`

`routine.category.replace(...)` throws if `category` is absent. `/generate` always
supplies it, but `/ai-generate` does not guarantee it (its JSON schema only requires
`title` and `phases`), so the AI path can crash here before Task 1.3 even matters.

**Change:** `esc((routine.category || 'workout').replace('_',' ').toUpperCase())`.
Apply the same defensive treatment to `routine.intensity` and `routine.duration_min`.

**Verify:** `renderRoutine({title:'x', phases:[]})` in the console must not throw.

### Task 1.3 — Make the AI coach path render at all

**Where:** `app/routers/workouts.py:733-819` and `static/js/workout.js:283-285`

`/api/workouts/generate` returns `{warmup, main, cooldown, phases}`.
`/api/workouts/ai-generate` returns only `{title, phases, coaching_advice, ...}`.
`renderRoutine` reads `routine.warmup / .main / .cooldown` only — so even when Ollama
succeeds, the AI routine renders three empty phases.

**Change — pick the normalising option, not the branching one.** In
`ai_generate_workout`, after `data = json.loads(content)`, map the model's free-form
`phases` back onto the canonical shape before returning:

```python
def _phases_to_canonical(data: dict) -> dict:
    """The AI returns free-form phase names; the UI needs warmup/main/cooldown."""
    buckets = {"warmup": [], "main": [], "cooldown": []}
    for phase in data.get("phases") or []:
        name = str(phase.get("name", "")).lower()
        if "warm" in name:
            key = "warmup"
        elif "cool" in name or "stretch" in name or "down" in name:
            key = "cooldown"
        else:
            key = "main"
        for ex in phase.get("exercises") or []:
            buckets[key].append({
                "id": "",
                "name": str(ex.get("name", ""))[:120],
                "equipment": str(ex.get("equipment") or "none"),
                "phase": key,
                "type": "time" if "s" in str(ex.get("target", "")) else "reps",
                "default_target": str(ex.get("target") or ""),
                "target_muscles": str(ex.get("target_muscles") or ""),
                "instructions": str(ex.get("instructions") or ""),
            })
    data.update(buckets)
    return data
```

Also set `data.setdefault("category", params.category)`,
`data.setdefault("intensity", params.level)`,
`data.setdefault("duration_min", params.duration_min)`,
`data.setdefault("rounds", 3)`.

**Guard the equipment constraint server-side.** The system prompt *asks* the model not
to prescribe unavailable gear, but nothing enforces it. After normalising, drop any
exercise whose `equipment` key is not in `owned_keys`, and if that empties the main
bucket, fall back to `generate_workout`. A prompt is not a constraint.

**Verify:** with Ollama running, toggle the AI Coach switch and generate. Exercises
must appear in all three phases. With Ollama stopped, generation must still succeed via
the deterministic fallback.

### Task 1.4 — Raise the AI generate timeout

**Where:** `app/routers/workouts.py:806`

`httpx.AsyncClient(timeout=45.0)` is hardcoded, while `config.OLLAMA_TIMEOUT` defaults
to 180s. A cold 12B model load routinely exceeds 45s, so the *first* AI generation
almost always times out and silently falls back to the deterministic generator — the
user toggles "AI Coach", waits 45 seconds, and gets a non-AI routine with no
explanation.

**Change:** use `timeout=config.OLLAMA_TIMEOUT`. Separately, when the fallback fires,
return `"generator": "offline-fallback"` in the payload and have `workout.js` surface
a toast: *"AI coach unavailable — used the offline designer."* A silent fallback that
takes 45 seconds is worse than an honest error.

**Verify:** stop Ollama, generate with AI on, confirm the toast says the fallback was
used and a routine still renders.

### Task 1.5 — Send the level the user actually picked

**Where:** `static/js/workout.js:206-211`

The frontend posts `{category, duration_min, intensity}`. `WorkoutGenerateIn`
(`app/models.py:91`) declares `level`, not `intensity`. Pydantic silently ignores the
unknown field, so **the Beginner / Intermediate / Advanced pills have never done
anything** — every routine is generated at the default `"intermediate"`.

**Change:** post `level` (keep sending `intensity` too if you want, or rename the pill
group's read). Then make `level` actually matter in `generate_workout`
(`workouts.py:614`) — currently it is echoed into the response and never used to select
anything. Minimum viable: scale `rounds` and rest by level
(beginner 2 rounds / longer rest, advanced 4-5 rounds / shorter rest), and prefer or
exclude explosive movements (`jump_squats_power`, `burpees_full_body`,
`jump_rope_high_knees`) at beginner level.

**Verify:** generating at Beginner and Advanced must produce visibly different round
counts.

### Task 1.6 — Test suite — ✅ ALREADY WRITTEN, USE IT AS THE WORKLIST

**This is done. 60 tests exist and are committed.** Run them:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Current state: **43 pass, 17 fail.** Every failure is a real bug from this plan. Nothing
is xfail-marked and nothing is skipped — **your job is to make all 17 go green**, and a
green suite is the definition of done for Phases 1–3.

| File | Covers |
|---|---|
| `tests/conftest.py` | Isolated `STORAGE_DIR`/`DB_PATH` in a temp dir. Verified not to touch `storage/`. |
| `tests/test_workout_contract.py` | The API/UI contract that commit 4dc8413 broke |
| `tests/test_equipment.py` | Catalog coverage + the equipment constraint |
| `tests/test_profile_isolation.py` | The cross-profile meal leak |
| `tests/test_weights.py` | Trend maths for irregular weigh-ins |
| `tests/test_stats_and_meals.py` | Totals, meal slots, `normalize()`, workout day/week windows |

The failing list, mapped to tasks:

```
test_workout_contract.py::test_frontend_only_reads_exercise_fields_the_api_sends   → 1.1
test_equipment.py::test_post_equipment_twice_does_not_silently_remove_it           → 3.3
test_equipment.py::test_advertised_equipment_unlocks_exercises[7 params]           → 3.1
test_profile_isolation.py::test_cannot_{read,edit,delete,duplicate}_...            → 2.1
test_stats_and_meals.py::test_workout_list_can_be_filtered_to_a_single_day         → 2.3
test_stats_and_meals.py::test_this_week_window_covers_exactly_seven_days           → 2.4
test_weights.py::test_seven_day_change_spans_seven_days_not_seven_entries          → 2.2
test_weights.py::test_comparison_span_is_reported_so_the_label_can_be_honest       → 2.2
```

**The most valuable test is `test_frontend_only_reads_exercise_fields_the_api_sends`.**
It scrapes every `ex.<field>` access out of `workout.js` and asserts the API actually
sends it. That is the check that would have caught 4dc8413 at commit time. It currently
reports:

```
static/js/workout.js reads ex.{duration_sec, reps, rest_sec, sets},
which /api/workouts/generate never sends.
Available: category, default_target, equipment, id, instructions, name, phase,
           target_muscles, type
```

Note `rest_sec` — a fourth phantom field beyond the three named in Task 1.1. Handle it
too: there is no per-exercise rest in the API, so drive rest from the routine-level
`work_rest` string or drop the reference.

**Do not weaken a test to make it pass.** If you believe a test asserts the wrong
behaviour, say so and leave it failing rather than editing the assertion — two of these
(`change_span_days`, `rounds`) assert fields that do not exist yet *by design*, because
the fix requires adding them.

---

## Phase 2 — Data correctness and cross-profile leakage

### Task 2.1 — Meal endpoints ignore the active profile (confirmed exploitable)

**Where:** `app/routers/meals.py:156` (`get_meal`), `:189` (`update_meal`),
`:214` (`delete_meal`), `:165` (`duplicate_meal`)

These four endpoints take a bare `meal_id` and never call `get_profile_id`. I verified
this against the running app:

```
Created profile 2, logged "Secret meal" under it.
GET    /api/meals/<id>  with X-Profile-ID: 1  → 200, returns "Secret meal"
DELETE /api/meals/<id>  with X-Profile-ID: 1  → 204, deleted
```

In a household install, any profile can read, edit and delete any other profile's meal
log. `duplicate_meal` will additionally copy another profile's meal — including its
photo path — into yours.

**Change:** every one of these must resolve `profile_id = get_profile_id(request, conn)`
and scope the query: `WHERE id = ? AND profile_id = ?`, returning 404 on no match.
`update_meal` and `delete_meal` need `request: Request` added to their signatures.

**Verify:** repeat the sequence above; the cross-profile read and delete must both 404.
Add `tests/test_profile_isolation.py` covering all four endpoints — this is exactly the
class of bug that reappears.

### Task 2.2 — "7d change" on the weight card is not a 7-day change

**Where:** `app/routers/weights.py:47`

```python
prior = entries[6] if len(entries) >= 7 else ...
```

`entries` is ordered by *day desc*, but it is a list of **logs**, not days. `entries[6]`
means "seven weigh-ins ago". If the user weighs in twice a week, the "7d change"
displayed on the dashboard is a **three-and-a-half-week** change. The number is wrong
and it is wrong in the direction that flatters or alarms, depending on the trend.

**Daily weigh-ins must not be required.** Weighing in a few times a week is normal and
correct — the fix must work well for sporadic loggers, not push people toward daily
weighing. So: do not demand an entry exactly 7 days old, and do not return `None` just
because there isn't one.

**Change:** pick the weigh-in *nearest to* 7 days before the latest one, and report how
many days the comparison actually spans so the label can be honest:

```python
from datetime import date, timedelta

change_7d = None
change_span_days = None
if latest and len(entries) > 1:
    latest_day = date.fromisoformat(latest["day"])
    target = latest_day - timedelta(days=7)
    # entries are day-desc; consider everything strictly older than the latest.
    older = [e for e in entries if e["day"] != latest["day"]]
    if older:
        prior = min(older, key=lambda e: abs((date.fromisoformat(e["day"]) - target).days))
        change_7d = round(latest["weight_kg"] - prior["weight_kg"], 2)
        change_span_days = (latest_day - date.fromisoformat(prior["day"])).days
```

Return both fields. Then in `static/js/dashboard.js:223` and
`static/js/progress.js:72`, label the figure with the real span: render `7d change` only
when `change_span_days == 7`, otherwise `${change_span_days}d change`. A user who
weighs in on the 1st and the 12th should see **"11d change"**, not a wrong "7d change".

**Verify:** `tests/test_weights.py` already covers this — see
`test_seven_day_change_spans_seven_days_not_seven_entries` (7 weigh-ins over 40 days must
give −1.0, not −6.0), `test_seven_day_change_works_with_only_two_weigh_ins`, and
`test_comparison_span_is_reported_so_the_label_can_be_honest`. All three currently fail.

### Task 2.3 — The dashboard's "today's workout" card ignores the selected day

**Where:** `static/js/dashboard.js:258` requests `/api/workouts?day=${day}`;
`app/routers/workouts.py:847` accepts only `limit` and ignores `day` entirely.

The card therefore shows *the most recently logged workout ever*, labelled as today's,
on every day you navigate to.

**Change:** add `day: date | None = None` to `list_workouts` and filter on it when
supplied. Keep the unfiltered list for the history page (`workout.js` calls
`?limit=15`), so the parameter must be optional.

**Verify:** log a workout today, navigate the dashboard back one day — the card must
read "No workout completed yet today."

### Task 2.4 — "This week" is computed in UTC, not the configured timezone

**Where:** `app/routers/workouts.py:867` — `day >= date('now', '-7 days')`

SQLite's `date('now')` is always UTC. With `TZ=Europe/Madrid` (UTC+2 in summer), every
workout logged between 22:00 and midnight local falls on the wrong side of the window,
and the whole week boundary is shifted. The rest of the codebase is scrupulous about
this — `config.now()` exists precisely for it.

**Change:** compute the cutoff in Python and bind it:
```python
cutoff = (config.now().date() - timedelta(days=6)).isoformat()
... WHERE profile_id = ? AND day >= ?
```
(`-6` gives a true 7-day inclusive window ending today; `-7` gives 8 days.)

**Verify:** grep the whole codebase for `date('now'` and `datetime('now'` — fix every
occurrence, not just this one.

### Task 2.5 — Startup silently re-adds equipment the user deleted

**Where:** `app/db.py:243-256`, inside `_migrate`, which runs on **every** `init_db()`,
i.e. every application start.

```python
if count == 0:
    INSERT ... yoga_mat, jump_rope
```

A user who deliberately empties their equipment list (say, to record that they own
nothing) gets Yoga Mat and Jump Rope silently restored on the next restart, forever.
Seeding is a first-run concern, not a per-boot one.

**Change:** seed only for profiles created *after* this migration — add a
`seeded_equipment INTEGER NOT NULL DEFAULT 0` column to `profiles`, set it when seeding,
and skip any profile that already has it set. Seed new profiles at creation time in
`profiles.create_profile` instead of at boot.

**Verify:** remove all equipment, restart the server, confirm the list stays empty.

### Task 2.6 — Delete the write-only `settings` table

**Where:** `app/db.py:75-82`, `app/routers/stats.py:110-126`,
`app/routers/profiles.py:100-111`

The `settings` table is written from two places and **read from none** — targets moved
onto `profiles` when multi-profile landed. Worse, `PUT /api/settings` writes the global
row from whichever profile is active, so a secondary profile's target change stomps a
row that represents nobody.

**Change:** drop the table from `SCHEMA`, delete both write sites, and add a one-line
`DROP TABLE IF EXISTS settings` to the migration. Keep `PUT /api/settings` as an
endpoint — it correctly updates the active profile — just stop the second write.

**Verify:** `grep -rn "settings" app/ --include=*.py` returns only the profile-scoped
endpoint. App still boots against an existing database.

### Task 2.7 — Progress photos are served with no ownership check

**Where:** `app/routers/photos.py:184-193`

`GET /media/{path}` validates against directory traversal (correctly — see
`images.resolve_media`) but performs **no ownership check at all**. Combined with the
deterministic filenames written by `images.save_progress_photo`
(`{day}_{pose}[_p{profile_id}].jpg`), every progress photo in the system is
enumerable by anyone who can reach the app:

```
/media/front/2026-09-10_front.jpg      → profile 1's front photo
/media/front/2026-09-10_front_p2.jpg   → profile 2's front photo
/media/profile/2026-09-09_profile_p2.jpg
```

No guessing of a token, no authentication. For body photos this is the most sensitive
data in the app, and today it is the least protected.

**Change, in two parts:**

1. **Check ownership.** Look the path up in `progress_photos`, resolve the requesting
   profile, and 404 on a mismatch. Meal photos under `meals/` are already
   non-deterministically named (they carry a UUID fragment), so scope this to the pose
   directories first and extend if you add other media.
2. **Stop encoding identity in the filename.** Give new photos a random component
   (`{day}_{pose}_{uuid4().hex[:8]}.jpg`) so the path is not guessable even if the
   check is ever bypassed. Existing files keep working — the DB stores the path, so
   only new writes change. Defence in depth: the check is the control, the random name
   is the backstop.

**Verify:** log a photo under profile 2, note its `url` from the API response, then
request that URL with `X-Profile-ID: 1` — it must 404. Add this to
`tests/test_profile_isolation.py`.

---

## Phase 3 — Feature completeness and hardening

### Task 3.1 — Five of eleven equipment types unlock zero exercises

I counted the catalog: **44 exercises**, distributed as

| equipment | exercises |
|---|---|
| yoga_mat | 17 |
| none (bodyweight) | 14 |
| jump_rope | 4 |
| pull_up_bar | 3 |
| dumbbells | 3 |
| resistance_bands | 2 |
| kettlebell | 1 ⚠️ |
| **bench** | **0** |
| **barbell** | **0** |
| **dip_station** | **0** |
| **ab_wheel** | **0** |
| **foam_roller** | **0** |

`tests/test_equipment.py::test_advertised_equipment_unlocks_exercises` sets the bar at
three exercises per advertised item and **fails on seven of the eleven keys** — the five
with zero, plus `resistance_bands` (2) and `kettlebell` (1).

`STANDARD_EQUIPMENT` (`workouts.py:20-32`) advertises all eleven with descriptions like
*"Heavy compound lifts"* — but adding a barbell to your inventory changes literally
nothing about what the generator produces. The inventory UI promises a payoff it cannot
deliver.

**Change:** add at minimum 4-5 exercises per orphaned key, following the exact existing
dict shape (`id, name, category, equipment, phase, type, default_target,
target_muscles, instructions`). Suggested coverage:

- **barbell** — back squat, deadlift, bench press, overhead press, bent-over row (all `phase: main`)
- **bench** — dumbbell bench press, incline press, step-ups, bulgarian split squat (bench variant), seated shoulder press
- **dip_station** — parallel bar dips, leg raises, L-sit hold, inverted rows
- **ab_wheel** — kneeling rollout, standing rollout, oblique rollout
- **foam_roller** — IT band, thoracic extension, quad and calf release (all `phase: cooldown`)

Also thin the imbalance: `kettlebell` has one movement (swings) — add goblet squat,
Turkish get-up, single-arm row, clean & press.

**Verify:** add a test asserting every key in `STANDARD_EQUIPMENT` has ≥3 exercises in
`EXERCISE_CATALOG`, so the next equipment type added cannot ship empty.

### Task 3.2 — Move the catalog out of the router

`app/routers/workouts.py` is 891 lines, of which **~500 are a hardcoded data literal**.
The routing logic is buried below it and the file is painful to navigate or diff.

**Change:** move `STANDARD_EQUIPMENT` and `EXERCISE_CATALOG` to
`app/data/exercises.py` (or a JSON file loaded once at import). No behaviour change —
this is purely so Phase 3.1's additions do not push the router past 1,400 lines.
`workouts.py` should end up around 350 lines of actual logic.

### Task 3.3 — `POST /api/workouts/equipment` is a toggle that deletes

**Where:** `app/routers/workouts.py:571-600`

A `POST` that removes a row on second call, returns `201 Created` for a deletion, and
has a sibling `DELETE` endpoint that does the same thing properly. The frontend already
uses `DELETE` for removal (`workout.js:150`), so the toggle-off branch is reachable only
by accident — e.g. a double-tap on a chip, or a retried request, which silently deletes
gear the user just added.

**Change:** make `POST` idempotent-add only (`INSERT ... ON CONFLICT DO NOTHING`,
return 200 with the current state). Removal stays on `DELETE`. Also make `DELETE` return
404 when the key was not owned, instead of a silent 204.

### Task 3.4 — Blocking SQLite inside `async def` handlers

`app/main.py:1-7` documents the project's own rule: *"endpoints that only touch SQLite
are declared `def`, not `async def`, so the blocking sqlite3 driver never stalls the
event loop."*

Three places break it:

- `app/routers/knowledge.py:19` and `:31` — `async def` handlers that open `get_conn()`
  and run synchronous queries **and then hold that connection open across a 180-second
  Ollama call**. One user asking a nutrition question can block the event loop's
  progress and pin a SQLite connection for three minutes.
- `app/routers/workouts.py:734` — same pattern, plus it calls the synchronous
  `generate_workout(request, params)` from inside the async fallback path.

**Change:** in all three, read what you need from SQLite inside a short `with get_conn()`
block, **close it**, then `await` the model call outside the block. For
`knowledge.py`, this means `explain_balance` / `ask_nutrition_question` should take the
already-extracted `snapshot` and `docs` rather than a live `conn`.

**Verify:** no `await` appears lexically inside a `with get_conn()` block anywhere in
`app/`. That is a greppable invariant worth stating in the module docstring.

### Task 3.5 — Bare `except: pass` swallows real errors

**Where:** `app/services/knowledge.py:300-301`, `app/routers/photos.py:139-140`,
`app/db.py:269`

`except Exception: pass` around the Ollama call means a `KeyError` in your own prompt-
building code is indistinguishable from Ollama being offline — you get the deterministic
fallback and no log line, forever.

**Change:** catch `httpx.HTTPError` / `json.JSONDecodeError` specifically, and
`log.warning("...: %s", exc)` on every fallback path. Same for the photo-unlink
`except Exception: pass`.

### Task 3.6 — Escape model output before it reaches `innerHTML`

Several render paths interpolate unescaped strings into `innerHTML`:

- `workout.js:322` — `prescription`, `equipLabel`
- `workout.js:326` — `ex.target_muscles.join(...)`
- `workout.js:280` — `routine.equipment_used.join(', ')`
- `dashboard.js:719-722` — `renderSimpleMarkdown` builds HTML from `data.explanation`

With `/ai-generate` live, **that content is LLM output**, and with the equipment endpoint
accepting arbitrary `item_key`/`name` it is also user input. This is a single-user LAN
app so the blast radius is small, but the fix is one function call and the codebase
already has `esc()` and uses it correctly almost everywhere.

**Change:** wrap every interpolated dynamic value in `esc()`. For
`renderSimpleMarkdown`, escape the input string *first*, then apply the markdown
regexes to the escaped text — check the current order at `dashboard.js:715`, because
escaping after the regexes would destroy the tags you just generated.

### Task 3.7 — Authentication (answering "how do we address the security?")

**Current state:** there is no authentication of any kind. `HOST=0.0.0.0`, nginx on
8443, and README instructions for Tailscale and Cloudflare Tunnel mean this app is one
port-forward away from the public internet, and **anyone who reaches it has full
read/write access to health records, body weight history and progress photos.**
`X-Profile-ID` is a plain client-supplied header with no secret behind it — so Phase
2.1's isolation fix is a *correctness* fix, not a security boundary. Even after 2.1,
switching profiles is one header edit away.

The right answer depends on the threat you are defending against, so do these in order —
each layer is independently useful and layer 1 is worth doing this week.

#### Layer 0 (free, do it first): don't expose it at all

The strongest control is network reachability. **Tailscale is the recommended default**
and the README already documents it:

```bash
tailscale serve --bg --https=443 http://localhost:8000
```

This gives a trusted Let's Encrypt cert (which satisfies the iOS/Android camera
requirement), works from anywhere, and **opens zero firewall ports** — only devices on
your tailnet can reach it. For a single-household install this is genuinely sufficient,
and it is strictly better than port-forwarding plus a password.

Make the README say this in as many words: *do not port-forward this app; use Tailscale.*
Right now the README lists Tailscale as one option among several, alongside a
Cloudflare Tunnel that would put an unauthenticated medical app on the public internet.

#### Layer 1: a shared-secret gate (`APP_PASSWORD`)

Defends against: someone else on your LAN (guests, IoT devices, a roommate), and an
accidental exposure.

**Design — no dependencies, no user table, ~80 lines:**

- `APP_PASSWORD` env var. **When unset, auth is disabled entirely** so the current LAN
  experience is unchanged and nobody is locked out by an upgrade.
- Derive a key once at startup: `hashlib.scrypt(password, salt=<derived from password>, ...)`.
  Do not store the password anywhere but the environment.
- `GET /login` serves a minimal page; `POST /login` compares with
  `hmac.compare_digest` (constant-time — a plain `==` leaks the password one character
  at a time under timing analysis).
- On success set a cookie: `HttpOnly`, `SameSite=Lax`, `Secure` when the request arrived
  over HTTPS (check `X-Forwarded-Proto`, which `nginx.conf:22` already sets), value =
  `<expiry>.<hmac_sha256(key, expiry)>`, 30-day expiry.
- A `@app.middleware("http")` that rejects everything with 401 except `/login`,
  `/static/*`, `/sw.js`, `/manifest.webmanifest`, and `/api/health/live`.
- Rate-limit failed logins: an in-memory `dict[ip, (count, first_attempt_ts)]`, 10
  attempts per 15 minutes. Not bulletproof, but it turns an offline-speed brute force
  into an infeasible one.

**Why a shared secret and not accounts:** accounts mean a user table, password resets,
session invalidation and an admin UI — a large surface for a homelab app whose entire
premise is "no accounts, no cloud". One password shared by the household matches how the
app is actually used, and it composes cleanly with Layer 0.

#### Layer 2: make the profile header non-spoofable

Only worth doing once you have Layer 1 **and** more than one person's data in one
instance (i.e. if you pursue Phase 6 Option B).

Bind the profile to the session rather than trusting the request: put the profile id
inside the signed cookie, add `POST /api/profiles/{id}/activate` as the only way to
change it, and have `get_profile_id` (`app/deps.py:13`) read the cookie first and fall
back to the header only when auth is disabled. Until then, `X-Profile-ID` is a
convenience, not a control, and the code should say so in a comment so nobody mistakes
it for one.

#### What not to do

- **Do not put this behind a Cloudflare Tunnel without Layer 1.** A tunnel is a
  publicly-resolvable hostname; "nobody knows the URL" is not access control.
- **Do not add OAuth / Authelia / Authentik** unless you already run one. Each adds a
  service, a database and a failure mode to an app that currently has none, for a
  household of two.
- **Do not encrypt the SQLite database at rest** as a first move. It protects against
  someone who already has your disk, which is a much later threat than the open port,
  and it complicates every backup.

**Verify:** with `APP_PASSWORD` set, `curl -s -o /dev/null -w '%{http_code}'
http://localhost:8000/api/stats/daily` returns 401; with a valid cookie it returns 200;
with `APP_PASSWORD` unset it returns 200. Add `tests/test_auth.py` covering all three.

---

## Phase 4 — Documentation and deployment truth

The `5646c04` "align with subscription-free homelab vision" commit rewrote the README
into a marketing document. Several claims are now false.

### Task 4.1 — Document the Ollama version floor for Gemma 4

**Correction to an earlier draft of this plan: `gemma4:12b` is correct and must not be
changed.** Gemma 4 12B is a real, vision-capable, encoder-free multimodal model, it is
published at `ollama.com/library/gemma4:12b`, and it is installed and reporting
`capabilities: [completion, tools, thinking, vision]` on this machine (Ollama 0.33.3).
The earlier claim that it did not exist came from a model knowledge cutoff that predates
its release. Leave `VISION_MODEL=gemma4:12b` alone everywhere.

There is a genuine documentation gap underneath, though: **Gemma 4 requires Ollama 0.22
or newer.** A user on an older Ollama gets a pull failure or a model that loads without
vision, and `/api/health` will report `model_vision_capable: false` with no explanation
of why.

**Change:** in the README's "Setting up Ollama" section, state the 0.22 minimum and give
the check:
```bash
ollama --version   # must be >= 0.22 for gemma4
```
Also extend `/api/health`'s `hint` (`app/routers/stats.py:161`) so that when the
configured model is installed but not vision-capable, it mentions the Ollama version
floor as a likely cause rather than only listing alternative models.

Note the model also advertises a `thinking` capability, which is why
`vision.py:122` sends `"think": False` and has a dedicated error path for a model that
spends its whole budget reasoning. That handling is correct — do not remove it.

### Task 4.2 — Correct the overstated feature claims

- README line ~35: *"from a 70+ exercise catalog"* → the catalog has **44** entries.
  Either raise the count in Phase 3.1 until the claim is true, or write the real number.
- README line ~36: *"Interactive Workout Player: Real-time circuit tracking with
  checkable sets"* → describes a feature that throws on every use until Phase 1 lands.
- README Project Structure: *"Dockerfile # Multi-stage container definition"* → it is a
  single-stage build.
- README License section: *"Open source and free forever"* → **there is no LICENSE
  file.** Without one the work is legally all-rights-reserved. Add an actual
  `LICENSE` (MIT or AGPL-3.0 — AGPL fits the anti-SaaS framing better) or soften the
  claim.

### Task 4.3 — nginx listens on ports compose never publishes

`nginx.conf:2` listens on 80 (HTTP→HTTPS redirect) and `:9` on 443, but
`docker-compose.yml` publishes **only** `8443:8443`. The redirect and the standard HTTPS
port are unreachable from the host, so `http://server/` just fails to connect instead of
redirecting.

**Change:** publish `80:80` and `443:443` alongside `8443:8443`, or delete the unused
`listen` directives. Publishing them is the friendlier option — pick it and note in the
README that ports 80/443 must be free on the host.

### Task 4.4 — Docker healthcheck can time out on its own dependency

`Dockerfile:29` — `HEALTHCHECK --timeout=5s CMD curl .../api/health`. But `/api/health`
calls `vision.list_models()` with a **10-second** httpx timeout. If Ollama is
unreachable but not refusing connections (a common firewall case), the health endpoint
takes ~10s, curl gives up at 5s, and the container is marked unhealthy — restarting a
perfectly working tracker because an *optional* dependency is slow.

**Change:** either raise the healthcheck timeout to 15s, or — better — add a
`/api/health/live` that only confirms the process and database are up, and point the
Docker healthcheck at that. Keep the rich `/api/health` for the UI banner.

### Task 4.5 — Retire the stale handoff docs

`HANDOFF.md` (12KB) and `AGY_PROMPT.md` describe a **two-feature** app — photo calorie
counting and ghost-overlay photos — and instruct the reader that it is "finished,
tested, and verified end-to-end". The app now has seven feature areas, one of which
ships broken. Any agent that reads these first, as `AGY_PROMPT.md` explicitly
instructs, starts from a false picture.

**Change:** fold anything still true (the landmines section, the no-cloud constraint)
into `README.md` or a new `CONTRIBUTING.md`, then delete both files. Do not leave two
onboarding documents contradicting each other.

### Task 4.6 — Reconcile the three different ports

`.env` says `PORT=8010`, `.claude/launch.json` uses `8077`, README says `8000`.
Pick 8000 as the documented default and note the others as local overrides.

---

## Phase 5 — Guided profile setup (new feature)

Motivated by Task 3.1: the generator only knows about a yoga mat and a jump rope because
nothing ever asked. The same is true of calorie targets (everyone starts on a generic
2200/160/220/70) and of body weight, without which the knowledge engine cannot compute
protein g/kg — the single most useful number it produces.

**Build a short onboarding interview that runs once per new profile.** Not a settings
page — a sequence of one-question-per-screen steps, skippable at any point, that writes
real data instead of leaving defaults in place.

### Task 5.1 — The flow

Trigger it from `create_profile` (new profiles) and offer it as "Set up your profile"
for existing ones. Six steps, none mandatory:

1. **Name + avatar colour** — already collected; keep it as step 1 for continuity.
2. **Body stats** — sex, age, height, current weight, activity level. Write the weight
   straight into the `weights` table so the trend graph starts immediately and
   `protein_per_kg` becomes computable on day one.
3. **Goal** — lose / maintain / gain, and a rate (e.g. 0.5 kg/week). Compute
   BMR via Mifflin-St Jeor and TDEE from the activity multiplier — the formula is
   already referenced in `app/services/knowledge.py:20`, so the science is in the repo,
   it just is not wired to setup.
4. **Macro targets** — present the computed split with the *reasoning* (protein at
   1.6–2.2 g/kg per ISSN, fat above the 20%-of-energy endocrine floor, carbs as the
   remainder), and let the user override any number. Reuse
   `_deterministic_balance_explanation()` so this works with Ollama offline.
5. **Equipment** — the existing inventory grid, presented as a checklist with a "just
   bodyweight" fast path. **This is the step that fixes the Task 3.1 blindness.**
6. **Schedule** — days per week and session length, stored as profile defaults so the
   Studio's pills come pre-set rather than always starting at 25 min / intermediate.

### Task 5.2 — Schema and API

Add to `profiles`: `sex`, `birth_year`, `height_cm`, `activity_level`, `goal`,
`goal_rate_kg_per_week`, `onboarded_at`. All nullable — existing profiles must keep
working untouched, and `onboarded_at IS NULL` is what triggers the prompt.

Add `POST /api/profiles/{id}/onboarding` accepting the whole payload in one call, so a
half-finished interview never leaves a profile in a partial state. Compute BMR/TDEE
**server-side** (`app/services/targets.py`) so the numbers are testable — a pure function
over stats is exactly what a unit test wants, and it keeps the arithmetic out of the DOM.

### Task 5.3 — Tests

`tests/test_targets.py`: Mifflin-St Jeor against published worked examples; protein
lands in 1.6–2.2 g/kg for a normal weight; fat never falls below 20% of energy; macros
sum to within 2% of the calorie target. These are pure functions — no fixtures needed.

---

## Phase 6 — Sharing with friends (roadmap, decide before building)

You asked how to share this while keeping their data private. There are three real
options and **they are not equally good.** My recommendation is Option A.

### Option A — They run their own instance (recommended)

Each friend gets their own container on their own hardware. Their data never touches
your machine, so "keeping their data private" is guaranteed by architecture rather than
by your code being correct. It also matches the project's whole premise, and it means a
bug in Phase 2.1-style isolation can never expose one friend to another.

**What this needs from you — this is a packaging problem, not a features problem:**

| # | Work | Why |
|---|---|---|
| 6.A1 | Publish a prebuilt image to GHCR (`ghcr.io/<you>/health-app:latest`) via a GitHub Action | `docker compose up` with no local build is the difference between 5 minutes and an evening |
| 6.A2 | A `docker-compose.yml` that needs **zero edits** to work | Currently it assumes a sibling `nginx.conf` and `certs/`; ship a single-service compose as the default |
| 6.A3 | First-run setup wizard | Phase 5 already gives you this — it doubles as onboarding for a stranger |
| 6.A4 | Add a real `LICENSE` (see Task 4.2) | Without one, nobody can legally run or modify it |
| 6.A5 | Backup/restore buttons in the UI | `tar` instructions are fine for you; a friend needs a "Download my data" button. Also the honest answer to "can I leave?" |
| 6.A6 | An `ARCHITECTURE.md` and a real README quick start | The current README is a sales page; a self-hoster needs the map |

**Cost to you:** one weekend of packaging. **Privacy risk: zero.** No shared database,
no shared secrets, no liability for someone else's medical records.

### Option B — One instance, multiple households

Your existing multi-profile support, opened to non-family. **Do not do this until Task
2.1, Task 3.7 Layer 1 and Layer 2 are all shipped and tested**, and understand what you
are taking on:

- Every profile-scoping bug becomes a breach of someone else's medical data. You already
  had four such endpoints, found only because someone reviewed the code.
- Progress photos are stored as plain JPEGs under predictable paths
  (`front/2026-09-10_front_p2.jpg`) served by `/media/{path}` with **no ownership check**
  (`app/routers/photos.py:184`). Anyone authenticated can enumerate everyone's body
  photos by guessing dates. This must be fixed — serve media through an ownership-checked
  handler and give files random names — before a second household exists.
- You become the data controller for other people's health data. In the EU that is
  GDPR Article 9 special-category data, and "it's a hobby project" is not an exemption
  once it is other people's data on your hardware.

If you do it anyway: separate `households` from `profiles`, scope every single query to
`household_id`, and add a test that enumerates all routes and fails on any that does not
filter by it.

### Option C — Federation / sync

Don't. A sync protocol between instances is a distributed-systems project with
conflict resolution and key exchange, and it would be the first thing in this codebase
that could leak data across a network boundary. It contradicts "your data never leaves
your home network".

### Recommendation

**Take Option A.** It is less work than Option B, it is the only one where you are not
responsible for your friends' medical data, and the work (6.A1–6.A6) makes the project
better for you too. Revisit Option B only if a friend genuinely cannot self-host, and
treat that as a separate project with its own security review.

---

## Suggested commit sequence

| # | Commit message | Tasks |
|---|---|---|
| 1 | `Fix workout routine rendering against the real API contract` | 1.1, 1.2, 1.5 |
| 2 | `Normalize AI-generated routines and enforce equipment constraint server-side` | 1.3, 1.4 |
| ~~3~~ | ~~`Add pytest harness`~~ — **already committed, 43/60 green** | 1.6 ✅ |
| 4 | `Scope meal endpoints to the active profile` | 2.1 |
| 5 | `Fix 7-day weight delta, workout day filter, and local-time week window` | 2.2, 2.3, 2.4 |
| 6 | `Stop reseeding equipment on boot; drop the unused settings table` | 2.5, 2.6 |
| 7 | `Expand exercise catalog to cover all advertised equipment` | 3.1, 3.2 |
| 8 | `Harden API semantics, escaping, and error logging` | 3.3, 3.4, 3.5, 3.6 |
| 9 | `Add optional shared-secret authentication` | 3.7 |
| 10 | `Document Ollama version floor, correct feature claims and deployment config` | 4.1–4.6 |
| 11 | `Add guided profile setup with computed targets` | 5.1–5.3 |
| 12 | `Package for self-hosting by others` | 6.A1–6.A6 |

Phases 1–4 are remediation and should land before Phase 5. Phase 6 is a roadmap
decision, not a task list — read it and choose before writing any of it.

---

## Definition of done

**Phases 1–3 (`python -m pytest tests/ -q` must be 60/60):**

- [ ] Generate Workout produces a rendered routine on the first click, with no console error
- [ ] AI Coach toggle produces a rendered routine, or an honest "fallback used" toast
- [ ] Beginner and Advanced produce measurably different routines
- [ ] All 17 currently-failing tests pass, with no assertion weakened to get there
- [ ] Profile 1 receives 404 for every profile-2 meal operation
- [ ] Every `STANDARD_EQUIPMENT` key unlocks at least three exercises
- [ ] `grep -rn "date('now'" app/` returns nothing
- [ ] No `await` inside a `with get_conn()` block
- [ ] `grep -n "ex\." static/js/workout.js` reads only fields the API sends

**Phase 4:**

- [ ] `VISION_MODEL=gemma4:12b` left intact; README states the Ollama 0.22+ requirement
- [ ] A `LICENSE` file exists
- [ ] README contains no claim contradicted by the code
- [ ] `HANDOFF.md` and `AGY_PROMPT.md` are gone or accurate

**Security (Task 3.7) — at minimum, before this is reachable from outside the LAN:**

- [ ] README recommends Tailscale over port-forwarding, in those words
- [ ] `APP_PASSWORD` gate implemented, off by default, with `tests/test_auth.py` green
- [ ] `/media/{path}` checks ownership before serving a progress photo

---

## Phase 7 — Follow-ups from the post-Gemini review (Claude, 2026-09-11)

Gemini's work is in good shape: **89 tests pass**, the catalog reaches 75 movements with
every advertised equipment key covered, `gemma4:12b` was correctly left intact, and the
README now leads with "do not port-forward this application."

Five defects were found and **already fixed** in that review — do not redo them:
`photos.py` selecting `id` but reading `existing["path"]` (retaking a photo 500'd and
rolled back), reflected XSS via `/login?error=`, attribute injection via `/login?next=`,
an open redirect after login, a login rate limit fully bypassable with a rotating
`X-Forwarded-For`, and ~48ms of uncached scrypt on **every authenticated request**.
Regression tests for all of them are in `tests/test_auth.py` and
`tests/test_profile_isolation.py`.

Two items remain. Both are design decisions rather than bugs, which is why they were
left for you rather than patched.

### Task 7.1 — `/api/backup/export` bypasses every profile boundary

**Where:** `app/routers/backup.py:21`

The endpoint is not profile-scoped. It serialises the **entire** database — every
profile's meals, weights, workouts and body photos — plus all of `storage/`, into one
ZIP. Verified working: `GET /api/backup/export` → 200, 48KB with the current data.

That is the correct behaviour for *"back up my instance"* and the wrong behaviour for
*"a household member downloads their data"*. It also drives a hole straight through the
profile isolation you just built: a secondary profile can retrieve another person's
progress photos in one request. And because auth is **off by default**, on a LAN
deployment this is an unauthenticated full-data export to anyone who can reach port 8000.

Pick one and implement it:

- **(a) Admin-only, recommended.** Restrict to the default profile
  (`profiles.is_default = 1`), and additionally require `APP_PASSWORD` to be configured —
  return 403 with a message explaining why when it is not. A whole-instance export is an
  administrative action and should be gated like one.
- **(b) Per-profile export.** Filter every table by the requesting `profile_id` and
  include only that profile's media. This is the honest reading of the "download my data"
  button promised in Phase 6 (6.A5), and it is what a friend running their own copy would
  expect. More work, better product.

Either way, add `tests/test_backup.py` asserting that profile B cannot obtain profile A's
photos through this endpoint.

### Task 7.2 — Document what the export actually contains

**Where:** `README.md:204`

The README lists `GET /api/backup/export` under "Storage & Backups" without saying that,
with authentication disabled, it hands the complete health record of everyone in the
household to any device on the network. Add one sentence saying so, and cross-reference
the `APP_PASSWORD` section. This is the single highest-value line of documentation in
the file — someone will otherwise expose this endpoint through a tunnel without
realising what it is.

### Smaller, optional

- `app/auth.py` — `logout()` calls `delete_cookie` without the `samesite`/`secure`
  attributes used when setting it. Some browsers will not clear the cookie. Pass matching
  attributes.
- `app/routers/backup.py` — the ZIP is built entirely in memory. Fine for a homelab,
  but a few years of progress photos will make it a problem. Stream it if that ever bites.
