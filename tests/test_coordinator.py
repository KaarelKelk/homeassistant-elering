"""Tests for the Elering Estfeed coordinator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.elering_estfeed.api import EleringEstfeedError
from custom_components.elering_estfeed.coordinator import EleringEstfeedCoordinator
from custom_components.elering_estfeed.const import DOMAIN

from .conftest import MOCK_EIC


def _make_coordinator(
    mock_client: AsyncMock,
    metering_data: list[dict[str, Any]] | None = None,
) -> EleringEstfeedCoordinator:
    """Create a coordinator with a mocked hass + client."""
    hass = MagicMock()
    hass.async_create_task = MagicMock()

    history = MagicMock()
    history.history_available = False
    history.history_points = 0

    if metering_data is not None:
        mock_client.async_get_metering_data = AsyncMock(return_value=metering_data)

    coord = EleringEstfeedCoordinator(
        hass=hass,
        client=mock_client,
        eic=MOCK_EIC,
        commodity_type="ELECTRICITY",
        history=history,
    )
    return coord


@pytest.mark.asyncio
async def test_coordinator_returns_latest_datapoint(
    mock_api_client: AsyncMock,
    mock_metering_data: list[dict[str, Any]],
) -> None:
    """Test that _async_update_data returns the most recent measurement."""
    coord = _make_coordinator(mock_api_client, metering_data=mock_metering_data)

    result = await coord._async_update_data()

    assert result["energyIn"] == 2.34
    assert result["timestamp"] == "2025-01-01T01:00:00+0000"


@pytest.mark.asyncio
async def test_coordinator_returns_empty_on_no_data(
    mock_api_client: AsyncMock,
) -> None:
    """Test that _async_update_data returns {} when no measurements exist."""
    coord = _make_coordinator(mock_api_client, metering_data=[])

    result = await coord._async_update_data()

    assert result == {}


@pytest.mark.asyncio
async def test_coordinator_raises_update_failed_on_api_error(
    mock_api_client: AsyncMock,
) -> None:
    """Test that an API error is wrapped into UpdateFailed."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_api_client.async_get_metering_data = AsyncMock(
        side_effect=EleringEstfeedError("boom")
    )
    coord = _make_coordinator(mock_api_client)

    with pytest.raises(UpdateFailed, match="boom"):
        await coord._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_update_options(
    mock_api_client: AsyncMock,
    mock_metering_data: list[dict[str, Any]],
) -> None:
    """Test that update_options changes interval and resolution."""
    coord = _make_coordinator(mock_api_client, metering_data=mock_metering_data)

    coord.update_options(scan_interval=120, resolution="FIFTEEN_MIN")

    assert coord.update_interval.total_seconds() == 120
    assert coord.resolution == "FIFTEEN_MIN"
