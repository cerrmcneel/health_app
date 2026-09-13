# LocalPulse &middot; Self-Hosted, Subscription-Free Health & Fitness Suite

> **LocalPulse is a private, 100% self-hosted health, nutrition, and workout suite for your homelab or local network.**  
> Zero monthly subscriptions. Zero cloud dependencies. Zero telemetry. No accounts or credit cards required.

---

## Why This Exists

Commercial fitness apps have shifted almost entirely to aggressive monthly paywalls and locked-down cloud silos:
- **MyFitnessPal & LoseIt** charge \$20–\$80/year for basic macro breakdown and barcode/meal logging.
- **MacroFactor** charges \$12/month for sports nutrition rationale and expenditure algorithms.
- **Happy Scale & TrendWeight** charge subscriptions for moving average weight trendlines.
- **Fitbod, Caliverse & Freeletics** charge \$80–\$120/year for equipment-tailored workout routines.
- **Progress photo apps** charge subscriptions to store and compare photos in their cloud.

**LocalPulse replaces all of them.** It runs completely on your own hardware — a Raspberry Pi, mini-PC, TrueNAS, Unraid, Proxmox VM, or regular desktop PC. Your personal health data, weigh-ins, photos, and training logs never leave your home network.

---

## Core Features

### 🥗 1. Meal & Macro Tracking (Replaces MyFitnessPal)
- **Local AI Vision Estimation**: Snap a photo of your meal; a local vision model (e.g. Gemma 4, Qwen2.5-VL via Ollama) estimates ingredients, portions, and macros without cloud APIs.
- **Instant Manual Logging**: Fast manual meal and snack logging with diacritics-normalized English & Spanish keyword matching and automatic visual badges for 15+ food categories (poultry, beef, fish, eggs, rice, pasta, dairy, veggies, fruit, etc.).
- **Daily Totals & Goals**: Dynamic calorie and macro progress bars (Protein, Carbs, Fat) with real-time remaining calorie readouts.

### 💡 2. Sports Nutrition Rationale & Q&A (Replaces MacroFactor)
- **Evidence-Based Energy Balance**: Dynamic analysis explaining your caloric deficit/surplus math, fat loss rates, and metabolic realities.
- **Interactive Nutrition Q&A**: Tap quick chips (e.g., *"Why 2g/kg protein?"*, *"Can I lower carbs?"*, *"Why not zero fat?"*) or ask custom nutrition questions answered by sports science literature and your local model.

### 🏋️ 3. Equipment Arsenal & Tailored Workout Studio (Replaces Fitbod / Caliverse)
- **Dynamic Equipment Inventory**: Manage your available gear (Yoga Mat, Jump Rope, Pull-up Bar, Resistance Bands, Dumbbells, Kettlebell, Bench, Barbell, Dip Station, Ab Wheel, etc.) or add custom equipment.
- **Strictly-Constrained Routine Designer**: Generates balanced workout routines (Full Body, HIIT & Cardio, Upper Body, Lower Body, Core & Mobility) from a 70+ exercise catalog. **Never prescribes exercises requiring gear you do not own.**
- **Interactive Workout Player**: Real-time circuit tracking with checkable sets (`Set 1`, `Set 2`, `Set 3`).
- **Built-in Interval & Rest Timer**: High-visibility digital countdown (`00:45`) with presets (`+15s`, `+30s`, `45s`, `60s`, `90s`) and an offline two-tone chime synthesized via the browser's native Web Audio API (zero external audio files).
- **Workout History**: Logs completed sessions with duration, category, and equipment used.

### 📸 4. Ghost-Overlay Camera & Alignment Comparison Studio
- **Ghost-Overlay Viewfinder**: Overlays your previous session's photo semi-transparently over the live camera so today's framing, distance, and pose match yesterday's.
- **Multi-Pose Progression**: Standard Front and Profile capture with an **optional Back photo** that can be toggled on/off on the fly right from the camera or Progress Studio.
- **Interactive Alignment & Comparison**: Side-by-side Before/After split slider defaulting to earliest vs. latest photo for each pose.
- **Precision Nudge & Auto-Centering**: Drag-to-pan, 4-way 2px nudge buttons, zoom scaling (70%–140%), and an **Auto-Align** algorithm that calculates subject centroids to center photos automatically. Alignment offsets persist per photo.

### 📈 5. Body Weight Progress & Trend Smoothing (Replaces Happy Scale)
- **Interactive SVG Weight Graph**: Filter by `14D`, `30D`, `90D`, or `All`.
- **7-Day Trailing Moving Average**: Automatically smooths out water weight and sodium fluctuations so you see your true trend rate.
- **Touch & Mouse Crosshair Scrubber**: Inspect individual weigh-in data points and moving average values on hover/drag.

### 👥 6. Multi-Profile Household & Guided Setup Wizard
- Switch between different members of your household with one tap.
- **Guided Setup Interview**: Step-by-step onboarding deriving scientific BMR (Mifflin-St Jeor), TDEE, and ISSN macro recommendations ($1.6 - 2.2\text{ g/kg}$ protein, $\ge 20\%$ fat floor), initial weigh-in, and equipment inventory.
- Each profile maintains completely independent calorie/macro targets, weight history, progress photos, and equipment inventories.

### 📱 7. Mobile-First Progressive Web App (PWA)
- Installable on iOS (Safari: Share &rarr; *Add to Home Screen*) and Android (Chrome: *Install App*).
- Launches fullscreen with standalone icon, app-switcher entry, and no URL bar.
- **Android Share Target**: Share photos directly from your phone's native camera or gallery app straight into the meal logger.
- 100% offline-first static asset caching via Service Worker.

---

## Quick Start (1 Command)

> [!IMPORTANT]
> **Homelab Production Deployment Notice**:
> In this setup, production is deployed strictly to the dedicated **Linux Homelab VM** (`100.103.11.109` / `192.168.1.168`) running Docker Compose behind Nginx at **`https://100.103.11.109/`**. The local Windows workstation serves solely for local development and GPU worker inference (running Ollama), and is **never** used as the production deployment target.

### Option A: Docker Compose (Recommended for Homelabs, TrueNAS, Unraid, Proxmox)

1. Clone the repository:
   ```bash
   git clone https://github.com/cerrmcneel/localpulse.git
   cd localpulse
   ```

2. Start the application:
   ```bash
   docker compose up -d
   ```

3. Open your browser:
   - **Direct HTTP**: <http://localhost:8000> (or `http://<your-server-ip>:8000`)
   - **Local HTTPS**: <https://localhost:8443> (or `https://<your-server-ip>:8443`) &mdash; *auto-generates self-signed TLS cert on first boot so mobile camera works immediately!*

---

### Option B: Native Python (Lightweight / Local Machine)

Requirements: Python 3.11+

```bash
git clone https://github.com/cerrmcneel/localpulse.git
cd localpulse
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Navigate to <http://localhost:8000>.

---

## Is Ollama / a GPU Required?

**NO! Ollama is 100% optional.**

| Feature | Without Ollama (Zero GPU) | With Ollama (Local AI) |
|---|:---:|:---:|
| **Manual Meal & Snack Logging** | &check; Full support | &check; Full support |
| **Food Category Icon Recognition** | &check; Full support (15+ groups) | &check; Full support |
| **Macro & Calorie Daily Dashboards** | &check; Full support | &check; Full support |
| **Weight Tracking & Trendline Graph** | &check; Full support | &check; Full support |
| **Ghost Overlay Camera & Photo Alignment** | &check; Full support | &check; Full support |
| **Equipment Inventory Management** | &check; Full support | &check; Full support |
| **Tailored Workout Generation & Timer** | &check; Full instant deterministic generator | &check; Plus optional AI Coach variations |
| **Multi-Profile Household Management** | &check; Full support | &check; Full support |
| **AI Photo Meal Macro Estimation** | Manual macro entry | &check; Automatic AI volume & macro estimate |
| **Interactive Nutrition AI Q&A** | Static science literature | &check; Interactive LLM reasoning |

If you do not have Ollama or a GPU, the app runs smoothly as a lightweight, lightning-fast tracker. If you do have Ollama, simply point `OLLAMA_URL` in `.env` or `docker-compose.yml` to your instance.

### Setting up Ollama (Optional)

1. Install Ollama from [ollama.com](https://ollama.com). Note: **Gemma 4 requires Ollama 0.22 or newer** for vision support:
   ```bash
   ollama --version   # verify >= 0.22
   ```
2. Pull a vision-capable model:
   ```bash
   ollama pull gemma4:12b
   # or for smaller VRAM cards:
   ollama pull qwen2.5-vl:7b
   ```
3. Set `OLLAMA_URL` in `.env`:
   - Same machine (native): `http://localhost:11434`
   - Same machine (Docker): `http://host.docker.internal:11434`
   - Another machine on LAN: `http://192.168.1.50:11434`
   - Over Tailscale: `http://100.x.y.z:11434`

---

## Adaptable to All Homelab Setups

### 1. Reverse Proxies (Nginx Proxy Manager, Caddy, Traefik, Cloudflare Tunnel)
If you already run a reverse proxy terminating SSL on your homelab, simply point your proxy at the `tracker` service on port `8000`:
- **Forward Host**: `<your-server-ip>`
- **Forward Port**: `8000`
- Enable `Websockets Support` and pass `Host`, `X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto https` headers.

### 2. Tailscale (Recommended Default: Zero Port Forwarding + Free Trusted SSL)
**Do not port-forward this application to the public internet.** The recommended remote access method is Tailscale:
```bash
tailscale serve --bg --https=443 http://localhost:8000
```
This serves the app at `https://<your-device>.<tailnet>.ts.net` with an automatic Let's Encrypt certificate:
1. Access from anywhere outside the home with zero open router/firewall ports.
2. Trusted HTTPS that satisfies iOS and Android camera and PWA install requirements.

### 3. Windows Service (Auto-Start at Boot)
To run natively in the background on a Windows machine:
```powershell
powershell -ExecutionPolicy Bypass -File install_autostart.ps1
```
This registers a scheduled background task that starts automatically with Windows, runs silently in the background without any open console window, and logs to `logs/tracker.log`.

### 4. Optional Shared-Secret Security Gate (`APP_PASSWORD`)
To protect your health records on a shared local network or guest Wi-Fi:
- Set `APP_PASSWORD=your_secure_password` in `.env` or `docker-compose.yml`.
- When set, all requests are gated behind `/login`, returning 401 on unauthorized API access and setting a 30-day constant-time HMAC-signed session cookie upon authentication.
- When unset, auth is completely disabled for zero-friction local usage.

---

## Phone Camera Access (The HTTPS Rule)

Mobile web browsers (iOS Safari, Android Chrome) enforce a strict security policy: **`getUserMedia` (the camera API) is only permitted on a secure context (`https://` or `localhost`).**

If you open `http://192.168.1.x:8000` over plain HTTP on your phone, meal logging and workouts work fine, but the browser blocks camera access.

Choose one of the following to use the live camera:
1. **Tailscale (Recommended)**: Access via `https://<node>.<tailnet>.ts.net`.
2. **Built-in HTTPS Proxy**: Open `https://<your-ip>:8443` (or ports `443` / `80` if free on your host) and accept the local self-signed certificate.
3. **Your Own Reverse Proxy**: Access via your local domain with valid SSL.

---

## Storage & Backups

Everything is stored inside a single directory:
```
storage/fitness_tracker/
├── tracker.db          # SQLite database (WAL mode, foreign keys enabled)
├── front/              # Front progress photos (YYYY-MM-DD_front_*.jpg)
├── profile/            # Profile progress photos (YYYY-MM-DD_profile_*.jpg)
├── back/               # Back progress photos (YYYY-MM-DD_back_*.jpg)
├── meals/              # Captured meal photos (YYYY/MM/*.jpg)
└── _pending/           # Temporary staging for unconfirmed photo analyses
```

### Backing Up & Data Portability
- **One-Click UI Download**: Click **"💾 Download Data (.zip)"** in the profile switcher modal to download a standalone, WAL-consistent ZIP archive containing the active profile's database records and personal media files.
- **REST Endpoint**: `GET /api/backup/export` streams the requesting profile's isolated dataset by default. A full-instance dump (`GET /api/backup/export?scope=all`) requires `APP_PASSWORD` to be configured and the active profile to be the default one, returning 403 Forbidden otherwise. Note that the profile check is a guard rail rather than a security boundary: the active profile is supplied by the client, so any household member who knows the password can reach the full dump. `APP_PASSWORD` is a single shared secret, so this grants nothing they could not already obtain.
> [!WARNING]
> **LAN Data Exposure Notice**: When `APP_PASSWORD` is unset (the default for zero-friction single-user homelab setups), any device or user on your local network can reach `GET /api/backup/export` to download health records and body photos. If your instance is accessible to untrusted LAN devices, guest Wi-Fi, or roommates, configure `APP_PASSWORD` (see [Optional Shared-Secret Security Gate](#4-optional-shared-secret-security-gate-app_password)) or restrict remote access strictly via [Tailscale](#2-tailscale-recommended-default-zero-port-forwarding--free-trusted-ssl).
- **Direct Filesystem Backup**:
  ```bash
  tar -czvf localpulse_backup_$(date +%F).tar.gz storage/
  ```
  To restore, unpack it back into place. That's it!

---

## Technical Architecture

Detailed architectural documentation, concurrency invariants, SQLite WAL mode guidelines, and security models are documented in [**ARCHITECTURE.md**](ARCHITECTURE.md).

---

## Project Structure

```
LocalPulse/
├── .github/workflows/
│   └── docker-publish.yml # Automated multi-arch GHCR container build
├── app/
│   ├── main.py            # FastAPI app setup, page routes, lifecycle hooks
│   ├── auth.py            # Optional APP_PASSWORD shared-secret gate & session signing
│   ├── config.py          # Environment settings, directory resolution, timezone
│   ├── db.py              # SQLite connection, schema migrations, automatic seeding
│   ├── models.py          # Pydantic data schemas
│   ├── data/
│   │   └── exercises.py   # 75-movement exercise library & standard equipment
│   ├── routers/
│   │   ├── backup.py      # Standalone WAL-safe data export & ZIP packager
│   │   ├── meals.py       # Meal logging & Ollama photo analysis
│   │   ├── photos.py      # Progress photo capture, ghost retrieval & media serving
│   │   ├── stats.py       # Macro totals, daily stats & system health
│   │   ├── profiles.py    # Multi-profile CRUD, onboarding & target preferences
│   │   ├── weights.py     # Body weight tracking & moving averages
│   │   ├── knowledge.py   # Nutrition science knowledge & interactive Q&A
│   │   └── workouts.py    # Equipment inventory & strictly constrained routine designer
│   └── services/
│       ├── images.py      # EXIF rotation, thumbnail generation & path security
│       ├── knowledge.py   # Sports nutrition literature extractor & prompt builder
│       ├── targets.py     # Mifflin-St Jeor BMR, TDEE & ISSN macro distribution
│       └── vision.py      # Ollama client, JSON Schema constraints & fallback
├── static/
│   ├── index.html         # Dashboard (calorie ring, macros, today's workout)
│   ├── log.html           # Meal logger (photo analysis + manual entry)
│   ├── workout.html       # Workout Studio (gear inventory, designer, rest timer)
│   ├── progress.html      # Weight graph & photo alignment comparison studio
│   ├── capture.html       # Ghost-overlay camera viewfinder
│   ├── css/app.css        # Mobile-first dark theme CSS (zero external CDNs)
│   └── js/                # Native ES modules (api, dashboard, log, workout, progress, capture)
├── tests/                 # Full automated test suite (pytest)
├── Dockerfile             # Container definition
├── docker-compose.yml     # Universal homelab compose file with auto-cert SSL (ports 80, 443, 8443)
├── ARCHITECTURE.md        # Technical architecture, system map & design invariants
├── CONTRIBUTING.md        # Development guidelines, landmines & testing standards
├── LICENSE                # GNU Affero General Public License v3.0 (AGPL-3.0)
└── README.md              # Documentation
```

---

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for architectural invariants, testing practices, and hard constraints before making changes.

---

## License

Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE) for full text. Built for everyone who values their health and privacy over monthly SaaS subscriptions.
