"""On-disk caching of Open-Meteo API responses.

Responses are stored as gzip-compressed JSON. A fingerprint of the
request parameters is stored alongside the data so a change in
location, weather model, or requested variables invalidates the cache.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SECONDS_PER_DAY = 86400


def fingerprint(params: dict[str, Any]) -> str:
    """Return a stable hash of the request parameters."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    """A cached API response with bookkeeping metadata."""

    data: dict[str, Any]
    refreshed_at: float

    @property
    def times(self) -> list[float]:
        """Timestamps covered by the cached response."""
        return self.data["minutely_15"]["time"]

    @property
    def utc_offset(self) -> int:
        """UTC offset (seconds) the response was generated with."""
        return self.data.get("utc_offset_seconds", 0)


class ResponseCache:
    """Reads and writes cached Open-Meteo responses at a fixed path."""

    def __init__(self, path: str | Path) -> None:
        """Initialize the cache for *path*."""
        self._path = Path(path)

    def read(self, params_hash: str) -> CacheEntry | None:
        """Load the cache entry, or None if absent, corrupt, or stale.

        A mismatching schema version or request fingerprint counts as
        stale and returns None.
        """
        try:
            with gzip.open(self._path, "rt", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, EOFError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        if raw.get("schema") != SCHEMA_VERSION or raw.get("fingerprint") != params_hash:
            return None
        data = raw.get("data")
        if not isinstance(data, dict):
            return None
        minutely = data.get("minutely_15")
        if not isinstance(minutely, dict) or not minutely.get("time"):
            return None
        try:
            refreshed_at = float(raw["refreshed_at"])
        except (KeyError, TypeError, ValueError):
            return None
        return CacheEntry(data=data, refreshed_at=refreshed_at)

    def write(self, params_hash: str, entry: CacheEntry) -> None:
        """Atomically persist *entry* to disk."""
        raw = {
            "schema": SCHEMA_VERSION,
            "fingerprint": params_hash,
            "refreshed_at": entry.refreshed_at,
            "data": entry.data,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".part")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(raw, fh, separators=(",", ":"))
        tmp.replace(self._path)


def merge_series(cached: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Combine a cached response with a freshly fetched one.

    Fresh values win wherever both cover a timestamp; cached entries
    strictly before the fresh window are prepended. If the cached data
    does not connect to the fresh window (a gap), it is dropped so the
    series stays contiguous.
    """
    cached_m = cached["minutely_15"]
    fresh_m = fresh["minutely_15"]
    fresh_start = fresh_m["time"][0]

    if cached_m["time"][-1] < fresh_start:
        return fresh

    keep = sum(1 for ts in cached_m["time"] if ts < fresh_start)

    result = dict(fresh)
    result["minutely_15"] = {
        var: cached_m[var][:keep] + series for var, series in fresh_m.items()
    }
    return result


def prune_before(data: dict[str, Any], cutoff: float) -> dict[str, Any]:
    """Return *data* without minutely rows strictly before *cutoff*."""
    minutely = data["minutely_15"]
    drop = sum(1 for ts in minutely["time"] if ts < cutoff)
    if drop == 0:
        return data
    result = dict(data)
    result["minutely_15"] = {var: series[drop:] for var, series in minutely.items()}
    return result
