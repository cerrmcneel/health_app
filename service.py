r"""Windows service entrypoint: runs the tracker with no console and no activated venv.

Launched by Task Scheduler as:
    <project>\.venv\Scripts\pythonw.exe  <project>\service.py

pythonw.exe has no console, so there is nowhere for a traceback to go -- every
failure path here has to reach a file or it is invisible. Logs land in
logs/tracker.log (rotated), and an early crash that happens before logging is up
is written to logs/crash.log as a last resort.
"""
import logging
import os
import socket
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"


def _write_crash(exc: BaseException) -> None:
    """Last-resort record for a failure that beat the logging setup."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "crash.log").open("a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 70 + "\n")
            fh.write(f"python={sys.executable}\ncwd={os.getcwd()}\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
    except Exception:
        pass  # nothing further can be done without a console


def _port_in_use(port: int) -> bool:
    """True if something is already listening on the port locally."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_DIR / "tracker.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return logging.getLogger("service")


def main() -> int:
    log = _setup_logging()
    try:
        # Run from the project root so relative paths in .env resolve the same
        # way they do when started by hand. Task Scheduler's working directory
        # is not guaranteed.
        os.chdir(BASE_DIR)
        sys.path.insert(0, str(BASE_DIR))

        import uvicorn

        from app import config

        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "8010"))

        # The Task Scheduler watchdog re-launches this every few minutes, and the
        # task reports Ready even while the app is running, so MultipleInstances
        # does not suppress it. Without this check the duplicate reaches uvicorn,
        # fails to bind, and writes a traceback -- several hundred a day, which
        # buries anything real. Exit quietly instead; the port is the mutex.
        if _port_in_use(port):
            log.info("port %s already serving; another instance is live, exiting", port)
            return 0

        # Serve TLS directly when a certificate is present. The camera and the
        # installable app both require a secure context, so this is what makes
        # the phone usable; without it the app still serves plain HTTP.
        certfile = os.getenv("SSL_CERTFILE", "")
        keyfile = os.getenv("SSL_KEYFILE", "")
        ssl_kwargs = {}
        if certfile and keyfile and Path(certfile).is_file() and Path(keyfile).is_file():
            ssl_kwargs = {"ssl_certfile": certfile, "ssl_keyfile": keyfile}
            log.info("TLS enabled using %s", certfile)
        elif certfile or keyfile:
            log.warning("SSL_CERTFILE/SSL_KEYFILE set but not found on disk; serving HTTP")

        log.info("starting tracker on %s://%s:%s",
                 "https" if ssl_kwargs else "http", host, port)
        log.info("python=%s", sys.executable)
        log.info("storage=%s db=%s", config.STORAGE_DIR, config.DB_PATH)
        log.info("ollama=%s model=%s", config.OLLAMA_URL, config.VISION_MODEL)

        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=False,
            # Reuse the root logger configured above so uvicorn's output lands
            # in the same rotated file instead of a console that does not exist.
            log_config=None,
            access_log=False,
            **ssl_kwargs,
        )
        return 0
    except BaseException as exc:  # noqa: BLE001 - must never escape silently
        log.exception("tracker failed to start")
        _write_crash(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
