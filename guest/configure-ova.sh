#!/bin/sh
set -eu

# One runcmd entry preserves failures through cloud-init's parent script.
case "$1" in
  true) /usr/local/sbin/configure-ova-ssh true ;;
  false) ;; # Preserve the source image's SSH defaults for console variants.
  *) echo '[ERROR] Invalid SSH mode' >&2; exit 1 ;;
esac
systemctl daemon-reload
case "$2" in
  true)
    systemctl enable open-vm-tools
    systemctl start open-vm-tools
    ;;
  false) ;;
  *) echo '[ERROR] Invalid VM tools mode' >&2; exit 1 ;;
esac
