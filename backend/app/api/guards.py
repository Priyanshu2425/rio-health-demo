"""Upload checks, the per-IP parse rate limit, and the error helper."""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, UploadFile

from app.core.config import get_settings


def error(status: int, code: str, message: str) -> HTTPException:
    """main.py's handler turns 'code: message' into ErrorResponse."""
    return HTTPException(status, detail=f"{code}: {message}")


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
DECLARED_OK = ALLOWED_TYPES | {"image/jpg", "application/octet-stream", ""}


def sniff_image(head: bytes) -> str | None:
    """The real type from magic bytes, or None if it is not jpeg / png / webp."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_image(request: Request, image: UploadFile) -> tuple[bytes, str]:
    """(bytes, mime) or 400 unsupported_image / 413 image_too_large."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    too_large = error(413, "image_too_large", f"images must be {get_settings().max_upload_mb} MB or smaller")
    declared_len = request.headers.get("content-length")
    # The multipart envelope adds a little; allow 64 KB of slack before refusing early.
    if declared_len and declared_len.isdigit() and int(declared_len) > max_bytes + 65536:
        raise too_large
    data = await image.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise too_large
    declared = (image.content_type or "").lower()
    if declared not in DECLARED_OK:
        raise error(400, "unsupported_image", f"{declared} is not supported; send a jpeg, png or webp photo")
    mime = sniff_image(data[:16])
    if mime is None:
        raise error(400, "unsupported_image", "that file is not a readable jpeg, png or webp image")
    return data, mime


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def client_ip(request: Request) -> str:
    """Cloudflare's CF-Connecting-IP behind the tunnel, else the peer address."""
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding window, in memory: fine for one uvicorn worker on one instance."""

    def __init__(self, window_s: float = 3600.0) -> None:
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def hit(self, key: str, limit: int, now: float | None = None) -> float | None:
        """Record one attempt. Returns None if allowed, else seconds until the next slot."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            if len(hits) >= limit:
                return max(0.0, hits[0] + self.window_s - now)
            hits.append(now)
            return None


parse_limiter = RateLimiter()


def check_parse_rate(request: Request) -> None:
    limit = get_settings().parse_rate_limit_per_hour
    wait = parse_limiter.hit(client_ip(request), limit)
    if wait is not None:
        minutes = max(1, math.ceil(wait / 60))
        raise error(
            429,
            "rate_limited",
            f"{limit} prescription uploads per hour; try again in {minutes} min, or try a sample",
        )
