# -*- coding: utf-8 -*-
"""人审队列普查：谁在队列里、为什么、哪路信号对、哪条新通道能吃掉多少。

`pipeline_review_2026-09-04.md` 的数字全部出自这里。三块：

1. **队列构成**：人审原因、按页分布、各路信号（库 / OCR / 上下文）对金标的准确率；
2. **通道回放**：用用户的 confirm 事件当独立真值，模拟「整理本 × 库 top1」与
   「三方一致」两条 v2 还没接的通道，报触发数与错例；
3. **生僻字缺口**：用户定的字里系统三路候选都没给的有几条、语料频次多少。

锚定串用「定字 → 库 top1 → OCR top1」逐级兜底填满（§2 的 A 刀），而不是
`v2_align._slots_from_decision` 那样只收定了字的位——两者覆盖率差 15 个点。

用法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/survey_review_queue.py
    [--book vol01] [--pages dev_set] [--events <feedback/events/*.jsonl>]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from open_guji_cv.products import kinds as _kinds  # noqa: F401  注册产物种类
from open_guji_cv.products.store import ProductStore
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import page_key
from open_guji_cv.clustering.align_label import build_ngram_index, label_page
from open_guji_cv.clustering.confusable import NEVER_MATCH_FAMILIES
from open_guji_cv.gold.v2_align import DEFAULT_CORPUS, align_book

FAM = frozenset(c for pair in NEVER_MATCH_FAMILIES for c in pair)


def load_truth(paths: list[Path]) -> dict[str, tuple[str, str]]:
    """用户 confirm 事件 → {字位: (shape, reading)}。后裁的覆盖先裁的。"""
    out: dict[str, tuple[str, str]] = {}
    for p in paths:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            pl = e.get("payload") or {}
            if e.get("actor") == "user" and e.get("kind") == "confirm" \
                    and pl.get("v") == "confirm" and pl.get("shape"):
                out[e["target"]["key"]] = (pl["shape"], pl.get("reading") or pl["shape"])
    return out


def anchor_slots(match, dec, ocr) -> list[tuple[int, int, str]]:
    """锚定串：定字 → 库 top1 → OCR top1，位位有字。"""
    dm = {r.id: r for cc in dec.columns for r in cc.chars}
    om = {r.id: r for cc in ocr.columns for r in cc.chars}
    out = []
    for cc in sorted(match.columns, key=lambda c: c.col):
        for r in sorted(cc.chars, key=lambda x: (x.slot, x.sub or "")):
            d = dm.get(r.id)
            ch = ((d.char if d and d.char else None)
                  or (r.candidates[0][0] if r.candidates else None)
                  or (om[r.id].topk[0][0] if r.id in om and om[r.id].topk else None))
            if ch:
                out.append((cc.col, r.slot, ch))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--pages", default="dev_set")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--events", nargs="*", default=None,
                    help="用户裁决事件 jsonl；缺省找数据集仓 feedback/events/<book>-*.jsonl")
    a = ap.parse_args()

    st = ProductStore()
    bk = load_book(a.book)
    pgs = bk.resolve_pages(a.pages)
    text = Path(a.corpus).read_text(encoding="utf-8")
    idx = build_ngram_index(text)
    freq = Counter(ch for ch in text if "㐀" <= ch <= "鿿")
    gold = {c.id: c for g in align_book(a.book, pgs, st, a.corpus) if g.anchored for c in g.chars}

    ev_paths = [Path(p) for p in a.events] if a.events else sorted(
        Path("../open-guji-dataset/feedback/events").glob(f"{a.book}-*.jsonl"))
    truth = load_truth(ev_paths)

    n_tot = n_auto = 0
    reasons: Counter = Counter()
    by_page: Counter = Counter()
    sig_gold: Counter = Counter()
    n_gold_rev = 0
    sig_truth: Counter = Counter()
    n_truth = 0
    chan: Counter = Counter()
    chan_ok: Counter = Counter()
    bad: list = []
    nocand: list = []
    rest: list = []

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
        labs, ok = label_page(str(pg), anchor_slots(mt, dc, oc), a.book, text, idx)
        al = {l.instance_id: l for l in labs} if ok else {}

        for cc in adm.columns:
            for r in cc.chars:
                n_tot += 1
                if r.admit:
                    n_auto += 1
                    continue
                by_page[pg] += 1
                for dq in r.doubts or []:
                    reasons[dq.split("(")[0]] += 1
                mr, orr, d = mm.get(r.id), om.get(r.id), dm.get(r.id)
                db = mr.candidates[0][0] if mr and mr.candidates else None
                cov = mr.cov if mr else 0.0
                o1 = orr.topk[0][0] if orr and orr.topk else None
                c1 = d.ranked[0][0] if d and d.ranked else None

                g = gold.get(r.id)
                if g:
                    n_gold_rev += 1
                    sig_gold["库 top1"] += db == g.shape
                    sig_gold["OCR top1"] += o1 == g.shape
                    sig_gold["上下文 top1"] += c1 == g.shape

                if r.id not in truth:
                    continue
                ts, tr = truth[r.id]
                n_truth += 1
                sig_truth["库 top1"] += db == ts
                sig_truth["OCR top1"] += o1 == ts
                sig_truth["上下文 top1"] += c1 == ts
                allc = ({c for c, _ in (mr.candidates if mr else [])}
                        | {c for c, _ in (orr.topk if orr else [])}
                        | {c for c, _ in (d.ranked if d else [])})
                if ts not in allc:
                    nocand.append((r.id, ts, freq.get(ts, 0)))

                l = al.get(r.id)
                hit = lambda x: x == ts or x == tr  # noqa: E731
                if l and l.op == "equal" and db and l.char == db:
                    chan["整理本equal×库top1"] += 1
                    chan_ok["整理本equal×库top1"] += hit(l.char)
                    if not hit(l.char):
                        bad.append((r.id, "align", l.char, "user", ts))
                elif db and o1 and c1 and db == o1 == c1:
                    chan["三方一致"] += 1
                    chan_ok["三方一致"] += hit(db)
                    if not hit(db):
                        bad.append((r.id, "three", db, "user", ts))
                else:
                    why = ("无整理本锚" if not l else f"整理本{l.op}={l.char}")
                    rest.append((r.id, f"{why} | 库={db}({cov:.2f}) ocr={o1} 用户={ts}"
                                 + (" [形近表]" if ts in FAM or db in FAM else "")
                                 + (f" [freq={freq.get(ts, 0)}]" if freq.get(ts, 0) <= 3 else "")))

    n_rev = n_tot - n_auto
    print(f"字位 {n_tot}  自动 {n_auto} ({n_auto / n_tot:.1%})  人审 {n_rev} ({n_rev / n_tot:.1%})")
    print("\n== 人审原因（可叠加）==")
    for k, v in reasons.most_common():
        print(f"  {v:4d}  {k}")
    print("\n== 人审按页 ==")
    print("  " + "  ".join(f"p{p}:{by_page[p]}" for p in pgs))
    if n_gold_rev:
        print(f"\n== 人审且有整理本金标 {n_gold_rev} 条，各信号准确率 ==")
        for k, v in sig_gold.items():
            print(f"  {k:10s} {v}/{n_gold_rev} = {v / n_gold_rev:.0%}")
    if n_truth:
        print(f"\n== 人审且有用户裁决真值 {n_truth} 条（事件文件 {len(ev_paths)} 个）==")
        for k, v in sig_truth.items():
            print(f"  {k:10s} {v}/{n_truth} = {v / n_truth:.0%}")
        print("\n== 通道回放（v2 尚未接的通道）==")
        for k in chan:
            print(f"  {k:18s} 触发 {chan[k]:3d}  对 {chan_ok[k]:3d}")
        print(f"  {'仍需人审':18s} {len(rest):3d}")
        if bad:
            print("  错例:", bad)
        print(f"\n== 生僻字缺口：系统三路候选都没给用户字的 {len(nocand)} 条 ==")
        print("  ", nocand)
        print(f"\n== 仍需人审 {len(rest)} 条 ==")
        for i, w in rest:
            print("  ", i, w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
