"""Tests for on-disk response caching."""

# ruff: noqa: S101, SLF001

import gzip
import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.cache import (
    CacheEntry,
    ResponseCache,
    fingerprint,
    merge_series,
    prune_before,
)
from open_meteo_solar_forecast.exceptions import (
    OpenMeteoSolarForecastAuthenticationError,
    OpenMeteoSolarForecastConnectionError,
)

STEP = 900
DAY = 86400


def _response(start: int, count: int, value: float = 1.0) -> dict:
    """Build a minimal Open-Meteo-style response."""
    return {
        "utc_offset_seconds": 0,
        "minutely_15": {
            "time": [start + i * STEP for i in range(count)],
            "temperature_2m": [value] * count,
        },
    }


def _forecast(cache_path: str, **kwargs) -> OpenMeteoSolarForecast:
    return OpenMeteoSolarForecast(
        latitude=48.0,
        longitude=11.0,
        declination=30,
        azimuth=0,
        dc_kwp=2.0,
        cache_path=cache_path,
        **kwargs,
    )


class ResponseCacheTests(unittest.TestCase):
    """Reading, writing and invalidating the cache file."""

    def test_round_trip(self) -> None:
        """Written entries load back identically."""
        with TemporaryDirectory() as tmp:
            cache = ResponseCache(Path(tmp) / "omcache.gz")
            h = fingerprint({"latitude": "48.0"})
            cache.write(h, CacheEntry(data=_response(0, 4), refreshed_at=42.0))
            entry = cache.read(h)
            assert entry is not None
            assert entry.data == _response(0, 4)
            assert entry.refreshed_at == 42.0

    def test_stored_as_gzip_json(self) -> None:
        """The on-disk format is gzip-compressed JSON."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "omcache.gz"
            ResponseCache(path).write(
                "h", CacheEntry(data=_response(0, 4), refreshed_at=0.0)
            )
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                assert json.load(fh)["schema"] == 1

    def test_missing_file(self) -> None:
        """A missing file reads as None."""
        assert ResponseCache("/nonexistent/omcache.gz").read("h") is None

    def test_fingerprint_mismatch(self) -> None:
        """A different request fingerprint invalidates the cache."""
        with TemporaryDirectory() as tmp:
            cache = ResponseCache(Path(tmp) / "omcache.gz")
            cache.write("aaa", CacheEntry(data=_response(0, 4), refreshed_at=0.0))
            assert cache.read("bbb") is None

    def test_corrupt_file(self) -> None:
        """Garbage on disk reads as None instead of raising."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "omcache.gz"
            path.write_bytes(b"\x00garbage")
            assert ResponseCache(path).read("h") is None


class SeriesTests(unittest.TestCase):
    """Merging and pruning of minutely series."""

    def test_fresh_wins_on_overlap(self) -> None:
        """Overlapping timestamps take the fresh values."""
        merged = merge_series(_response(0, 8, 1.0), _response(4 * STEP, 8, 2.0))
        m = merged["minutely_15"]
        assert m["time"] == [i * STEP for i in range(12)]
        assert m["temperature_2m"] == [1.0] * 4 + [2.0] * 8

    def test_gap_drops_cached(self) -> None:
        """Disjoint cached data is discarded to keep the series contiguous."""
        fresh = _response(50 * STEP, 4, 2.0)
        assert merge_series(_response(0, 4), fresh) == fresh

    def test_prune_before(self) -> None:
        """prune_before drops rows strictly before the cutoff."""
        pruned = prune_before(_response(0, 8), 3 * STEP)
        assert pruned["minutely_15"]["time"][0] == 3 * STEP
        assert len(pruned["minutely_15"]["temperature_2m"]) == 5


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    """Serving cached data when the API is down."""

    async def test_retryable_error_serves_cache(self) -> None:
        """A connection error with a warm cache returns cached data."""
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "omcache.gz")
            forecast = _forecast(path)
            data = _response(int(time.time()), 4)
            ResponseCache(path).write(
                forecast._cache_fingerprint(),
                CacheEntry(data=data, refreshed_at=time.time()),
            )

            async def boom(uri, *, params=None):  # noqa: ANN001, ANN202, ARG001
                raise OpenMeteoSolarForecastConnectionError("down")

            forecast._request = boom
            assert await forecast._fetch_forecast() == data

    async def test_non_retryable_error_raises(self) -> None:
        """An auth error re-raises even with a warm cache."""
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "omcache.gz")
            forecast = _forecast(path)
            ResponseCache(path).write(
                forecast._cache_fingerprint(),
                CacheEntry(
                    data=_response(int(time.time()), 4),
                    refreshed_at=time.time(),
                ),
            )

            async def boom(uri, *, params=None):  # noqa: ANN001, ANN202, ARG001
                raise OpenMeteoSolarForecastAuthenticationError("bad key")

            forecast._request = boom
            with self.assertRaises(OpenMeteoSolarForecastAuthenticationError):  # noqa: PT027
                await forecast._fetch_forecast()

    async def test_cold_cache_raises(self) -> None:
        """A retryable error without cached data still raises."""
        with TemporaryDirectory() as tmp:
            forecast = _forecast(str(Path(tmp) / "omcache.gz"))

            async def boom(uri, *, params=None):  # noqa: ANN001, ANN202, ARG001
                raise OpenMeteoSolarForecastConnectionError("down")

            forecast._request = boom
            with self.assertRaises(OpenMeteoSolarForecastConnectionError):  # noqa: PT027
                await forecast._fetch_forecast()


class MaxAgeTests(unittest.IsolatedAsyncioTestCase):
    """Behaviour of the cache_max_age option."""

    @staticmethod
    def _warm_cache(path: str, forecast, data: dict, age: float) -> None:  # noqa: ANN001
        ResponseCache(path).write(
            forecast._cache_fingerprint(),
            CacheEntry(data=data, refreshed_at=time.time() - age),
        )

    async def test_fresh_cache_skips_api(self) -> None:
        """A cache younger than cache_max_age is served without any request."""
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "omcache.gz")
            forecast = _forecast(path, cache_max_age=1800)
            data = _response(int(time.time()), 4)
            self._warm_cache(path, forecast, data, age=60)

            async def boom(uri, *, params=None):  # noqa: ANN001, ANN202, ARG001
                raise AssertionError("API must not be called")

            forecast._request = boom
            assert await forecast._fetch_forecast() == data

    async def test_stale_cache_calls_api(self) -> None:
        """A cache older than cache_max_age triggers a refresh."""
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "omcache.gz")
            forecast = _forecast(path, cache_max_age=1800)
            now = int(time.time())
            self._warm_cache(path, forecast, _response(now, 4), age=3600)
            called = False

            async def fake(uri, *, params=None):  # noqa: ANN001, ANN202, ARG001
                nonlocal called
                called = True
                return _response(now - (now % STEP), 8, value=2.0)

            forecast._request = fake
            await forecast._fetch_forecast()
            assert called

    async def test_no_max_age_always_calls_api(self) -> None:
        """Without cache_max_age even a brand-new cache is refreshed."""
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "omcache.gz")
            forecast = _forecast(path)
            now = int(time.time())
            self._warm_cache(path, forecast, _response(now, 4), age=0)
            called = False

            async def fake(uri, *, params=None):  # noqa: ANN001, ANN202, ARG001
                nonlocal called
                called = True
                return _response(now - (now % STEP), 8, value=2.0)

            forecast._request = fake
            await forecast._fetch_forecast()
            assert called


class PruneOptionTests(unittest.IsolatedAsyncioTestCase):
    """Behaviour of the cache_prune option."""

    async def _run(self, *, cache_prune: bool) -> tuple[dict, dict]:
        """Fetch against a cache with ancient data; return (result, on-disk)."""
        now = int(time.time())
        old_start = now - 150 * DAY
        with TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "omcache.gz")
            forecast = _forecast(path, past_days=2, cache_prune=cache_prune)
            # +1 so the cached series overlaps the fresh window
            count = (now - old_start) // STEP + 1
            ResponseCache(path).write(
                forecast._cache_fingerprint(),
                CacheEntry(data=_response(old_start, count), refreshed_at=now),
            )

            async def fake(uri, *, params=None):  # noqa: ANN001, ANN202, ARG001
                return _response(now - (now % STEP), 4, value=2.0)

            forecast._request = fake
            result = await forecast._fetch_forecast()
            saved = ResponseCache(path).read(forecast._cache_fingerprint())
            assert saved is not None
            return result, saved.data

    async def test_prune_trims_disk(self) -> None:
        """With pruning (default) old rows leave both result and disk."""
        result, saved = await self._run(cache_prune=True)
        window = 3 * DAY  # past_days=2 plus midnight-alignment slack
        assert result["minutely_15"]["time"][0] > time.time() - window
        assert saved["minutely_15"]["time"][0] > time.time() - window

    async def test_no_prune_keeps_history_on_disk(self) -> None:
        """Without pruning the full history stays on disk only."""
        result, saved = await self._run(cache_prune=False)
        assert result["minutely_15"]["time"][0] > time.time() - 3 * DAY
        assert saved["minutely_15"]["time"][0] < time.time() - 149 * DAY


if __name__ == "__main__":
    unittest.main()
