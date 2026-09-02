"""FastAPI entrypoint for the self-hosted calorie and body progress tracker.

Route style note: endpoints that only touch SQLite are declared `def`, not
`async def`, so FastAPI runs them in a threadpool and the blocking sqlite3 driver
never stalls the event loop. Only the Ollama call -- the genuinely slow, I/O-bound
one -- is `async def`, which is where the async win actually is.
"""
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.db import init_db
from app.routers import meals, photos, profiles, stats, weights
from app.services import images

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tracker")


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_dirs()
    init_db()
    purged = images.purge_pending()
    log.info("storage=%s db=%s tz=%s", config.STORAGE_DIR, config.DB_PATH, config.TZ)
    log.info("ollama=%s model=%s", config.OLLAMA_URL, config.VISION_MODEL)
    if purged:
        log.info("purged %d stale pending image(s)", purged)
    yield


app = FastAPI(title="Fitness Tracker", version="1.0.0", lifespan=lifespan)

app.include_router(meals.router)
app.include_router(photos.router)
app.include_router(stats.router)
app.include_router(profiles.router)
app.include_router(weights.router)


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal error. Check server logs."})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/log", include_in_schema=False)
def log_page():
    return FileResponse(config.STATIC_DIR / "log.html")


@app.get("/capture", include_in_schema=False)
def capture_page():
    return FileResponse(config.STATIC_DIR / "capture.html")


@app.get("/progress", include_in_schema=False)
def progress_page():
    return FileResponse(config.STATIC_DIR / "progress.html")


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


# Mounted last so it cannot shadow the API routes above.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
