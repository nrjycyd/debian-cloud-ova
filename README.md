# Debian Cloud OVA Builder

基于 **Debian 官方云镜像**（源自 [cloud.debian.org](https://cloud.debian.org/images/cloud/)），通过封装 Cloud-Init 配置，自动构建可直接导入 **VMware ESXi / Workstation** 及 **VirtualBox** 的 OVA 虚拟机模板。

> [!CAUTION]
> **安全警告：仅限内部测试环境使用**
>
> - 本工具生成的镜像包含预设的**默认凭据**。
> - **绝对不要**将生成的 OVA 文件直接部署到公网或生产环境。
> - 部署后必须**第一时间修改密码**。

---

## 功能特性

- **官方源构建**：基于 `Debian Official Cloud Images` 构建，确保纯净安全。
- **多版本支持**：Debian 11 (Bullseye)、12 (Bookworm)、13 (Trixie)，每次选择一个系统构建。Guest OS 标识（DGNU）按 ESXi 兼容性选择，与实际系统版本独立。
- **机型精确匹配**：构建时选择 ESXi 机型（vmx-14 ~ vmx-22），自动设置对应的 OVF 硬件版本与 Guest OS 类型。
- **硬件定制**：构建时可自定义 vCPU、内存和磁盘大小（输入最小 2 GiB；小于源镜像实际虚拟容量时，自动采用源镜像容量继续构建）。
- **自动化发布**：GitHub Actions 一键构建，并自动以 Debian 官方 build 号为标签发布 Release。
- **Cloud-Init**：自动配置主机名、登录账户、密码和 SSH 状态。

---

## 快速开始（GitHub Actions）

本项目仅支持通过 **GitHub Actions** 构建，不再提供本地构建入口。

1. 进入项目的 **Actions** 页面。
2. 选择 **「构建并发布 Debian OVA」** 工作流。
3. 点击 **Run workflow** 按钮。
4. 根据需求填写参数：

    | 参数 | 说明 | 默认值 | 可选范围 / 备注 |
    | --- | --- | --- | --- |
    | `Debian 系统版本` | 系统单选下拉框 | `13` | `11` / `12` / `13` |
    | `ESXi 机型 + Guest OS` | 构建目标组合（机型 + DGNU） | `ESXi 9.0+ + DGNU 13 (vmx-22)` | 下拉选择，工作流自动校验机型与版本匹配 |
    | `vCPU` | 虚拟 CPU 数量 | `2` | 1 – 64 |
    | `内存` | 内存大小（MB） | `1024` | 256 – 262144 |
    | `磁盘大小` | 磁盘容量（GiB） | `4` | 2 – 2048；实际容量取请求容量与源镜像容量中的较大值 |
    | `主机名` | 虚拟机主机名 | `debian-cloud` | 字母/数字/连字符，≤ 63 字符 |
    | `启用 SSH 服务` | root 密码登录 | 不勾选 | 勾选后仅配置 root，不创建默认普通用户 |
    | `默认用户名` | 控制台用户 | `debian` | 仅未启用 SSH 时使用；启用时忽略，登录账户固定为 root |
    | `登录密码` | 登录账户密码 | `123456` | 启用 SSH 时用于 root；仅允许字母/数字及 `@#%+=.,_-`（构建日志中可见） |

5. 构建完成后，在 **Releases** 页面下载生成的 `.ova` 文件。

每次从下拉框选择一个 Debian 系统版本，默认 Debian 13；如需其他版本，请分别启动构建。

请求容量不足时会在日志中提示自动调整；构建摘要分别列出请求容量与实际容量，Release 说明仅列出实际磁盘大小。

### SSH 与登录方式

- **未启用 SSH（默认）**：创建指定的普通用户，供虚拟机控制台登录；首次启动时停止并屏蔽 SSH 服务和 socket。
- **启用 SSH**：仅配置 root 账户，使用面板中的登录密码；设置 `PermitRootLogin yes`、`PasswordAuthentication yes`，启动 SSH 并设置开机启动。不主动删除镜像可能已有的其他账户。
- 等待首次启动的 cloud-init 完成后，再使用 `ssh root@<虚拟机 IP>` 登录；需有可用网络和可达的 22 端口。配置失败可在控制台查看 `cloud-init status --long` 和 `/var/log/cloud-init-output.log`。
- 镜像文件名分别以 `-ssh.ova`、`-console.ova` 结尾，避免两种模式的资产相互覆盖。已有 Release 的说明更新为最近一次成功构建的信息，只保留一份完整说明；历史下载资产保留。说明中的配置与凭据对应其中标明的镜像文件。


---

## 安全操作指南（必读）

由于 OVA 镜像使用了预设密码，系统启动后存在极大安全风险。请务必执行以下操作：

### 1. 首次登录

- **控制台登录**：使用 VMware/ESXi 的 Web Console 或 VMRC，登录本次配置的账户。
- **SSH 登录**：仅启用 SSH 的镜像可使用 `ssh root@<IP>`。
- **默认凭据**：SSH 关闭时为 `debian` / `123456`；启用时为 `root` / `123456`，请在构建时修改密码。

### 2. 修改登录密码（高优先级）

登录后使用 `passwd` 修改当前账户密码。root 登录时直接执行，无需 `sudo`：

```bash
passwd
```

系统会提示：

1. 普通用户可能需要输入当前密码（`Current password`）
2. 输入新密码（`New password`）
3. 确认新密码（`Retype new password`）

### 3. 修改 / 锁定 Root 密码

SSH 关闭模式不会设置 root 密码；SSH 开启模式已为 root 设置面板中的登录密码。普通用户可通过 `sudo` 管理 root 密码。

**设置 root 密码（如需）：**

```bash
sudo passwd root
```

### 4. 强制定期修改（可选 - 适用于测试团队）

如果你是管理员，希望强制使用者在第一次登录时必须修改密码，请在虚拟机启动后运行：

```bash
sudo chage -d 0 debian
```

*效果：用户下次登录时，系统会强制要求其立即更改密码，否则无法进入 Shell。*

---

## 初始系统配置

### 1. 替换软件源

> [!NOTE]
> Debian 12 及之前使用传统格式 `/etc/apt/sources.list`；Debian 13 变更为 `DEB822` 格式 `/etc/apt/sources.list.d/debian.sources`。

保留默认源文件不删除，将下面的内容**直接覆盖**到 `/etc/apt/sources.list.d/debian.sources`（官方默认源以注释形式保留，以 trixie 为例）：

```text
# 清华源（生效）
Types: deb
URIs: https://mirrors.tuna.tsinghua.edu.cn/debian
Suites: trixie trixie-updates trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

# 官方安全更新（生效）
Types: deb
URIs: https://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

# === 以下为默认的官方源，已注释保留，无需删除 ===
# Types: deb
# URIs: https://deb.debian.org/debian
# Suites: trixie trixie-updates trixie-backports
# Components: main contrib non-free non-free-firmware
# Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
#
# Types: deb
# URIs: https://security.debian.org/debian-security
# Suites: trixie-security
# Components: main contrib non-free non-free-firmware
# Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
```

> 若你只想快速替换，也可以用 `sed` 把文件里的官方域名直接改成清华域名（不会引入重复源）：
> ```bash
> cp -a /etc/apt/mirrors/debian.list /etc/apt/mirrors/debian.list.bak-$(date +%Y%m%d) && printf 'https://mirrors.tuna.tsinghua.edu.cn/debian\n' > /etc/apt/mirrors/debian.list
> ```

更新源：

```bash
sudo apt update
```

### 2. 安装虚拟机工具集（非必须）

Debian Cloud 镜像若安装时未联网，工具集可能安装失败，建议手动安装：

```bash
sudo apt install open-vm-tools
```

### 3. 修改时区（Timezone）

默认时区为 UTC。若在中国大陆地区使用，建议修改为 `Asia/Shanghai` (CST)：

```bash
sudo dpkg-reconfigure tzdata
```

---

## 常见问题

**Q: 导入 VMware 后无法获取 IP？**
A: 镜像使用 Cloud-Init 配置网络（DHCP）。请确保 VMware 网络适配器已连接，且该网段内有可用的 DHCP 服务。

**Q: 构建日志里能看到我的密码吗？**
A: 是的。当前构建脚本通过命令行传递密码，GitHub Actions 日志会明文记录。因此再次强调：**仅限内部测试使用，部署后必须立即修改密码，不要直接用于公网或生产环境。**
