#!/usr/bin/env bash
# Shared helpers for deploy/install.sh and deploy/update.sh. Source, do not execute.

PM25_UNITS=(
	pm25-reader.service pm25-web.service pm25-sync.service pm25-sync.timer
	pm25-alert.service pm25-alert.timer
	pm25-update.service pm25-update.path pm25-autoupdate.service pm25-autoupdate.timer
)

# Read one value from /etc/pm25/config.toml through the app's own loader (validated, with defaults).
pm25_config_value() {
	local python="$1" expr="$2" fallback="$3" value
	value="$("$python" -c "from pm25.config import load_config; c = load_config('/etc/pm25/config.toml'); print($expr)" 2>/dev/null)" || value=""
	printf '%s\n' "${value:-$fallback}"
}

# Render the unit templates into /etc/systemd/system.
pm25_install_units() {
	local repo="$1" python="$2" hardware_groups="$3" ota_dir="$4" u
	for u in "${PM25_UNITS[@]}"; do
		sed -e "s#{{REPO}}#$repo#g" -e "s#{{PYTHON}}#$python#g" \
			-e "s#{{HARDWARE_GROUPS}}#$hardware_groups#g" -e "s#{{OTA_DIR}}#$ota_dir#g" \
			"$repo/deploy/$u" > "/etc/systemd/system/$u"
	done
	install -m 644 "$repo/deploy/pm25-wifi-powersave.service" /etc/systemd/system/pm25-wifi-powersave.service
	install -m 755 "$repo/deploy/firewall.sh" /usr/local/sbin/pm25-firewall
	install -m 644 "$repo/deploy/pm25-firewall.service" /etc/systemd/system/pm25-firewall.service
}

# OTA state dir: root writes status/version, the web service (group pm25-data) may only drop a request.
pm25_prepare_ota() {
	local ota_dir="$1"
	install -d -o root -g pm25-data -m 2770 "$ota_dir"
	install -d -o root -g root -m 755 "$ota_dir/wheels"
	chown -R root:root "$ota_dir/wheels"
	if [[ ! -f /etc/pm25/update.env ]]; then
		# Read by systemd as root before pm25-web drops privileges, so the file can stay root-only.
		umask 077
		printf 'PM25_UPDATE_TOKEN=%s\n' "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" > /etc/pm25/update.env
		umask 022
		echo "Created /etc/pm25/update.env (dashboard update token; view with: sudo cat /etc/pm25/update.env)"
	fi
	chown root:root /etc/pm25/update.env
	chmod 600 /etc/pm25/update.env
}

# Enable or disable the OTA units according to [update] in config.toml.
pm25_enable_ota_units() {
	local python="$1" allow auto
	allow="$(pm25_config_value "$python" 'c.update.allow_web_trigger' True)"
	auto="$(pm25_config_value "$python" 'c.update.auto_pull' False)"
	if [[ "$allow" == "True" ]]; then
		systemctl enable pm25-update.path >/dev/null 2>&1
		systemctl restart pm25-update.path
	else
		systemctl disable --now pm25-update.path >/dev/null 2>&1 || true
	fi
	if [[ "$auto" == "True" ]]; then
		systemctl enable pm25-autoupdate.timer >/dev/null 2>&1
		systemctl restart pm25-autoupdate.timer
	else
		systemctl disable --now pm25-autoupdate.timer >/dev/null 2>&1 || true
	fi
}

# Status files read by the dashboard. Messages are generated here, but strip quotes/backslashes anyway.
pm25_json_safe() { printf '%s' "$1" | tr -d '"\\' | tr -cd '[:print:]'; }

pm25_write_status() {
	local ota_dir="$1" state="$2" mode="$3" source="$4" message="$5" from="$6" to="$7" tmp
	tmp="$ota_dir/.status.json.tmp"
	printf '{"state": "%s", "mode": "%s", "source": "%s", "message": "%s", "from": "%s", "to": "%s", "ts": %s}\n' \
		"$state" "$mode" "$source" "$(pm25_json_safe "$message")" "$from" "$to" "$(date +%s)" > "$tmp"
	chmod 644 "$tmp"
	mv -f "$tmp" "$ota_dir/status.json"
}

pm25_write_version() {
	local repo="$1" ota_dir="$2" source="$3" tmp sha branch subject
	sha="$(git -C "$repo" rev-parse HEAD)"
	branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
	subject="$(git -C "$repo" log -1 --format=%s)"
	tmp="$ota_dir/.version.json.tmp"
	printf '{"sha": "%s", "short": "%s", "branch": "%s", "subject": "%s", "source": "%s", "updated_ts": %s}\n' \
		"$sha" "${sha:0:7}" "$(pm25_json_safe "$branch")" "$(pm25_json_safe "$subject")" "$source" "$(date +%s)" > "$tmp"
	chmod 644 "$tmp"
	mv -f "$tmp" "$ota_dir/version.json"
}

# Tailscale drop-ins: memory guardrail + re-apply the egress firewall once tailscaled's cgroup exists.
pm25_install_tailscaled_dropins() {
	local repo="$1"
	systemctl list-unit-files tailscaled.service >/dev/null 2>&1 || return 0
	install -d /etc/systemd/system/tailscaled.service.d
	install -m 644 "$repo/deploy/tailscaled-memory.conf" /etc/systemd/system/tailscaled.service.d/memory.conf
	install -m 644 "$repo/deploy/tailscaled-firewall.conf" /etc/systemd/system/tailscaled.service.d/pm25-firewall.conf
}
