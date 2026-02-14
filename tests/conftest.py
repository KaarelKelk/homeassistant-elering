"""Shared fixtures for Elering Estfeed tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.elering_estfeed.api import EleringEstfeedApiClient
from custom_components.elering_estfeed.const import (
    CONF_API_HOST,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_COMMODITY_TYPE,
    CONF_EIC,
    DEFAULT_API_HOST,
    DOMAIN,
)

MOCK_EIC = "38ZEE-1000000A-B"
MOCK_CLIENT_ID = "test-client-id"
MOCK_CLIENT_SECRET = "test-client-secret"


@pytest.fixture
def mock_config_entry_data() -> dict[str, Any]:
    """Return a minimal config entry data dict."""
    return {
        CONF_API_HOST: DEFAULT_API_HOST,
        CONF_CLIENT_ID: MOCK_CLIENT_ID,
        CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
        CONF_EIC: MOCK_EIC,
        CONF_COMMODITY_TYPE: "ELECTRICITY",
    }


@pytest.fixture
def mock_metering_points() -> list[dict[str, Any]]:
    """Return a sample metering-points API response."""
    return [
        {
            "eic": MOCK_EIC,
            "commodityType": "ELECTRICITY",
            "validFrom": "2023-01-01",
            "validTo": None,
        },
    ]


@pytest.fixture
def mock_metering_data() -> list[dict[str, Any]]:
    """Return a sample metering-data API response."""
    return [
        {
            "timestamp": "2025-01-01T00:00:00+0000",
            "energyIn": 1.23,
            "energyOut": 0.45,
            "unit": "kWh",
        },
        {
            "timestamp": "2025-01-01T01:00:00+0000",
            "energyIn": 2.34,
            "energyOut": 0.67,
            "unit": "kWh",
        },
    ]


@pytest.fixture
def mock_api_client(
    mock_metering_points: list[dict[str, Any]],
    mock_metering_data: list[dict[str, Any]],
) -> AsyncMock:
    """Return a fully mocked EleringEstfeedApiClient."""
    client = AsyncMock(spec=EleringEstfeedApiClient)
    client.async_get_access_token = AsyncMock(return_value="mock-access-token")
    client.async_get_metering_points = AsyncMock(return_value=mock_metering_points)
    client.async_get_metering_data = AsyncMock(return_value=mock_metering_data)
    client.rate_limit_info = {
        "last_request_time": None,
        "next_allowed_time": None,
        "blocked_requests_count": 0,
    }
    return client
