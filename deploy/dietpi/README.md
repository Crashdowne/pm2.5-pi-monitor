# Zero-touch DietPi deployment (headless, no GUI)

Flash once, drop three files on the boot partition, power on. On first boot DietPi
installs itself unattended and runs our installer, which sets up the venv, systemd
services, UART/I2C, and Tailscale.

## 1. Flash the image

Use the **DietPi ARM64 (64-bit) image for Raspberry Pi Zero 2 W** (Debian Trixie).
64-bit + Trixie (glibc 2.41) means every Python dependency installs from a prebuilt
wheel — no on-device compiler needed.

## 2. Configure the boot partition (FAT, mounts as `/boot`)

After flashing, the boot partition is readable on your PC. Then:

1. Edit `dietpi.txt`: apply the keys from [dietpi.txt.snippet](dietpi.txt.snippet)
   (set your timezone, hostname, and Wi-Fi country).
2. Copy [dietpi-wifi.txt](dietpi-wifi.txt) to the boot partition and fill in your SSID/key.
3. Copy [Automation_Custom_Script.sh](Automation_Custom_Script.sh) to the boot partition
   and set `REPO_URL`.

## 3. Boot

Insert the card and power the Pi. First-run setup takes a while (it downloads Python and
dependencies). To watch progress, SSH in and tail
`/var/tmp/dietpi/logs/dietpi-firstrun-setup.log`.

## 4. Join Tailscale

The installer sets up the Tailscale client and starts `tailscaled`. After first boot, SSH
in and run `sudo tailscale up`, then open the printed login link on any device signed into
your tailnet to add the monitor.

The dashboard is then at `http://<pi-hostname-or-ip>:8080`.

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
sudo tailscale up         # join your tailnet (opens a login link)
```
