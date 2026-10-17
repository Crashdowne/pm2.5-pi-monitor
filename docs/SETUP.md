# Setup guide: from blank microSD to a locked-down monitor

This guide builds a PM2.5 monitor on DietPi with no keyboard, monitor, or manual SSH. It
covers both supported boards:

- **Raspberry Pi Zero 2 W**
- **Radxa ZERO 3W** (2 GB RAM recommended; any size works)

On first boot the device:

1. installs DietPi unattended;
2. installs Tailscale and joins your tailnet;
3. downloads the app from your dev machine **over the tailnet**;
4. installs it, serves the dashboard over HTTPS with `tailscale serve`, and blocks all
   other internet traffic.

From then on, updates, data offload, and remote access go through Tailscale only. See
[OTA.md](OTA.md) for updates after setup.

## Contents

1. [What you need](#1-what-you-need)
2. [Wire the sensors](#2-wire-the-sensors)
3. [Prepare your tailnet (once)](#3-prepare-your-tailnet-once)
4. [Serve the app from your dev machine](#4-serve-the-app-from-your-dev-machine)
5. [Flash the microSD card](#5-flash-the-microsd-card)
6. [Put the setup files on the card](#6-put-the-setup-files-on-the-card)
7. [First boot](#7-first-boot)
8. [Verify](#8-verify)
9. [If first boot doesn't work](#9-if-first-boot-doesnt-work)
10. [Troubleshooting](#10-troubleshooting)

## 1. What you need

| Item | Notes |
|---|---|
| Board | Raspberry Pi Zero 2 W or Radxa ZERO 3W |
| microSD | 32 GB, A1/A2 class, from a known brand |
| Sensors | Plantower PMS5003 (PM) and a 3.3 V SHT31 breakout (temperature/humidity) |
| Power | 5 V, 2 A or more; USB-C for the Radxa |
| Wi-Fi | 2.4 GHz is the most reliable for an outdoor node |
| Dev machine | Linux, macOS, or Windows with Git Bash; Tailscale installed and signed in |
| Tailscale account | Admin rights on the tailnet |

The first boot needs **internet access** for DietPi, apt packages, Tailscale, and Python
wheels. The app source itself never touches the internet. After the installer finishes, the
egress firewall blocks everything except Tailscale, DNS, and NTP.

## 2. Wire the sensors

Wire the board before powering it. Follow the guide for your board:

- Raspberry Pi Zero 2 W: [hardware/HARDWARE_SETUP.md](hardware/HARDWARE_SETUP.md)
- Radxa ZERO 3W: [hardware/HARDWARE_SETUP-radxa.md](hardware/HARDWARE_SETUP-radxa.md)

The PMS5003 uses a UART and 5 V; the SHT31 uses I2C (pins 3/5) and **3.3 V only**. The
UART pins differ between boards (Pi: pins 8/10; Radxa: UART4), so follow the pin table in
your board's guide exactly.

## 3. Prepare your tailnet (once)

In the [Tailscale admin console](https://login.tailscale.com/admin):

1. **DNS:** turn on **MagicDNS** and **HTTPS certificates**. The device needs these to get a
   trusted certificate for `https://pm25.<tailnet>.ts.net`, and to resolve your dev
   machine's name.
2. **Access controls:** add a tag for the monitors, let admins reach them (including
   Tailscale SSH as root, which OTA pushes use), and let the monitors reach your dev machine
   on port 8443 for the first-boot download. Replace `you@example.com` with the user that
   owns your dev machine, or with its tag:

   ```jsonc
   {
     "tagOwners": { "tag:pm25": ["autogroup:admin"] },
     "grants": [
       { "src": ["autogroup:admin"], "dst": ["tag:pm25"], "ip": ["*"] },
       { "src": ["tag:pm25"], "dst": ["you@example.com"], "ip": ["tcp:8443"] }
     ],
     "ssh": [
       { "action": "accept", "src": ["autogroup:admin"], "dst": ["tag:pm25"], "users": ["root"] }
     ]
   }
   ```

   Merge these entries into your existing policy instead of replacing it.
3. **Auth key:** **Settings → Keys → Generate auth key**. Choose:
   - **Reusable: off** (one device per key);
   - **Pre-approved: on**;
   - **Tags: `tag:pm25`**;
   - a short expiry, such as one day.

   Tagged devices don't expire their node key, so the monitor stays on the tailnet.
4. **Never enable Funnel** for the monitor. Funnel would publish the dashboard, which has no
   login, to the internet.

## 4. Serve the app from your dev machine

Commit the version you want to install, then run, from the repository root:

```bash
deploy/serve-source.sh
```

It packages the commit as a single-file git bundle and serves it on your tailnet with
`tailscale serve` (tailnet only, never public). It prints two lines to paste into the
bootstrap script in step 6:

```text
SOURCE_URL="https://devbox.your-tailnet.ts.net:8443/pm25.bundle"
SOURCE_SHA256="3f5a…"
```

Options:

| Option | Effect |
|---|---|
| `--ref v1.2.0` | package a tag, branch, or commit instead of `HEAD` |
| `--port 8443` | HTTPS port (must match the ACL grant) |
| `--bundle-only` | write the bundle without serving it, for the SD-card drop-in (Pi only) |
| `--stop` | stop serving once the device is installed |

Uncommitted changes are **not** included; the script warns if there are any.

Leave it running until the device is installed. If the dev machine is off or asleep at
first boot, that's fine: the device retries every 15 minutes.

## 5. Flash the microSD card

1. Download the DietPi image for your board from <https://dietpi.com/#download>:
   - Raspberry Pi Zero 2 W: **ARMv8 (64-bit), Debian Trixie**;
   - Radxa ZERO 3W: **Radxa ZERO 3**.

   64-bit Trixie (glibc 2.41) means every Python dependency installs from a prebuilt
   wheel, so the device never compiles anything.
2. Flash it with [balenaEtcher](https://etcher.balena.io/) or Raspberry Pi Imager
   ("Use custom").
3. Unplug and replug the card so your PC mounts its boot partition.

### Which partition you'll see

| Board | Partition on your PC | What DietPi reads from it |
|---|---|---|
| Raspberry Pi | FAT boot partition (hundreds of MB) | everything; it stays mounted as `/boot` or `/boot/firmware` |
| Radxa ZERO 3W | 1 MiB `DIETPISETUP` partition | only `dietpi.txt`, `dietpi-wifi.txt`, `Automation_Custom_PreScript.sh`, and `Automation_Custom_Script.sh`; it's copied to `/boot`, then deleted |

On Radxa, any other file you put on the card (bundles, extra installers, key files) is
lost. Put everything into the four files above.

## 6. Put the setup files on the card

All the files are in [deploy/dietpi/](../deploy/dietpi/).

### 6.1 `dietpi.txt`

Edit the existing `dietpi.txt` on the card. **Don't replace the file**; change these keys
in place (they are listed in [dietpi.txt.snippet](../deploy/dietpi/dietpi.txt.snippet)):

```ini
AUTO_SETUP_ACCEPT_LICENSE=1
AUTO_SETUP_AUTOMATED=1
AUTO_SETUP_TIMEZONE=America/Los_Angeles
AUTO_SETUP_NET_HOSTNAME=pm25-monitor
AUTO_SETUP_NET_ETHERNET_ENABLED=0
AUTO_SETUP_NET_WIFI_ENABLED=1
AUTO_SETUP_NET_WIFI_COUNTRY_CODE=US
AUTO_SETUP_APT_INSTALLS=git iw ca-certificates curl
AUTO_SETUP_INSTALL_SOFTWARE_ID=58
AUTO_SETUP_CUSTOM_SCRIPT_EXEC=1
SURVEY_OPTED_IN=0
```

`AUTO_SETUP_INSTALL_SOFTWARE_ID=58` is DietPi's own Tailscale package. It gets installed
even if our script never runs, so you can still rescue the device (see section 9).

### 6.2 `dietpi-wifi.txt`

Edit the existing `dietpi-wifi.txt` (or copy [ours](../deploy/dietpi/dietpi-wifi.txt)) and
fill in `aWIFI_SSID[0]` and `aWIFI_KEY[0]`.

### 6.3 `Automation_Custom_Script.sh` (the bootstrap)

Copy [Automation_Custom_Script.sh](../deploy/dietpi/Automation_Custom_Script.sh) to the card
and edit the block at the top:

```bash
TS_AUTHKEY="tskey-auth-..."   # from step 3
TS_HOSTNAME="pm25"            # -> https://pm25.<tailnet>.ts.net
TS_HTTPS=1
LOCKDOWN=1
BOARD=""                      # empty = auto-detect
SOURCE_URL="https://devbox.your-tailnet.ts.net:8443/pm25.bundle"   # from step 4
SOURCE_SHA256="3f5a…"                                            # from step 4
REPO_URL=""                   # optional: internet git clone if SOURCE_URL fails
```

Save it with **LF line endings** (VS Code: bottom-right `CRLF` → `LF`). The repository's
`.gitattributes` already checks it out with LF.

The auth key is moved to `/etc/pm25/tailscale-authkey` (mode 600) on first boot, blanked
from every copy of the script, and shredded once Tailscale has joined.

### 6.4 `Automation_Custom_PreScript.sh` (the safety net)

Copy [Automation_Custom_PreScript.sh](../deploy/dietpi/Automation_Custom_PreScript.sh)
unchanged. DietPi runs it early, before networking. It installs the bootstrap as
`/usr/local/sbin/pm25-bootstrap` with a systemd timer, so the bootstrap still runs if
DietPi's first-run setup fails before it reaches the custom script.

### 6.5 Optional drop-ins (Raspberry Pi only)

Instead of `SOURCE_URL`, you can place these next to the scripts on a Pi card:

| File | Effect |
|---|---|
| `pm25.bundle` | the app, from `deploy/serve-source.sh --bundle-only --dir <card>`; no download needed |
| `pm25-installer.sh` | your own installer, run instead of the built-in fetch and install; see [pm25-installer.example.sh](../deploy/dietpi/pm25-installer.example.sh) |
| `pm25-tailscale-authkey` | the auth key, instead of `TS_AUTHKEY` in the script |

## 7. First boot

Eject the card, insert it, and power the board. What happens:

| Time (approx.) | Step |
|---|---|
| 0–2 min | PreScript installs the retry timer; DietPi expands the filesystem and connects Wi-Fi |
| 2–20 min | DietPi updates packages and installs Tailscale (ID 58) |
| end of DietPi setup | bootstrap: joins the tailnet, downloads `SOURCE_URL`, runs `deploy/install.sh` |
| +10–20 min | `install.sh`: apt packages, `uv`, Python, wheels, services, HTTPS, firewall |

The order of source attempts is: drop-in installer, drop-in bundle, `SOURCE_URL`,
`REPO_URL`. If none is available, the bootstrap leaves Tailscale running and retries every
15 minutes until one works. While DietPi's first run is still going, retries wait (for up
to one hour of uptime) so they don't fight over apt.

The device appears in the Tailscale admin console as `pm25` with tag `tag:pm25` as soon as
it joins, even before the app is installed.

### Watching progress

From your dev machine, once the device is on the tailnet:

```bash
tailscale ssh root@pm25 tail -f /var/lib/pm25/bootstrap.log
tailscale ssh root@pm25 tail -f /var/tmp/dietpi/logs/dietpi-firstrun-setup.log
tailscale ssh root@pm25 systemctl list-timers pm25-bootstrap.timer
```

On a Raspberry Pi you can also take the card out and read `pm25-bootstrap.log` on the boot
partition; the bootstrap copies its log there after every attempt.

## 8. Verify

1. Open `https://pm25.<tailnet>.ts.net` from any device on your tailnet. The certificate
   should be trusted.
2. Check the services and firewall:

   ```bash
   tailscale ssh root@pm25 'systemctl --no-pager status pm25-reader pm25-web; pm25-firewall status'
   ```

3. Confirm internet egress is blocked:

   ```bash
   tailscale ssh root@pm25 'curl -m 5 -sI https://example.com || echo blocked'
   ```

4. Stop serving the bundle on your dev machine:

   ```bash
   deploy/serve-source.sh --stop
   ```

5. Enable the Radxa UART and I2C overlays if you haven't (Radxa only, see
   [hardware/HARDWARE_SETUP-radxa.md](hardware/HARDWARE_SETUP-radxa.md)), then reboot.

From now on, update with `deploy/ota-push.sh pm25` (see [OTA.md](OTA.md)).

## 9. If first boot doesn't work

The setup has several layers so that one failure doesn't leave you with an unreachable
device.

| What failed | What still happens | What to do |
|---|---|---|
| Dev machine offline or `SOURCE_URL` wrong | Tailscale joins; bootstrap retries every 15 min | Start `serve-source.sh`, or fix the URL (below) |
| DietPi first run aborted | PreScript timer runs the bootstrap anyway (after the 1 h wait) | Wait, or start it now (below) |
| Bootstrap never ran (PreScript missing too) | Tailscale is installed by DietPi (ID 58) but not joined | Join by hand over local SSH (below) |
| Tailscale join failed (bad or expired key) | Device is on Wi-Fi only | New key, then local SSH (below) |
| `install.sh` failed | Tailscale works; the error is in the log | Fix, then re-run (below) |

### Start or re-run the bootstrap

```bash
tailscale ssh root@pm25
systemctl start pm25-bootstrap      # runs now instead of waiting for the timer
tail -n 50 /var/lib/pm25/bootstrap.log
```

To run it again after it has finished, delete the marker first:
`rm /var/lib/pm25/bootstrap.done && systemctl enable --now pm25-bootstrap.timer`.

### Change the source after first boot

Settings are saved in `/etc/pm25/bootstrap.env` on the first run and override the values in
the script. Edit that file (for example to fix `SOURCE_URL`, `SOURCE_SHA256`, or set
`REPO_URL`), then `systemctl start pm25-bootstrap`.

You can also drop files into `/boot` on the device itself, which works on both boards:

```bash
# On your dev machine:
deploy/serve-source.sh --bundle-only --dir /tmp/pm25
scp /tmp/pm25/pm25.bundle root@pm25:/boot/pm25.bundle
tailscale ssh root@pm25 systemctl start pm25-bootstrap
```

The same goes for `/boot/pm25-installer.sh` if you want to run your own installer.

### Join Tailscale by hand (no tailnet access)

Find the device's IP in your router, then SSH in over the LAN as `root` (DietPi's default
password is `dietpi`; change it with `passwd`):

```bash
ssh root@<device-ip>
tailscale up --ssh --hostname pm25 --advertise-tags=tag:pm25   # opens a login link
systemctl start pm25-bootstrap                                 # if the timer is installed
```

If the timer isn't installed, run the bootstrap once by hand:
`bash /boot/Automation_Custom_Script.sh`.

### Start again from scratch

Reflash the card and repeat sections 5–6 with a new auth key. Remove the old `pm25` machine
from the Tailscale admin console first, so the new one gets the same name.

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Device never appears in Tailscale | Wrong Wi-Fi details, 5 GHz-only network, or expired key | Check router DHCP leases; join by hand (section 9) |
| Device appears as `pm25-1` | An old `pm25` machine still exists | Delete the old machine, then `tailscale set --hostname pm25` |
| Log: `could not download … ACL` | ACL grant to port 8443 is missing, or dev machine is offline | Add the grant in section 3; check `tailscale serve status` on the dev machine |
| Log: `checksum mismatch` | Bundle was rebuilt after you copied `SOURCE_SHA256` | Update `SOURCE_SHA256` in `/etc/pm25/bootstrap.env` |
| Log: `DietPi first-run setup still in progress` | DietPi is still working, or stuck | Check `dietpi-firstrun-setup.log`; the bootstrap proceeds after one hour of uptime |
| HTTPS certificate warning | HTTPS certificates are not enabled on the tailnet | Turn them on (section 3), then `tailscale serve --bg --https=443 http://127.0.0.1:8080` |
| `install.sh` fails on pip/apt | Internet blocked or flaky during first install | `pm25-firewall open 30`, then `systemctl start pm25-bootstrap` |
| No PM readings | Wiring, or UART not enabled | See the hardware guide for your board |

Need the internet for a one-off task later (for example `apt upgrade`)? Run
`pm25-firewall open 30` to open it for 30 minutes.
