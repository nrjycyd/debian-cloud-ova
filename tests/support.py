import hashlib
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from config import VARIANTS, variant_policy
from release import policy


def source_info(version="12", payload=b"qcow2", variant=None):
    build = "20261106-1234"
    codename = {"12": "bookworm", "13": "trixie"}[version]
    # 默认取当前配置的优先变体，测试不写死具体名称。
    variant = variant or variant_policy(VARIANTS)[0]
    return {"debian_version": version, "build": build, "variant": variant,
            "url": f"https://cloud.debian.org/images/cloud/{codename}/{build}/debian-{version}-{variant}-amd64-{build}.qcow2",
            "sha512": hashlib.sha512(payload).hexdigest()}


def environment():
    return {
        "TARGET_VERSION": "13", "TARGET_VCPU": "2", "TARGET_MEMORY": "1024", "TARGET_DISK": "4",
        "TARGET_HOSTNAME": "debian-cloud", "TARGET_USERNAME": "debian", "TARGET_PASSWORD": "123456",
        "TARGET_ENABLE_SSH": "true", "TARGET_APT_MIRROR": "官方源",
        "TARGET_INSTALL_VM_TOOLS": "true", "TARGET_TIMEZONE": "UTC",
        "TARGET_BUILD": "ESXi 6.7 U3 + DGNU 10 (vmx-15)",
        "TARGET_BUILD_2": "ESXi 7.0 U3 + DGNU 11 (vmx-19)",
        "TARGET_BUILD_3": "ESXi 8.0 U3 + DGNU 13 (vmx-21)",
        "TARGET_BUILD_4": "ESXi 9.0+ + DGNU 13 (vmx-22)",
    }


def sample_manifest():
    return {"settings": {"version": "13", "vcpu": 2, "memory": 1024, "disk": 4,
                         "hostname": "debian13", "username": "debian", "mirror": "official",
                         "install_vm_tools": True, "timezone": "UTC"},
            "source": source_info("13"), "release": policy("refs/heads/main", "13", "20261106-1234"),
            "build_time": "2026-11-06 00:00:00 UTC", "target_count": 1,
            "images": [{"target": "ESXi 7.0 U3 + DGNU 11 (vmx-19)", "kind": "console",
                        "filename": "debian13-console.ova", "username": "debian", "size": "320M",
                        "disk_gib": "4.00", "disk_bytes": 4294967296}]}


@contextmanager
def build_fixture():
    """使用真实构建、tar 和渲染程序，仅替换外部磁盘与 ISO 工具。"""
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="ova-regression-") as directory:
        work = Path(directory)
        binaries = work / "bin"
        binaries.mkdir()
        mocks = {
            "cloud-localds": '#!/bin/sh\ncp "$2" "$1"\nif [ "${MOCK_TEMP_RESIDUE:-}" = true ]; then touch "$(dirname "$2")/residue"; fi\n',
            # 将 runner 的 sudo 分支限制在隔离的工具替身中。
            "sudo": '#!/bin/sh\n[ "$1" = -n ] || exit 1\nshift\necho sudo >> sudo-calls\nexec "$@"\n',
            "guestfish": '''#!/usr/bin/python3
import os, sys
from pathlib import Path
commands = sys.stdin.read()
if '--ro' in sys.argv:
    assert '--format=vmdk' in sys.argv and 'filesize /etc/growroot-disabled' in commands
    with Path('verify-calls').open('a') as output: output.write('verify\\n')
    mode = os.environ.get('MOCK_VERIFY', '')
    if mode == 'fail': sys.exit(1)
    print('false' if mode == 'missing' else 'true')
    print('1' if mode == 'nonempty' else '0')
    sys.exit()
assert 'touch /etc/growroot-disabled' in commands and 'is-file /etc/growroot-disabled' in commands
with Path('guestfish-calls').open('a') as output: output.write('prepare\\n')
mode = os.environ.get('MOCK_GUESTFISH', '')
if mode == 'fail': sys.exit(1)
if mode == 'missing': print('false'); sys.exit()
disk = Path(sys.argv[sys.argv.index('-a') + 1])
with disk.open('ab') as output: output.write(b'growroot-disabled\\n')
print('true')
''',
            "qemu-img": '''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if os.environ.get('MOCK_FAIL_VMX') == os.environ.get('VIRTUAL_SYSTEM_TYPE'): sys.exit(31)
mode = os.environ.get('MOCK_QEMU', '')
if args[0] == 'info':
    if mode == 'invalid-json': print('bad JSON'); sys.exit()
    size = int(Path(args[-1]).read_text().splitlines()[0])
    print(json.dumps({'format-specific': {'data': {'virtual-size': 512}}, 'virtual-size': size}))
elif args[0] == 'resize':
    Path(args[-2]).write_text(str(int(args[-1][:-1]) * 1073741824) + '\\n')
elif args[0] == 'convert':
    size = int(Path(args[-2]).read_text().splitlines()[0])
    if mode == 'wrong-vmdk': size -= 512
    Path(args[-1]).write_text(str(size) + '\\n')
    with Path('convert-calls').open('a') as output: output.write('convert\\n')
''',
        }
        for name, content in mocks.items():
            executable = binaries / name
            executable.write_text(content)
            executable.chmod(0o755)
        os.chdir(work)
        try:
            yield work, dict(os.environ, PATH=str(binaries) + ":" + os.environ["PATH"],
                             GITHUB_ACTIONS="true", RUNNER_TEMP=str(work), GITHUB_OUTPUT=str(work / "outputs"),
                             TMPDIR=str(work), GITHUB_SHA="a" * 40, GITHUB_REF="refs/heads/main")
        finally:
            os.chdir(previous)


def fake_download(info, destination):
    Path(destination).write_bytes(b"3221225472\n")
