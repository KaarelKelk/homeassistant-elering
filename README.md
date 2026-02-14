# Elering Estfeed – Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/kaarelkelk/homeassistant-elering)](https://github.com/kaarelkelk/homeassistant-elering/releases)

Custom [Home Assistant](https://www.home-assistant.io/) integration for the [Elering Estfeed](https://estfeed.elering.ee) API.
Monitor your electricity and gas metering data directly in Home Assistant using your own Estfeed API credentials.

## Features

- **OAuth2 authentication** – client-credentials flow against the Elering SSO.
- **Metering point discovery** – automatically lists all EIC codes your credentials can access.
- **Dynamic sensors** – every numeric metric in the API response becomes a Home Assistant sensor (energy, power, etc.).
- **Rate limiting** – respects the Estfeed 1-request-per-5-seconds limit, with diagnostic sensors for visibility.
- **Historical backfill** – fetches and caches up to 365 days of historical data locally.
- **Options flow** – adjust scan interval, data resolution, backfill depth, and commodity toggles without re-adding the integration.

## Installation

### HACS (recommended)

1. Open **HACS** in your Home Assistant instance.
2. Go to **Integrations** → click the **⋮** menu (top-right) → **Custom repositories**.
3. Paste the repository URL:

   ```
   https://github.com/kaarelkelk/homeassistant-elering
   ```

4. Select category **Integration** and click **Add**.
5. Close the dialog, then search for **Elering Estfeed** in HACS and click **Install**.
6. **Restart Home Assistant**.

### Manual installation

1. Download the [latest release](https://github.com/kaarelkelk/homeassistant-elering/releases) or clone this repository.
2. Copy the `custom_components/elering_estfeed` folder into your Home Assistant `config/custom_components/` directory.
3. **Restart Home Assistant**.

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **Elering Estfeed**.
3. Enter your credentials:
   | Field | Description | Default |
   |---|---|---|
   | **API Host** | Base URL of the Estfeed API | `https://estfeed.elering.ee` |
   | **Client ID** | Your OAuth2 client ID | — |
   | **Client Secret** | Your OAuth2 client secret | — |
4. Select the metering point (EIC) you want to monitor.
5. The integration creates sensors automatically based on the API response.

### Options

After initial setup, click **Configure** on the integration card to adjust:

| Option | Description | Default |
|---|---|---|
| **Scan interval** | How often to poll the API (60–3600 s) | `300` |
| **Data resolution** | Granularity: 15 min, 1 hour, 1 week, 1 month | `1h` |
| **History backfill days** | Days of history to fetch on setup (0 = disabled) | `90` |
| **Enable electricity** | Toggle electricity metering points on/off | `true` |
| **Enable gas** | Toggle gas metering points on/off | `true` |

### Services

| Service | Description |
|---|---|
| `elering_estfeed.fetch_history` | Manually fetch historical data (1–365 days). Cached locally. |

## Sensors

The integration creates sensors dynamically based on the data returned by the API:

- **Metering sensors** – one per numeric field (e.g. `energyIn`, `energyOut`, `reactivePower`). Device class and unit are inferred automatically.
- **Rate-limit diagnostics** – last request time, next allowed time, blocked count, and server rate-limit headers (if returned).
- **History diagnostics** – whether cached history is available and how many data-points are stored.

## Local development

```bash
# Clone the repo
git clone https://github.com/kaarelkelk/homeassistant-elering.git
cd homeassistant-elering

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install runtime + dev dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Running in a Home Assistant dev container

Mount or symlink `custom_components/elering_estfeed` into the container's `config/custom_components/` path and restart Home Assistant.
Runtime dependencies listed in `manifest.json` are installed automatically by HA on first load.

### Linting & formatting

```bash
ruff check custom_components/ tests/
black --check custom_components/ tests/
```

### Tests

```bash
pytest
```

## Project structure

```
homeassistant-elering/
├── custom_components/
│   └── elering_estfeed/
│       ├── __init__.py          # Integration setup & service registration
│       ├── api.py               # API client (OAuth2, rate limiting, endpoints)
│       ├── config_flow.py       # Config flow + options flow
│       ├── const.py             # Constants & default values
│       ├── coordinator.py       # DataUpdateCoordinator
│       ├── diagnostics.py       # Diagnostics dump (redacts secrets)
│       ├── history.py           # Historical data backfill & local cache
│       ├── manifest.json        # HA integration manifest
│       ├── sensor.py            # Dynamic sensor platform
│       ├── services.yaml        # Service definitions (UI)
│       ├── strings.json         # i18n source strings
│       └── translations/
│           └── en.json          # English translations
├── tests/
│   ├── conftest.py              # Shared test fixtures
│   ├── test_config_flow.py      # Config flow tests
│   ├── test_coordinator.py      # Coordinator tests
│   └── test_rate_limiter.py     # Rate limiter tests
├── hacs.json                    # HACS metadata
├── pyproject.toml               # Tooling config (pytest, ruff, black)
├── requirements.txt             # Runtime dependencies
├── requirements-dev.txt         # Development dependencies
├── LICENSE                      # MIT
└── README.md
```

## License

[MIT](LICENSE)
