# PM2.5 / PM10 Monitor — Radxa ZERO 3W on DietPi Plan

**Status:** Phase 2 implemented in the working tree; hardware validation pending · **Complexity:** Medium

Last updated: 2026-10-16

### Change log

- **2026-10-16 — Tailscale OTA and lockdown:** added staged/pull/request/reinstall updates,
  fast-forward-only application with `flock` and rollback to the previous commit on failed
  health checks; dev-box push with optional offline wheels; authenticated tailnet/loopback
  API requests and root path-unit execution; optional nightly pulls; `[update]` config;
  nftables egress lockdown; `tailscale serve` HTTPS; unattended `TS_AUTHKEY` join; LF
  enforcement for scripts/units. Guide: [docs/OTA.md](docs/OTA.md).
  Checks reported passed: 106/106 unit tests (`python -m unittest discover -s tests`),
  `bash -n` on all deploy scripts, and ruleset rendering with `firewall.sh print`.
  On-device checks: not run. Changes, including the earlier Radxa support, are uncommitted;
  branch/HEAD and pushed state were not supplied.
  Unverified: nft `socket cgroupv2 level 2` requires nft >= 1.0; tailscaled bypass mark
  `0x80000`; uv cross-platform aarch64 wheel builds; hatchling availability for offline
  editable installs.
  Next: flash DietPi on the Radxa ZERO 3W and test first boot with `TS_AUTHKEY`, `ota-push`,
  rollback, and lockdown on-device.

This plan moves the sensor node to a **Radxa ZERO 3W** running **DietPi**. The board has an RK3566 SoC, a 4× Cortex-A55 CPU, 2 GB of RAM on the target board, a 32 GB microSD card for storage, and Wi-Fi 6. The plan also uses the extra headroom to improve data quality and charts. The sensor contract, AQI math, data model, and offload protocol from [PLAN.md](PLAN.md) and [PLAN-pi4.md](PLAN-pi4.md) stay the same.

---

## 1. Assessment

### Hardware fit

| | Pi Zero 2 W | Radxa ZERO 3W |
|---|---|---|
| CPU | 4× A53 @ 1 GHz | 4× A55 @ 1.6 GHz (~1.5–2× faster) |
| RAM | 512 MB | 2 GB on the target board (ample) |
| Storage | microSD | 32 GB microSD on the target board (no eMMC) |
| Wi-Fi | 2.4 GHz b/g/n | Wi-Fi 6 / BT 5.4, external antenna option |
| GPIO stack | `gpiozero` + `lgpio` (BCM numbering) | **libgpiod** (gpiochip + line); BCM numbers do not apply |
| Serial | `/dev/ttyAMA0` on pins 8/10 | Pins 8/10 are the **debug console (UART2, 1500000 baud)** and must not be used |
| Boot config | `/boot/config.txt`, `cmdline.txt` | `/boot/dietpiEnv.txt` with device-tree overlays |

The full stack runs comfortably on the board: reader, Flask/waitress, SQLite, the sync and alert timers, Tailscale or cloudflared, and the prebuilt React dashboard. Only the hardware glue is Pi-specific.

### What already works well (keep it)

- EPA/Barkjohn humidity correction ([aqi.py](src/pm25/aqi.py)), which analytics prefers when RH is available.
- NowCast, events classification, and the diurnal forecast.
- Duty-cycled sampling (180 s period, 30 s warm-up, 8 s burst), which protects laser life.
- Self-healing reader (RESET after 3 failures, UART reopen after 6).
- Rollups kept forever. Raw rows are pruned only after the VPS acknowledges them.
- SSE live tiles and dashboard views drawn as hand-built SVG (no chart-library weight).

### Pi-specific code that blocked the port (resolved)

All rows below were addressed in Phase 2.

| Location | Problem | Resolution |
|---|---|---|
| [config.py](src/pm25/config.py), [config.example.toml](config.example.toml) | Defaults `device="/dev/ttyAMA0"`, `pin_enable=22`, `pin_reset=27` (BCM). | Pi defaults kept; Radxa values documented; `install.sh` writes them on a Radxa. |
| [pms5003.py](src/pm25/pms5003.py) | SET and RESET use `gpiozero.OutputDevice`, which has no reliable RK3566 backend. | Pins may be `"gpiochipN:line"`, driven through libgpiod (v1 or v2). |
| [setup.py](src/pm25/setup.py) | Probes only `/dev/i2c-1` and `/dev/i2c-0`. | The wizard asks for the I2C bus and probes it. |
| [sensor_sht31.py](src/pm25/sensor_sht31.py) | The I2C bus number must be configurable. | New `sensor.i2c_bus` setting (default `1`). |
| [deploy/install.sh](deploy/install.sh) | Edits `config.txt` and `cmdline.txt`, disables `hciuart` and `serial-getty@ttyAMA0`. | Board detection in [deploy/board.sh](deploy/board.sh); Pi-only steps skipped on Radxa. |
| [deploy/dietpi/](deploy/dietpi/) | The zero-touch flow assumes a Pi image. | Inherits detection; optional `BOARD` override. |
| [pyproject.toml](pyproject.toml) | The `pi` extra pulls `gpiozero` and `lgpio`. | New `radxa` extra with `pyserial`, `smbus2`, `gpiod`. |

---

## 2. Wiring (40-pin header)

The ZERO 3W uses the Pi header layout, but the pin functions differ. Pin 3, 5, 27, and 28 have I2C pull-ups. The step-by-step build is in [docs/hardware/HARDWARE_SETUP-radxa.md](docs/hardware/HARDWARE_SETUP-radxa.md).

| Signal | Radxa pin | SoC function | Linux node (expected) |
|---|---|---|---|
| PMS5003 VCC (5 V) | 2 or 4 | +5 V | — |
| PMS5003 GND | 6 | GND | — |
| PMS5003 TX → board RX | **16** | UART4_RX_M1 (GPIO3_B1) | `/dev/ttyS4` |
| PMS5003 RX ← board TX | **18** | UART4_TX_M1 (GPIO3_B2) | `/dev/ttyS4` |
| SHT31 VIN / GND | 1 / 9 | 3.3 V / GND | — |
| SHT31 SDA | **3** | I2C3_SDA_M0 (GPIO1_A0) | `/dev/i2c-3` |
| SHT31 SCL | **5** | I2C3_SCL_M0 (GPIO1_A1) | `/dev/i2c-3` |
| PMS5003 SET (optional) | 15 | GPIO3_B0 | gpiochip3 line 8 |

Alternatives:
- SHT31 on I2C4 (pins 27/28) gives `/dev/i2c-4`.
- PMS5003 on UART9_M1 (pin 21 TX, pin 24 RX).

Do **not** use pins 8/10. Debug-console input during boot can stop U-Boot.

Start with SET and RESET unwired (`-1`). The reader then sleeps and wakes the sensor with UART commands, so no GPIO library is needed on day one.

---

## 3. Phased plan

### Phase 0 — Image and base OS
1. Flash the DietPi **Radxa ZERO 3** image. Use the 32 GB microSD card. A high-endurance or A1/A2-rated card is best.
2. Pre-seed `dietpi.txt` for headless Wi-Fi, hostname, timezone, and SSH, as in [deploy/dietpi/dietpi.txt.snippet](deploy/dietpi/dietpi.txt.snippet).
3. First boot: confirm Wi-Fi, run `dietpi-update`, and confirm time sync (`timedatectl`). The board has no RTC.

### Phase 1 — Enable UART and I2C overlays
1. List the overlays the image ships: `ls /boot/dtb/rockchip/overlay/`.
2. Edit `/boot/dietpiEnv.txt` to match the real filenames. The prefix and name format vary by image, so verify them first. The expected shape is:
   ```
   overlay_path=rockchip
   overlay_prefix=rk3568
   overlays=uart4-m1 i2c3-m0
   ```
3. Reboot, then verify:
   - `dmesg | grep -i overlay`
   - `ls /dev/ttyS* /dev/i2c-*`
   - `i2cdetect -y 3` shows `0x44`.
   - `cat /dev/ttyS4 | xxd | head` shows `42 4d` frames.
4. Check that no `serial-getty` runs on the chosen UART.
5. Known risk: DietPi issue MichaIng/DietPi#7573 reports overlay-prefix problems on the Zero 3. If overlays do not load, try the `radxa-zero3` prefix or copy the `.dtbo` files from the Radxa overlay package.

### Phase 2 — Code changes for the port (done)
1. **Config:** keep the Pi defaults, document Radxa values in `config.example.toml`, and add `sensor.i2c_bus` (default `1`).
   Radxa values: `device="/dev/ttyS4"`, `pin_enable=-1`, `pin_reset=-1`, `i2c_bus=3`.
2. **GPIO backend:** `make_output()` in `pms5003.py` picks the backend.
   - An integer pin uses `gpiozero` (Pi).
   - `"gpiochipN:line"` uses `gpiod` (for example `"gpiochip3:8"`).
   - `-1` means UART commands only.
3. **SHT31:** `i2c_bus` is passed to the driver. `pm25-setup` asks for the bus number and probes it for `0x44`/`0x45`.
4. **Install script:** [deploy/board.sh](deploy/board.sh) detects the board from `PM25_BOARD`, `/proc/device-tree/model`, or `/boot/dietpiEnv.txt`.
   - Pi-only `config.txt`, Bluetooth, and getty steps are skipped on Radxa.
   - Overlay instructions are printed instead of edited, because names vary.
   - A fresh `config.toml` gets the Radxa values and `commit_interval_s = 300`.
5. **Packaging:** the `radxa` extra in `pyproject.toml` has `pyserial`, `smbus2`, and `gpiod`. `install.sh` and `update.sh` run `uv sync --extra <board>`.
6. **DietPi automation:** `Automation_Custom_Script.sh` relies on auto-detection, with an optional `BOARD` override.

### Phase 3 — Better data
1. **Robust burst statistic:** use the median or a 20% trimmed mean in `reader._avg` instead of a plain mean.
2. **Spike rejection:** drop frames more than 3 MAD from the burst median.
3. **Settle frames:** discard the first 2–3 frames after wake, even after warm-up.
4. **Quality columns:** store the per-burst sample count and spread (stddev or IQR), and flag rows with low counts.
5. **Keep full sensor output:** CF1, ATM, and the six particle-count bins, for later recalibration.
6. **Time integrity:** do not write samples until NTP sync is confirmed, and mark rows written before sync.
7. **RH and temperature placement:** mount the SHT31 away from the RK3566. The board runs warmer than a Pi Zero, and heat skews RH and the humidity correction. Use a radiation shield or a short cable.
8. **Sampling cadence (optional):** a 120 s period gives finer charts. Each step down costs PMS5003 laser life (about 8,000 h rated), so keep duty cycling.
9. **Storage (32 GB microSD):** the default `commit_interval_s = 0` writes on every sample. Set it to `300` to batch writes and reduce card wear. Keep DietPi's RAM-backed `/var/log` (DietPi-RAMlog), and do not add swap on the card. With 2 GB of RAM, swap is not needed. At about one row per sample, 30 days of raw data plus the rollups are only a few megabytes, so 32 GB leaves ample room for longer retention. Take regular backups, because microSD cards fail without warning.

### Phase 4 — Better charts
1. **Server-side downsampling:** apply LTTB or min/max buckets in [analytics.py](src/pm25/analytics.py) so 30-day and 1-year views stay sharp and light.
2. **Raw vs corrected overlay:** show raw CF1 PM2.5 and corrected PM2.5 together, with RH on a second axis.
3. **Uncertainty bands:** shade the burst spread or the hourly min/max around the line.
4. **Explicit gaps:** break lines where data is missing, using the coverage data already computed.
5. **AQI category bands:** draw background bands and annotate detected events on History.
6. **Particle-size view:** a stacked chart of the count bins helps tell smoke from dust.
7. **Daily and weekly comparisons:** compare this week with last week and with the typical diurnal profile.

The charts are hand-built SVG in [HistoryView.tsx](aqi-worker/web/src/components/views/HistoryView.tsx) and [PatternsView.tsx](aqi-worker/web/src/components/views/PatternsView.tsx). Keep it that way and add the features through the existing components. The dashboard is still built off-device.

### Phase 5 — Verify and soak
1. Unit tests for the burst statistics, the GPIO backend selection, the I2C bus discovery, and the downsampling.
2. On-device checks:
   - `pm25-setup` passes.
   - The reader logs valid frames.
   - The dashboard loads on `:8080`.
   - Sync acknowledgements arrive.
3. A 7-day soak. Watch frame error rate, coverage %, CPU temperature (`/sys/class/thermal`), Wi-Fi drops, and disk writes.
4. Update the README and the DietPi docs with the Radxa wiring and overlay steps.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| Overlay names or prefix differ in the DietPi image | Verify `/boot/dtb/rockchip/overlay/` before editing. Fallback: Radxa `.dtbo` files. |
| `/dev/ttySx` or `/dev/i2c-x` numbering differs | Keep paths in config. Have `setup.py` discover them. |
| Board heat biases RH | Separate the SHT31 and shield it. |
| No RTC means bad timestamps after a power cut | Gate writes on NTP sync. |
| Accidental use of the debug UART | Document pins 8/10 as forbidden. |
| Weak Wi-Fi in an enclosure | Use the external antenna. |

## 5. Open questions

- Are the PMS5003 SET and RESET lines wired, or is UART-only sleep acceptable?
- Is the SHT31 present on every node?
