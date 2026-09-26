# -*- coding: utf-8 -*-
"""影子放行模型·信号 v2：在 extract.py 的结果上补整理本信号、刷新标签（不重跑一小时的小笔画判别）。

    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/experiments/shadow_admit/augment.py bxgb <in.jsonl> <out.jsonl>

整理本信号按用户 2026-09-25 的说法拆三组：
1. 候选与整理本字的**关系**：完全相同 / 同字异体 / 通假（config/dicts/jiajie.tsv）/ 本书用字对照（books/<id>.yaml
   char_conventions，含避讳、人名改字）/ 形近不同字 / 无关；
2. 本书整理本的**写法习惯**：按「候选形 × 整理本形」字对统计，在 train.py 里逐折做（防泄漏），这里只留 ref_char；
3. 这一处**对齐可靠度**：所在逐字相同长串的长度（ref_run）、前后各 5 格里对不上的比例。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def main() -> None:
    book, src, dst = sys.argv[1:4]
    import yaml
    from open_guji_cv.clustering.confusable import partners as _partners
    from open_guji_cv.clustering.variants import VariantMap
    from open_guji_cv.core.book import load_book  # noqa: F401  (确认工作区)
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.core.workspace import workspace_root
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.feedback.lookup import human_chars
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.report.slots import page_slots

    vm, partners, st = VariantMap.load(), _partners(), ProductStore()
    repo = Path(__file__).resolve().parents[3]
    jiajie = set()
    for l in (repo / "config/dicts/jiajie.tsv").read_text(encoding="utf-8").splitlines():
        if l and not l.startswith("#"):
            a, b = l.split("\t")[:2]
            jiajie |= {(a, b), (b, a)}
    conv = set()
    y = yaml.safe_load((workspace_root() / "books" / f"{book}.yaml").read_text(encoding="utf-8"))
    for c in y.get("char_conventions") or []:
        a, b = c["pair"]
        conv |= {(a, b), (b, a)}

    labels = {k: v[0] for k, v in human_chars(book).items()}
    for e in EventLog().iter_all():
        if e.kind == "collate_ok" and e.target.key.startswith(book + ":") and e.target.key not in labels:
            pair = (e.payload or {}).get("pair") or []
            if pair:
                labels[e.target.key] = pair[0]

    # 对齐可靠度：按页读序，前后 5 格里 align_op≠equal 的比例
    align: dict[str, dict] = {}
    local: dict[str, float] = {}
    pages = set()
    rows = [json.loads(l) for l in open(src, encoding="utf-8")]
    for r in rows:
        pages.add(r["page"])
    for pg in sorted(pages):
        al = {r["id"]: r for r in st.read(book, "align_ref", page_key(pg), "align_ref").model_dump()["chars"]}
        seq = [s.id for s in page_slots(st, book, pg) if s.is_text]
        ops = [(al.get(i) or {}).get("align_op") for i in seq]
        for k, i in enumerate(seq):
            win = [o for j, o in enumerate(ops[max(0, k - 5):k + 6]) if j != min(k, 5)]
            local[i] = sum(o != "equal" for o in win) / max(1, len(win))
            align[i] = al.get(i) or {}

    with open(dst, "w", encoding="utf-8") as f:
        for r in rows:
            c, a = r["cand"], align.get(r["id"], {})
            ref = a.get("align_char")
            truth = labels.get(r["id"])
            r["label"] = None if truth is None else int(c == truth)
            r["ref_char"] = ref or ""
            rel = "none"
            if ref:
                if c == ref:
                    rel = "exact"
                elif (c, ref) in conv:
                    rel = "convention"
                elif vm.semantic(c) == vm.semantic(ref):
                    rel = "variant"
                elif (c, ref) in jiajie:
                    rel = "jiajie"
                elif ref in partners.get(c, frozenset()):
                    rel = "confusable"
                else:
                    rel = "unrelated"
            for k in ("exact", "variant", "jiajie", "convention", "confusable", "unrelated"):
                r[f"rel_{k}"] = int(rel == k)
            r["ref_run"] = float(a.get("ref_run") or 0)
            r["ref_local_mismatch"] = local.get(r["id"], 0.0)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} 行；标签 {len(labels)} 格")


if __name__ == "__main__":
    main()
