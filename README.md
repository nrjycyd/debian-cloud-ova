# 🚀 Debian Cloud OVA Builder

基于 **Debian 官方云镜像**（`genericcloud`，源自 [cloud.debian.org](https://cloud.debian.org/images/cloud/)），通过封装 Cloud-Init 配置，自动构建可直接导入 **VMware ESXi / Workstation** 及 **VirtualBox** 的 OVA 虚拟机模板。

> [!CAUTION]
> **⚠️ 安全警告：仅限内部测试环境使用**
>
> - 本工具生成的镜像包含预设的**默认凭据**。
> - **绝对不要**将生成的 OVA 文件直接部署到公网或生产环境，除非你已在构建时注入了安全的 SSH Key 并禁用了密码登录。
> - 部署后必须**第一时间修改密码**。

---

## ✨ 功能特性

- **官方源构建**：基于官方 `genericcloud` 镜像构建，确保纯净安全。
- **多版本支持**：Debian 10 (Buster) ~ 13 (Trixie)，以及版本对应的 Guest OS 标识（DGNU）。
- **机型精确匹配**：构建时选择 ESXi 机型（vmx-14 ~ vmx-22），自动设置对应的 OVF 硬件版本与 Guest OS 类型。
- **硬件定制**：构建时可自定义 vCPU、内存和磁盘大小（磁盘最小 2GB）。
- **自动化发布**：GitHub Actions 一键构建，并自动以 Debian 官方 build 号为标签发布 Release。
- **Cloud-Init**：自动注入主机名、默认用户和 SSH 公钥。

---

## 🛠️ 快速开始（GitHub Actions）

这是**最推荐的使用方式**，无需本地环境。

1. 进入项目的 **Actions** 页面。
2. 选择 **「🚀 构建并发布 Debian OVA」** 工作流。
3. 点击 **Run workflow** 按钮。
4. 根据需求填写参数：

    | 参数 | 说明 | 默认值 | 可选范围 / 备注 |
    | --- | --- | --- | --- |
    | `Debian 版本` | 系统版本 | `13` | `10` / `11` / `12` / `13` |
    | `ESXi 机型 + Guest OS` | 构建目标组合（机型 + DGNU） | `ESXi 9.0+ + DGNU 13 (vmx-22)` | 见下方列表，DGNU 不得超过机型可识别上限 |
    | `vCPU` | 虚拟 CPU 数量 | `2` | 1 – 64 |
    | `内存` | 内存大小（MB） | `1024` | 256 – 262144 |
    | `磁盘大小` | 磁盘大小（GB） | `4` | 2 – 2048 |
    | `主机名` | 虚拟机主机名 | `debian-cloud` | 字母/数字/连字符，≤ 63 字符 |
    | `默认用户名` | 初始用户 | `debian` | 小写字母开头，≤ 32 字符 |
    | `密码` | 用户密码 | `123456` | 仅允许字母/数字及 `@#%+=.,_-`（构建日志中可见，请注意安全） |

5. 构建完成后，在 **Releases** 页面下载生成的 `.ova` 文件。

### 构建目标（ESXi 机型 + DGNU）对照

DGNU 不得超过机型可识别的 Guest OS 上限，工作流会在构建前自动校验：

| ESXi 版本 | 机型 (vmx) | 可识别 DGNU 上限 |
| --- | --- | --- |
| ESXi 6.7 | vmx-14 | 10 |
| ESXi 6.7 U2+ | vmx-15 | 10 |
| ESXi 7.0 | vmx-17 | 10 |
| ESXi 7.0 U1 | vmx-18 | 10 |
| ESXi 7.0 U2/U3 | vmx-19 | 11 |
| ESXi 8.0 / 8.0 U1 | vmx-20 | 12 |
| ESXi 8.0 U2/U3 | vmx-21 | 13 |
| ESXi 9.0+ | vmx-22 | 13 |

> 例如 `ESXi 6.7 + DGNU 9 (vmx-14)` 合法，但 `ESXi 6.7 + DGNU 13 (vmx-14)` 会被拒绝。

---

## 🔐 安全操作指南（必读）

由于 OVA 镜像使用了预设密码，系统启动后存在极大安全风险。请务必执行以下操作：

### 1. 首次登录

- **控制台登录**：使用 VMware/ESXi 的 Web Console 或 VMRC。
- **SSH 登录**：`ssh <用户名>@<IP>`
- **默认凭据**：构建时未修改则为 `debian` / `123456`。

### 2. 修改默认用户密码（高优先级）

登录系统后，立即运行以下命令修改当前用户的密码：

```bash
sudo passwd debian
```

系统会提示：

1. 输入当前密码（`Current password`）
2. 输入新密码（`New password`）
3. 确认新密码（`Retype new password`）

### 3. 修改 / 锁定 Root 密码

默认情况下 Debian Cloud 镜像锁定了 root 登录，但在使用 `sudo` 提权后，建议重置 root 密码或确保其处于锁定状态。

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

## ⚙️ 初始系统配置

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
> sudo sed -i 's|https://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' /etc/apt/sources.list.d/debian.sources
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

## ❓ 常见问题

**Q: 导入 VMware 后无法获取 IP？**
A: 镜像使用 Cloud-Init 配置网络（DHCP）。请确保 VMware 网络适配器已连接，且该网段内有可用的 DHCP 服务。

**Q: 构建日志里能看到我的密码吗？**
A: 是的。当前构建脚本通过命令行传递密码，GitHub Actions 日志会明文记录。因此再次强调：**仅限内部测试使用，生产环境请使用 SSH Key 注入并禁用密码登录。**
