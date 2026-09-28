# -*- coding: utf-8 -*-
"""从 IDS 拆分生成「形近对表」（overview#128，2026-09-28）。

字表范围 = **整理本字表 ∪ 各书库字种**（不是全量 10 万字的 `ids_lv1.txt`）：
从各书工作区的 `corpus/*.txt`（整理本）与 `output/glyph_store/exemplars.jsonl`
的 `char` 字段（该书字形库已收的字种）取并集。任务卡原话「表会很大且多数对
在本书从不同时出现——按册字表过滤后再用」，这里在**生成时**就把范围收紧到
项目实际会用到的字，而不是生成全量表以后再筛。

用法::

    .venv/bin/python scripts/build_confusable_pairs.py \\
        --workspace /home/user/guji-workspace \\
        --book 96mid1ogzk-欽定四庫全書總目武英殿刻本 \\
        --book 988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一 \\
        --book qtw-draft \\
        --out config/ids/ids_confusable_pairs_v1.tsv

不传 `--book` 时按 `--workspace` 下所有含 `corpus/` 或 `output/glyph_store/`
的一级子目录自动发现。只读 guji-workspace（不写），只写 cv 仓自己的
`config/ids/` 数据文件——与任务卡写域一致。

缺省按 `--max-shared-freq 1000` 出**推荐档**（见 `ids_struct.slot1_pairs` 文档串：
2 槽 slot 类按共享部件冷僻度过滤，全表 448,659→61,376，校准集召回不掉）；
传 `--max-shared-freq -1` 出全量表。随仓库提交的 `config/ids/ids_confusable_pairs_v1.tsv`
就是推荐档。校准数字见 `scripts/eval_confusable_recall.py`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.clustering import ids_struct as S


def _is_cjk(ch: str) -> bool:
    return ("一" <= ch <= "鿿") or ("㐀" <= ch <= "䶿") \
        or ("\U00020000" <= ch <= "\U0002ffff") or ("豈" <= ch <= "﫿")


def _discover_books(ws: Path) -> list[Path]:
    out = []
    for d in sorted(ws.iterdir()):
        if not d.is_dir():
            continue
        if (d / "corpus").exists() or (d / "output" / "glyph_store").exists():
            out.append(d)
    return out


def collect_universe(book_dirs: list[Path]) -> tuple[set[str], dict[str, int]]:
    """→ (字集合, {书目录名: 该书贡献的字数})，供 done 单报数用。"""
    chars: set[str] = set()
    per_book: dict[str, int] = {}
    for d in book_dirs:
        before = len(chars)
        corpus = d / "corpus"
        if corpus.exists():
            for f in corpus.glob("*.txt"):
                txt = f.read_text(encoding="utf-8", errors="ignore")
                chars.update(ch for ch in txt if _is_cjk(ch))
        ex = d / "output" / "glyph_store" / "exemplars.jsonl"
        if ex.exists():
            for line in ex.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ch = rec.get("char")
                if ch and _is_cjk(ch):
                    chars.add(ch)
        per_book[d.name] = len(chars) - before
    return chars, per_book


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default="/home/user/guji-workspace")
    ap.add_argument("--book", action="append", default=[],
                    help="书目录名（可多次给）；不给则自动发现全部")
    ap.add_argument("--out", default=str(S.CONFUSABLE_FILE))
    ap.add_argument("-k", type=int, default=S.DEFAULT_K)
    ap.add_argument("--max-shared-freq", type=int, default=1000,
                    help="2 槽 slot 对的共享部件一级频次门槛（见 ids_struct.slot1_pairs "
                         "文档串）。默认 1000＝推荐档（全表 448,659→61,376，降 86%%，"
                         "eval_confusable_recall.py 校准集召回不掉）。传负数＝关闭过滤，"
                         "出全量表。")
    a = ap.parse_args(argv)
    max_shared_freq = None if a.max_shared_freq is not None and a.max_shared_freq < 0 \
        else a.max_shared_freq

    ws = Path(a.workspace)
    book_dirs = [ws / b for b in a.book] if a.book else _discover_books(ws)
    missing = [str(d) for d in book_dirs if not d.exists()]
    if missing:
        raise SystemExit(f"书目录不存在: {missing}")

    chars, per_book = collect_universe(book_dirs)
    print(f"universe: {len(chars)} 字，来自 {len(book_dirs)} 本书")
    for name, n in per_book.items():
        print(f"  + {name}: 新增 {n} 字（累计）")

    pairs = S.build_confusable_pairs(sorted(chars), a.k, max_shared_freq=max_shared_freq)
    from collections import Counter
    kinds = Counter(p.kind for p in pairs)
    print(f"生成 {len(pairs)} 对：{dict(kinds)}")

    out = S.write_confusable_pairs(pairs, Path(a.out))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
