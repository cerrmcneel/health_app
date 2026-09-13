# Contributing & Architectural Guidelines &middot; LocalPulse

This document preserves the hard-won lessons, architectural boundaries, and deployment landmines discovered during the development of this project. Read this before submitting PRs or modifying the codebase.

---

## 1. Core Philosophy & Inviolable Constraints

1. **Zero Cloud Dependencies & 100% Privacy**:
   - **No external CDNs, hosted fonts, analytics, or telemetry.** The app must work flawlessly with the WAN cable unplugged or in an air-gapped homelab.
   - **No hosted AI APIs** (no OpenAI, Anthropic, or cloud endpoints). All machine intelligence is powered by local Ollama instances or deterministic offline algorithms.
   - **No npm build steps.** All frontend code is standard vanilla HTML5, CSS3, and native ES modules (`<script type="module">`).

2. **Single-User / Household Multi-Profile Design**:
   - Profiles are isolated at the database level (`profile_id`). Every record (meals, weights, photos, workouts, equipment) belongs to an active profile.
   - Cross-profile data leakage is treated as a security bug.

---

## 2. Python / Backend Architecture Invariants

1. **Sync `def` vs. `async def` Route Handlers**:
   - **Endpoints that touch SQLite MUST be declared `def`, NOT `async def`.** FastAPI executes synchronous `def` endpoints in a threadpool so the blocking `sqlite3` driver never stalls the asyncio event loop.
   - Only genuinely I/O-bound endpoints (such as Ollama HTTP requests) should be declared `async def`.
   - **Invariant:** No `await` expression may appear lexically inside a `with get_conn()` block anywhere in `app/`. Extract your data from SQLite, close the connection, and then `await` external calls outside the block.

2. **Ollama and Reasoning ("Thinking") Models**:
   - Modern multimodal models (e.g. `gemma4:12b`, `deepseek-r1`) often feature reasoning channels. If prompted without constraints, they can consume their entire token budget inside `thinking` tokens and return an empty `content` string.
   - Always send `"think": False` in `/api/chat` requests to suppress this behavior (with an automatic fallback in case older Ollama builds reject the parameter).

3. **Timezone & Date Windows**:
   - Do NOT use SQLite's `date('now')` or `datetime('now')` directly in queries. `date('now')` resolves in UTC, while daily macro totals and workouts must align with the user's local day boundary (`config.TZ`).
   - Always resolve timestamps via `config.now()` in Python and pass explicit ISO formatted dates to SQL queries.
   - On Windows, `zoneinfo` depends on the `tzdata` package (included in `requirements.txt`).

4. **Specific Exception Handling**:
   - Avoid bare `except: pass` or unlogged `except Exception: pass`. Catch specific errors (`httpx.HTTPError`, `json.JSONDecodeError`, `OSError`) and log warnings using `log.warning(...)` so operational failures remain visible in container logs.

---

## 3. Frontend Architecture Invariants

1. **DOM Safety & Dynamic Escaping**:
   - Always sanitize dynamic or model-generated strings using `esc()` before interpolating them into `innerHTML`.
   - For markdown parsing (e.g., `renderSimpleMarkdown`), sanitize the text with `esc()` *before* applying regex transformations to prevent XSS while rendering formatting cleanly.

2. **Service Worker Cache Invalidation**:
   - Do not hand-bump cache version numbers. `app/main.py` dynamically injects a `__BUILD_ID__` hash derived from the file size and mtime of all static files into `static/sw.js`. Editing any static asset automatically invalidates the cache on the next client load.

---

## 4. Deployment & Networking Landmines

1. **Container &rarr; Host Ollama Networking**:
   - Inside a Docker container, `localhost` refers to the container, not the host machine.
   - Use `http://host.docker.internal:11434` along with `extra_hosts: ["host.docker.internal:host-gateway"]` in `docker-compose.yml`.
   - If Ollama is running on a different LAN machine, ensure it listens externally with `OLLAMA_HOST=0.0.0.0`.

2. **Phone Camera & HTTPS Requirement**:
   - Mobile browsers (iOS Safari and Android Chrome) strictly require a **Secure Context** (`https://` or `localhost`) to access the camera API (`navigator.mediaDevices.getUserMedia`).
   - **Recommended:** Use **Tailscale** (`tailscale serve --bg --https=443 http://localhost:8000`). It provides automatic, trusted Let's Encrypt certificates without opening firewall ports, enabling both camera access and home-screen PWA installation.
   - For offline local networks, `nginx.conf` and `docker-compose.yml` provide a built-in proxy with auto-generated self-signed certificates on port `8443`.

3. **Docker Healthchecks**:
   - Use the lightweight `/api/health/live` probe for Docker `HEALTHCHECK` commands. It checks only that the web server process and SQLite are responsive.
   - Do not point container healthchecks at `/api/health`, which queries Ollama with a 10-second timeout and could cause container restarts if an optional model server is slow to respond.

4. **Container Volume Permissions**:
   - The production container runs as non-root user `tracker` (UID 1000). Ensure the mounted storage directory on the host is writable:
     ```bash
     sudo chown -R 1000:1000 ./storage/fitness_tracker
     ```

5. **Shared-Secret Access Gate (`APP_PASSWORD`)**:
   - When running on a shared household network or exposed across Tailscale, set `APP_PASSWORD=your_secret_password` in `.env`.
   - When set, all unauthenticated requests return 401 (or redirect to `/login`), and authentication is maintained via a constant-time HMAC-signed session cookie.
   - When unset, auth is completely disabled for zero-friction local development.

6. **Production Deployment Target Invariant (Homelab Linux VM, Never Windows)**:
   - **Production deployment MUST ALWAYS target the homelab Linux VM (`100.103.11.109`), NEVER the local Windows machine.**
   - The local Windows workstation serves strictly as the development environment and GPU inference worker (providing Ollama via `extra_hosts: [gpu-worker:100.102.124.29]`).
   - The user and household members access the live application from phones and mobile devices via **`https://100.103.11.109/`**.
   - Standard deployment procedure:
     ```bash
     # 1. Sync updated code and assets to the homelab VM
     scp -r app static requirements.txt eric-mcneel@100.103.11.109:~/fitness-tracker/

     # 2. Set permissions, rebuild, and restart the tracker container
     ssh eric-mcneel@100.103.11.109 "chmod -R a+rX ~/fitness-tracker/app ~/fitness-tracker/static && cd ~/fitness-tracker && docker compose build tracker && docker compose up -d tracker"
     ```
