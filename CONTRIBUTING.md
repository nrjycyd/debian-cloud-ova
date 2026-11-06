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
| `tests/` | 参数、配置、缓存、打包与发布失败路径的回归检查 |

修改机型目录后运行 `python3 scripts/update-panel.py` 更新静态下拉选项，保留原有默认值。检查工作流会校验面板与目录一致。

并发队列使用 GitHub 的 [`queue: max`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)，防止新请求替换已排队的构建。actionlint 1.7.12 尚不识别该字段；不要为通过旧版校验器而删除队列策略。

## 本地检查

在 Debian/Ubuntu 或 WSL 中安装 `python3-yaml`、`cloud-init`、`shellcheck` 后运行：

```sh
shellcheck debian-ova-creator.sh scripts/publish.sh guest/*.sh
/usr/bin/python3 scripts/update-panel.py --check
/usr/bin/python3 -m unittest discover -s tests -v
```

测试使用隔离目录和磁盘工具替身，不下载真实 qcow2、不发布 Release、不修改宿主机服务或软件源。它们不能代替 ESXi 启动验证。启动相关变更还应验证无串口环境中的首次扩容、`cloud-init status --long`、SSH/控制台账户以及实际分区和文件系统容量。

## 必须保留的约定

- 仅构建 Debian 12/13，机型和 Guest OS 使用目录中的有效组合。
- console 镜像必建；SSH 开关只增加 root 密码登录镜像。
- 磁盘不缩小，实际容量至少为官方源镜像容量。
- 构建前写入 `/etc/growroot-disabled`；首次启动由 cloud-init 接管扩容。
- 换源仅修改已有 `/etc/apt/mirrors/*.list`，保留源定义、安全更新地址和原文件备份。
- 源版本在下载前固定，原始 qcow2 校验通过后才进入可变磁盘准备流程。
- 所有机型构建成功后才产生发布清单。同一 Debian 版本排队执行，跨分支共用队列，不取消正在执行的构建。
- 复用官方 build 标签，历史资产保留，Release 正文只保留本次的一份说明。

`build-manifest.json` 保存本次批量结果，不含密码；镜像内的 `/etc/ova-build-info.json` 记录源版本、摘要、代码提交和请求配置。公开 Release 的登录密码行为保持原有约定，不能填写私人复用密码。SHA512 校验依据从 Debian HTTPS 获取的摘要，不等同于离线签名验证。
