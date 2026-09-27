# -*- coding: utf-8 -*-
"""把用「字体 mtime」算出来的旧 `emb_*.npz` 按新 key（字体内容）改名，不重建。

## 背景

`font_candidates.font_set_fingerprint()` 2026-09-28 起从 `名字:大小:mtime` 改按
字体**内容**（sha256）算（CV 总管 09-27 23:45Z 追加到任务书-R-rare前向去重与
测试隔离；K 快照自动导入 #51 查出：同一份字体，不同机器 checkout 的 mtime 不同，
key 就不同，云端预建的 embedding 索引到服务器上全部 miss，服务器只能现建，
差点 OOM）。这个脚本不重新跑网络，只对每本书的 `(cs_base, cs_esc)` 两档字表：

1. 用**旧公式**（本脚本内联的 `_old_font_set_fingerprint`）算旧 key；
2. 若 `models/<ckpt 名>/emb_<旧key>.npz` 存在、且新 key 对应的文件还不存在，
   原子改名到 `emb_<新key>.npz`（`os.replace`，不覆盖已有的新文件）；
3. 旧 key 文件不存在（本来就没建过）——跳过，交给正常的现建路径。

## 用法

    .venv/bin/python scripts/migrate_font_fingerprint_keys.py --book vol01 vol02 ... [--dry-run]
    .venv/bin/python scripts/migrate_font_fingerprint_keys.py --book vol01 --ckpt models/glyph_cnn_r5/best.pt

`--dry-run` 只打印会改什么，不真的改名。跑之前先确认 `GUJI_WORKSPACE`/工作区
已经指到正确的书（`book_charsets` 靠它拿整理本语料）。
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def _old_font_set_fingerprint(root: str = "fonts") -> str:
    """`font_set_fingerprint` 2026-09-28 改按内容算**之前**的算法（名字:大小:mtime）。
    只给这个迁移脚本找旧文件用——生产代码不再调用这个版本。"""
    from open_guji_cv.clustering.font_candidates import _font_files

    files = _font_files(root)
    if not files:
        return "nofonts"
    h = hashlib.sha1()
    for f in files:
        st = Path(f).stat()
        h.update(f"{Path(f).name}:{st.st_size}:{int(st.st_mtime)}|".encode())
    return h.hexdigest()[:12]


def _old_emb_index_key(ckpt: Path, cs: tuple, extra_keys: tuple) -> str:
    from open_guji_cv.clustering import cnn_candidates as cc

    old_font_fp = _old_font_set_fingerprint()
    return hashlib.sha1((cc.fingerprint(ckpt) + old_font_fp + "".join(cs)
                        + "|".join(extra_keys)).encode("utf-8")).hexdigest()[:16]


def migrate_book(book: str, ckpt: Path, dry_run: bool = False) -> list[str]:
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering.rare_panel import book_charsets
    from open_guji_cv.steps.align_ref import book_corpus

    corpus = book_corpus(book)
    cs_base, cs_esc, spec = book_charsets(book, corpus)
    inst = cc.CnnCandidates(ckpt=ckpt)
    report = []
    for name, cs in (("base", cs_base), ("escalate", cs_esc)):
        if not cs:
            report.append(f"{book}:{name}：空表，跳过")
            continue
        new_key, new_path, extra = inst.emb_index_key(cs)
        extra_keys = tuple(sorted(extra))
        old_key = _old_emb_index_key(ckpt, cs, extra_keys)
        old_path = ckpt.parent / f"emb_{old_key}.npz"
        if new_path.exists():
            report.append(f"{book}:{name}：新 key 已存在（{new_path.name}），跳过")
            continue
        if not old_path.exists():
            report.append(f"{book}:{name}：旧 key 文件不存在（{old_path.name}），"
                          "跳过（要靠 guji cache build-rare-index 现建）")
            continue
        report.append(f"{book}:{name}：{old_path.name} -> {new_path.name}"
                      f"{'（--dry-run，未真改）' if dry_run else ''}")
        if not dry_run:
            import os
            os.replace(old_path, new_path)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", nargs="+", required=True,
                    help="要迁移的书（可给多个），与 book_charsets(book, ...) 的 book 参数同名")
    ap.add_argument("--ckpt", default=None,
                    help="checkpoint 路径，缺省用 cnn_candidates.DEFAULT_CKPT")
    ap.add_argument("--dry-run", action="store_true", help="只打印会改什么，不真的改名")
    args = ap.parse_args()

    from open_guji_cv.clustering import cnn_candidates as cc
    ckpt = Path(args.ckpt) if args.ckpt else cc.DEFAULT_CKPT

    for book in args.book:
        for line in migrate_book(book, ckpt, dry_run=args.dry_run):
            print(line)


if __name__ == "__main__":
    main()
