# -*- coding: utf-8 -*-
"""提交前压库：丢掉可重算的派生缓存 + VACUUM。

    PYTHONPATH=. python scripts/compact_glyph_db.py --db output/glyph.db

## 为什么

`derived` 表里 `feat_hog` 是 HOG 特征缓存，**全仓库没有任何读者**：
`load_matcher_from_db` 只取 `kind='norm'`，`GlyphMatcher.add()` 拿到 norm
自己算特征；`_select_exemplars` 用的是导入时内存里的 feats。可它按每实例
约 7KB 写盘，vol01 铺到 15008 条时独占 **100MB**，把 glyph.db 顶到 179MB
——超过 GitHub 单文件 100MB 硬上限，推送被 pre-receive 钩子拒掉
（2026-08-26 实锤）。

丢掉是安全的：`admit_instance` / `refresh_instance_patch` 每次都会重写
`_write_derived`，需要时自然重建；`norm`(7MB) 与 `skeleton`(5MB) 有读者，
不动。

## 什么时候跑

每轮入库、重跑 seed 之后、`git commit` 之前。幂等。
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DROPPABLE = ("feat_hog",)     # 无读者的纯缓存


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--keep-feat", action="store_true",
                    help="保留 feat_hog（只 VACUUM）")
    args = ap.parse_args()
    p = Path(args.db)
    before = p.stat().st_size
    c = sqlite3.connect(p)
    dropped = 0
    if not args.keep_feat:
        for kind in DROPPABLE:
            n = c.execute("SELECT count(*) FROM derived WHERE kind=?",
                          (kind,)).fetchone()[0]
            c.execute("DELETE FROM derived WHERE kind=?", (kind,))
            dropped += n
        c.commit()
    c.execute("VACUUM")
    c.close()
    after = p.stat().st_size
    print(f"{p}：{before/2**20:.0f}MB → {after/2**20:.0f}MB"
          f"（丢弃 {dropped} 行可重算缓存）")
    if after > 100 * 2**20:
        print("⚠ 仍超 GitHub 100MB 单文件上限，推送会被拒")


if __name__ == "__main__":
    main()
