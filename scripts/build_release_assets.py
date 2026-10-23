#!/usr/bin/env python3
"""打发版附件：wheel（代码）＋资源包（models/、config/、formats/、precleaned/）＋ install_release.py ＋ SHA256SUMS。

用法：python scripts/build_release_assets.py [--out dist/release]

为什么要资源包：代码里大量按 `Path(__file__).resolve().parents[2] / "models|config|…"` 找仓库根，
wheel 只含 `open_guji_cv/`，装进 site-packages 后这些目录不在。资源包按**同一相对布局**
（`models/…`、`config/…`）解到 `open_guji_cv` 的上一级目录，源码零改动，各 Step 的 code_hash 不变。
清单取 `git ls-files`（不带 gitignore 的缓存），不带 `models/glyph_cnn_r4`（上一代，可切回时自取）。
corpus/ 走中心库（`guji db pull`）；fonts/（194 MB）暂不在包里，`db pull` 也不取字体，是否另出字体包待用户定。
设计见 doc/design/发版附带Python执行包.md。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIRS = ("models", "config", "formats", "precleaned")
SKIP_PREFIXES = ("models/glyph_cnn_r4/",)


def version() -> str:
    import tomllib
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def data_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", *DATA_DIRS], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return sorted(f for f in out.split("\0") if f and not f.startswith(SKIP_PREFIXES))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "release"))
    out = Path(ap.parse_args().out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    ver = version()

    subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(out)], cwd=ROOT, check=True)

    files = data_files()
    if not files:
        print("没有取到资源文件（要在 git 检出里跑）", file=sys.stderr)
        return 1
    data = out / f"open-guji-cv-data-{ver}.tar.gz"
    with tarfile.open(data, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        for rel in files:
            ti = tf.gettarinfo(str(ROOT / rel), arcname=rel)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mtime = 0  # 同一输入出同一字节
            with (ROOT / rel).open("rb") as f:
                tf.addfile(ti, f)

    shutil.copy(ROOT / "scripts" / "install_release.py", out / "install_release.py")
    sums = [f"{sha256(p)}  {p.name}" for p in sorted(out.iterdir()) if p.is_file()]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    for p in sorted(out.iterdir()):
        print(f"{p.stat().st_size / 1e6:8.1f} MB  {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
