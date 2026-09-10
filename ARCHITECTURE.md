# Architecture & Technical Design

This document details the system design, data flow, concurrency patterns, and security guarantees of the Health App. It serves as the primary map for developers, homelab operators, and self-hosters.

---

## 1. Core Design Invariants

- **Local Network Boundary**: Zero telemetry, zero external CDNs, zero cloud dependencies. No asset, font, or script is ever requested outside the host machine.
- **Data Sovereignty**: All metrics, meal records, workouts, and photos reside on the local filesystem in SQLite and local media directories.
- **Graceful Degradation**: Core tracking, calorie calculations, weight trend analysis, and workout generation function 100% offline without Ollama or an internet connection.
- **Strict Profile Isolation**: Every query reading or modifying user health data must filter by `profile_id`. Health data never leaks between profiles.

---

## 2. System Overview & Component Diagram

```
+-------------------------------------------------------------------------+
| Browser Client (Desktop / Mobile PWA)                                   |
|   - Vanilla ES Modules (no build step, no NPM)                          |
|   - Service Worker (offline asset caching with versioned revalidation)  |
+-------------------------------------------------------------------------+
                                 │
                                 │ HTTP / JSON (or Tailscale HTTPS)
                                 ▼
+-------------------------------------------------------------------------+
| FastAPI Application (Uvicorn)                                           |
|   ├─ Auth Middleware (Optional APP_PASSWORD gate, HMAC cookies, rate limit)
|   ├─ Synchronous Routers (def handlers for SQLite — no loop stall)       |
|   │   ├─ /api/meals       (Meals & item breakdowns)                     |
|   │   ├─ /api/weights     (Trend analysis & nearest-neighbor 7d deltas) |
|   │   ├─ /api/profiles    (Multi-profile, Mifflin-St Jeor onboarding)   |
|   │   ├─ /api/workouts    (Catalog generator with equipment constraint) |
|   │   └─ /api/backup      (WAL-safe SQLite backup & media zipping)      |
|   └─ Async Routers (async def handlers for external services)           |
|       ├─ /api/analyze     (Ollama multimodal vision meal estimation)    |
|       ├─ /api/knowledge   (Ollama nutrition QA & BM25 FTS5 retrieval)   |
|       └─ /api/workouts/ai (Ollama custom coaching routine design)       |
+-------------------------------------------------------------------------+
          │                                              │
          ▼                                              ▼
+------------------------------------+   +--------------------------------+
| SQLite 3 (WAL Mode)                |   | Local Ollama Server (Optional) |
|   - tracker.db                     |   |   - gemma4:12b (Ollama >= 0.22)|
|   - WAL journal & shared memory    |   |   - Vision, Completion         |
|   - FTS5 Full-Text Search index    |   +--------------------------------+
+------------------------------------+
          │
          ▼
+------------------------------------+
| Local Storage (STORAGE_DIR)        |
|   - meals/   (meal photos)         |
|   - front/   (progress photos)     |
|   - profile/ (side progress photos)|
+------------------------------------+
```

---

## 3. Database & Concurrency Architecture

### SQLite WAL Mode
The database engine runs with Write-Ahead Logging (`PRAGMA journal_mode=WAL`) and foreign keys enforced (`PRAGMA foreign_keys=ON`).
- Reads and writes run concurrently without blocking.
- Checkpoints are managed automatically by SQLite.

### The Synchronous vs. Asynchronous Invariant
As Python's built-in `sqlite3` driver is synchronous and blocking:
1. **Rule**: All endpoints interacting exclusively with SQLite are declared as standard synchronous functions (`def handler(...)`). FastAPI automatically runs them in an internal threadpool (`anyio.to_thread.run_sync`), preventing event loop stalls.
2. **Rule**: Handlers that communicate asynchronously with Ollama (`async def`) must **never** execute an `await` expression while holding an open SQLite connection. Data extraction occurs in a short synchronous `with get_conn()` block, is cleanly closed, and the network request is awaited outside the block.

---

## 4. Evidence-Based Nutrition & Workout Engines

### Mifflin-St Jeor & ISSN Targets (`app/services/targets.py`)
Calorie and macronutrient calculations follow established clinical formulas:
- **Basal Metabolic Rate (BMR)**:
  $$\text{BMR}_{\text{male}} = 10 \cdot \text{weight} + 6.25 \cdot \text{height} - 5 \cdot \text{age} + 5$$
  $$\text{BMR}_{\text{female}} = 10 \cdot \text{weight} + 6.25 \cdot \text{height} - 5 \cdot \text{age} - 161$$
- **Total Daily Energy Expenditure (TDEE)**:
  Multiplies BMR by activity factor (1.2 to 1.9).
- **ISSN Protein Standard**:
  Protein is prescribed at $1.6 - 2.2\text{ g/kg}$, elevated during caloric deficits to spare lean tissue.
- **Endocrine Minimum Fat Floor**:
  Dietary fat is constrained to $\ge 20\%$ of total calories to maintain steroidogenesis and hormonal health.
- **Physiological Floor**:
  Absolute minimum intake of 1200 kcal (women) and 1400 kcal (men).

### Workout Routine Designer (`app/routers/workouts.py` & `app/data/exercises.py`)
- Standard catalog of 75 exercises spanning all 11 equipment keys (`yoga_mat`, `jump_rope`, `pull_up_bar`, `resistance_bands`, `dumbbells`, `kettlebell`, `bench`, `barbell`, `dip_station`, `ab_wheel`, `foam_roller`).
- **Strict Constraint Enforcement**: Exercises are filtered strictly against the active profile's owned equipment. If an item is not owned, it will never appear in generated routines.
- **Level Scaling**: Adjusts circuit rounds, rest intervals, and excludes high-impact plyometrics for beginners.
- **Deterministic AI Fallback**: If local Ollama is unreachable or times out, the system automatically falls back to the deterministic designer and returns `generator: "offline-fallback"`.

---

## 5. Security & Isolation Model

- **Profile Isolation**: All read, write, and delete operations on meals, weights, workouts, and photos enforce profile ownership (`WHERE id = ? AND profile_id = ?`).
- **Progress Photo Protection**: `/media/{path}` validates relative path traversal and checks DB ownership against the active profile before serving.
- **Optional `APP_PASSWORD` Layer**:
  - Off by default for seamless LAN usage.
  - When enabled, authenticates via constant-time HMAC comparison and sets an `HttpOnly`, `SameSite=Lax` signed cookie valid for 30 days.
  - In-memory rate limiting throttles brute-force attempts.
- **Zero-Lock-in Data Export**:
  `GET /api/backup/export` performs an in-memory SQLite `.backup()` checkpoint and bundles the database and all user media into a downloadable `.zip` file.
