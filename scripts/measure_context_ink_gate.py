# -*- coding: utf-8 -*-
"""D 铁证复核（2026-09-27）第 3 步：context 通道空白弃权闸的阈值要从全书墨量分布
量出来。量两件事：

1. 全书 `char_index.ink_ratio`（`step3_kind=="char"` 的格）分布——找主分布与
   近空白孤簇之间的空隙，供 `SeedAdmitParams.context_min_ink` 定值。
2. 现在 `channel=="context"`（seed_admit 产物）的格里，ink_ratio 分布——
   `vol03:9:9:21` 这种「几乎空白却被 context 放行」的格该落在孤簇里。

    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/measure_context_ink_gate.py \
        vol03 --pages 1-107
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("--pages", required=True)
    a = ap.parse_args()

    st = ProductStore()
    lo, _, hi = a.pages.partition("-")
    all_ink: list[float] = []
    ctx_ink: list[tuple[str, float, str]] = []      # (id, ink, final_char)
    for pg in range(int(lo), int(hi or lo) + 1):
        chars = st.read(a.book, "cell_shrink", f"p{pg:04d}", "char_index")
        sadm = st.read(a.book, "seed_admit", f"p{pg:04d}", "seed_admit")
        if chars is None:
            continue
        imap = {r.id: r for cc in chars.columns for r in cc.chars}
        for cc in chars.columns:
            for r in cc.chars:
                if r.step3_kind == "char":
                    all_ink.append(r.ink_ratio)
        if sadm is None:
            continue
        for cc in sadm.columns:
            for r in cc.chars:
                if r.channel == "context":
                    ink = imap[r.id].ink_ratio if r.id in imap else None
                    if ink is not None:
                        ctx_ink.append((r.id, ink, r.char))

    arr = np.array(all_ink)
    print(f"=== {a.book} 全书 char 格 ink_ratio 分布（n={len(arr)}）===")
    for pct in (0.1, 0.5, 1, 2, 5, 10, 25, 50):
        print(f"  p{pct:>5}: {np.percentile(arr, pct):.4f}")
    print(f"  <0.005: {int((arr < 0.005).sum())}  <0.01: {int((arr < 0.01).sum())}  "
         f"<0.02: {int((arr < 0.02).sum())}  <0.03: {int((arr < 0.03).sum())}  "
         f"<0.05: {int((arr < 0.05).sum())}")

    print(f"\n=== {a.book} channel=context 格的 ink_ratio（n={len(ctx_ink)}）===")
    ctx_ink.sort(key=lambda t: t[1])
    for iid, ink, ch in ctx_ink[:30]:
        print(f"  {iid}  ink={ink:.4f}  char={ch}")


if __name__ == "__main__":
    main()
