#!/bin/sh
set -eu

# One runcmd entry preserves failures through cloud-init's parent script.
/usr/local/sbin/configure-ova-ssh "$1"
systemctl daemon-reload
case "$2" in
  true)
    systemctl enable open-vm-tools
    systemctl start open-vm-tools
    ;;
  false) ;;
  *) echo '[ERROR] Invalid VM tools mode' >&2; exit 1 ;;
esac
