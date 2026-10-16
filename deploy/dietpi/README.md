# Zero-touch DietPi deployment (headless, no GUI)

Flash once, drop a few files on the boot partition, power on. On first boot DietPi
installs itself unattended and runs our bootstrap, which joins Tailscale, fetches the app
from your dev machine over the tailnet, and runs the installer (venv, systemd services,
UART/I2C, HTTPS, egress lockdown).

**Step-by-step guide with tailnet setup, fallbacks, and troubleshooting:
[docs/SETUP.md](../../docs/SETUP.md).** This page is the short version.

## 1. Flash the image

Use the **DietPi ARM64 (64-bit) image for Raspberry Pi Zero 2 W** (Debian Trixie).
64-bit + Trixie (glibc 2.41) means every Python dependency installs from a prebuilt
wheel — no on-device compiler needed.

**Radxa ZERO 3W:** use the DietPi image for the Radxa ZERO 3 instead. The same flow works;
`install.sh` detects the board, installs the `radxa` extra, and writes Radxa defaults.
Enable the UART and I2C overlays by hand afterwards, as described in
[HARDWARE_SETUP-radxa.md](../../docs/hardware/HARDWARE_SETUP-radxa.md).

## 2. Configure the boot partition

After flashing, the boot partition is readable on your PC. On Raspberry Pi images it is the
FAT boot partition. On Radxa images it is a small (1 MiB) `DIETPISETUP` partition. DietPi
imports only its own files from it (`dietpi.txt`, `dietpi-wifi.txt`, and the two
`Automation_Custom_*` scripts) and then deletes it, so extra drop-in files only work on Pi.

1. Edit `dietpi.txt`: apply the keys from [dietpi.txt.snippet](dietpi.txt.snippet)
   (set your timezone, hostname, and Wi-Fi country).
2. Copy [dietpi-wifi.txt](dietpi-wifi.txt) to the boot partition and fill in your SSID/key.
3. Run `deploy/serve-source.sh` on your dev machine. It serves a git bundle of the app over
   the tailnet and prints `SOURCE_URL` and `SOURCE_SHA256`.
4. Copy [Automation_Custom_Script.sh](Automation_Custom_Script.sh) to the boot partition
   and set `TS_AUTHKEY` (a one-off, pre-approved, tagged key), `TS_HOSTNAME`, `SOURCE_URL`,
   and `SOURCE_SHA256`. `REPO_URL` is an optional internet fallback. `TS_HTTPS=1` and
   `LOCKDOWN=1` are the defaults. See [docs/OTA.md](../../docs/OTA.md) for the tailnet ACL.
5. Copy [Automation_Custom_PreScript.sh](Automation_Custom_PreScript.sh) unchanged. It
   installs the bootstrap's retry timer early, so Tailscale and the app still get installed
   if DietPi's first-run setup fails.

## 3. Boot

Insert the card and power the board. First-run setup takes a while (it downloads Python and
dependencies). Progress: `/var/tmp/dietpi/logs/dietpi-firstrun-setup.log` and
`/var/lib/pm25/bootstrap.log` on the device. On Pi, the bootstrap log is also copied to the
boot partition as `pm25-bootstrap.log`, readable on your PC. If the source isn't reachable
yet, the bootstrap retries every 15 minutes.

## 4. Join Tailscale

With `TS_AUTHKEY` set, the device joins the tailnet on its own (with Tailscale SSH),
publishes the dashboard at `https://<TS_HOSTNAME>.<tailnet>.ts.net`, and then turns on the
egress lockdown. After that, all internet traffic except Tailscale (plus DNS and NTP) is
blocked.

Without a key, SSH in after first boot and run
`sudo tailscale up --ssh --hostname pm25`, then open the printed login link on any device
signed into your tailnet. To get HTTPS, also run
`sudo tailscale serve --bg --https=443 http://127.0.0.1:8080`.

On the LAN, the dashboard is also at `http://<pi-hostname-or-ip>:8080`.

## 5. Updates

The first boot is the only time the device needs the internet. Later updates arrive over
Tailscale. From your dev machine, run:

```bash
deploy/ota-push.sh pm25             # push HEAD and apply it (automatic rollback on failure)
deploy/ota-push.sh --wheels pm25    # also ship wheels when dependencies changed
```

Staged updates can also be applied from the dashboard (`POST /api/update`, tailnet only,
token in `/etc/pm25/update.env`). For one-off internet access, for example
`apt upgrade`, run `sudo pm25-firewall open 30`. Full details: [docs/OTA.md](../../docs/OTA.md).

## Optional: Cloudflare Tunnel (public sharing)

Tailscale already covers private remote access. Only add a Cloudflare Tunnel if you need to
expose the dashboard publicly — and put **Cloudflare Access** in front of it, because the
dashboard has no built-in authentication.

1. Install `cloudflared` (per Cloudflare's docs) so `/usr/bin/cloudflared` exists.
2. Create a tunnel in the Cloudflare Zero Trust dashboard and point its public hostname at
   `http://localhost:8080`.
3. Put the tunnel token in `/etc/pm25/cloudflared.env` (copy from
   [../cloudflared.env.example](../cloudflared.env.example); `root:root`, `chmod 600`).
4. Install and start the memory-capped unit:

   ```bash
   sudo install -m 644 deploy/pm25-cloudflared.service /etc/systemd/system/pm25-cloudflared.service
   sudo systemctl daemon-reload && sudo systemctl enable --now pm25-cloudflared
   ```

The unit is capped (`MemoryMax=150M`) and runs `--no-autoupdate` to avoid extra SD writes.

## Manual install (existing DietPi box)

```bash
git clone <repo> /opt/pm25 && cd /opt/pm25
sudo deploy/install.sh    # deps, UART/I2C, services, and the Tailscale client
sudo reboot               # applies the UART / Bluetooth change
sudo tailscale up --ssh   # join your tailnet (opens a login link)
```

Or run it unattended with Tailscale, HTTPS, and the lockdown:
`sudo TS_AUTHKEY=tskey-auth-... TS_HOSTNAME=pm25 PM25_TS_HTTPS=1 PM25_LOCKDOWN=1 deploy/install.sh`.
