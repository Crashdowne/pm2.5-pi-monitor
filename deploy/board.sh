# Board detection and Radxa helpers, sourced by install.sh and update.sh.

# Print "pi" or "radxa". PM25_BOARD overrides auto-detection.
detect_board() {
  if [[ -n "${PM25_BOARD:-}" ]]; then
    case "$PM25_BOARD" in
      pi|radxa) echo "$PM25_BOARD"; return ;;
      *) echo "error: PM25_BOARD must be 'pi' or 'radxa', got '$PM25_BOARD'" >&2; exit 1 ;;
    esac
  fi
  local model=""
  [[ -r /proc/device-tree/model ]] && model="$(tr -d '\0' < /proc/device-tree/model)"
  if [[ "$model" == *Radxa* || "$model" == *RK3566* || -f /boot/dietpiEnv.txt ]]; then
    echo radxa
  else
    echo pi
  fi
}

# Rewrite a fresh config.toml with the Radxa ZERO 3W wiring from docs/hardware/HARDWARE_SETUP-radxa.md.
apply_radxa_defaults() {
  local cfg="$1"
  sed -i \
    -e 's#^device = "/dev/ttyAMA0"#device = "/dev/ttyS4"#' \
    -e 's#^pin_enable = 22\b#pin_enable = -1#' \
    -e 's#^pin_reset = 27\b#pin_reset = -1#' \
    -e 's#^i2c_bus = 1\b#i2c_bus = 3#' \
    -e 's#^commit_interval_s = 0\b#commit_interval_s = 300#' \
    "$cfg"
}

print_radxa_overlay_help() {
  cat <<'EOF'

Radxa ZERO 3W: enable the UART and I2C overlays manually (names vary by image).
  1. ls /boot/dtb/rockchip/overlay/ | grep -E 'uart4|i2c3'
  2. Edit /boot/dietpiEnv.txt to match those file names, for example:
       overlay_path=rockchip
       overlay_prefix=rk3568
       overlays=uart4-m1 i2c3-m0
  3. Reboot, then check: ls /dev/ttyS4 /dev/i2c-3 && sudo i2cdetect -y 3
  See docs/hardware/HARDWARE_SETUP-radxa.md for details.
EOF
}
