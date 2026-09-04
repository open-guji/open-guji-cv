# -*- coding: utf-8 -*-
"""建 `rare-char` 测试集：生僻字候选召回的验收集。

## 为什么单独建一个集

A 刀之后残余人审 64 条，其中一多半是**生僻字**：语料频次 ≤3、库里没样本、
OCR 字表够不着。这类字位有一个共同特征——**系统三路候选里根本没有正确答案**
（袤 埴 殫 偓 綺 奩 䙝 㕔 鏤 濡 槧 効…），所以调任何阈值都救不了，人只能
去字统网查。C 刀（字体模板 kNN / IDS 结构检索 / 部件模型）要解决的正是这个，
而它的 KPI 是 **top-10 命中率**，不是 top-1 准确率——目标是「人在候选里点」，
不是「机器自动定字」。

没有这个集，L1/L2/L3 三级方案一级都没法验收（handbook §3 P1：先建集再动手）。

## 收哪些字位

1. **系统给不出候选**：用户/金标定的字不在库候选 ∪ OCR top-k ∪ 上下文 ranked 里；
2. **语料稀有**：整理本频次 ≤3（这类在新书上会大量出现——换一本书，库从零开始，
   所有字一开始都是生僻字）。

两类取并集。参考答案优先用**用户裁决**（独立真值），没有才退回整理本金标。

## 每条记什么

字块图路径、参考答案、语料频次、IDS 拆字、Unicode 码点、当前三路候选
（冻结，供「新算法 vs 现状」可比）。`in_candidates` 标出它是不是「三路都没有」
那一类——报数时要分层：**给不出候选的那一档才是真难题**。

用法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_rare_char_set.py \
        [--book vol01] [--pages dev_set] [--out <dataset>/rare-char]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from open_guji_cv.products import kinds as _kinds  # noqa: F401  注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import page_key
from open_guji_cv.gold.v2_align import DEFAULT_CORPUS, align_book
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

DEFAULT_OUT = Path("../open-guji-dataset/rare-char")
RARE_FREQ = 3          # 整理本频次 ≤ 此值算稀有


def load_user_verdicts(book: str) -> dict[str, str]:
    """用户 confirm 事件 → {字位: 字形}。这是与整理本无关的独立真值。"""
    root = Path("../open-guji-dataset/feedback/events")
    out: dict[str, str] = {}
    for p in sorted(root.glob(f"{book}-*.jsonl")) if root.exists() else []:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            pl = e.get("payload") or {}
            if e.get("actor") == "user" and e.get("kind") == "confirm" \
                    and pl.get("v") == "confirm" and pl.get("shape"):
                out[e["target"]["key"]] = pl["shape"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--pages", default="dev_set")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--rare-freq", type=int, default=RARE_FREQ)
    a = ap.parse_args()

    from open_guji_cv.clustering.ids_guard import ids_of

    st = ProductStore()
    cache = ImageCache()
    bk = load_book(a.book)
    pgs = bk.resolve_pages(a.pages)
    text = Path(a.corpus).read_text(encoding="utf-8")
    freq = Counter(ch for ch in text if "㐀" <= ch <= "鿿")
    gold = {c.id: c for g in align_book(a.book, pgs, st, a.corpus)
            if g.anchored for c in g.chars}
    verdicts = load_user_verdicts(a.book)

    items: list[dict] = []
    for pg in pgs:
        adm = st.read(a.book, "seed_admit", page_key(pg), "seed_admit")
        if adm is None:
            continue
        mt = st.read(a.book, "glyph_match", page_key(pg), "glyph_match")
        oc = st.read(a.book, "ocr_candidates", page_key(pg), "ocr_candidates")
        dc = st.read(a.book, "context_decide", page_key(pg), "context_decision")
        mm = {r.id: r for cc in mt.columns for r in cc.chars}
        om = {r.id: r for cc in oc.columns for r in cc.chars}
        dm = {r.id: r for cc in dc.columns for r in cc.chars}
        for cc in adm.columns:
            for r in cc.chars:
                # 只收人审位——自动放行的不是这个集要解决的问题
                if r.admit:
                    continue
                g = gold.get(r.id)
                ref = verdicts.get(r.id) or (g.shape if g else None)
                if not ref:
                    continue
                mr, orr, dd = mm.get(r.id), om.get(r.id), dm.get(r.id)
                db = [[c, round(v, 4)] for c, v in (mr.candidates[:10] if mr else [])]
                ocr = [[c, round(v, 4)] for c, v in (orr.topk[:10] if orr else [])]
                ctx = [[c, round(v, 4)] for c, v in (dd.ranked[:10] if dd else [])]
                allc = {c for c, _ in db} | {c for c, _ in ocr} | {c for c, _ in ctx}
                in_cand = ref in allc
                f = freq.get(ref, 0)
                if in_cand and f > a.rare_freq:
                    continue          # 既不稀有、候选里又有，不是难题
                _b, p_, col, slot = r.id.split(":")
                sub = ""
                if slot and slot[-1] in "ab":
                    slot, sub = slot[:-1], slot[-1]
                ck = f"p{int(p_):04d}c{int(col):02d}s{int(slot)}{sub}"
                patch = cache.get(a.book, "char_patch", ck)
                items.append({
                    "id": r.id,
                    "anchor": {"book": a.book, "page": pg, "col": cc.col,
                               "slot": r.slot, "sub": r.sub},
                    "input": {
                        "patch": str(patch) if patch else None,
                        "patch_key": ck,
                        # 冻结候选：新算法要和现状可比
                        "db_candidates": db,
                        "ocr_topk": ocr,
                        "context_ranked": ctx,
                    },
                    "expected": {
                        "char": ref,
                        "source": "human" if r.id in verdicts else "align",
                        "corpus_freq": f,
                        "ids": ids_of(ref),
                        "unicode_cp": f"U+{ord(ref):04X}" if len(ref) == 1 else "",
                        # 分层用：三路候选里有没有正确答案
                        "in_candidates": in_cand,
                    },
                })

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "items.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    n_hard = sum(1 for i in items if not i["expected"]["in_candidates"])
    n_human = sum(1 for i in items if i["expected"]["source"] == "human")
    meta = {
        "name": "rare-char", "version": "0.1.0", "schema_version": 1,
        "description": "生僻字候选召回：库/OCR/上下文都给不出正确答案的字位",
        "created": "2026-09-04",
        "status": "实集",
        "total_samples": len(items),
        "sample_unit": "字位",
        "metric": "top-10 命中率（分层：in_candidates=False 的那档才是真难题）",
        "strata": {
            "候选里没有正确答案": n_hard,
            "候选里有但字稀有": len(items) - n_hard,
            "参考答案来自用户裁决": n_human,
            "参考答案来自整理本": len(items) - n_human,
        },
        "notes": [
            "参考答案优先用用户裁决（独立真值），没有才退回整理本金标。",
            "候选已冻结，比较新算法时用冻结候选，别用实时候选——否则分不清"
            "是新算法强还是上游候选变了。",
            "top-10 命中率是 KPI，不是 top-1 准确率：目标是人在候选里点，"
            "不是机器自动定字。任何新候选源都只出候选、不自动放行。",
        ],
        "build_command": "python scripts/build_rare_char_set.py",
    }
    (out / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写出 {len(items)} 条 → {out}")
    print(f"  候选里没有正确答案（真难题）: {n_hard}")
    print(f"  候选里有但字稀有            : {len(items) - n_hard}")
    print(f"  参考答案来自用户裁决        : {n_human}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
