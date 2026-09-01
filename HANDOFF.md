# Handoff — Fitness Tracker

You are taking over a **finished, working application** and getting it deployed to
a homelab. This document is self-contained; read it before touching anything.

**Do not rewrite the app.** It is built, tested, and verified end-to-end against a
live model. Your job is deployment plus the small follow-ups in §6. If you think
something needs restructuring, say so before doing it.

---

## 1. What this is

A private, self-hosted calorie and body-progress tracker for mobile browser use.
Two features:

1. **Photo calorie counter** — photograph a meal → a local Ollama vision model
   estimates items and macros → user edits an on-screen card → saved to SQLite.
2. **Ghost-overlay progress photos** — the previous shot for each pose is overlaid
   semi-transparently on the live viewfinder so today's framing matches yesterday's.

Stack: FastAPI + SQLite (WAL) + vanilla JS PWA + Ollama. No external APIs, no
accounts, no subscriptions. That constraint is the whole point of the project —
**do not introduce a cloud dependency, CDN, telemetry, or hosted AI API.**

Read `README.md` for architecture, the full API table, and schema.

---

## 2. Current state — verified working

Everything below was tested, not assumed:

- Live inference against Ollama returning correct schema-constrained JSON
- Full photo → analyze → edit → save flow driven through the real UI
- Ghost overlay compositing + capture → upload → 1080×1440 JPEG on disk
- Path-traversal guard on `/media` (`../`, absolute, Windows separators)
- 14-endpoint API smoke suite; all JS `node --check` clean; Python compiles
- PWA: service worker registers at root scope, 13 shell entries cached, API
  responses correctly excluded from cache
- Android share-target: POST intercepted → file stashed → redirect → logger
  consumes it and starts analysis
- **Docker image builds and runs, and reaches host Ollama** via
  `host.docker.internal` (see §4.1)

### Not yet verified — you must confirm these on real hardware

- Camera capture on an actual phone (needs HTTPS; see §4.2)
- PWA install to home screen on iOS and Android
- Android share-target with a real share sheet (the mechanism is tested, the
  OS integration is not)
- Estimate accuracy against a kitchen scale

---

## 3. Environment facts

| Thing | Value |
|---|---|
| Project root | `C:\Users\PC GAMING\projects\Health_App` |
| Dev box | Windows 11 Pro, Python 3.13.2 |
| Ollama | Running, reachable at `http://localhost:11434` |
| Installed vision model | **`gemma4:12b` only** |
| Other installed models | `deepseek-r1:14b`, `devstral:24b`, `qwen3-coder:30b` (none vision-capable) |
| Dev port | 8077 (port 8000 was occupied by an unrelated python process) |
| Git | **Not a repo yet.** `git init` before deploying. |
| Docker | v29.7.2 available; user already runs containers (nginx on 8082, 8086) |

`.env` is gitignored. `.env.example` is the template.

### Demo data — wipe before production

The database currently holds **31 seeded demo meals and 11 synthetic progress
photos** used to exercise the UI. It is all fake. Before going live:

```bash
rm -rf storage/fitness_tracker
```

The schema recreates itself on next start.

---

## 4. Landmines

These will cost you hours if you rediscover them the hard way.

### 4.1 Container → host Ollama

A container's `localhost` is not the host. `OLLAMA_URL=http://localhost:11434`
inside a container fails. Use `http://host.docker.internal:11434` **plus** the
`extra_hosts: host.docker.internal:host-gateway` mapping — required on Linux,
harmless on Docker Desktop. Both are already set in `docker-compose.yml` and
verified working.

If Ollama runs on a *different* machine from the app, set `OLLAMA_URL` to that
host and make sure Ollama listens beyond loopback (`OLLAMA_HOST=0.0.0.0`).

### 4.2 The camera needs HTTPS — and so does the PWA

`getUserMedia` and service workers require a **secure context**: `https://` or
`localhost`. Browsing to `http://192.168.1.x:8000` from a phone loads the app but
the camera will not open and the app will not install. The capture page detects
this and shows an explanation rather than failing silently.

A **self-signed cert is not enough for the PWA.** Browsers refuse to register a
service worker over an untrusted certificate, so with self-signed you get the
camera but not home-screen install.

**Recommended: Tailscale.** `tailscale cert <host>.<tailnet>.ts.net` issues a real
Let's Encrypt certificate, which gives camera + PWA install + remote access off
the LAN, with no port forwarding. This is the single highest-value deployment
decision — see §5.

`make_cert.py` generates a self-signed cert as a fallback for LAN-only use.

### 4.3 Thinking models return empty content

Reasoning models (`gemma4`, `deepseek-r1`, `qwen3`) spend their entire token
budget in `message.thinking` and return `content: ''`. `app/services/vision.py`
sends `think: false` to suppress this, with automatic fallback for models that
reject the field. **Do not remove it.** Without it, every single photo fails.

### 4.4 Timezone decides the day boundary

`TZ` in `.env` determines which day a late-night meal lands on. Set it on the
deploy target; a container defaults to UTC.

### 4.5 Volume permissions

The image runs as uid 1000 (`tracker`). The host storage directory must be
writable by that uid:

```bash
sudo chown -R 1000:1000 /path/to/storage
```

### 4.6 Model choice on the deploy host

`gemma4:12b` needs meaningful GPU/RAM. If the homelab box is weaker than the dev
machine, either point `OLLAMA_URL` back at the strong machine, or pull a smaller
vision model (`qwen2.5-vl:7b`) and set `VISION_MODEL`. Verify with
`GET /api/health` — `model_ready: true` means installed *and* vision-capable.

---

## 5. Your mission

### Step 1 — Ask the user these first. Do not guess.

1. **Which machine is the homelab target?** This Windows box, or a separate
   Linux host? Hostname / IP?
2. **Does Ollama run on that same machine**, or should the app call back to the
   Windows box? (Drives §4.6.)
3. **Is Tailscale available?** Determines whether they get a real certificate
   (camera + installable app) or self-signed (camera only). Strongly recommend
   Tailscale; explain the tradeoff from §4.2.
4. **Storage path** on the target for the DB + photos, and whether it is backed up.
5. **Production `VISION_MODEL`.**

### Step 2 — Deploy

`Dockerfile`, `.dockerignore` and `docker-compose.yml` exist and are verified.
Preferred path:

```bash
git init && git add -A && git commit -m "Initial commit"
docker compose up -d --build
curl -s http://localhost:8000/api/health
```

Confirm `"ollama": "ok"` and `"model_ready": true`.

Then put TLS in front of it. If they already run a reverse proxy (nginx is on
8082/8086), extending it is cleaner than adding another. Otherwise Caddy with a
Tailscale cert is the least-effort route.

### Step 3 — Verify on a real phone

This is the acceptance test. Nothing counts until these pass:

- [ ] App loads over HTTPS from the phone
- [ ] "Add to Home Screen" / "Install" is offered, and launches with no browser chrome
- [ ] Capture page opens the camera and shows the ghost overlay
- [ ] A captured photo lands at `{pose}/YYYY-MM-DD_{pose}.jpg` on the host
- [ ] Photographing a real meal returns sane macros within ~60s
- [ ] Sharing a photo from the gallery into the app opens the logger with it (Android)
- [ ] Data survives `docker compose restart`

### Step 4 — Operational basics

- Backup for the storage directory (DB + all photos, no cloud copy exists)
- Confirm `restart: unless-stopped` brings it back after a reboot
- Consider pre-warming the model (`ollama run <model> ""` on a timer) so the
  first photo of the day is not a cold load

---

## 6. Remaining build work (only after deployment works)

Ranked. None are blockers.

1. **Body-weight logging** — a `weight` table plus a trend line on the dashboard.
   The most requested thing missing; pairs naturally with progress photos.
2. **Barcode / packaged foods** — the vision model is poor at packaged items.
   A local OpenFoodFacts dump would beat inference for anything with a barcode.
3. **Meal reuse** — "log this again" from history. Most meals repeat; this would
   cut daily interaction more than any model improvement.
4. **Edit a saved meal** — `PATCH /api/meals/{id}` exists and is tested, but no
   UI reaches it. Currently users delete and re-add.
5. **Prompt tuning** — after comparing ~10 estimates against a kitchen scale,
   adjust the density and portion heuristics in `SYSTEM_PROMPT`.
6. **Export** — CSV/JSON dump for data portability.

---

## 7. Conventions

- Match the existing style; do not reformat working files.
- Comments explain *why*, not *what*. The codebase has a deliberate density —
  match it rather than stripping or padding.
- DB-only endpoints are sync `def` (FastAPI threadpools them); only the Ollama
  call is `async def`. **Do not make DB routes async** — that stalls the event loop.
- Daily totals are the SQL view `v_daily_totals`, never a stored column.
- No CDNs, no external fonts, no analytics. Must work with the WAN unplugged.
- Frontend is dependency-free vanilla ES modules. Keep it that way unless there
  is a concrete reason, agreed with the user.
- Validate and clamp anything from the model before it reaches the DB —
  `vision.normalize()` is the chokepoint.

## 8. If something looks wrong

Report it rather than silently reworking it. The design decisions in §7 were
deliberate and are explained in `README.md`. If you disagree with one, raise it
with the user first.
