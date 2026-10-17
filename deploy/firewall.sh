#!/usr/bin/env bash
# pm25-firewall: egress lockdown for the PM2.5 monitor (installed to /usr/local/sbin/pm25-firewall).
#
#   pm25-firewall apply           load the lockdown ruleset (also: close)
#   pm25-firewall open [MINUTES]  remove the lockdown; with MINUTES, re-apply automatically afterwards
#   pm25-firewall status          show the active ruleset and recent drops
#
# Allowed: loopback, LAN (in + out), anything over tailscale0, tailscaled's own control/DERP/WireGuard
# traffic, DHCP, ICMP, and optionally DNS + NTP (needed for name resolution and a correct clock for TLS).
# Everything else leaving the device is dropped and logged as "pm25-egress-drop".
# Settings live in /etc/pm25/firewall.env (the lockdown is only active while that file exists).
set -euo pipefail

ENV_FILE=/etc/pm25/firewall.env
TABLE=pm25

PM25_LAN_CIDRS4="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16"
PM25_LAN_CIDRS6="fc00::/7 fe80::/10"
PM25_ALLOW_DNS=1
PM25_ALLOW_NTP=1
PM25_ROOT_EGRESS=0
# shellcheck disable=SC1090
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"

need_root() { [[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run as root." >&2; exit 1; }; }

set_elements() { local out="" c; for c in $1; do out="${out:+$out, }$c"; done; printf '%s' "$out"; }

ruleset() {
	local lan4 lan6 cgroup_rule="" dns_rules="" ntp_rule="" root_rule=""
	lan4="$(set_elements "$PM25_LAN_CIDRS4")"
	lan6="$(set_elements "$PM25_LAN_CIDRS6")"
	if [[ -d /sys/fs/cgroup/system.slice/tailscaled.service ]]; then
		cgroup_rule='socket cgroupv2 level 2 "system.slice/tailscaled.service" accept'
	fi
	if [[ "$PM25_ALLOW_DNS" == 1 ]]; then
		dns_rules=$'udp dport 53 accept\n\t\ttcp dport 53 accept'
	fi
	[[ "$PM25_ALLOW_NTP" == 1 ]] && ntp_rule='udp dport 123 accept'
	# Fallback for images where tailscaled cannot be matched: let any root process out (weaker).
	[[ "$PM25_ROOT_EGRESS" == 1 ]] && root_rule='meta skuid 0 accept'

	cat <<EOF
table inet $TABLE
delete table inet $TABLE
table inet $TABLE {
	set lan4 { type ipv4_addr; flags interval; ${lan4:+elements = { $lan4 }} }
	set lan6 { type ipv6_addr; flags interval; ${lan6:+elements = { $lan6 }} }

	chain input {
		type filter hook input priority filter; policy drop;
		iif lo accept
		ct state established,related accept
		ct state invalid drop
		iifname "tailscale0" accept
		meta l4proto { icmp, ipv6-icmp } accept
		udp dport 68 accept
		udp dport 41641 accept
		ip saddr @lan4 accept
		ip6 saddr @lan6 accept
	}

	chain output {
		type filter hook output priority filter; policy drop;
		oif lo accept
		ct state established,related accept
		oifname "tailscale0" accept
		meta mark & 0x80000 == 0x80000 accept
		$cgroup_rule
		$root_rule
		ip daddr @lan4 accept
		ip6 daddr @lan6 accept
		meta l4proto { icmp, ipv6-icmp } accept
		udp dport 67 accept
		$dns_rules
		$ntp_rule
		limit rate 6/minute log prefix "pm25-egress-drop " level info
		counter drop
	}
}
EOF
}

apply() {
	need_root
	command -v nft >/dev/null 2>&1 || { echo "nft not found; install the nftables package." >&2; exit 1; }
	local rules
	rules="$(ruleset)"
	if ! nft -c -f - <<<"$rules"; then
		echo "pm25-firewall: ruleset failed validation; leaving the current firewall unchanged." >&2
		exit 1
	fi
	nft -f - <<<"$rules"
	systemctl stop pm25-firewall-reclose.timer 2>/dev/null || true
	if [[ -d /sys/fs/cgroup/system.slice/tailscaled.service ]]; then
		echo "pm25-firewall: lockdown active (tailscaled matched by cgroup + socket mark)."
	else
		echo "pm25-firewall: lockdown active (tailscaled not running yet; matched by socket mark only)."
	fi
}

open_window() {
	need_root
	nft delete table inet "$TABLE" 2>/dev/null || true
	if [[ -n "${1:-}" ]]; then
		[[ "$1" =~ ^[0-9]+$ ]] || { echo "MINUTES must be a number" >&2; exit 2; }
		systemctl stop pm25-firewall-reclose.timer 2>/dev/null || true
		systemd-run --quiet --unit=pm25-firewall-reclose --on-active="${1}m" /usr/local/sbin/pm25-firewall apply
		echo "pm25-firewall: egress OPEN for $1 minute(s); the lockdown re-applies automatically."
	else
		echo "pm25-firewall: egress OPEN until 'pm25-firewall apply' or the next boot."
	fi
}

status() {
	nft list table inet "$TABLE" 2>/dev/null || echo "pm25-firewall: lockdown NOT active."
	echo "--- recent drops ---"
	journalctl -k --no-pager -n 20 -g 'pm25-egress-drop' 2>/dev/null || true
}

case "${1:-status}" in
	apply | close) apply ;;
	open) open_window "${2:-}" ;;
	status) status ;;
	print) ruleset ;;
	*) echo "usage: pm25-firewall {apply|open [MINUTES]|status|print}" >&2; exit 2 ;;
esac
