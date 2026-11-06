#!/bin/sh
set -eu

# 通过单个 runcmd 调用，确保初始化错误传播到 cloud-init。
case "$1" in
  true) /usr/local/sbin/configure-ova-ssh true ;;
  false) ;; # console 沿用源镜像的 SSH 默认值。
  *) echo '[ERROR] 无效的 SSH 模式' >&2; exit 1 ;;
esac
systemctl daemon-reload
case "$2" in
  true)
    systemctl enable open-vm-tools
    systemctl start open-vm-tools
    ;;
  false) ;;
  *) echo '[ERROR] 无效的工具安装开关' >&2; exit 1 ;;
esac
