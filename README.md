# Self-Hosted Calorie & Body Progress Tracker

A private, mobile-first fitness tracker that runs entirely on your own hardware.
No accounts, no external APIs, no subscriptions. Two features:

1. **Photo calorie counter** — photograph a meal, a local vision model estimates
   items and macros, you correct anything wrong before it is saved.
2. **Ghost-overlay progress photos** — the previous shot for each pose is
   overlaid on the live viewfinder so today's photo matches yesterday's framing.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then edit VISION_MODEL to a model you have
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>.

Check that the model is wired up correctly before relying on it:

```bash
curl -s localhost:8000/api/health
```

`model_ready: true` means Ollama is reachable and the configured model can
actually process images. If it is false, the response carries a `hint` naming
the problem, and every page shows a banner instead of failing silently later.

### Picking a vision model

The model must be **vision-capable**. List what you have:

```bash
curl -s localhost:11434/api/tags
```

Look for `"vision"` in a model's `capabilities`. If nothing qualifies:

```bash
ollama pull qwen2.5-vl:7b
```

Then set `VISION_MODEL=qwen2.5-vl:7b` in `.env`.

> **Thinking models.** Reasoning models (gemma4, deepseek-r1, qwen3) spend their
> whole token budget in a `thinking` field and return empty content. The client
> sends `think: false` to suppress that. It falls back automatically for models
> that reject the field.

---

## The HTTPS requirement (read this before using the camera on your phone)

`getUserMedia` is only exposed on a **secure context**: `https://` or
`localhost`. Browsing to `http://192.168.1.50:8000` from your phone will load
the app fine but the camera will not open — the capture page detects this and
tells you so rather than failing mysteriously.

Pick one:

**A. Self-signed certificate** (simplest)

```bash
pip install cryptography
python make_cert.py 192.168.1.50          # your homelab's LAN IP
python -m uvicorn app.main:app --host 0.0.0.0 --port 8443 \
    --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
```

Open `https://192.168.1.50:8443` and accept the warning once per device.

**B. Tailscale / WireGuard** — reach the box over a `*.ts.net` hostname, which
gets a real certificate. Best option if you already run either.

**C. Reverse proxy** — Caddy or nginx terminating TLS in front of uvicorn.

Photo *calorie* logging works fine over plain HTTP; only the live viewfinder
needs the secure context.

---

## Installing it as an app (no browser)

The app is a PWA, so it installs to the phone's home screen and launches
standalone — its own icon, its own app-switcher entry, no address bar.

- **Android/Chrome:** menu → "Install app" (or the prompt that appears).
- **iOS/Safari:** Share → "Add to Home Screen".

Long-pressing the installed icon exposes shortcuts straight to **Log a meal** and
**Progress photo**.

**On Android you can skip the app entirely for meal logging.** The app registers
as a share target, so: shoot the meal with your normal camera app → Share →
Tracker → the estimate is already running when the screen opens.

### This needs a *trusted* certificate

Install requires a secure context, and browsers refuse to register a service
worker over a **self-signed** certificate. So:

| Setup | Camera | Installable |
|---|---|---|
| `http://` over LAN IP | No | No |
| Self-signed cert (`make_cert.py`) | Yes | No |
| Tailscale / real cert | Yes | Yes |

`tailscale cert <host>.<tailnet>.ts.net` issues a real Let's Encrypt certificate,
which gets you camera, home-screen install, and access from outside the LAN
without forwarding a port.

---

## Running it as a Windows service (starts with Windows)

The app runs from a virtual environment invoked by absolute path, so nothing has
to be activated and no terminal stays open.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File install_autostart.ps1
```

That registers a `FitnessTracker` scheduled task which:

- starts at logon after a 20s delay (so Ollama and Docker settle first),
- runs `pythonw.exe`, so there is no console window,
- restarts up to 3 times, a minute apart, if it dies,
- never times out (`ExecutionTimeLimit` is disabled for long-running services).

| Action | Command |
|---|---|
| Check | `Invoke-RestMethod http://localhost:8010/api/health \| Format-List` |
| Logs | `Get-Content logs	racker.log -Tail 40 -Wait` |
| Stop | `Stop-ScheduledTask -TaskName FitnessTracker` |
| Start | `Start-ScheduledTask -TaskName FitnessTracker` |
| Remove | `powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Uninstall` |

`pythonw.exe` has no console, so a traceback has nowhere to go. Everything is
logged to `logs/tracker.log` (rotated, 5 x 2 MB), and a failure that happens
before logging is configured is written to `logs/crash.log`.

To start before any user logs in, run an **elevated** PowerShell and pass
`-Trigger AtStartup`; the task then runs as SYSTEM. Note that Ollama itself
starts from a per-user startup entry on this machine, so photo analysis only
becomes available after logon either way.

### Serving HTTPS

Set `SSL_CERTFILE` and `SSL_KEYFILE` in `.env` and the service serves TLS
directly. With Tailscale already installed, the least-effort option is to let it
terminate TLS and manage renewal for you:

```powershell
tailscale serve --bg --https=443 http://localhost:8010
```

The app is then reachable at `https://<machine>.<tailnet>.ts.net` with a real
certificate — which is what the camera and home-screen install both require.

---

## Deployment

See `Dockerfile` and `docker-compose.yml`; `HANDOFF.md` covers the details.

---

## Layout

```
Health_App/
├── app/
│   ├── main.py            FastAPI app, page routes, lifespan startup
│   ├── config.py          .env loading, paths, timezone
│   ├── db.py              SQLite connection + schema (WAL, foreign keys)
│   ├── models.py          Pydantic request/response models
│   ├── routers/
│   │   ├── meals.py       /api/analyze, /api/meals CRUD
│   │   ├── photos.py      /api/photos, ghost lookup, /media serving
│   │   └── stats.py       daily + range totals, settings, health
│   └── services/
│       ├── vision.py      Ollama client, system prompt, JSON schema
│       └── images.py      EXIF rotation, downscaling, disk layout
├── static/
│   ├── index.html         dashboard      log.html      meal logger
│   ├── capture.html       ghost camera   progress.html photo history
│   ├── css/app.css
│   └── js/{api,dashboard,log,capture,progress}.js
├── storage/fitness_tracker/     ← STORAGE_DIR
│   ├── front/YYYY-MM-DD_front.jpg
│   ├── profile/YYYY-MM-DD_profile.jpg
│   ├── meals/YYYY/MM/*.jpg
│   ├── _pending/                analysed but not yet confirmed
│   └── tracker.db
└── make_cert.py
```

Set `STORAGE_DIR=/storage/fitness_tracker` in `.env` on a Linux homelab to get
the exact folder convention there.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/analyze` | Meal photo → macro estimate. **Writes nothing.** Returns a `pending_image` token. |
| `POST` | `/api/meals` | Commit a reviewed meal; claims the pending photo. |
| `GET` | `/api/meals?day=` | Meals for a day (default today). |
| `GET` | `/api/meals/{id}` | One meal with items and totals. |
| `PATCH` | `/api/meals/{id}` | Edit fields; supplying `items` replaces the list. |
| `DELETE` | `/api/meals/{id}` | Remove a meal (the photo on disk is kept). |
| `GET` | `/api/stats/daily?day=` | Totals, targets, remaining. |
| `GET` | `/api/stats/range?days=` | Dense day-by-day series (gaps as zeros). |
| `GET`/`PUT` | `/api/settings` | Daily macro targets. |
| `GET` | `/api/photos/ghost?pose=` | Most recent photo for a pose, **excluding today**. |
| `GET` | `/api/photos/status` | Which poses are done today. |
| `GET` | `/api/photos?pose=&limit=` | Photo history. |
| `POST` | `/api/photos` | Save a capture; upserts on `(day, pose)`. |
| `GET` | `/media/{path}` | Serve a stored image (traversal-guarded). |
| `GET` | `/api/health` | Ollama reachability + model capability. |

Interactive docs at `/docs`.

### Why analyse and log are separate calls

`/api/analyze` is deliberately read-only. The model is an estimator, not an
oracle — separating the calls guarantees you always get an editable card before
anything reaches the database. The photo waits in `_pending/` and is claimed by
token on confirm; unconfirmed images are purged after 24h at startup.

---

## Schema

```
meals(id, day, logged_at, name, meal_type, source, image_path, model, notes, raw_json)
meal_items(id, meal_id→meals, name, grams, calories, protein_g, carbs_g, fat_g, confidence, position)
progress_photos(id, day, taken_at, pose, path, width, height, bytes)   UNIQUE(day, pose)
settings(id=1, calorie_target, protein_target, carbs_target, fat_target)
v_daily_totals  -- VIEW: per-day sums
```

Two deliberate choices:

- **Daily totals are a view, not a table.** Storing them would let an edited meal
  drift out of sync with the day's headline number. SQLite aggregates a few
  thousand rows instantly; there is nothing to gain by caching it.
- **`raw_json` keeps the model's unedited output.** When an estimate looks wrong
  months later you can see what the model actually said versus what you changed.

---

## How the estimate is made reliable

Local vision models are enthusiastic and imprecise. Four things constrain them:

1. **A JSON Schema passed as Ollama's `format`.** Decoding is constrained to the
   schema, so no code-fence scraping. Without it the model invents its own shape.
2. **A procedural system prompt.** It forces the model to scale the scene against
   a known reference object (plate, fork, can) *before* estimating volume, then
   convert volume to mass by density. Each item reports the reference it used in
   `basis`, which is shown in the UI — an estimate you can audit beats a number
   you cannot.
3. **Server-side arithmetic enforcement.** If stated calories disagree with
   `4P + 4C + 9F` by more than 15%, the macros win. They are estimated
   per-component; the calorie figure tends to be recalled wholesale.
4. **A mandatory human review step.** Nothing is saved until you confirm it.

Editing any macro in the review card re-derives that item's calories live.
Editing the calorie field directly is left alone, since you may be copying a
label value.

The prompt lives in `SYSTEM_PROMPT` in [`app/services/vision.py`](app/services/vision.py).
Tune the density and portion heuristics there to your own cooking.

---

## Ghost overlay: the alignment contract

The live video, the ghost image, and the saved JPEG are all full camera frames
of the same aspect ratio, rendered with `object-fit: cover`. Because every layer
is cropped identically, whatever lines up on screen lines up in the stored file
— so tomorrow's ghost is a faithful reference.

- The ghost excludes **today's** shot, so re-taking a pose aligns against your
  last session rather than the attempt you are replacing.
- Opacity is adjustable 0–70% (default 35%).
- With no prior photo for a pose, a rule-of-thirds grid is the alignment aid.
- Front → profile advances automatically; a self-timer (0/3/10s) gives you time
  to step back.
- Selfie-camera captures are mirrored to match the preview, so photos do not
  flip between sessions.

---

## Notes

- **Timezone matters.** `TZ` in `.env` decides where the day boundary falls. A
  late-night meal lands on the right day only if this is set correctly.
- **Back up `storage/`.** It holds the database and every photo. There is no
  cloud copy — that is the point.
- **Resetting.** Deleting `storage/fitness_tracker/` wipes everything; the schema
  is recreated on next start.
- **Concurrency.** WAL mode plus a 5s busy timeout is ample for household use.
  Database endpoints are sync `def` so FastAPI runs them in a threadpool; only
  the Ollama call is `async`, which is where the async win actually is.
