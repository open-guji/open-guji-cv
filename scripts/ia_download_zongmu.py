#!/usr/bin/env python3
"""下载武英殿刻本《钦定四库全书总目》全套扫描（Internet Archive）。

来源：浙大 CADAL 600dpi 扫描，IA 上以连续编号上传：
    06061300.cn ~ 06061498.cn   （199 册 = 卷首四 + 总目 200 卷）
    首册: https://archive.org/details/06061300.cn
    见 book-index: Book/9/6/m/96mid1ogzk-欽定四庫全書總目武英殿刻本.json

用法（可随时中断、重跑续传）：
    python scripts/ia_download_zongmu.py --out data_full/zongmu            # 全套
    python scripts/ia_download_zongmu.py --out data_full/zongmu --start 06061300 --count 5
    python scripts/ia_download_zongmu.py --out data_full/zongmu --prefer pdf

行为：
- 每册先取 metadata，优先选 *_jp2.zip（无损页图），--prefer pdf 时选 PDF；
- 断点续传（HTTP Range），完成后按 IA metadata 的 md5 校验，校验通过写
  <item>.ok 标记，重跑自动跳过；
- 下载前检查磁盘余量（须 > 预估体积 + 5GB 缓冲），不足即停；
- 全程限一个连接（对 IA 友好），失败退避重试 3 次；
- 清单进度写 <out>/manifest.jsonl（一册一行：item、文件、大小、md5、状态）。

注意：Claude Code 远程容器的出口代理封锁 archive.org（组织策略 403），
此脚本须在网络可达 archive.org 的环境运行（本机，或放开策略后的容器）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

FIRST, LAST = 6061300, 6061498          # 06061300.cn ~ 06061498.cn


def http_json(url: str, retries: int = 3) -> dict:
    for k in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if k == retries - 1:
                raise
            time.sleep(5 * (k + 1))
    raise RuntimeError


def pick_file(meta: dict, prefer: str) -> dict | None:
    files = meta.get("files", [])
    def find(pred):
        cands = [f for f in files if pred(f)]
        return max(cands, key=lambda f: int(f.get("size", 0))) if cands else None
    if prefer == "pdf":
        order = [lambda f: f["name"].endswith(".pdf"),
                 lambda f: f["name"].endswith("_cnbook.zip")]
    else:
        # CADAL 中文书 item 无 jp2：原始扫描在 _cnbook.zip（信息量最大，
        # book9 管线即用其中 tif），其次处理版 _tif.zip
        order = [lambda f: f["name"].endswith("_cnbook.zip"),
                 lambda f: f["name"].endswith("_tif.zip"),
                 lambda f: f["name"].endswith("_jp2.zip"),
                 lambda f: f["name"].endswith("_jp2.tar"),
                 lambda f: f["name"].endswith(".pdf")]
    for pred in order:
        f = find(pred)
        if f:
            return f
    return None


def download(url: str, dest: Path, expect_size: int, retries: int = 3) -> None:
    """curl 下载（-L 跟随 IA 302 到存储节点，-C - 断点续传）。

    urllib 经代理跟随跨主机 302 时会 Connection reset（且无 UA 易被
    IA 掐断）；环境里 curl 对代理/CA 的配置最完善，直接复用。"""
    import subprocess
    tmp = dest.with_suffix(dest.suffix + ".part")
    cmd = ["curl", "-sS", "-L", "-C", "-", "--retry", str(retries),
           "--retry-delay", "5", "-m", "1800",
           "-A", "open-guji-cv/1.0 (batch scan fetch; contact via github)",
           "-o", str(tmp), url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl 失败({r.returncode}): {r.stderr.strip()[:200]}")
    if expect_size and tmp.stat().st_size != expect_size:
        raise RuntimeError(f"大小不符: {tmp.stat().st_size} != {expect_size}")
    tmp.rename(dest)


def md5sum(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--start", default=f"0{FIRST}", help="起始编号（如 06061300）")
    ap.add_argument("--count", type=int, default=LAST - FIRST + 1,
                    help="册数（默认全套 199）")
    ap.add_argument("--prefer", default="jp2", choices=["jp2", "pdf"])
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.jsonl"
    start_n = int(args.start.lstrip("0") or "0")
    items = [f"0{n}.cn" for n in range(start_n, min(start_n + args.count, LAST + 1))]
    print(f"计划 {len(items)} 册: {items[0]} ~ {items[-1]}  → {out}")

    done = failed = 0
    for i, item in enumerate(items, 1):
        ok_mark = out / f"{item}.ok"
        if ok_mark.exists():
            done += 1
            continue
        print(f"[{i}/{len(items)}] {item}")
        try:
            meta = http_json(f"https://archive.org/metadata/{item}")
            f = pick_file(meta, args.prefer)
            if f is None:
                raise RuntimeError("未找到可下载文件（jp2.zip/pdf）")
            size = int(f.get("size", 0))
            free = shutil.disk_usage(out).free
            if free < size + 5 * (1 << 30):
                print(f"磁盘余量不足（{free / 1e9:.1f}GB），停在 {item}")
                sys.exit(2)
            dest = out / f["name"]
            if not dest.exists():
                url = f"https://archive.org/download/{item}/{f['name']}"
                print(f"    {f['name']}  {size / 1e6:.0f} MB")
                download(url, dest, size)
            digest = md5sum(dest)
            if f.get("md5") and digest != f["md5"]:
                dest.unlink()
                raise RuntimeError(f"md5 不符（{digest} != {f['md5']}），已删待重下")
            with open(manifest, "a", encoding="utf-8") as mf:
                mf.write(json.dumps({"item": item, "file": f["name"],
                                     "size": size, "md5": digest,
                                     "ts": time.strftime("%F %T")},
                                    ensure_ascii=False) + "\n")
            ok_mark.write_text(digest)
            done += 1
        except SystemExit:
            raise
        except Exception as e:
            print(f"    失败: {e}")
            failed += 1
    print(f"完成 {done}/{len(items)}，失败 {failed}")


if __name__ == "__main__":
    main()
