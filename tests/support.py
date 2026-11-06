import hashlib
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def source_info(version="12", payload=b"qcow2"):
    build = "20261106-1234"
    codename = {"12": "bookworm", "13": "trixie"}[version]
    return {"debian_version": version, "build": build,
            "url": f"https://cloud.debian.org/images/cloud/{codename}/{build}/debian-{version}-genericcloud-amd64-{build}.qcow2",
            "sha512": hashlib.sha512(payload).hexdigest()}


@contextmanager
def build_fixture():
    """Real builder/tar/rendering; fake only the external disk/ISO tools."""
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="ova-regression-") as directory:
        work = Path(directory)
        binaries = work / "bin"
        binaries.mkdir()
        mocks = {
            "cloud-localds": '#!/bin/sh\ncp "$2" "$1"\n',
            # Keep the runner's sudo branch inside the isolated fake toolchain.
            "sudo": '#!/bin/sh\n[ "$1" = -n ] || exit 1\nshift\necho sudo >> sudo-calls\nexec "$@"\n',
            "guestfish": '''#!/usr/bin/python3
import os, sys
from pathlib import Path
commands = sys.stdin.read()
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
                             TMPDIR=str(work), GITHUB_SHA="a" * 40)
        finally:
            os.chdir(previous)


def fake_download(info, destination):
    Path(destination).write_bytes(b"3221225472\n")
