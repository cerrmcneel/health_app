"""FastAPI entrypoint for LocalPulse: self-hosted health and fitness tracker.

Route style note: endpoints that only touch SQLite are declared `def`, not
`async def`, so FastAPI runs them in a threadpool and the blocking sqlite3 driver
never stalls the event loop. Only the Ollama call -- the genuinely slow, I/O-bound
one -- is `async def`, which is where the async win actually is.
"""
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import auth, config
from app.db import init_db
from app.routers import backup, knowledge, meals, photos, profiles, stats, weights, workouts
from app.services import images

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tracker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    init_db()
    purged = images.purge_pending()
    log.info("storage=%s db=%s tz=%s", config.STORAGE_DIR, config.DB_PATH, config.TZ)
    log.info("ollama=%s model=%s", config.OLLAMA_URL, config.VISION_MODEL)
    if purged:
        log.info("purged %d stale pending image(s)", purged)
    yield


app = FastAPI(title="LocalPulse", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if not auth.is_auth_enabled():
        return await call_next(request)

    path = request.url.path
    # Exempt routes: login, logout, static files, sw, manifest, liveness probe
    if (
        path in ("/login", "/logout", "/sw.js", "/manifest.webmanifest", "/api/health/live")
        or path.startswith("/static/")
    ):
        return await call_next(request)

    cookie = request.cookies.get(auth.COOKIE_NAME)
    if not auth.verify_session(cookie):
        accept = request.headers.get("accept", "")
        if path.startswith("/api/") or "application/json" in accept:
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
        return RedirectResponse(f"/login?next={path}", status_code=303)

    return await call_next(request)


app.include_router(auth.router)
app.include_router(meals.router)
app.include_router(photos.router)
app.include_router(stats.router)
app.include_router(profiles.router)
app.include_router(weights.router)
app.include_router(knowledge.router)
app.include_router(workouts.router)
app.include_router(backup.router)


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal error. Check server logs."})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/log", include_in_schema=False)
def log_page():
    return FileResponse(config.STATIC_DIR / "log.html", headers={"Cache-Control": "no-cache"})


@app.get("/capture", include_in_schema=False)
def capture_page():
    return FileResponse(config.STATIC_DIR / "capture.html", headers={"Cache-Control": "no-cache"})


@app.get("/progress", include_in_schema=False)
def progress_page():
    return FileResponse(config.STATIC_DIR / "progress.html", headers={"Cache-Control": "no-cache"})


@app.get("/workout", include_in_schema=False)
@app.get("/workouts", include_in_schema=False)
def workout_page():
    return FileResponse(config.STATIC_DIR / "workout.html", headers={"Cache-Control": "no-cache"})


def _build_id() -> str:
    """Short hash of every static file's size and mtime.

    The service worker keys its cache on this, so editing any asset changes the
    cache name and installed clients pick the change up on their next visit.
    Relying on a hand-bumped constant meant a forgotten bump shipped stale JS
    against fresh HTML, which is exactly the kind of breakage nobody reproduces.
    """
    digest = hashlib.sha256()
    for path in sorted(config.STATIC_DIR.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest.update(path.name.encode())
            digest.update(str(stat.st_size).encode())
            digest.update(str(int(stat.st_mtime)).encode())
    return digest.hexdigest()[:12]


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Served from the root so the worker's scope covers the whole app.

    At /static/js/sw.js its scope would be limited to /static/js/, and it could
    not control the pages or intercept the share target.
    """
    source = (config.STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    return Response(
        content=source.replace("__BUILD_ID__", _build_id()),
        media_type="application/javascript",
        # The worker is the update mechanism for everything else, so it must
        # never be served from the HTTP cache.
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(
        config.STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.post("/share-target", include_in_schema=False)
def share_target():
    """Fallback for a share that arrives before the service worker is active.

    Normally the worker intercepts this POST and keeps the file; if it does not,
    send the user to the logger rather than showing them a bare 404.
    """
    return RedirectResponse("/log", status_code=303)


class RevalidatingStaticFiles(StaticFiles):
    """Static assets that must be revalidated rather than assumed fresh.

    Starlette sends ETag and Last-Modified but no Cache-Control, so browsers fall
    back to heuristic freshness and can serve a cached module for hours. The
    service worker's build-id versioning cannot help: the HTTP cache sits
    underneath it, so a client that already holds stale JS never asks for the new
    file. `no-cache` still allows a conditional request, so the common case is a
    cheap 304, not a re-download.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


# Mounted last so it cannot shadow the API routes above.
app.mount("/static", RevalidatingStaticFiles(directory=config.STATIC_DIR), name="static")


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
