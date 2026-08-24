"""字体字形当「兜底候选源」值不值：在真实待审字位上量。

既有的 `bench_font_glyphs.py` 回答 go/no-go（能不能匹配上，答案是
**不能当定论**：separable=false）。本脚本回答**下一个**问题：

    刻本库匹配不上（或匹配很弱）时，从字体库里找备选，能救回多少？

因为字体字形的用法已经定死在「语义候选层」——降权、只出候选不出定论
（glyph_db_expansion_research.md §0）——所以要量的不是精度而是**召回**：
正确字有没有被**带进候选集**。带进来了，后面有整理本和上下文 LM 去裁；
带不进来，那一格只能人审。

    PYTHONPATH=. python scripts/eval_font_fallback.py output/vol01 \\
        --editions font:iming --k 10

分层报告是要害：整体召回会被「刻本库本来就能搞定」的格稀释，真正该看
的是**刻本库弱**的那一层——那才是字体库要救的人。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.glyph_db import GlyphDB          # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.variants import VariantMap        # noqa: E402

DECIDED = {"confirmed", "confirmed_label_only", "auto_admitted"}


def db_tier(row: dict) -> str:
    """该格的刻本库证据强度（分层用；口径同设计 §7.3）。"""
    m = row.get("match") or {}
    if m.get("verdict") == "same":
        return "same"
    cands = m.get("candidates") or []
    if not cands:
        return "无候选"
    top = max(c[1] for c in cands)
    return ("≥0.99" if top >= 0.99 else "≥0.98" if top >= 0.98
            else "≥0.95" if top >= 0.95 else "<0.95")


def main() -> int:
    ap = argparse.ArgumentParser(description="字体兜底候选的召回实测")
    ap.add_argument("book_out_dir")
    ap.add_argument("--store", default="glyph_store")
    ap.add_argument("--editions", default="font:iming",
                    help="字体来源，逗号分隔")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--sample", type=int, default=None,
                    help="只跑前 N 个字位（检索是重活，先小样看趋势）")
    ap.add_argument("--human-only", action="store_true",
                    help="只用人工裁决的格（金标最硬，且是真难例）")
    ap.add_argument("--decide", action="store_true",
                    help="决策层 A/B：加/不加字体候选各跑一遍门槛化裁决")
    ap.add_argument("--gate", type=float, default=0.70)
    ap.add_argument("--font-weight", type=float, default=0.6,
                    help="字体候选的先验权重（对比：库 3.0 / OCR 1.5 / 语料 2.5）")
    ap.add_argument("--cov-gate", type=float, default=0.95,
                    help="刻本库 top cov 低于此才查字体库")
    ap.add_argument("--corpus", action="append", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    book_dir = Path(args.book_out_dir)
    root = book_dir / "phase4_chars"
    vm = VariantMap.load()
    rows = [json.loads(l) for l in
            (book_dir / "phase9_seed" / "queue.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    slots = [r for r in rows if r["status"] in DECIDED and r.get("decided_char")]
    if args.human_only:
        slots = [r for r in slots if r["status"].startswith("confirmed")]
    if args.sample:
        slots = slots[:args.sample]

    editions = [e.strip() for e in args.editions.split(",") if e.strip()]
    if args.decide:
        st = decide_ab(book_dir, Path(args.store), editions,
                       args.corpus or ["corpus/zongmu_wuyingdian_reference.txt",
                                       "corpus/vol01_supplement.txt"],
                       args.k, args.gate, args.font_weight,
                       args.cov_gate, args.sample)
        print(f"决策层 A/B：{st['n']} 个人审难例，其中 {st['consulted']} 格"
              f"（刻本库 cov < {args.cov_gate}）查了字体库\n")
        print(f"{'臂':<8}{'定字对':>8}{'门槛进库':>10}{'其中对':>8}{'门槛精度':>10}")
        for arm, name in (("base", "不查字体"), ("font", "查字体")):
            a = st[arm]
            acc = a["admit_ok"] / a["admit"] if a["admit"] else 0
            print(f"{name:<9}{a['top1']:>7}{a['admit']:>10}{a['admit_ok']:>8}"
                  f"{acc:>10.1%}")
        d1 = st["font"]["top1"] - st["base"]["top1"]
        d2 = st["font"]["admit_ok"] - st["base"]["admit_ok"]
        d3 = ((st["font"]["admit"] - st["font"]["admit_ok"])
              - (st["base"]["admit"] - st["base"]["admit_ok"]))
        print(f"\n定字对 {d1:+d}　门槛进库对 {d2:+d}　门槛进库错 {d3:+d}")
        return 0
    db = GlyphDB(Path(args.store) / "glyphdb.sqlite")
    have = {r[0] for r in db.conn.execute(
        "SELECT DISTINCT edition_tag FROM glyphs")}
    missing = [e for e in editions if e not in have]
    if missing:
        print(f"库里没有这些来源：{missing}（先跑 glyph-db import-font）")
        return 1
    n_font_chars = db.conn.execute(
        "SELECT COUNT(DISTINCT char) FROM glyphs WHERE edition_tag IN "
        f"({','.join('?' * len(editions))})", editions).fetchone()[0]

    # 分层桶：tier → [n, 字体命中@1, @k, 现有候选已含金标]
    buckets: dict[str, list[int]] = {}
    rescue = []            # 现有候选没有金标、但字体带进来了
    n_done = 0
    for r in slots:
        gray = cv2.imread(str(root / r["patch_path"]), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        gold = r["decided_char"]
        norm = normalize_patch(gray)
        hits = db.query(norm, editions=editions, k=args.k)
        chars = [h.char for h in hits]
        sem_gold = vm.semantic(gold)
        r1 = bool(chars) and vm.semantic(chars[0]) == sem_gold
        rk = any(vm.semantic(c) == sem_gold for c in chars)

        # 现有候选（刻本库 ∪ OCR）里有没有金标
        cur = {c for c, _ in (r.get("match") or {}).get("candidates") or []}
        if (r.get("ocr") or {}).get("char"):
            cur.add(r["ocr"]["char"])
        cur_has = any(vm.semantic(c) == sem_gold for c in cur)

        t = db_tier(r)
        b = buckets.setdefault(t, [0, 0, 0, 0])
        b[0] += 1
        b[1] += r1
        b[2] += rk
        b[3] += cur_has
        if rk and not cur_has:
            rescue.append({"instance_id": r["instance_id"], "gold": gold,
                           "tier": t, "font_rank": next(
                               i + 1 for i, c in enumerate(chars)
                               if vm.semantic(c) == sem_gold)})
        n_done += 1

    order = ["same", "≥0.99", "≥0.98", "≥0.95", "<0.95", "无候选"]
    print(f"字体来源 {editions}（{n_font_chars} 字）× {n_done} 个已定字位"
          f"{'（仅人审难例）' if args.human_only else ''}\n")
    print(f"{'刻本库档':<8}{'字位':>6}{'字体@1':>9}{f'字体@{args.k}':>9}"
          f"{'现有候选已含':>13}{'字体能救':>9}")
    tot = [0, 0, 0, 0]
    for t in order:
        b = buckets.get(t)
        if not b:
            continue
        for i in range(4):
            tot[i] += b[i]
        resc = sum(1 for x in rescue if x["tier"] == t)
        print(f"{t:<9}{b[0]:>5}{b[1]/b[0]:>9.0%}{b[2]/b[0]:>9.0%}"
              f"{b[3]/b[0]:>13.0%}{resc:>9}")
    if tot[0]:
        print(f"{'合计':<9}{tot[0]:>5}{tot[1]/tot[0]:>9.0%}{tot[2]/tot[0]:>9.0%}"
              f"{tot[3]/tot[0]:>13.0%}{len(rescue):>9}")
    gap = tot[0] - tot[3]
    print(f"\n候选缺口 {gap} 格（现有候选里没有金标）→ 字体能带进来 "
          f"{len(rescue)} 格 = {len(rescue)/gap if gap else 0:.0%}")
    if rescue:
        print("\n救回样例（字体检索里金标的名次）：")
        for x in rescue[:12]:
            print(f"  {x['instance_id']:<18} 金标 {x['gold']}  "
                  f"刻本库档 {x['tier']:<6} 字体第 {x['font_rank']} 名")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"editions": editions, "font_chars": n_font_chars,
             "n": n_done, "buckets": buckets, "rescue": rescue},
            ensure_ascii=False, indent=1), encoding="utf-8")
    return 0



# ── 决策层 A/B：把字体候选喂进去，最终定字会不会更好 ──────────────

def decide_ab(book_dir: Path, store: Path, editions: list[str],
              corpus_paths: list[str], k: int, gate: float,
              weight: float, cov_gate: float, sample: int | None) -> dict:
    """同一批字位，加/不加字体候选各跑一遍门槛化裁决，比最终定字。

    只在**刻本库弱**的字位上加字体候选（cov < cov_gate 或无候选）——
    库强的层现有候选已含金标 99~100%，查字体是白花钱还添噪声。
    """
    from open_guji_cv.clustering.context_step import build_strategy
    from open_guji_cv.clustering.recognize_flow import fuse_priors
    from open_guji_cv.clustering.seeding import build_seed_lm

    root = book_dir / "phase4_chars"
    vm = VariantMap.load()
    rows = [json.loads(l) for l in
            (book_dir / "phase9_seed" / "queue.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    # **只算锚定页**：未锚定页的上下文通道整个是关的（无语料没安全网），
    # 字体候选在那里根本不会被查——混进来数字会虚高（首轮实测教训）。
    anchored = {r["page"] for r in rows
                if (r.get("context") or {}).get("ref_char")}
    slots = [r for r in rows if r["status"].startswith("confirmed")
             and r.get("decided_char") and r["page"] in anchored]
    if sample:
        slots = slots[:sample]

    corpus_text = "\n".join(Path(p).read_text(encoding="utf-8")
                            for p in corpus_paths if Path(p).exists())
    lm = build_seed_lm(corpus_text, sorted(Path("corpus/external").glob("*.txt")))
    decider = build_strategy("gated_ngram", lm=lm, semantic_fn=vm.semantic)
    db = GlyphDB(store / "glyphdb.sqlite")

    # 同列前文（金标，教师强制口径——与 context-correction 评测一致）
    by_col: dict[tuple, list] = {}
    for r in rows:
        by_col.setdefault((r["page"], r["col"]), []).append(r)
    for v in by_col.values():
        v.sort(key=lambda x: x["idx"])

    def ctx_of(r):
        prev = [x for x in by_col[(r["page"], r["col"])]
                if x["idx"] < r["idx"] and x.get("decided_char")]
        return tuple(x["decided_char"] for x in prev[-4:])

    stat = {"n": 0, "consulted": 0}
    for arm in ("base", "font"):
        stat[arm] = {"top1": 0, "admit": 0, "admit_ok": 0}
    for r in slots:
        gold, sem_gold = r["decided_char"], vm.semantic(r["decided_char"])
        cands = [(c, v) for c, v in
                 (r.get("match") or {}).get("candidates") or []]
        topcov = max((v for _, v in cands), default=0.0)
        weak = topcov < cov_gate
        ocr = (r.get("ocr") or {}).get("char")
        topk = [(ocr, (r.get("ocr") or {}).get("prob", 0.0))] if ocr else []
        corpus_char = ((r.get("align") or {}).get("char")
                       or (r.get("context") or {}).get("ref_char"))
        extra = [(corpus_char, 1.0)] if corpus_char else None
        ctx = ctx_of(r)
        stat["n"] += 1

        font_extra = []
        if weak:
            gray = cv2.imread(str(root / r["patch_path"]), cv2.IMREAD_GRAYSCALE)
            if gray is not None:
                hits = db.query(normalize_patch(gray), editions=editions, k=k)
                # 名次衰减：字体检索本身 recall@1 只有两成，靠的是「带进来」
                font_extra = [(h.char, weight / (i + 1))
                              for i, h in enumerate(hits)]
                stat["consulted"] += 1

        for arm, fe in (("base", []), ("font", font_extra)):
            pri = fuse_priors(cands, topk, extra=(extra or []) + fe)
            res = decider.decide(pri, context=ctx)
            if res.surface and vm.semantic(res.surface) == sem_gold:
                stat[arm]["top1"] += 1
            if res.surface and res.margin >= gate and len(pri) >= 2:
                stat[arm]["admit"] += 1
                stat[arm]["admit_ok"] += (
                    vm.semantic(res.surface) == sem_gold)
    return stat

if __name__ == "__main__":
    raise SystemExit(main())
