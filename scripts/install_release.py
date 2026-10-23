#!/usr/bin/env python3
"""装发版附件（只用标准库 ＋ pip）：wheel 装进当前 Python，资源包解到 open_guji_cv 的上一级目录。

用法（版本号去掉 v）：
    python install_release.py 0.5.9            # 从 GitHub Release 下载
    python install_release.py --dir ./assets   # 附件已在本地目录

装好后 `guji --help` 可用；corpus 走中心库（`guji db pull`）；fonts/ 目前不在包里（`db pull` 不取字体），见 README。
资源（models/、config/、formats/、precleaned/）解到 open_guji_cv 的上一级目录。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "open-guji/open-guji-cv"


def fetch(name: str, tag: str, dest: Path) -> Path:
    p = dest / name
    urllib.request.urlretrieve(f"https://github.com/{REPO}/releases/download/{tag}/{name}", p)
    return p


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", nargs="?", help="如 0.5.9（不带 v）")
    ap.add_argument("--dir", help="附件所在本地目录（不下载）")
    ap.add_argument("--extras", default="", help="pip extras，如 cpu,datastore")
    ap.add_argument("--no-deps", action="store_true",
                    help="只装 wheel 本身、不解依赖（环境里已预装 torch/paddle 等时用，免得被换成别的轮子）")
    a = ap.parse_args()
    if bool(a.version) == bool(a.dir):
        ap.error("给版本号或 --dir，二选一")

    if a.dir:
        d = Path(a.dir)
    else:
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="guji-cv-"))
        tag = f"v{a.version}"
        sums = fetch("SHA256SUMS", tag, d)
        for line in sums.read_text().splitlines():
            name = line.split()[-1]
            if name.endswith((".whl", ".tar.gz")):
                fetch(name, tag, d)
    expect = {l.split()[-1]: l.split()[0] for l in (d / "SHA256SUMS").read_text().splitlines() if l.strip()}
    wheel = next(d.glob("open_guji_cv-*.whl"))
    data = next(d.glob("open-guji-cv-data-*.tar.gz"))
    for p in (wheel, data):
        if sha256(p) != expect.get(p.name):
            print(f"校验失败：{p.name}", file=sys.stderr)
            return 1

    spec = str(wheel) + (f"[{a.extras}]" if a.extras else "")
    # 优先 uv（uv venv 建的环境没有 pip），没有 uv 再用 pip
    uv = shutil.which("uv")
    cmd = [uv, "pip", "install", "--python", sys.executable] if uv else [sys.executable, "-m", "pip", "install"]
    if a.no_deps:
        cmd.append("--no-deps")
    subprocess.run([*cmd, spec], check=True)
    # 解到包所在目录的上一级：代码按 parents[2] 找 models/、config/，与仓库布局一致
    out = subprocess.run([sys.executable, "-c",
                          "import open_guji_cv,pathlib;print(pathlib.Path(open_guji_cv.__file__).resolve().parents[1])"],
                         check=True, capture_output=True, text=True).stdout.strip()
    with tarfile.open(data) as tf:
        for m in tf.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts or m.name.split("/")[0] not in ("models", "config", "formats", "precleaned"):
                raise ValueError(f"资源包里有不合规的路径：{m.name}")
        tf.extractall(out, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(out)
    # 装后自检：关键资源缺了就拒绝（缺 checkpoint 等处代码是静默退化，不报错）
    must = ["models/glyph_cnn_r5/best.pt", "models/partition_unet_v2", "config/charset", "config/groups",
            "formats/guji_page_v0.2.schema.json", "precleaned"]
    miss = [m for m in must if not (Path(out) / m).exists()]
    if miss:
        print(f"装后自检失败，缺：{miss}", file=sys.stderr)
        return 1
    print(f"已装 {wheel.name}；资源解到 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
