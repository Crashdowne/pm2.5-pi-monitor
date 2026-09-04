# pi-aqi-monitor (aqi-site)

A **read-only analytics sidecar** for the [pm2.5-pi-monitor](../README.md) warehouse.
It runs on your VPS, is reachable only over **Tailscale**, reads the SQLite database
that `server/ingest.py` writes (never writing to it), and serves a rich ECharts
dashboard plus an **asthma-aware mask advisor**.

Published to Docker Hub as **`crashdowne/pi-aqi-monitor`**.

> Informational only — **not medical advice**. The mask guidance is derived from the
> public EPA/AirNow AQI bands and configurable thresholds. Follow your own asthma
> action plan and clinician.

## Features

- **Live AQI gauge** with NowCast AQI, corrected PM2.5/PM10, temp/RH, dominant pollutant.
- **History explorer** — PM2.5 / PM10 / AQI / temp / RH over 6h–1y with zoom and AQI band shading.
- **Yearly calendar heatmap**, **hour × weekday pattern**, **time-in-band donut**, **daily profile**.
- **Exposure report card** — 24h/7d/30d means, peak, unhealthy hours, cigarette-equivalent.
- **Mask advisor** — conservative, asthma-tuned levels with trend, personalization, and a best-window finder.
- **Alerts** — in-app banner plus ntfy / webhook push with hysteresis and quiet hours.
- **Multi-sensor**, installable **PWA**, dark theme.

## Data source

Temperature and humidity originate from the **GY-SHT31** (Sensirion SHT31-D) on the
Pi; the same RH drives the humidity-corrected PM2.5 (`pm2_5_corr`). These are
optional — when the sensor is disabled or a read fails, charts and corrections fall
back to raw PM2.5. See [PLAN.md](PLAN.md).

## Quick start (Docker)

```bash
# From the repo root:
docker compose -f aqi-site/docker-compose.yml up -d --build
```

The warehouse directory is mounted at `/data`. Reading a **live** WAL database needs
write access to that directory so SQLite can attach its `-shm`/`-wal` files — the app
enforces `PRAGMA query_only` so it can never modify your data. To read a **static
snapshot** instead, set `AQI_SITE_DB_IMMUTABLE=true` and mount the warehouse `:ro`.

### Tailscale

Bind the published port to your tailnet only (e.g. map to your Tailscale IP in
`docker-compose.yml`) and restrict access with a tailnet ACL. There is no login —
the tailnet is the authentication boundary.

## Configuration

Copy [`config.example.toml`](config.example.toml) and mount it at `/config/config.toml`,
or override any value with environment variables:

| Env | Default | Purpose |
| --- | --- | --- |
| `AQI_SITE_DB` | `/data/pm25.db` | Warehouse database path |
| `AQI_SITE_DB_IMMUTABLE` | `false` | Read a static snapshot (`immutable=1`) |
| `AQI_SITE_STATE_DB` | `/state/aqi-site-state.db` | Sidecar alert-state store |
| `AQI_SITE_HOST` / `AQI_SITE_PORT` | `0.0.0.0` / `8080` | Bind address |
| `AQI_SITE_CONFIG` | — | Path to a TOML config file |
| `AQI_SITE_DEFAULT_SENSOR` | most recent | Default sensor in the UI |

Mask sensitivity presets (NowCast-AQI thresholds for carry/recommended/strong/indoors):

| Preset | carry | recommended | strong | indoors |
| --- | --- | --- | --- | --- |
| general | 76 | 101 | 151 | 301 |
| **asthma** (default) | 51 | 76 | 101 | 201 |
| very_sensitive | 26 | 51 | 76 | 151 |

## API (read-only)

`GET /healthz` · `GET /api/config` · `GET /api/sensors` ·
`GET /api/sensors/<id>/{current,history,calendar,heatmap,distribution,diurnal,summary,mask,export}` ·
`GET|POST /api/alerts`

## Development

```bash
# Backend (from the repo root) — serve against a seeded/real warehouse:
AQI_SITE_DB=/path/to/pm25.db AQI_SITE_STATE_DB=/tmp/state.db \
  PYTHONPATH=aqi-site uv run python -m aqi_site

# Tests:
uv run python -m unittest discover -s aqi-site/tests -t aqi-site

# Frontend (hot reload, proxies /api to :8080):
cd aqi-site/web && npm install && npm run dev
# Production build (output to aqi-site/web/dist, served by the backend):
npm run build
```
