"""形近对消歧的 n-gram 语言模型臂。

给定挖空的上下文，在形近对的两个字里选一个。打分不是只看左文——把
目标位左右各取一段窗口，两个候选各代入一次，算**整窗序列**在 n-gram 下
的对数概率，比谁高。这样右文也参与决策（前向 n-gram 单看 P(c|左文)
会丢掉「諭旨」这种右文才成立的证据）。

三种语料配置，差别就是这套评测的全部意义所在：

* ``book``      本书整理本 + 通用语料（**生产口径，但对本集有泄漏**——
                测试题的原文就在训练语料里，等于开卷考）
* ``heldout``   本书整理本**剔掉所有测试列的原文** + 通用语料
                （诚实口径：LM 没见过这些句子，考的是真泛化）
* ``general``   只有通用语料，完全不碰本书（泛化下界）

``book`` 与 ``heldout`` 的落差就是记忆的贡献；只报 ``book`` 会把
「背下来了」说成「学会了」。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.lm import CharNgramLM, InterpolatedLM, train_ngram

MASK = "△"
GAP = "·"


def read_text(paths: list[Path]) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


def best_effort_text(ref: str | None, ocr: str | None) -> str:
    """整理本优先、脱字位拿 OCR 补——生产里能拿到的最好的一版文本。"""
    if not ref:
        return ocr or ""
    ocr = ocr or ""
    out = []
    for i, ch in enumerate(ref):
        if ch == GAP:
            out.append(ocr[i] if i < len(ocr) else "")
        else:
            out.append(ch)
    return "".join(out)


def window(case: dict, left: int, right: int) -> tuple[str, str, str]:
    """(前文, 目标位左右的右文, 更前面的引导文)。目标位已被 MASK 占住。"""
    col = best_effort_text(case.get("col_ref_masked"), case.get("col_masked"))
    prev = best_effort_text(case.get("prev_ref"), case.get("prev_ocr"))
    pos = case["pos"]
    # 目标位在 col 里仍是 MASK（best_effort 不会替换它——ref/ocr 同位都是 MASK）
    if pos >= len(col) or col[pos] != MASK:
        col = case["col_masked"]
    lead = (prev + col[:pos])[-(left):] if left else ""
    tail = col[pos + 1:pos + 1 + right]
    return lead, tail, prev


def seq_logp(lm, text: str, primer: str, order: int) -> float:
    """log P(text | primer)，逐字累加。"""
    total = 0.0
    ctx = list(primer)
    for ch in text:
        total += lm.logp(ch, tuple(ctx[-(order - 1):]))
        ctx.append(ch)
    return total


def build_lm(mode: str, book: list[Path], general: list[Path],
             cases: list[dict], order: int,
             book_w: float, gen_w: float):
    gen_txt = read_text(general) if general else ""
    book_txt = read_text(book) if book else ""
    removed = 0
    if mode == "general":
        book_txt = ""
    elif mode == "heldout":
        # 把每道题所在列（及前后列）的整理本原文从语料里剔掉
        frags = set()
        for c in cases:
            for k in ("col_ref_masked", "prev_ref", "next_ref"):
                t = (c.get(k) or "").replace(GAP, "").replace(MASK, "")
                if len(t) >= 4:
                    frags.add(t)
        for f in sorted(frags, key=len, reverse=True):
            if f in book_txt:
                book_txt = book_txt.replace(f, "\n")
                removed += 1
    comps = []
    if book_txt.strip():
        comps.append((train_ngram([book_txt], order=order), book_w))
    if gen_txt.strip():
        comps.append((train_ngram([gen_txt], order=order), gen_w))
    if not comps:
        raise SystemExit("没有可用语料")
    lm = comps[0][0] if len(comps) == 1 else InterpolatedLM(comps)
    return lm, removed


def main() -> None:
    ap = argparse.ArgumentParser(description="形近对消歧 · n-gram 臂")
    ap.add_argument("cases", help="build_confusable_set.py 的产出")
    ap.add_argument("--book-corpus", action="append", default=[])
    ap.add_argument("--general-corpus", action="append", default=[])
    ap.add_argument("--mode", choices=["book", "heldout", "general"],
                    default="heldout")
    ap.add_argument("--order", type=int, default=3)
    ap.add_argument("--left", type=int, default=6)
    ap.add_argument("--right", type=int, default=4)
    ap.add_argument("--book-weight", type=float, default=0.9)
    ap.add_argument("--general-weight", type=float, default=0.1)
    ap.add_argument("--out", default=None, help="逐题结果 json")
    args = ap.parse_args()

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = data["cases"]
    lm, removed = build_lm(
        args.mode, [Path(p) for p in args.book_corpus],
        [Path(p) for p in args.general_corpus], cases, args.order,
        args.book_weight, args.general_weight)
    if args.mode == "heldout":
        print(f"留出：从本书语料剔除 {removed} 段测试原文")

    results = []
    for c in cases:
        lead, tail, _ = window(c, args.left, args.right)
        scores = {}
        for opt in c["options"]:
            scores[opt] = seq_logp(lm, opt + tail, lead, args.order)
        pick = max(scores, key=scores.get)
        vals = sorted(scores.values(), reverse=True)
        results.append({**{k: c[k] for k in
                           ("id", "pair", "gold", "tier", "options")},
                        "pick": pick, "correct": pick == c["gold"],
                        "margin": round(vals[0] - vals[1], 4),
                        "scores": {k: round(v, 3) for k, v in scores.items()}})

    report(results, f"n-gram({args.order}) · {args.mode}")
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"arm": f"ngram-{args.mode}", "results": results},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"逐题写出 {args.out}")


def report(results: list[dict], title: str) -> None:
    print(f"\n=== {title} ===")
    for tier in ("hard_ref_silent", "easy_ref_gives_answer", None):
        sub = [r for r in results if tier is None or r["tier"] == tier]
        if not sub:
            continue
        acc = sum(r["correct"] for r in sub) / len(sub)
        # 多数类基线：每个形近对内部按金标众数猜
        maj = 0
        for pk in {r["pair"] for r in sub}:
            g = Counter(r["gold"] for r in sub if r["pair"] == pk)
            maj += g.most_common(1)[0][1]
        name = {"hard_ref_silent": "真难档",
                "easy_ref_gives_answer": "送分档"}.get(tier, "合计")
        print(f"  {name:5s} n={len(sub):3d}  准确率 {acc:6.1%}"
              f"   （多数类基线 {maj / len(sub):.1%}）")


if __name__ == "__main__":
    main()
