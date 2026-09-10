"""从 context-correction 金标里挖「外部 LLM 有机会赢」的题。

不随机挖：只挑**现有生产策略（gated_ngram, margin_gate=0.70）判错**的
槽位——ngram 已经稳赢的位上比，比出来的数没有意义（任务书 §二·1）。
「判错」= 按生产口径算出的最终定字（过门槛用 LM 结果，不过门槛回落到
候选 top1）≠ 金标。金标不在候选集合里的槽位一律不选——铁律 1（字形层
不可改写）下这种槽位无论换哪个策略都救不回来，不是这一臂该比的对象。

上下文的算法（**教师强制**，与 `eval_context_correction.heldout_corpus`
持有的口径一致，见 known_limitation）：本列前文 = 已判槽位的金标顺序
拼接（`context_window` 个，同生产 `ContextDecideParams.context_window`
默认 6）；本题的 `context_before` / `context_after`（各约 10 字，供大模型
读，**不是**喂给 ngram 的那份）另外拼接列内金标 + 相邻列 `context.prev`/
`context.next`，取够 `--window-chars` 个字为止——ngram 只吃前文，这里
两个方向都给，是本评测集独有的题面设计，不代表生产改了口径。

用法：
    PYTHONPATH=. python scripts/build_llm_context_evalset.py \\
        ../open-guji-dataset/context-correction \\
        --general-corpus corpus/external/daizhige_zhaoling.txt \\
        --book-corpus corpus/zongmu_wuyingdian_reference.txt \\
        --out output/llm_context_evalset/evalset.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

DEFAULT_BOOK_WEIGHT = 0.9   # 同 seeding.BOOK_LM_WEIGHT（charset_and_lm.md §二标定）
DEFAULT_MARGIN_GATE = 0.70  # 同 ContextDecideParams.margin_gate 生产默认
DEFAULT_CONTEXT_WINDOW = 6  # 同 ContextDecideParams.context_window 生产默认
DEFAULT_WINDOW_CHARS = 10


def load_samples(root: Path) -> list[dict]:
    """同 eval_context_correction.load_samples：跳过占位样本。"""
    out = []
    for d in sorted((root / "samples").glob("*/")):
        f = d / "expected.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if "columns" not in data:
            continue
        out.append(data)
    return out


def build_lm(general_corpus: str | None, book_corpus: str | None,
            book_weight: float, gold_texts: list[str]):
    """按生产口径（本书高权重 + 通用低权重线性插值）建 LM，本书语料挖掉测试页。

    复用 `eval_context_correction.heldout_corpus`——不重新发明留出逻辑，
    免得两处口径漂开。
    """
    from open_guji_cv.clustering.lm import InterpolatedLM, UniformLM, train_ngram
    import eval_context_correction as ecc

    provenance: dict = {"book_weight": book_weight}
    general_lm = None
    if general_corpus:
        raw = Path(general_corpus).read_text(encoding="utf-8")
        segs = [x for x in raw.split("\n") if x.strip()]
        general_lm = train_ngram(segs, 3, 2)
        provenance["general_corpus"] = general_corpus

    book_lm = None
    if book_corpus:
        raw = Path(book_corpus).read_text(encoding="utf-8")
        held, removed = ecc.heldout_corpus(raw, gold_texts)
        segs = [x for x in held.split("\n") if x.strip()]
        book_lm = train_ngram(segs, 3, 1)
        provenance["book_corpus"] = book_corpus
        provenance["book_chars_removed_as_holdout"] = removed
        if removed == 0:
            print("⚠ 一个测试页窗口都没挖掉——本书 LM 可能在背答案")

    comps = []
    if general_lm is not None and (1 - book_weight) > 0:
        comps.append((general_lm, 1 - book_weight))
    if book_lm is not None and book_weight > 0:
        comps.append((book_lm, book_weight))
    lm = InterpolatedLM(comps) if comps else UniformLM()
    return lm, provenance


def production_decision(decider, cands: list[dict], ctx_chars: list[str],
                        margin_gate: float) -> dict:
    """复刻 `eval_context_correction.run_gated` 单槽位逻辑（生产口径）。"""
    if not cands:
        return {"base": None, "raw_pick": None, "raw_margin": 0.0, "final": None}
    priors = {c["char"]: c["prob"] for c in cands}
    base = cands[0]["char"]
    res = decider.decide(priors, context=tuple(ctx_chars))
    pick = res.surface
    final = (pick if (pick and pick != base and res.margin >= margin_gate
                      and len(cands) >= 2) else base)
    return {"base": base, "raw_pick": pick,
           "raw_margin": round(float(res.margin), 4), "final": final}


def build_items(samples: list[dict], decider, margin_gate: float,
                context_window: int, window_chars: int) -> tuple[list[dict], dict]:
    """跑一遍生产口径，收集判错且金标在候选内的槽位，附带上下各 window_chars 字。"""
    items: list[dict] = []
    n_total = n_wrong_unrescuable = 0
    origin_counts = {"total": {}, "wrong_rescuable": {}}

    for s in samples:
        for col in s["columns"]:
            slots = col["slots"]
            gold_seq = [sl["gold"] for sl in slots]
            decided: list[str] = []          # 生产用：教师强制的已判槽位金标
            prev_ctx = (col.get("context") or {}).get("prev") or ""
            next_ctx = (col.get("context") or {}).get("next") or ""
            for i, sl in enumerate(slots):
                n_total += 1
                origin = sl.get("origin") or "align"
                origin_counts["total"][origin] = origin_counts["total"].get(origin, 0) + 1
                cands = sl["candidates"]
                gold = sl["gold"]
                ctx_chars = decided[-context_window:]
                dec = production_decision(decider, cands, ctx_chars, margin_gate)
                decided.append(gold)          # 教师强制，放在算完本槽位之后

                if dec["final"] == gold:
                    continue                  # 现有策略已经答对，不是本臂该比的位
                cand_chars = [c["char"] for c in cands]
                if gold not in cand_chars:
                    n_wrong_unrescuable += 1
                    continue                  # 金标不在候选内，换哪个策略都救不回来

                origin_counts["wrong_rescuable"][origin] = (
                    origin_counts["wrong_rescuable"].get(origin, 0) + 1)

                before = "".join(gold_seq[:i])
                before_text = (prev_ctx + before)[-window_chars:]
                after = "".join(gold_seq[i + 1:])
                after_text = (after + next_ctx)[:window_chars]

                items.append({
                    "id": sl["instance_id"],
                    "column_id": col["column_id"],
                    "page": s.get("page"),
                    "source_item": s.get("source_item"),
                    "origin": origin,
                    "context_before": before_text,
                    "context_after": after_text,
                    "candidates": cands,
                    "candidates_chars": cand_chars,
                    "gold": gold,
                    "current_strategy": {
                        "name": "gated_ngram",
                        "margin_gate": margin_gate,
                        "context_window": context_window,
                        "baseline_top1": dec["base"],
                        "raw_pick": dec["raw_pick"],
                        "raw_margin": dec["raw_margin"],
                        "final_decision": dec["final"],
                        "gate_would_rescue_if_lowered":
                            dec["raw_pick"] == gold and dec["raw_pick"] != dec["base"],
                    },
                })

    stats = {
        "n_total_slots": n_total,
        "n_wrong_unrescuable_gold_not_in_candidates": n_wrong_unrescuable,
        "n_wrong_rescuable": len(items),
        "by_origin_total": origin_counts["total"],
        "by_origin_wrong_rescuable": origin_counts["wrong_rescuable"],
    }
    return items, stats


def stratified_sample(items: list[dict], limit: int, seed: int) -> list[dict]:
    """按 origin 比例分层抽样到 limit 条以内；不够 limit 就全要。"""
    if len(items) <= limit:
        return items
    by_origin: dict[str, list[dict]] = {}
    for it in items:
        by_origin.setdefault(it["origin"], []).append(it)
    rng = random.Random(seed)
    total = len(items)
    out: list[dict] = []
    for origin, group in by_origin.items():
        rng.shuffle(group)
        take = max(1, round(limit * len(group) / total))
        out.extend(group[:take])
    rng.shuffle(out)
    return out[:limit]


def book_title(book_id: str) -> str:
    try:
        from open_guji_cv.core.book import load_book
        return load_book(book_id).title
    except Exception as e:  # noqa: BLE001 — 拿不到书名不该拦住建集，退化用 id
        print(f"⚠ 拿不到 {book_id} 的书名（{e}），题面里退化用 book_id")
        return book_id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dataset", help="context-correction 数据集根目录")
    ap.add_argument("--general-corpus", default=None)
    ap.add_argument("--book-corpus", default=None)
    ap.add_argument("--book-weight", type=float, default=DEFAULT_BOOK_WEIGHT)
    ap.add_argument("--gate", type=float, default=DEFAULT_MARGIN_GATE)
    ap.add_argument("--context-window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    ap.add_argument("--window-chars", type=int, default=DEFAULT_WINDOW_CHARS)
    ap.add_argument("--limit", type=int, default=150,
                    help="题目数上限（够用就行，任务书 §二·1）")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from open_guji_cv.clustering.context_step import build_strategy
    from open_guji_cv.clustering.variants import VariantMap

    root = Path(args.dataset)
    samples = load_samples(root)
    if not samples:
        print("没有可用样本（只有占位目录？）")
        return

    gold_texts = ["".join(sl["gold"] for c in s["columns"] for sl in c["slots"])
                 for s in samples]
    lm, provenance = build_lm(args.general_corpus, args.book_corpus,
                              args.book_weight, gold_texts)

    vpath = REPO / "config" / "charset" / "variants.tsv"
    vm = VariantMap.load(vpath if vpath.exists() else None)
    decider = build_strategy("gated_ngram", lm=lm, semantic_fn=vm.semantic)

    items, stats = build_items(samples, decider, args.gate,
                               args.context_window, args.window_chars)
    print(json.dumps(stats, ensure_ascii=False, indent=1))

    book_ids = sorted({s.get("source_item") for s in samples if s.get("source_item")})
    titles = {bid: book_title(bid) for bid in book_ids}

    selected = stratified_sample(items, args.limit, args.seed)
    selected.sort(key=lambda it: it["id"])

    out = {
        "meta": {
            "source_dataset": str(root.as_posix()),
            "selection_rule": (
                "生产口径 gated_ngram(margin_gate=%.2f, context_window=%d) "
                "最终判错、且金标落在候选集合内的槽位——ngram 已经稳赢的位"
                "不选，见脚本头注释" % (args.gate, args.context_window)),
            "production_config": {
                "strategy": "gated_ngram", "margin_gate": args.gate,
                "context_window": args.context_window,
                "book_weight": args.book_weight,
                **provenance,
            },
            "book_titles": titles,
            "window_chars": args.window_chars,
            "stats": stats,
            "n_selected": len(selected),
            "sample_seed": args.seed,
            "known_limitation": [
                "上下文为教师强制（列内前文/后文用金标拼接），是评测上界口径，"
                "不是生产真实前文（生产前文可能带错）——同 context-correction 数据集本身的口径",
                "context_after 只服务本评测集的 LLM 题面，生产 ngram 仍是纯前向、不吃后文",
                "候选集合冻结自 context-correction 数据集，随其 pipeline_version 走",
            ],
        },
        "items": selected,
    }
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {outp}（{len(selected)}/{len(items)} 题，"
         f"从 {stats['n_total_slots']} 槽位里挑）")


if __name__ == "__main__":
    main()
