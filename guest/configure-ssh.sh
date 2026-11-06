#!/bin/sh
set -eu

case "$1" in
  true)
    config=/etc/ssh/sshd_config
    if [ ! -f "$config.ova-backup" ]; then
      cp -p "$config" "$config.ova-backup"
    fi
    # OpenSSH uses the first value: put our policy before distro includes.
    sed -i '/^# BEGIN OVA SSH$/,/^# END OVA SSH$/d' "$config"
    temp_config=$(mktemp)
    trap 'rm -f "$temp_config"' EXIT
    {
      printf '%s\n' '# BEGIN OVA SSH' 'PermitRootLogin yes' 'PasswordAuthentication yes' '# END OVA SSH'
      cat "$config"
    } > "$temp_config"
    install -m 0600 "$temp_config" "$config"
    mkdir -p /run/sshd
    ssh-keygen -A
    /usr/sbin/sshd -t
    effective=$(/usr/sbin/sshd -T -C user=root,host=localhost,addr=127.0.0.1)
    printf '%s\n' "$effective" | grep -qx 'permitrootlogin yes'
    printf '%s\n' "$effective" | grep -qx 'passwordauthentication yes'
    systemctl mask --now ssh.socket
    systemctl unmask ssh.service
    systemctl enable ssh.service
    systemctl restart ssh.service
    ;;
  false)
    systemctl disable ssh.service
    systemctl mask --now ssh.service ssh.socket
    ;;
  *) echo '[ERROR] Invalid SSH mode' >&2; exit 1 ;;
esac
