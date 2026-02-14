"""Tests for the Elering Estfeed API rate limiter."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.elering_estfeed.api import EleringEstfeedApiClient
from custom_components.elering_estfeed.const import RATE_LIMIT_SECONDS


def _make_client() -> EleringEstfeedApiClient:
    """Create a real API client with a mocked session."""
    session = MagicMock()
    return EleringEstfeedApiClient(
        api_host="https://test.example.com",
        client_id="id",
        client_secret="secret",
        session=session,
    )


@pytest.mark.asyncio
async def test_rate_limiter_no_wait_first_call() -> None:
    """First call should not wait."""
    client = _make_client()

    # _next_allowed_mono defaults to 0, so monotonic() is always larger.
    start = time.monotonic()
    await client._async_enforce_rate_limit()
    elapsed = time.monotonic() - start

    # Should finish nearly instantly.
    assert elapsed < 0.1
    assert client._blocked_count == 0


@pytest.mark.asyncio
async def test_rate_limiter_blocks_second_call() -> None:
    """If next_allowed_mono is in the future, the method should sleep."""
    client = _make_client()

    # Simulate that a request was just made.
    client._next_allowed_mono = time.monotonic() + 0.3  # 300ms in future

    start = time.monotonic()
    await client._async_enforce_rate_limit()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.25  # should have waited ~300ms
    assert client._blocked_count == 1


@pytest.mark.asyncio
async def test_rate_limiter_increments_blocked_count() -> None:
    """Blocked count should increase with each wait."""
    client = _make_client()

    for i in range(3):
        client._next_allowed_mono = time.monotonic() + 0.05
        await client._async_enforce_rate_limit()

    assert client._blocked_count == 3


def test_rate_limit_info_initial_state() -> None:
    """rate_limit_info should return sensible defaults before any request."""
    client = _make_client()
    info = client.rate_limit_info

    assert info["last_request_time"] is None
    assert info["next_allowed_time"] is None
    assert info["blocked_requests_count"] == 0
    # No server headers yet.
    assert "rate_limit_limit" not in info


def test_capture_rate_limit_headers() -> None:
    """_capture_rate_limit_headers should store integer header values."""
    client = _make_client()

    headers = {
        "X-RateLimit-Limit": "100",
        "X-RateLimit-Remaining": "42",
        "X-RateLimit-Reset": "1700000000",
    }
    client._capture_rate_limit_headers(headers)

    info = client.rate_limit_info
    assert info["rate_limit_limit"] == 100
    assert info["rate_limit_remaining"] == 42
    assert info["rate_limit_reset"] == 1700000000


def test_capture_rate_limit_headers_ignores_non_integer() -> None:
    """Non-integer header values should be silently skipped."""
    client = _make_client()

    headers = {"X-RateLimit-Limit": "not-a-number"}
    client._capture_rate_limit_headers(headers)

    assert "rate_limit_limit" not in client.rate_limit_info
