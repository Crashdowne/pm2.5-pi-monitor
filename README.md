# PM2.5 / PM10 Pi Monitor

Outdoor particulate monitor: a **Raspberry Pi Zero 2 W + PMS5003** on **DietPi** that reads
the sensor, stores readings in SQLite, serves an **installable PWA dashboard** (current +
hourly + daily + weekly averages with US-EPA AQI, plus SHT31 temperature/humidity history),
and offloads history to a central server over **Tailscale** before pruning locally.

See [PLAN.md](PLAN.md) for the full design, research, and roadmap.

## Layout

```
src/pm25/    reader · db · aqi · sensors · simulation · api · web · sync · alerts · config
web/         no-build PWA (index.html · app.js · charts.js · sw.js · manifest · icon)
deploy/      install.sh · update.sh · systemd units
server/      authenticated multi-sensor warehouse + fleet dashboard
```

## Hardware wiring (PMS5003 -> Pi 40-pin)

For illustrated, hardware-only assembly instructions covering both sensors, the microSD
card, power, and jumper options, see the [step-by-step hardware guide](docs/hardware/HARDWARE_SETUP.md).

| PMS5003 | Function | Pi phys pin | Pi GPIO |
|---|---|---|---|
| VCC | 5 V | 2 or 4 | 5 V |
| GND | Ground | 6 | GND |
| TXD | sensor -> Pi | 10 | GPIO15 (RXD) |
| SET | enable/sleep (opt.) | 15 | GPIO22 |
| RESET | reset (opt.) | 13 | GPIO27 |

Minimum to read = VCC, GND, TXD->RXD. SET/RESET enable duty-cycling. Logic is 3.3 V TTL (no
level shifter needed). An **SHT31-D** humidity/temp sensor (I2C, address `0x44`; SDA=GPIO2
pin 3, SCL=GPIO3 pin 5) is enabled in the sample config; `install.sh` turns on I2C. Set
`sht31.enabled = false` if you haven't wired it. When RH is available, PM2.5 is
humidity-corrected (EPA/Barkjohn); the local and fleet dashboards show corrected PM plus
hourly temperature and relative-humidity history. Enabling `sht31` later starts climate
history from that point on; earlier readings are not back-filled, since past relative
humidity was never stored.

## Install on the Pi (DietPi)

Use the **DietPi ARM64 (64-bit) image** (Debian Trixie) for the Pi Zero 2 W. 64-bit +
Trixie (glibc 2.41) lets every Python dependency install from a prebuilt wheel, so no
compiler is needed on the Pi.

**Zero-touch (headless, no GUI):** flash the image, then drop three files on the boot
partition for a fully unattended first-boot install - see
[deploy/dietpi/README.md](deploy/dietpi/README.md).

**Manual:**

```bash
git clone <repo> /opt/pm25 && cd /opt/pm25
sudo deploy/install.sh      # deps, UART/I2C, systemd services, and the Tailscale client
sudo reboot                 # applies the UART / Bluetooth change
sudo tailscale up           # join your tailnet (opens a login link)
```

`install.sh` also installs the Tailscale client and enables `tailscaled`; join your tailnet
after first boot by running `sudo tailscale up` (it prints a login link to open on any
device signed into your tailnet). It writes `/etc/pm25/config.toml` from the example on
first run. The dashboard is then at `http://<pi-lan-or-tailscale-ip>:8080`. Installation
creates the complete SQLite schema, including SHT31 temperature and humidity rollups, before
starting the services.

### Services

| Unit | Role |
|---|---|
| `pm25-reader.service` | reads the PMS5003 -> SQLite (raw + rollups) |
| `pm25-web.service` | Flask + waitress API and PWA on port 8080 |
| `pm25-sync.timer` | offload to the server over Tailscale, then prune (every 6 h) |
| `pm25-alert.timer` | evaluate AQI, stale sensor, sync, and disk alerts (every 2 min) |
| `pm25-wifi-powersave.service` | disable Wi-Fi power save so the dashboard stays reachable |

Services run under systemd memory caps (`MemoryMax`), and the journal is kept in RAM
(`Storage=volatile`) so the SD card mostly sees database writes, not logs. An optional,
memory-capped Cloudflare Tunnel unit ([deploy/pm25-cloudflared.service](deploy/pm25-cloudflared.service))
is available if you must expose the dashboard publicly — keep it behind Cloudflare Access.

Update in place: `sudo deploy/update.sh` (`git pull` + `uv sync` + restart).

## Choosing a backend

History can be offloaded to one of two backends:

- **Cloudflare Worker + D1 ([aqi-worker/](aqi-worker/), recommended).** The Pi *pushes* to a
  serverless Worker (no inbound path to the Pi), which stores readings in D1 and serves a
  public, read-only dashboard on Cloudflare's free tier. Gate alert-config edits with an
  `ADMIN_TOKEN` secret and add a Cloudflare rate-limiting rule on `/ingest`. See
  [aqi-worker/PLAN.md](aqi-worker/PLAN.md).
- **Self-hosted warehouse ([server/ingest.py](server/ingest.py), legacy).** A small
  Flask/waitress app on a tailnet host, described below. Still supported for fully
  self-hosted setups.

Both speak the same ingest contract
([contracts/ingest_ranges.json](contracts/ingest_ranges.json)), so the Pi repoints with
only a `sync.server_url` (and auth-header) change.

## Enabling Tailscale offload

1. Stand up the server (see below) and note its MagicDNS name / tailnet IP.
2. On the Pi, put the shared token in `/etc/pm25/sync.env`:
   `PM25_SYNC_TOKEN=<token>` (readable only by root, sync, and alert services).
3. In `/etc/pm25/config.toml` set `[sync] enabled = true`, `server_url`, and a unique
   `sensor_id` when operating multiple monitors.
4. `sudo systemctl restart pm25-sync.timer`.

The Pi pushes unacknowledged raw rows and marks each row only after the server accepts its batch.
Pruning removes only acknowledged rows. Rollups stay on the Pi so the weekly view works offline.

## Server (warehouse) — self-hosted (legacy)

> The Cloudflare Worker in [aqi-worker/](aqi-worker/) is the recommended backend (see
> [Choosing a backend](#choosing-a-backend)). Use this self-hosted warehouse only if you
> prefer to run your own host.

```bash
export PM25_INGEST_TOKEN=<same-token>
uv run python server/ingest.py --db /var/lib/pm25-server/pm25.db --port 9000
```

Bind it to the Tailscale interface and lock it down with a tailnet ACL so only the Pi's tag
can reach the ingest port. Open the same address in a browser for the fleet dashboard. The
read API and dashboard are unauthenticated by default (tailnet-only); set `PM25_READ_TOKEN`
to require HTTP Basic auth on them without affecting token-based ingest.

For per-monitor credentials, replace the shared token with a JSON map:

```bash
export PM25_INGEST_TOKENS='{"porch":"token-one","garage":"token-two"}'
```

Existing single-monitor warehouse databases migrate automatically to sensor ID `default`.

## Alerts

Set `[alerts] enabled = true` and `webhook_url` in `/etc/pm25/config.toml`. The webhook
receives small JSON transition events for sustained high AQI, recovery, stale readings,
sync failures, and low disk space. Optional webhook authentication uses the environment
variable named by `alerts.token_env`; put that value in `/etc/pm25/sync.env`.

After changing `alerts.enabled`, apply the timer state with:

```bash
sudo systemctl enable --now pm25-alert.timer   # enabled = true
sudo systemctl disable --now pm25-alert.timer  # enabled = false
```

The install and update scripts apply this automatically. Keeping the timer disabled with
alerts avoids launching an otherwise idle Python process every two minutes.

AQI alerts require consecutive checks and use separate trigger/recovery thresholds plus a
cooldown, preventing repeated notifications when values hover near a boundary.

## Local development (no hardware)

```bash
uv sync                     # core deps only (no serial/GPIO)
uv run python -m pm25.web --config config.example.toml
```

Run a deterministic simulated reader without Pi hardware:

```bash
uv run python -m pm25.reader --config config.example.toml --simulate normal
# profiles: normal, smoke, faulty
```

Run all regression tests with:

```bash
uv run python -W error::ResourceWarning -m unittest discover -s tests -v
```

## Security notes

- Dashboard + ingest are **LAN/tailnet only** by default - no public exposure, no Tailscale
  Funnel. The optional Cloudflare Tunnel unit is the one exception; gate it with Cloudflare
  Access, since the dashboard has no built-in authentication.
- Ingest requires a bearer token and should be bound to `tailscale0` behind an ACL.
- The Cloudflare Worker keeps its dashboard public but gates alert-config writes behind an
  `ADMIN_TOKEN` secret (fail-closed when unset); add a Cloudflare rate-limiting rule on
  `/ingest`. The self-hosted warehouse can require HTTP Basic on reads via `PM25_READ_TOKEN`.
- Responses carry a strict Content-Security-Policy plus `X-Content-Type-Options`,
  `Referrer-Policy`, and `X-Frame-Options`.
- All SQL is parameterized; API query params are whitelisted.
- Pi services use separate identities: only `pm25-reader` receives serial/GPIO/I2C access,
   only sync/alerts can read secrets, and all four share the SQLite data group.
