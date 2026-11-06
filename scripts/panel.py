"""校验工作流静态选项与共享目录是否一致。"""

import yaml

from config import MIRRORS, TIMEZONES, VERSIONS, catalog


def validate(text):
    workflow = yaml.safe_load(text)
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    expected = {
        "debian_version": list(VERSIONS), "apt_mirror": [label for label, _ in MIRRORS.values()],
        "timezone": list(TIMEZONES),
    }
    labels = [item["label"] for item in catalog()]
    for index, name in enumerate(("build_target", "build_target_2", "build_target_3", "build_target_4")):
        expected[name] = labels if index == 0 else ["不构建"] + labels
    for name, definition in inputs.items():
        if definition.get("type") == "choice" and definition.get("default") not in definition.get("options", []):
            raise ValueError(f"面板 {name} 的默认值不在可选列表中")
    for name, options in expected.items():
        if inputs[name]["options"] != options:
            raise ValueError(f"面板 {name} 的选项与共享配置不一致")
