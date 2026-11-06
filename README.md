# Debian Cloud OVA Builder

基于 **Debian 官方云镜像**（源自 [cloud.debian.org](https://cloud.debian.org/images/cloud/)），通过封装 Cloud-Init 配置，构建面向 **VMware ESXi / Workstation** 的 OVA 虚拟机模板。其他平台兼容性需自行验证。

> [!CAUTION]
> **安全警告：仅限内部测试环境使用**
>
> - 本工具生成的镜像包含预设的**默认凭据**。
> - **绝对不要**将生成的 OVA 文件直接部署到公网或生产环境。
> - 部署后必须**第一时间修改密码**。

---

## 功能特性

- **官方源构建**：基于 `Debian Official Cloud Images` 构建，确保纯净安全。
- **多版本支持**：Debian 12 (Bookworm)、13 (Trixie)，每次选择一个系统构建。Guest OS 标识（DGNU）按 ESXi 兼容性选择，与实际系统版本独立。
- **机型精确匹配**：通过四个下拉框一次选择最多四种 ESXi + Guest OS 组合，保留全部预设选项，重复组合自动去重。
- **硬件定制**：构建时可自定义 vCPU、内存和磁盘大小（输入最小 2 GiB；小于源镜像实际虚拟容量时，自动采用源镜像容量继续构建）。
- **自动化发布**：通过 GitHub Actions 构建并发布到 Releases。
- **Cloud-Init**：自动配置主机名、登录账户和密码；SSH 镜像额外启用 root 密码登录。

---

## 快速开始（GitHub Actions）

本项目仅支持通过 **GitHub Actions** 构建。

1. 进入项目的 **Actions** 页面。
2. 选择 **「构建并发布 Debian OVA」** 工作流。
3. 点击 **Run workflow** 按钮。
4. 根据需求填写参数：

    | 参数 | 说明 | 默认值 | 可选范围 / 备注 |
    | --- | --- | --- | --- |
    | `Debian 系统版本` | 系统单选下拉框 | `13` | `12` / `13` |
    | `ESXi 机型 + Guest OS` | ESXi 机型 + Guest OS | `ESXi 6.7 U3 + DGNU 10 (vmx-15)` | 下拉选择有效预设组合 |
    | `附加机型 1` | ESXi 机型 + Guest OS | `ESXi 7.0 U3 + DGNU 11 (vmx-19)` | 全部预设组合及“不构建” |
    | `附加机型 2` | ESXi 机型 + Guest OS | `ESXi 8.0 U3 + DGNU 13 (vmx-21)` | 全部预设组合及“不构建” |
    | `附加机型 3` | ESXi 机型 + Guest OS | `ESXi 9.0+ + DGNU 13 (vmx-22)` | 全部预设组合及“不构建” |
    | `vCPU` | 虚拟 CPU 数量 | `2` | 1 – 64 |
    | `内存` | 内存大小（MB） | `1024` | 256 – 262144 |
    | `磁盘大小` | 磁盘容量（GiB） | `4` | 2 – 2048；实际容量取请求容量与源镜像容量中的较大值 |
    | `主机名` | 虚拟机主机名 | `debian-cloud` | 字母/数字/连字符，≤ 63 字符 |
    | `启用 SSH` | 额外构建 SSH 镜像 | 不勾选 | 默认必建 console 镜像；勾选后同时生成 SSH 镜像 |
    | `用户名` | console 镜像的控制台用户 | `debian` | 必须为普通用户名；附加 SSH 镜像固定使用 root |
    | `更改软件源` | 首次启动时配置 APT | `官方源` | 官方源 / 清华大学 / 中国科学技术大学 / 阿里云 / 华为云；两种镜像采用相同设置 |
    | `安装 open-vm-tools` | VMware 工具服务 | 勾选 | 首次启动时安装并启用；不勾选则不主动安装或启动，不卸载镜像已有版本 |
    | `时区` | 虚拟机系统时区 | `UTC` | 上海、香港、新加坡、东京、伦敦、柏林、纽约或 UTC；两种镜像共用 |
    | `登录密码` | 两种镜像共用的登录密码 | `123456` | console 镜像用于普通用户，SSH 镜像用于 root；仅允许字母/数字及 `@#%+=.,_-`（构建日志中可见） |

5. 构建完成后，在 **Releases** 页面下载生成的 `.ova` 文件。

每次选择一个 Debian 版本（默认 13），最多构建四种机型。附加机型可选“不构建”，重复选择自动去重，各机型共用自定义参数。

磁盘小于源镜像容量时自动调整，实际大小见 Release；首次启动自动扩展分区和文件系统。

### SSH 与登录方式

| 镜像后缀 | 登录账户 | 登录方式 |
| --- | --- | --- |
| `-console.ova` | 指定的普通用户 | 虚拟机控制台；SSH 保持源镜像默认配置 |
| `-ssh.ova` | `root` | SSH 密码登录 |

console 镜像不额外关闭 SSH，也不主动开启密码认证；是否允许 SSH 密码登录取决于官方云镜像的默认配置。

首次启动需联网。用 `cloud-init status --long` 确认初始化完成后，再执行 `ssh root@<虚拟机 IP>`；此前已连接的客户端请断开重连。初始化失败时查看 `/var/log/cloud-init-output.log`。

---

## 安全操作指南（必读）

由于 OVA 镜像使用了预设密码，系统启动后存在极大安全风险。请务必执行以下操作：

### 1. 首次登录

- **控制台登录**：使用 VMware/ESXi 的 Web Console 或 VMRC，登录本次配置的账户。
- **SSH 登录**：SSH 镜像可直接使用 `ssh root@<IP>`；console 镜像沿用官方云镜像的 SSH 默认配置。
- **默认凭据**：console 镜像为 `debian` / `123456`；附加 SSH 镜像为 `root` / `123456`，请在构建时修改密码。

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

console 镜像不设置 root 密码；SSH 镜像已为 root 设置面板中的登录密码。普通用户可通过 `sudo` 管理 root 密码。

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

## 初始系统配置（可选）

### 1. 软件源

- **官方源（默认）**：保留官方镜像的软件源配置。
- **选择中国软件源**：首次启动时将已有 Debian 官方普通软件源地址替换为所选镜像站，安全更新仍使用 `https://security.debian.org/debian-security`。
- 源地址文件位于 `/etc/apt/mirrors/*.list`；首次修改前在原目录备份为 `.bak`（如 `debian.list.bak`），已有备份不覆盖。

| 选项 | 普通软件源地址 |
| --- | --- |
| 清华大学 | `https://mirrors.tuna.tsinghua.edu.cn/debian` |
| 中国科学技术大学 | `https://mirrors.ustc.edu.cn/debian` |
| 阿里云 | `https://mirrors.aliyun.com/debian` |
| 华为云 | `https://repo.huaweicloud.com/debian` |

官方源手动改源（以清华大学为例）：

```bash
sudo cp -a /etc/apt/mirrors/debian.list "/etc/apt/mirrors/debian.list.$(date +%Y%m%d_%H%M%S).bak"
printf '%s\n' 'https://mirrors.tuna.tsinghua.edu.cn/debian' | sudo tee /etc/apt/mirrors/debian.list > /dev/null
sudo apt update
```

可将示例地址替换为上表中的其他软件源；仅修改普通软件源列表，安全更新源保持不变。

### 2. 虚拟机工具集

面板中的“安装 open-vm-tools”默认勾选，首次启动时安装并启用。取消勾选后不主动安装或启动工具，也不卸载镜像可能已有的版本。未联网导致安装失败时，可在虚拟机中手动安装：

```bash
sudo apt install open-vm-tools
```

### 3. 修改时区（Timezone）

首次启动按面板所选时区设置，默认 `UTC`。可选 `Asia/Shanghai`、`Asia/Hong_Kong`、`Asia/Singapore`、`Asia/Tokyo`、`Europe/London`、`Europe/Berlin` 和 `America/New_York`，也可在部署后手动修改：

```bash
sudo dpkg-reconfigure tzdata
```

---

## 常见问题

**Q: 导入 VMware 后无法获取 IP？**
A: 镜像使用 Cloud-Init 配置网络（DHCP）。请确保 VMware 网络适配器已连接，且该网段内有可用的 DHCP 服务。

**Q: 构建日志里能看到我的密码吗？**
A: 是的。当前构建脚本通过命令行传递密码，GitHub Actions 日志会明文记录。因此再次强调：**仅限内部测试使用，部署后必须立即修改密码，不要直接用于公网或生产环境。**
