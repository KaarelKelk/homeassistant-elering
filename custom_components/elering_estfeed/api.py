"""API client for Elering Estfeed."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import (
    DEFAULT_RESOLUTION,
    DEFAULT_TOKEN_URL,
    METERING_DATA_PATH,
    METERING_POINTS_PATH,
    RATE_LIMIT_SECONDS,
    TOKEN_EXPIRY_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

# Response headers the server may return for rate-limit info.
_RL_HEADER_LIMIT = "X-RateLimit-Limit"
_RL_HEADER_REMAINING = "X-RateLimit-Remaining"
_RL_HEADER_RESET = "X-RateLimit-Reset"


class EleringEstfeedError(Exception):
    """Base exception for Elering Estfeed API errors."""


class EleringAuthError(EleringEstfeedError):
    """Raised when authentication fails (bad credentials or token request)."""


class EleringConnectionError(EleringEstfeedError):
    """Raised when an endpoint is unreachable."""


class EleringEstfeedApiClient:
    """API client for Elering Estfeed with OAuth2 client-credentials auth."""

    def __init__(
        self,
        api_host: str,
        client_id: str,
        client_secret: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialise the API client."""
        self._api_host = api_host.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session

        # Token cache
        self._access_token: str | None = None
        self._token_expiry: float = 0.0  # monotonic clock

        # Rate-limit state
        self._next_allowed_mono: float = 0.0
        self._last_request_time: datetime | None = None
        self._blocked_count: int = 0
        self._rate_limit_headers: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Rate-limit info (read by diagnostic sensors)
    # ------------------------------------------------------------------

    @property
    def rate_limit_info(self) -> dict[str, Any]:
        """Return a snapshot of the current rate-limit state.

        Keys always present:
        - last_request_time  (ISO str | None)
        - next_allowed_time  (ISO str | None)
        - blocked_requests_count (int)

        Keys present only when the server returns the headers:
        - rate_limit_limit     (int)
        - rate_limit_remaining (int)
        - rate_limit_reset     (int)
        """
        info: dict[str, Any] = {
            "last_request_time": (
                self._last_request_time.isoformat()
                if self._last_request_time
                else None
            ),
            "blocked_requests_count": self._blocked_count,
        }

        # Compute wall-clock next-allowed from monotonic delta.
        now_mono = time.monotonic()
        if self._next_allowed_mono > now_mono:
            delta = self._next_allowed_mono - now_mono
            next_dt = datetime.now(timezone.utc) + timedelta(seconds=delta)
            info["next_allowed_time"] = next_dt.isoformat()
        else:
            info["next_allowed_time"] = None

        # Merge server-reported headers (if any).
        info.update(self._rate_limit_headers)

        return info

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing when needed.

        The token is cached and reused until TOKEN_EXPIRY_MARGIN seconds
        before it expires.  Secrets and tokens are **never** logged.
        """
        now = time.monotonic()
        if self._access_token is not None and now < self._token_expiry:
            _LOGGER.debug("Using cached access token (still valid)")
            return self._access_token

        _LOGGER.debug("Requesting new access token from %s", DEFAULT_TOKEN_URL)

        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        try:
            async with self._session.post(
                DEFAULT_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                body = await resp.text()

                if resp.status in (401, 403):
                    _LOGGER.error(
                        "Authentication failed (HTTP %s) from %s – "
                        "verify your client_id and client_secret are correct. "
                        "Response: %s",
                        resp.status,
                        DEFAULT_TOKEN_URL,
                        body,
                    )
                    raise EleringAuthError(
                        f"Authentication failed (HTTP {resp.status}): {body}"
                    )

                if resp.status != 200:
                    _LOGGER.error(
                        "Token request to %s failed (HTTP %s). Response: %s",
                        DEFAULT_TOKEN_URL,
                        resp.status,
                        body,
                    )
                    raise EleringEstfeedError(
                        f"Token request failed (HTTP {resp.status}): {body}"
                    )

                result: dict[str, Any] = await resp.json(content_type=None)

        except EleringEstfeedError:
            raise
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Cannot reach token endpoint %s: %s", DEFAULT_TOKEN_URL, err
            )
            raise EleringConnectionError(
                f"Cannot reach token endpoint {DEFAULT_TOKEN_URL}: {err}"
            ) from err

        access_token = result.get("access_token")
        if not access_token:
            _LOGGER.error(
                "Token response from %s did not contain an access_token field. "
                "This may indicate an unexpected response format",
                DEFAULT_TOKEN_URL,
            )
            raise EleringAuthError(
                "Token response did not contain access_token"
            )

        expires_in: int = int(result.get("expires_in", 300))

        self._access_token = access_token
        self._token_expiry = now + expires_in - TOKEN_EXPIRY_MARGIN

        _LOGGER.debug(
            "Access token obtained successfully, expires in %ss "
            "(will refresh in %ss)",
            expires_in,
            expires_in - TOKEN_EXPIRY_MARGIN,
        )

        return self._access_token

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _async_enforce_rate_limit(self) -> None:
        """Sleep if needed to respect the minimum interval between requests."""
        now = time.monotonic()
        if now < self._next_allowed_mono:
            wait = self._next_allowed_mono - now
            self._blocked_count += 1
            _LOGGER.debug(
                "Rate limit: waiting %.1fs before next request "
                "(blocked %d time(s) total)",
                wait,
                self._blocked_count,
            )
            await asyncio.sleep(wait)

    def _capture_rate_limit_headers(
        self, headers: Any
    ) -> None:
        """Store server-reported rate-limit headers (if present)."""
        new: dict[str, int] = {}
        for header, key in (
            (_RL_HEADER_LIMIT, "rate_limit_limit"),
            (_RL_HEADER_REMAINING, "rate_limit_remaining"),
            (_RL_HEADER_RESET, "rate_limit_reset"),
        ):
            value = headers.get(header)
            if value is not None:
                try:
                    new[key] = int(value)
                except (ValueError, TypeError):
                    _LOGGER.debug(
                        "Non-integer rate-limit header %s=%s", header, value
                    )
        self._rate_limit_headers = new

    # ------------------------------------------------------------------
    # Authenticated requests
    # ------------------------------------------------------------------

    async def _async_request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Make an authenticated, rate-limited request to the Estfeed API.

        Automatically attaches the Bearer token, enforces the minimum
        interval between requests, and captures rate-limit headers.
        """
        await self._async_enforce_rate_limit()

        token = await self.async_get_access_token()
        url = f"{self._api_host}{path}"

        _LOGGER.debug("API %s %s params=%s", method, url, params)

        try:
            async with self._session.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            ) as resp:
                body = await resp.text()

                # Record timing AFTER the request returns (even on errors).
                self._last_request_time = datetime.now(timezone.utc)
                self._next_allowed_mono = (
                    time.monotonic() + RATE_LIMIT_SECONDS
                )

                # Capture server rate-limit headers.
                self._capture_rate_limit_headers(resp.headers)

                if resp.status in (401, 403):
                    self._access_token = None
                    _LOGGER.error(
                        "API request to %s returned HTTP %s – "
                        "access token may be invalid. Response: %s",
                        url,
                        resp.status,
                        body,
                    )
                    raise EleringAuthError(
                        f"API auth failed (HTTP {resp.status}): {body}"
                    )

                if resp.status != 200:
                    _LOGGER.error(
                        "API request to %s failed (HTTP %s). Response: %s",
                        url,
                        resp.status,
                        body,
                    )
                    raise EleringEstfeedError(
                        f"API request failed (HTTP {resp.status}): {body}"
                    )

                return await resp.json(content_type=None)

        except EleringEstfeedError:
            raise
        except aiohttp.ClientError as err:
            _LOGGER.error("Cannot reach API endpoint %s: %s", url, err)
            raise EleringConnectionError(
                f"Cannot reach API endpoint {url}: {err}"
            ) from err

    # ------------------------------------------------------------------
    # Metering points
    # ------------------------------------------------------------------

    async def async_get_metering_points(self) -> list[dict[str, Any]]:
        """Fetch the list of metering-point EICs the credentials grant access to.

        Returns a list of dicts, each containing at least:
        - eic:            the EIC code (str)
        - commodityType:  "ELECTRICITY" | "GAS" (str)
        - validFrom / validTo:  access period boundaries (str | None)
        """
        now = datetime.now(timezone.utc)
        params = {
            "startDateTime": _format_dt(now),
            "endDateTime": _format_dt(now),
        }
        data = await self._async_request(
            "GET", METERING_POINTS_PATH, params=params
        )

        if isinstance(data, list):
            points = data
        elif isinstance(data, dict):
            points = (
                data.get("meteringPoints")
                or data.get("data")
                or data.get("content")
                or []
            )
        else:
            points = []

        if not points:
            _LOGGER.warning(
                "No metering points returned from %s%s – "
                "verify your credentials have access to at least one EIC",
                self._api_host,
                METERING_POINTS_PATH,
            )

        _LOGGER.debug("Fetched %d metering point(s)", len(points))
        return points  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Metering data
    # ------------------------------------------------------------------

    async def async_get_metering_data(
        self,
        eic: str,
        start: datetime,
        end: datetime,
        resolution: str = DEFAULT_RESOLUTION,
    ) -> list[dict[str, Any]]:
        """Fetch metering data for a single EIC within *start* – *end*.

        The API constrains each request to max 31 days.
        Callers must ensure the window fits within that limit.

        Returns the raw list of measurement dicts from the API, sorted by
        timestamp ascending.  Each dict typically contains at least:
        - timestamp (str, ISO-8601)
        - value (float)
        - unit (str, e.g. "kWh")
        """
        params = {
            "startDateTime": _format_dt(start),
            "endDateTime": _format_dt(end),
            "resolution": resolution,
            "meteringPointEics": eic,
        }

        _LOGGER.debug(
            "Fetching metering data for EIC %s from %s to %s (resolution=%s)",
            eic,
            params["startDateTime"],
            params["endDateTime"],
            resolution,
        )

        data = await self._async_request("GET", METERING_DATA_PATH, params=params)

        measurements = _extract_measurements(data, eic)

        # Sort ascending by timestamp for consistent ordering.
        measurements.sort(key=lambda m: m.get("timestamp", ""))

        _LOGGER.debug(
            "Received %d measurement(s) for EIC %s", len(measurements), eic
        )
        return measurements


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _format_dt(dt: datetime) -> str:
    """Format a datetime as ISO-8601 with UTC offset for the Estfeed API."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _extract_measurements(
    data: Any,
    eic: str,
) -> list[dict[str, Any]]:
    """Extract measurement entries from the API response.

    The response shape can vary:
    - A bare list of measurement dicts
    - A list of per-EIC objects each containing a "measurements" list
    - A dict wrapping one of the above
    """
    # Unwrap top-level dict if needed.
    if isinstance(data, dict):
        data = (
            data.get("meteringData")
            or data.get("data")
            or data.get("content")
            or data.get("measurements")
            or []
        )

    if not isinstance(data, list):
        _LOGGER.warning(
            "Unexpected metering-data response type: %s", type(data).__name__
        )
        return []

    # If each element has a "measurements" sub-list, find the one for our EIC.
    for item in data:
        if isinstance(item, dict) and "measurements" in item:
            item_eic = item.get("meteringPointEic") or item.get("eic") or ""
            if item_eic == eic:
                return item["measurements"]  # type: ignore[no-any-return]
            # If only one entry, use it regardless of EIC label.
            if len(data) == 1:
                return item["measurements"]  # type: ignore[no-any-return]
        else:
            # Looks like a flat list of measurements already.
            return data  # type: ignore[return-value]

    return []
