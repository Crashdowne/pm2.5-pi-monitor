#!/bin/bash
# PM2.5 monitor: early first-boot hook for DietPi.
#
# Copy to the boot partition as Automation_Custom_PreScript.sh, next to
# Automation_Custom_Script.sh. DietPi runs it before networking and software installs. It only
# installs the pm25-bootstrap retry timer (no network needed), so Tailscale and the app still
# get installed if DietPi's first-run setup fails before it reaches Automation_Custom_Script.sh.
for d in /boot /boot/firmware; do
	if [ -f "$d/Automation_Custom_Script.sh" ]; then
		bash "$d/Automation_Custom_Script.sh" --persist
		exit 0
	fi
done
echo "pm25: Automation_Custom_Script.sh not found on the boot partition" >&2
exit 0
