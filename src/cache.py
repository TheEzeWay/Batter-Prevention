"""
cache.py – Simple file-based JSON cache with TTL support.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)


def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def cache_get(key: str, ttl_key: str = "schedule") -> Optional[Any]:
    """Return cached value if it exists and hasn't expired, else None."""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ttl = CACHE_TTL.get(ttl_key, 3600)
        age = time.time() - payload.get("ts", 0)
        if age > ttl:
            logger.debug("Cache expired for %s (age=%.0fs)", key, age)
            return None
        return payload["data"]
    except Exception as exc:
        logger.warning("Cache read error for %s: %s", key, exc)
        return None


def cache_set(key: str, data: Any) -> None:
    """Write data to cache with current timestamp."""
    path = _cache_path(key)
    try:
        path.write_text(
            json.dumps({"ts": time.time(), "data": data}, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Cache write error for %s: %s", key, exc)


def cache_clear(key: str) -> None:
    """Delete a single cache entry."""
    path = _cache_path(key)
    if path.exists():
        path.unlink()
        logger.info("Cleared cache: %s", key)


def cache_clear_all() -> int:
    """Delete all cache files. Returns count deleted."""
    count = 0
    for f in CACHE_DIR.glob("*.json"):
        f.unlink()
        count += 1
    logger.info("Cleared %d cache files", count)
    return count
