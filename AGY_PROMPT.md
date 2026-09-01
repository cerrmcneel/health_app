You are taking over a finished, working application and deploying it to a homelab.

## First, read these, in this order

1. `HANDOFF.md` — written specifically for you. Current state, landmines, your mission.
2. `README.md` — architecture, API table, schema, design rationale.

Do not skip them. They document failures that were already hit and solved; you
will waste hours rediscovering them.

## What this is

A private, self-hosted calorie and body-progress tracker: photograph a meal and a
local Ollama vision model estimates the macros; photograph yourself daily with the
previous shot ghosted over the live viewfinder for alignment. FastAPI + SQLite +
vanilla-JS PWA + Ollama. It is built, tested, and verified end-to-end against a
live model.

## Hard constraints

- **Do not rewrite or restructure the app.** It works. Your job is deployment plus
  the follow-ups in HANDOFF.md §6. If you believe something needs restructuring,
  say so and wait — do not just do it.
- **Never add a cloud dependency.** No hosted AI APIs, no CDNs, no external fonts,
  no analytics, no telemetry. The app must work with the WAN cable unplugged.
  This constraint is the entire point of the project.
- **Do not commit `.env`** or any certificate/key material.
- Match the existing code style. Comments explain *why*, not *what*.
- Do not make database routes `async def` — they are sync on purpose so FastAPI
  threadpools them. Only the Ollama call is async.
- Do not remove `"think": False` from `app/services/vision.py`. Without it every
  photo fails silently.

## Before you touch anything, ask me these five questions

1. Which machine is the deploy target — this Windows box, or a separate Linux
   host? Hostname or IP?
2. Does Ollama run on that same machine, or should the app call back to the
   Windows box? (A 12B vision model needs real GPU/RAM.)
3. Is Tailscale available? This decides whether I get a trusted certificate.
   Explain the tradeoff before I answer: self-signed gives the camera but the app
   will **not** install to my home screen, because browsers refuse to register a
   service worker over an untrusted cert. Tailscale gives camera + installable
   app + off-LAN access with no port forwarding.
4. What storage path on the target should hold the database and photos, and is it
   backed up?
5. Which vision model should production use?

Wait for my answers. Do not guess these.

## Then deploy

`Dockerfile`, `.dockerignore` and `docker-compose.yml` already exist and are
verified — the image builds, runs, and reaches host Ollama. Start there rather
than writing your own.

```bash
git init && git add -A && git commit -m "Initial commit"
docker compose up -d --build
curl -s http://localhost:8000/api/health
```

Require `"ollama": "ok"` and `"model_ready": true` before going further.

Then put TLS in front of it. I already run nginx containers on ports 8082 and
8086 — extending an existing proxy is cleaner than adding another.

**Wipe the demo data before this becomes my real database.** It currently holds
31 seeded fake meals and 11 synthetic progress photos: `rm -rf storage/fitness_tracker`
(the schema recreates itself on next start).

## Definition of done

Nothing counts until these pass on my actual phone, not on localhost:

- [ ] Loads over HTTPS from the phone
- [ ] Offers "Install" / "Add to Home Screen" and launches with no browser chrome
- [ ] Capture page opens the camera and shows the ghost overlay
- [ ] A capture lands at `{pose}/YYYY-MM-DD_{pose}.jpg` on the host
- [ ] A real meal photo returns sane macros in about a minute
- [ ] Sharing a photo from the gallery opens the logger with it (Android)
- [ ] Data survives `docker compose restart`
- [ ] It comes back automatically after a host reboot

## How to work

Report what you actually did and what you verified, separately from what you
assumed. If a step fails, show me the real error rather than working around it
quietly. If something in the codebase looks wrong, raise it before changing it —
the design decisions are deliberate and explained in README.md.
