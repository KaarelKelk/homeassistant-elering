"""Historical data backfill and local cache for Elering Estfeed."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import EleringEstfeedApiClient
from .const import API_MAX_WINDOW_DAYS, DOMAIN, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class EleringHistoryStore:
    """Manages fetching, caching, and persisting historical metering data.

    Data is stored in ``.storage/elering_estfeed_<eic>.json`` via
    Home Assistant's built-in ``Store`` helper.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: EleringEstfeedApiClient,
        eic: str,
    ) -> None:
        """Initialise the history store."""
        self._hass = hass
        self._client = client
        self._eic = eic

        storage_key = f"{DOMAIN}_{eic}".lower()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key
        )

        # In-memory cache (populated from disk on load).
        self._measurements: list[dict[str, Any]] = []
        self._last_fetch: str | None = None

    # ------------------------------------------------------------------
    # Public properties (read by diagnostic sensors)
    # ------------------------------------------------------------------

    @property
    def history_available(self) -> bool:
        """Whether any cached history data exists."""
        return len(self._measurements) > 0

    @property
    def history_points(self) -> int:
        """Number of data-points currently in the local cache."""
        return len(self._measurements)

    @property
    def measurements(self) -> list[dict[str, Any]]:
        """Return the full list of cached measurements."""
        return self._measurements

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    async def async_load(self) -> None:
        """Load persisted history from disk (if any)."""
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self._measurements = data.get("measurements", [])
            self._last_fetch = data.get("last_fetch")
            _LOGGER.debug(
                "Loaded %d cached history point(s) for EIC %s (last_fetch=%s)",
                len(self._measurements),
                self._eic,
                self._last_fetch,
            )
        else:
            _LOGGER.debug("No cached history found for EIC %s", self._eic)

    async def _async_save(self) -> None:
        """Persist current in-memory cache to disk."""
        await self._store.async_save(
            {
                "eic": self._eic,
                "last_fetch": datetime.now(timezone.utc).isoformat(),
                "point_count": len(self._measurements),
                "measurements": self._measurements,
            }
        )

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    async def async_fetch_history(self, days: int) -> None:
        """Fetch *days* of historical data, chunked into ≤31-day windows.

        Results are merged into the local cache (de-duplicated by
        timestamp) and persisted to disk.  The existing API rate limiter
        ensures requests are spaced ≥ 5 s apart.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        _LOGGER.info(
            "Starting history backfill for EIC %s: %d day(s) "
            "(%s → %s)",
            self._eic,
            days,
            start.isoformat(),
            end.isoformat(),
        )

        all_new: list[dict[str, Any]] = []
        chunk_start = start

        while chunk_start < end:
            chunk_end = min(
                chunk_start + timedelta(days=API_MAX_WINDOW_DAYS), end
            )
            try:
                chunk = await self._client.async_get_metering_data(
                    eic=self._eic,
                    start=chunk_start,
                    end=chunk_end,
                )
                all_new.extend(chunk)
                _LOGGER.debug(
                    "History chunk %s → %s: %d point(s)",
                    chunk_start.isoformat(),
                    chunk_end.isoformat(),
                    len(chunk),
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "History backfill chunk failed for EIC %s (%s → %s). "
                    "Continuing with remaining chunks",
                    self._eic,
                    chunk_start.isoformat(),
                    chunk_end.isoformat(),
                    exc_info=True,
                )
            chunk_start = chunk_end

        if all_new:
            self._merge(all_new)
            await self._async_save()

        _LOGGER.info(
            "History backfill complete for EIC %s: "
            "%d new point(s) fetched, %d total cached",
            self._eic,
            len(all_new),
            len(self._measurements),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _merge(self, new_points: list[dict[str, Any]]) -> None:
        """Merge new data-points into the existing cache, de-dup by timestamp."""
        existing_ts: set[str] = {
            m.get("timestamp", "") for m in self._measurements
        }
        added = 0
        for point in new_points:
            ts = point.get("timestamp", "")
            if ts and ts not in existing_ts:
                self._measurements.append(point)
                existing_ts.add(ts)
                added += 1

        # Keep sorted ascending.
        self._measurements.sort(key=lambda m: m.get("timestamp", ""))
        _LOGGER.debug("Merged %d new point(s) into cache", added)
