"""按清单针对性地查字统网，攒进本机缓存（总设计 B4）。一次一字、≥3 秒间隔，只存派生事实。

    python scripts/zi_fetch.py 歷互亙                          # 直接给字
    python scripts/zi_fetch.py --file 待查.txt                  # 文件里出现的字（去重）
    python scripts/zi_fetch.py --cards <册>.cards.alt.json      # 待审卡上的近似字（同 audit alt 的取法）
    python scripts/zi_fetch.py --pivot-rows research/pivot_family/rows.jsonl.gz   # 回归集的近似字与金标字

- 缓存目录同 `ZiCache`（`$GUJI_ZITOOLS_CACHE`，缺省 `$GUJI_DATA_HOME/_shared/zitools/`）；
  已有新格式的跳过，旧格式（只有一跳族）的重取一次补上逐节点事实。可随时中断，重跑接着来。
- 攒够了出新版库：`python scripts/build_hanzi_db.py --zi-dir <缓存目录>`，再 `--upload`，全队共享。
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.variant_sources import ZiCache, is_han


def collect(args) -> list[str]:
    out: list[str] = []

    def put(s: str) -> None:
        for c in s or "":
            if is_han(c) and c not in out:
                out.append(c)

    for s in args.chars:
        put(s)
    if args.file:
        put(Path(args.file).read_text(encoding="utf-8"))
    if args.cards:
        from open_guji_cv.review.alt_cands import pivots_of
        doc = json.loads(Path(args.cards).read_text(encoding="utf-8"))
        for c in doc["cards"] if isinstance(doc, dict) else doc:
            put("".join(pivots_of(c)))
    if args.pivot_rows:
        with gzip.open(args.pivot_rows, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                put((r.get("pivot") or "") + r["g"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chars", nargs="*", help="要查的字（可连写）")
    ap.add_argument("--file")
    ap.add_argument("--cards")
    ap.add_argument("--pivot-rows")
    ap.add_argument("--cache", type=Path, default=None, help="缓存目录（缺省同 ZiCache）")
    ap.add_argument("--limit", type=int, default=0, help="最多联网取几个字（0＝不限）")
    args = ap.parse_args()

    chars = collect(args)
    z = ZiCache(args.cache, fetch=True)
    t0 = time.time()
    fetched = failed = 0
    for i, c in enumerate(chars, 1):
        if args.limit and fetched >= args.limit:
            break
        if z.ensure(c, upgrade=True):
            if z._mem.get(c) is None:
                failed += 1
            else:
                fetched += 1
        if i % 50 == 0:
            print(f"{i}/{len(chars)}  新取 {fetched}  失败 {failed}  {time.time() - t0:.0f} 秒", flush=True)
    print(f"完成：清单 {len(chars)} 字，新取 {fetched}，失败 {failed}，{time.time() - t0:.0f} 秒 → {z.root}")


if __name__ == "__main__":
    main()
