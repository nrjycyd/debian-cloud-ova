"""Change existing mirror lists only; keep source definitions and security origin."""

import re
import shutil
import sys
from pathlib import Path


def configure_mirrors(apt_dir, mirror):
    primary = re.compile(r"https?://(?:deb\.debian\.org|httpredir\.debian\.org|ftp\.debian\.org|ftp\.[a-z]{2}\.debian\.org)/debian(?=[/\s]|$)")
    security = re.compile(r"https?://(?:deb\.debian\.org|security\.debian\.org)/debian-security(?=[/\s]|$)")
    for path in sorted((apt_dir / "mirrors").glob("*.list")):
        if not path.is_file() or path.is_symlink():
            continue
        original = path.read_text(encoding="utf-8")
        updated = security.sub("https://security.debian.org/debian-security", original)
        updated = primary.sub(mirror, updated)
        if updated != original:
            backup = apt_dir / "ova-source-backups" / path.relative_to(apt_dir)
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
            path.write_text(updated, encoding="utf-8")
            print("[INFO] 已更新软件源：" + str(path))


if __name__ == "__main__":
    configure_mirrors(Path("/etc/apt"), sys.argv[1])
