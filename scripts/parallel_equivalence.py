"""串行与并行跑出来的产物是否逐字节相同（`core/parallel.py` 登记新步之前的最后一道验收）。

用法：同一册、同一批页，分别用 `--jobs 1` 与 `--jobs N` 跑进两个产物目录
（`GUJI_PRODUCTS_DIR`／`GUJI_CACHE_DIR` 各指一处），再比：

    python scripts/parallel_equivalence.py <串行产物根> <并行产物根> vol04 [--steps row_segment,glyph_match]

逐步逐页比产物文件的 sha256（manifest 不比：它记耗时、时间戳）。两边都有且相同 = 一致；
任一边缺页、或 sha 不同，都列出来，退出码 1。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def _shas(step_dir: Path) -> dict[str, str]:
    out = {}
    for p in sorted(step_dir.glob("p[0-9][0-9][0-9][0-9]*")):
        if p.is_file():
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def compare(a_root: Path, b_root: Path, book: str, steps: list[str] | None) -> dict[str, dict]:
    a_book, b_book = a_root / book, b_root / book
    names = steps or sorted({d.name for d in a_book.iterdir() if d.is_dir()}
                            | {d.name for d in b_book.iterdir() if d.is_dir()})
    rep: dict[str, dict] = {}
    for sid in names:
        sa, sb = _shas(a_book / sid), _shas(b_book / sid)
        rep[sid] = {
            "same": sum(1 for k in sa if sb.get(k) == sa[k]),
            "diff": sorted(k for k in sa if k in sb and sb[k] != sa[k]),
            "only_a": sorted(set(sa) - set(sb)),
            "only_b": sorted(set(sb) - set(sa)),
        }
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a", type=Path, help="串行产物根（GUJI_PRODUCTS_DIR）")
    ap.add_argument("b", type=Path, help="并行产物根")
    ap.add_argument("book")
    ap.add_argument("--steps", default=None, help="只比这几步（逗号分隔），缺省两边出现过的全部")
    args = ap.parse_args(argv)
    steps = [s for s in (args.steps or "").split(",") if s] or None
    rep = compare(args.a, args.b, args.book, steps)
    bad = False
    for sid, r in rep.items():
        ok = not (r["diff"] or r["only_a"] or r["only_b"])
        bad |= not ok
        print(f"{'✓' if ok else '✗'} {sid:16s} 相同 {r['same']:4d}"
              + (f"  不同 {len(r['diff'])}：{' '.join(r['diff'][:8])}" if r["diff"] else "")
              + (f"  只在串行 {len(r['only_a'])}" if r["only_a"] else "")
              + (f"  只在并行 {len(r['only_b'])}" if r["only_b"] else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
