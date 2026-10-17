# Over-the-air updates, Tailscale-only networking, and HTTPS

The monitor is designed to run with **all internet traffic blocked**. After the first boot:

- code updates, data offload, and remote access travel only over **Tailscale**;
- the dashboard is served on the local network (LAN and tailnet), with HTTPS through
  `tailscale serve`;
- everything else leaving the device is dropped by an nftables egress firewall.

The only internet traffic left is Tailscale's own control plane, DERP relays, and
certificate issuance (all handled by `tailscaled`), plus DNS and NTP. You can turn DNS
and NTP off too.

## 1. Tailnet prerequisites (admin console, once)

1. **DNS → MagicDNS: on**, and **HTTPS certificates: enabled**. Tailscale needs these to
   issue the Let's Encrypt certificate for `https://<hostname>.<tailnet>.ts.net`.
2. **Settings → Keys → Generate auth key.** Choose a one-off key that is pre-approved and
   has a tag (for example `tag:pm25`). Use it once and let it expire.
3. **Access controls.** Allow your dev machine to reach the device, and allow Tailscale SSH
   as root (OTA pushes use git over SSH). For the first-boot source download, also let
   `tag:pm25` reach `deploy/serve-source.sh` on your dev machine (port 8443). For example:

   ```jsonc
   "tagOwners": { "tag:pm25": ["autogroup:admin"] },
   "grants":    [
     { "src": ["autogroup:admin"], "dst": ["tag:pm25"], "ip": ["*"] },
     { "src": ["tag:pm25"], "dst": ["you@example.com"], "ip": ["tcp:8443"] }
   ],
   "ssh":       [{ "action": "accept", "src": ["autogroup:admin"], "dst": ["tag:pm25"], "users": ["root"] }]
   ```

4. **Never enable Funnel** for this device. Funnel would publish the dashboard to the internet.

## 2. First boot (the only internet window)

The first boot needs the internet. DietPi installs itself, then `install.sh` downloads
apt packages, `uv`, Python, and the wheels. The app source itself comes over the tailnet:
run `deploy/serve-source.sh` on your dev machine and paste the `SOURCE_URL` and
`SOURCE_SHA256` it prints into `deploy/dietpi/Automation_Custom_Script.sh`. Set these at the
top of that script before copying it to the boot partition (full walkthrough:
[SETUP.md](SETUP.md)):

| Variable | Default | Effect |
|---|---|---|
| `TS_AUTHKEY` | empty | joins the tailnet unattended (`tailscale up --ssh`); the key is blanked from `/boot` afterwards |
| `TS_HOSTNAME` | `pm25` | Tailscale machine name, which becomes `https://pm25.<tailnet>.ts.net` |
| `TS_HTTPS` | `1` | runs `tailscale serve --bg --https=443 http://127.0.0.1:8080` |
| `LOCKDOWN` | `1` | installs `/etc/pm25/firewall.env` and applies the egress firewall as the last install step |
| `SOURCE_URL` | empty | git bundle URL on your dev machine, from `serve-source.sh` |
| `SOURCE_SHA256` | empty | bundle checksum; a mismatch is refused |
| `REPO_URL` | empty | optional internet clone fallback |

For a manual install, pass the same values as environment variables:

```bash
sudo TS_AUTHKEY=tskey-auth-... TS_HOSTNAME=pm25 PM25_TS_HTTPS=1 PM25_LOCKDOWN=1 deploy/install.sh
```

You can also put the key in `/etc/pm25/tailscale-authkey` (mode 600). The installer
shreds the copy it uses. Without a key, run `sudo tailscale up --ssh --hostname pm25`
yourself, then `sudo tailscale serve --bg --https=443 http://127.0.0.1:8080`.

## 3. Updating: push from your dev machine (recommended)

`deploy/ota-push.sh` sends a commit to the device over Tailscale SSH, then applies it.
The device never contacts GitHub.

```bash
deploy/ota-push.sh pm25                     # push HEAD and apply it
deploy/ota-push.sh --ref v0.3.0 pm25        # push a tag or commit
deploy/ota-push.sh --wheels pm25            # also ship aarch64 wheels (needed when dependencies change)
deploy/ota-push.sh --stage-only pm25        # stage only; apply later from the dashboard or with update.sh
```

How it works:

1. `git push --force ssh://root@pm25/opt/pm25 <sha>:refs/ota/incoming`. This is a
   non-branch ref, so the device's checkout is never touched directly.
2. With `--wheels`, it resolves the dependencies for the device's Python and board
   (`uv pip compile --python-platform aarch64-unknown-linux-gnu`). It then downloads
   binary wheels on the dev machine and copies them to `<state_dir>/wheels/` on the device.
3. Unless `--stage-only` is set, it runs `deploy/update.sh --apply-staged`.

Updates are **fast-forward only**: the pushed commit must descend from the commit that is
installed. Your dev machine needs `git`, `ssh`, and `uv`. Options: `--user` (default
`root`), `--path` (default `/opt/pm25`).

## 4. Updating: pull from a tailnet git remote (optional)

If a git server is reachable on the tailnet (Gitea, a bare repo on a NAS, and so on),
point the device at it in `/etc/pm25/config.toml`:

```toml
[update]
remote = "ssh://git@nas.tail1234.ts.net/pm25.git"   # empty = origin (GitHub is blocked by the lockdown)
branch = "main"
auto_pull = true                                    # nightly pull via pm25-autoupdate.timer
```

Then `sudo /opt/pm25/deploy/update.sh --pull`, or trigger an update from the dashboard.
Pulls install dependencies from the shipped wheels, so push them with
`ota-push.sh --wheels --stage-only` whenever `pyproject.toml` changes.

## 5. Updating from the dashboard or API

The web service runs unprivileged and cannot update the code itself. Instead,
`POST /api/update` writes a request file into `[update].state_dir`. The root
`pm25-update.path` unit sees the file and runs `update.sh --request`.

Requests are accepted only when all of these hold:

- `[update] allow_web_trigger = true` (the default);
- the client is on the tailnet (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) or on loopback,
  which covers `tailscale serve`; LAN clients get 403;
- the request carries the bearer token from `/etc/pm25/update.env`, which the installer
  generates with mode 600.

```bash
TOKEN=$(ssh root@pm25 '. /etc/pm25/update.env; echo $PM25_UPDATE_TOKEN')
curl -s https://pm25.tail1234.ts.net/api/update                      # status
curl -s -X POST https://pm25.tail1234.ts.net/api/update \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"apply_staged"}'                                      # or "pull"
```

`GET /api/update` returns `package_version`, `installed` (commit, from `version.json`),
`last_run` (from `status.json`: `state`, `mode`, `source`, `message`, `from`, `to`, `ts`),
and `pending_request`. `POST` responds as follows:

| Code | Meaning |
|---|---|
| 202 | request accepted |
| 400 | unknown action |
| 401 | missing or wrong token |
| 403 | dashboard updates disabled, or the client is not on the tailnet |
| 409 | a request is already pending or an update is running |

## 6. What an update does, and rollback

`update.sh` takes a lock, records the current commit, and fast-forwards to the target.
It then re-executes the **new** `update.sh --finish`, which:

1. syncs dependencies offline when `pyproject.toml` or `uv.lock` changed. It uses the
   wheels in `<state_dir>/wheels` first, then the `uv` cache. It goes online only if
   `PM25_UPDATE_ALLOW_NETWORK=1`.
2. reinstalls the systemd units;
3. restarts the services and checks their health.

If any step fails, it resets to the previous commit, restarts the old version, and records
`failed` in `status.json`. Logs: `journalctl -u pm25-update -u pm25-autoupdate`.

## 7. Egress lockdown

`pm25-firewall` (installed from `deploy/firewall.sh`) loads the nftables `table inet pm25`
ruleset. It allows:

- loopback;
- the LAN, inbound and outbound (`PM25_LAN_CIDRS4/6`);
- everything on `tailscale0`;
- `tailscaled`'s own traffic (fwmark `0x80000`, plus its cgroup);
- DHCP and ICMP;
- optionally DNS and NTP.

Everything else is dropped and logged as `pm25-egress-drop`. Settings live in
`/etc/pm25/firewall.env` (template: `deploy/firewall.env.example`). The lockdown is active
only while that file exists. `pm25-firewall.service` re-applies it at boot.

```bash
sudo pm25-firewall status        # ruleset, counters, recent drops
sudo pm25-firewall open 30       # lift the lockdown for 30 minutes (apt upgrade, uv python install, ...)
sudo pm25-firewall apply         # re-apply now
```

The data offload (`pm25-sync`) goes to a tailnet address, so the lockdown doesn't affect it.
If you sync to a Cloudflare Worker instead, either open egress for it or use a server on
the tailnet.

## 8. Recovery

- **Update failed:** check `cat /var/lib/pm25/ota/status.json`. The device is already back
  on the previous commit. Fix the cause and push again.
- **Units or permissions look wrong:** `sudo /opt/pm25/deploy/update.sh --reinstall`.
- **Tailscale lost its connection under lockdown:** from the LAN, SSH in and run
  `sudo pm25-firewall open 30`. If tailscaled cannot be matched on your image, set
  `PM25_ROOT_EGRESS=1` in `firewall.env`. This lets all root processes out, which is weaker.
- **Lockdown off for good:** `sudo rm /etc/pm25/firewall.env && sudo pm25-firewall open`.
