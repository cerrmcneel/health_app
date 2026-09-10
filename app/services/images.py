"""Image decoding, EXIF-correct orientation, downscaling and on-disk storage."""
import base64
import io
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from app import config

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ImageError(ValueError):
    """The uploaded bytes were not a usable image."""


def open_image(raw: bytes) -> Image.Image:
    """Decode bytes to RGB, honouring EXIF rotation.

    Phone cameras record orientation in EXIF rather than rotating pixels. Without
    exif_transpose a portrait shot reaches the model on its side, which wrecks
    both portion estimates and ghost-overlay alignment.
    """
    if not raw:
        raise ImageError("Empty upload.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError(f"Image exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise ImageError(f"Not a readable image: {exc}") from exc
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def to_jpeg_bytes(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def downscale(img: Image.Image, max_edge: int) -> Image.Image:
    """Shrink so the longest edge is at most max_edge. Never upscales."""
    if max(img.size) <= max_edge:
        return img
    scale = max_edge / max(img.size)
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(new_size, Image.LANCZOS)


def prepare_for_vision(img: Image.Image) -> str:
    """Downscale and base64-encode for Ollama.

    Full-resolution phone photos cost inference time without improving portion
    estimates -- the model's vision encoder tiles down to a fixed grid regardless.
    """
    small = downscale(img, config.VISION_MAX_EDGE)
    return base64.b64encode(to_jpeg_bytes(small, quality=85)).decode("ascii")


def save_pending(img: Image.Image) -> str:
    """Stash an analysed-but-uncommitted meal photo. Returns an opaque token."""
    config.ensure_dirs()
    token = uuid.uuid4().hex
    (config.PENDING_DIR / f"{token}.jpg").write_bytes(
        to_jpeg_bytes(downscale(img, 1600))
    )
    return token


def commit_pending(token: str, when: datetime) -> str | None:
    """Move a pending image into the permanent meals tree.

    Returns the STORAGE_DIR-relative path, or None if the token is unknown --
    a meal logged from an expired token still saves, just without its photo.
    """
    if not token or not token.isalnum() or len(token) != 32:
        return None
    src = config.PENDING_DIR / f"{token}.jpg"
    if not src.is_file():
        return None
    dest_dir = config.MEALS_DIR / when.strftime("%Y") / when.strftime("%m")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{when.strftime('%Y-%m-%d_%H%M%S')}_{token[:8]}.jpg"
    src.replace(dest)
    return relative(dest)


def save_progress_photo(img: Image.Image, pose: str, day: str, profile_id: int = 1) -> tuple[str, int, int, int]:
    """Write a progress photo to {pose}/YYYY-MM-DD_{pose}_{rand}.jpg.

    Returns (relative_path, width, height, bytes).
    """
    if pose not in config.POSES:
        raise ImageError(f"Unknown pose '{pose}'.")
    directory = config.POSE_DIRS[pose]
    directory.mkdir(parents=True, exist_ok=True)
    rand_part = uuid.uuid4().hex[:8]
    dest = directory / f"{day}_{pose}_{rand_part}.jpg"
    data = to_jpeg_bytes(img, quality=92)
    dest.write_bytes(data)
    return relative(dest), img.width, img.height, len(data)


def relative(path: Path) -> str:
    """Path relative to STORAGE_DIR, with forward slashes for use in URLs."""
    return path.resolve().relative_to(config.STORAGE_DIR.resolve()).as_posix()


def resolve_media(rel: str) -> Path:
    """Resolve a stored relative path back to disk, refusing escapes.

    Paths come out of the DB, but a traversal here would serve arbitrary files
    off the homelab box, so it is checked rather than trusted.
    """
    target = (config.STORAGE_DIR / rel).resolve()
    if not target.is_relative_to(config.STORAGE_DIR.resolve()):
        raise ImageError("Path escapes the storage directory.")
    return target


def purge_pending(max_age_hours: float = 24.0) -> int:
    """Delete stale pending images (analysed but never confirmed). Returns count."""
    if not config.PENDING_DIR.is_dir():
        return 0
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    removed = 0
    for f in config.PENDING_DIR.glob("*.jpg"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed
