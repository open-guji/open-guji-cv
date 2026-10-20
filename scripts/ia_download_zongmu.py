#!/usr/bin/env python3
"""下载武英殿刻本《钦定四库全书总目》全套扫描（Internet Archive）。

来源：浙大 CADAL 600dpi 扫描，IA 上**分两段编号、共 99 册**（2026-10-20 GUJI-648 逐号核过，书单见
`doc/runbook/书单-四庫總目.md`）：
    06061300.cn ~ 06061320.cn   21 册：卷首一～四、卷一～四十四（vol01–vol21）
    06066140.cn ~ 06066217.cn   78 册：卷四十五～二百（vol22–vol99）
以前写的「199 册 = 06061300～06061498 连号」是错的：06061321 起是别的书。
    见 book-index: Book/g/z/k/96mid1ogzk-欽定四庫全書總目武英殿刻本.json

用法（可随时中断、重跑续传）：
    python scripts/ia_download_zongmu.py --out data_full/zongmu                 # 全套 99 册
    python scripts/ia_download_zongmu.py --out data_full/zongmu --vols 11-20    # 按册号（第 1 波）
    python scripts/ia_download_zongmu.py --out data_full/zongmu --prefer pdf

行为：
- 每册先取 metadata，缺省选 *_tif.zip：1-bit 600dpi 页图，与工作区现有 vol01–10 的 PNG 逐像素一致
  （GUJI-648 抽 vol03 第 10 页核过）；没有再退 _cnbook.zip（原始包，体积约 1.6 倍）；--prefer pdf 时选 PDF；
- 断点续传（HTTP Range），完成后按 IA metadata 的 md5 校验，校验通过写
  <item>.ok 标记，重跑自动跳过；
- 下载前检查磁盘余量（须 > 预估体积 + 5GB 缓冲），不足即停；
- 全程限一个连接（对 IA 友好），失败退避重试 3 次；
- 清单进度写 <out>/manifest.jsonl（一册一行：item、文件、大小、md5、状态）。
- 每册第 1 张是书脊标签；部分册有合扫页（vol03/04/07/09 各拆出 3 页），下完逐册查。
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

#: 全书 99 册的 IA 编号，下标＋1＝册号（vol01＝06061300.cn）。两段编号见模块头。
ITEMS = [f"0{n}.cn" for n in range(6061300, 6061321)] + [f"0{n}.cn" for n in range(6066140, 6066218)]


def select(vols: str | None) -> list[str]:
    """`11-20`／`3,5,7`／空（全套）→ IA 编号列表。"""
    if not vols:
        return list(ITEMS)
    want: list[int] = []
    for part in vols.split(","):
        a, _, b = part.partition("-")
        want += range(int(a), int(b or a) + 1)
    bad = [v for v in want if not 1 <= v <= len(ITEMS)]
    if bad:
        raise SystemExit(f"册号超出 1–{len(ITEMS)}：{bad}")
    return [ITEMS[v - 1] for v in want]


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
        # CADAL 中文书 item 无 jp2：_tif.zip 与工作区现有原图逐像素一致，体积小；
        # 没有再退原始包 _cnbook.zip（GUJI-648）
        order = [lambda f: f["name"].endswith("_tif.zip"),
                 lambda f: f["name"].endswith("_cnbook.zip"),
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
    ap.add_argument("--vols", default=None, help="册号，如 11-20 或 3,5,7；缺省全套 99 册")
    ap.add_argument("--prefer", default="tif", choices=["tif", "pdf"])
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.jsonl"
    items = select(args.vols)
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
                raise RuntimeError("未找到可下载文件（tif.zip/cnbook.zip/pdf）")
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
