# 维护说明

OVA 构建由 GitHub Actions 手动触发。`scripts/` 中的构建程序是工作流内部实现，不提供本地构建入口。

## 文件职责

| 路径 | 职责 |
| --- | --- |
| `.github/workflows/build-ova.yml` | 面板、依赖、构建与发布调度 |
| `.github/build-targets.json` | 有效机型与 Guest OS 组合 |
| `scripts/config.py` | 参数校验、规范化与目标选择 |
| `scripts/source.py` | 固定官方 build、下载与 SHA512 校验 |
| `scripts/build.py` | 批量构建与统一结果清单 |
| `scripts/render.py`、`templates/` | cloud-init 与 OVF 生成 |
| `guest/` | 首次启动运行的 SSH、工具和软件源配置 |
| `debian-ova-creator.sh` | 磁盘准备、转换与 OVA 打包 |
| `scripts/report.py`、`scripts/publish.sh` | 摘要、单份 Release 说明和资产发布 |
| `scripts/release.py` | main 发布标签与来源校验 |
| `scripts/manifest.py` | 构建清单字段、类型和资产列表校验 |
| `scripts/panel.py` | 所有下拉框的默认值及共享选项校验 |
| `tests/` | 参数、配置、缓存、打包与发布失败路径的回归检查 |

新增构建参数时，同时更新工作流 `inputs`/`env`、`config.py` 的环境变量映射、`build.py` 的调用参数和 `render.py` 的接收顺序，并核对 README。默认值仅由工作流提供；内部 Bash 入口要求所有参数显式传入。

修改机型目录后运行 `python3 scripts/update-panel.py` 更新静态下拉选项，保留原有默认值。检查工作流会校验面板与目录一致。

并发队列使用 GitHub 的 [`queue: max`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)，防止新请求替换已排队的构建。检查工具不识别该字段时应先核对工具版本，保留队列策略。

## 本地检查

检查环境要求 Linux（Debian/Ubuntu 或 WSL）、Python >=3.8，以及通过 apt 安装的 `python3-yaml`、`cloud-init`、`shellcheck`、`python3-venv`。使用系统 `/usr/bin/python3` 执行回归测试，避免虚拟环境解释器无法导入系统依赖。Pyflakes 单独装在工具虚拟环境，版本由 `requirements-check.txt` 固定：

```sh
shellcheck debian-ova-creator.sh scripts/publish.sh guest/*.sh
/usr/bin/python3 -m venv .venv-check
.venv-check/bin/python -m pip install -r requirements-check.txt
.venv-check/bin/python -m pyflakes scripts guest tests
/usr/bin/python3 scripts/check-environment.py
/usr/bin/python3 scripts/update-panel.py --check
/usr/bin/python3 -m unittest discover -s tests -t . -v
# 也可以独立运行模块：
/usr/bin/python3 -m unittest tests.test_panel_publish -v
```

CI 在 `$RUNNER_TEMP/check-venv` 创建临时工具环境；本地使用已被 Git 忽略的 `.venv-check/`，两者读取同一份 `requirements-check.txt`。

测试使用隔离目录和磁盘工具替身，不下载真实 qcow2、不发布 Release、不修改宿主机服务或软件源。它们不能代替 ESXi 启动验证。启动相关变更还应验证无串口环境中的首次扩容、`cloud-init status --long`、SSH/控制台账户以及实际分区和文件系统容量。

## 必须保留的约定

- 仅构建 Debian 12/13，机型和 Guest OS 使用目录中的有效组合。
- console 镜像必建；SSH 开关只增加 root 密码登录镜像。
- console 沿用官方镜像的 SSH 软件包、服务和认证配置；仅 SSH 镜像额外配置 root 密码登录。
- 磁盘不缩小，实际容量至少为官方源镜像容量。
- 构建前写入 `/etc/growroot-disabled`；首次启动由 cloud-init 接管扩容。
- 转换后的 VMDK 在独立只读会话中复核空标记，失败停止打包；成功结果绑定 VMDK 内容摘要并供批量构建复用。
- 换源仅修改已有 `/etc/apt/mirrors/*.list`，保留源定义、安全更新地址和原文件备份。
- 源版本在下载前固定，原始 qcow2 校验通过后才进入可变磁盘准备流程。
- 所有机型构建成功且通过清单校验后才产生发布输出。同一 Debian 版本排队执行，不取消正在执行或已排队的构建。
- 仅 main 发布正式版（显式传入 `--prerelease=false`），复用官方 build 标签；其他分支、tag 和 PR ref 不允许发布。历史资产保留，正文只保留本次的一份说明。
- 发布前再次校验分支、系统版本与标签。旧格式或损坏清单应明确报错，不通过缺省值绕过发布校验。

访客机配置以 Debian 12 的 cloud-init 22.4.2 和 Debian 13 为验证基线。软件源零替换时区分“已配置”和“未匹配到官方源”；后者记录警告并保留现有源，不因私人源或幂等重跑而强制失败。

`build-manifest.json` 保存本次批量结果，不含密码；镜像内的 `/etc/ova-build-info.json` 记录源版本、摘要、代码提交和请求配置。公开 Release 的登录密码行为保持原有约定，不能填写私人复用密码。SHA512 校验依据从 Debian HTTPS 获取的摘要，不等同于离线签名验证。

## 虚拟磁盘兼容性

当前 OVF 采用 `VirtualSCSI`；VMDK 描述符沿用 QEMU 的默认适配器元数据。`lsilogic` 不能直接视为与 `VirtualSCSI` 相同。现有 ESXi 镜像能够启动，暂不为消除文本差异而更换控制器或适配器类型。调整前应单独验证 ESXi 导入、实际驱动、首次启动和扩容；QEMU 的磁盘检查不代替 ESXi 导入回归。
