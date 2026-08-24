"""context-correction 评测：在冻结候选上量「通用 LM 低权重 + 本书 LM 高权重」。

    PYTHONPATH=. python scripts/eval_context_correction.py \
        ../open-guji-dataset/context-correction \
        --general-corpus corpus/external/daizhige_ru_yi.txt \
        --book-corpus corpus/zongmu_wuyingdian_reference.txt \
        --sweep 0,0.1,0.2,0.3,0.5,0.7,1.0

## 本书语料必须留出测试页

本书语料就是本书的整理本，而测试页的金标也是从同一份整理本对齐来的。
不做处理就是**背答案**：LM 见过一字不差的原文，测出来的增益全是假的。
故本脚本先把每个测试页的金标文本在语料里的对应窗口挖掉（前后再多挖
``HOLDOUT_PAD`` 字），再训本书 LM。挖掉多少字会打印出来，为零就说明
挖漏了，别接着往下看数字。

通用语料的泄漏由 `prepare_corpus.py --holdout` 事前查；本脚本再对
**测试页金标**复查一次 8-gram 重合率并打印。

## 四个指标必须一起看

- ``baseline_top1``：冻结候选的首选命中率，纠正前的基线；
- ``top1_gain``：纠正后相对基线的**绝对**提升，主指标；
- ``harmful_flip_rate``：原本正确被改错的比例。只报 gain 不报它，
  等于允许「改对 20 个、改错 15 个」被吹成净赚 5 个；
- ``glyph_layer_immutability``：硬断言。纠正只许在冻结候选里重排，
  不许引入候选外的字。断言失败即判本次评测无效——语义层无权改写
  字形层是本项目的纪律，不是可以用准确率换的参数。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOLDOUT_PAD = 200      # 测试页窗口两侧额外挖掉的字数


def load_samples(root: Path) -> list[dict]:
    out = []
    for d in sorted((root / "samples").glob("*/")):
        f = d / "expected.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if "columns" not in data:
            continue          # 占位样本
        out.append(data)
    return out


def heldout_corpus(corpus: str, gold_texts: list[str], pad: int = HOLDOUT_PAD
                   ) -> tuple[str, int]:
    """把测试页金标在语料里对应的窗口挖掉，返回 (剩余语料, 挖掉字数)。"""
    from open_guji_cv.clustering.align_eval import build_ngram_index, anchor_page

    index = build_ngram_index(corpus)
    spans: list[tuple[int, int]] = []
    for t in gold_texts:
        off = anchor_page(t, index)
        if off is None:
            continue
        spans.append((max(0, off - pad), min(len(corpus), off + len(t) + pad)))
    if not spans:
        return corpus, 0
    spans.sort()
    merged = [list(spans[0])]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    keep, prev = [], 0
    for lo, hi in merged:
        keep.append(corpus[prev:lo])
        prev = hi
    keep.append(corpus[prev:])
    removed = sum(hi - lo for lo, hi in merged)
    return "".join(keep), removed


def ngram_overlap(a: str, b: str, n: int = 8) -> float:
    if len(a) < n:
        return 0.0
    bs = {b[i:i + n] for i in range(len(b) - n + 1)}
    return sum(1 for i in range(len(a) - n + 1)
               if a[i:i + n] in bs) / (len(a) - n + 1)


def run_once(samples: list[dict], lm, vm, lam: float) -> dict:
    """在冻结候选上跑一遍 beam search，返回四个指标。"""
    from open_guji_cv.clustering.context_rank import (Slot, SlotCandidate,
                                                      beam_search)

    n = base_ok = new_ok = rescued = harmed = 0
    violations = 0
    for s in samples:
        for col in s["columns"]:
            slots, golds, allowed = [], [], []
            for sl in col["slots"]:
                cands = [SlotCandidate(c["char"],
                                       c.get("semantic") or vm.semantic(c["char"]),
                                       c["prob"])
                         for c in sl["candidates"]]
                slots.append(Slot(instance_id=sl["instance_id"],
                                  cluster_id=sl.get("cluster_id"),
                                  candidates=cands))
                golds.append(sl["gold"])
                allowed.append({c["char"] for c in sl["candidates"]})
            if not slots:
                continue
            res = beam_search(slots, lm, lam=lam)
            for sl, r, g, allow in zip(col["slots"], res, golds, allowed):
                n += 1
                b = sl["candidates"][0]["char"] if sl["candidates"] else None
                was = (b == g)
                now = (r.best == g)
                base_ok += was
                new_ok += now
                rescued += (now and not was)
                harmed += (was and not now)
                if allow and r.best not in allow:
                    violations += 1
    return {
        "n": n,
        "baseline_top1": round(base_ok / n, 4) if n else 0.0,
        "baseline_top1_n": base_ok,
        "top1": round(new_ok / n, 4) if n else 0.0,
        "top1_n": new_ok,
        "top1_gain": round((new_ok - base_ok) / n, 4) if n else 0.0,
        "rescued": rescued,
        "harmed": harmed,
        "harmful_flip_rate": round(harmed / base_ok, 4) if base_ok else 0.0,
        "glyph_layer_immutability": violations == 0,
        "violations": violations,
    }


def run_gated(samples: list[dict], lm, vm, lam: float, margin: float) -> dict:
    """生产口径（seed 上下文通道）：**门槛化**纠正，不做全局重排。

    十二轮实测定案：在含库匹配证据的强融合先验上，无条件 LM 重排
    在任何 λ 下都是净亏（λ=0.95 仍 救17/坏34）——LM 的正确用法是
    「先验拿不准时的裁判」，不是「对所有槽位的再排序器」。这里复刻
    seed 通道的裁决：语义层 margin ≥ 阈才改判，其余保持基线首选；
    上下文用列内金标前文（理想口径，同 context.prev 的说明）。
    按 origin（human/align）分层——human 层才是硬样本。"""
    import math

    def decide_slot(cands, ctx_chars):
        scores = {}
        for c in cands:
            lp = lm.logp(c["char"], tuple(ctx_chars))
            scores[c["char"]] = lam * math.log(max(c["prob"], 1e-12)) \
                + (1.0 - lam) * lp
        top = max(scores.values())
        exp = {ch: math.exp(s - top) for ch, s in scores.items()}
        z = sum(exp.values())
        ranked = sorted(((ch, e / z) for ch, e in exp.items()),
                        key=lambda t: -t[1])
        groups: dict[str, float] = {}
        for ch, p in ranked:
            g = vm.semantic(ch)
            groups[g] = groups.get(g, 0.0) + p
        top_sem = max(groups, key=lambda g: groups[g])
        rest = [v for g, v in groups.items() if g != top_sem]
        sem_margin = groups[top_sem] - (max(rest) if rest else 0.0)
        members = [ch for ch, _ in ranked if vm.semantic(ch) == top_sem]
        return members[0], sem_margin

    strata = {"human": [0, 0, 0, 0], "align": [0, 0, 0, 0]}  # n, base, new, flips
    rescued = harmed = flips = 0
    for s in samples:
        for col in s["columns"]:
            ctx: list[str] = []
            for sl in col["slots"]:
                cands = sl["candidates"]
                if not cands:
                    continue
                g = sl["gold"]
                base = cands[0]["char"]
                pick, m = decide_slot(cands, ctx[-4:])
                new = pick if (pick != base and m >= margin
                               and len(cands) >= 2) else base
                origin = sl.get("origin") or "align"
                st = strata.setdefault(origin, [0, 0, 0, 0])
                st[0] += 1
                st[1] += base == g
                st[2] += new == g
                if new != base:
                    flips += 1
                    st[3] += 1
                    rescued += (new == g and base != g)
                    harmed += (base == g and new != g)
                ctx.append(g)          # 教师强制：后文上下文用金标
    n = sum(v[0] for v in strata.values())
    base_ok = sum(v[1] for v in strata.values())
    new_ok = sum(v[2] for v in strata.values())
    return {
        "n": n, "gate_margin": margin,
        "baseline_top1": round(base_ok / n, 4) if n else 0.0,
        "top1": round(new_ok / n, 4) if n else 0.0,
        "top1_gain": round((new_ok - base_ok) / n, 4) if n else 0.0,
        "flips": flips, "rescued": rescued, "harmed": harmed,
        "harmful_flip_rate": round(harmed / base_ok, 4) if base_ok else 0.0,
        "flip_precision": round(rescued / flips, 4) if flips else None,
        "by_origin": {k: {"n": v[0],
                          "baseline_top1": round(v[1] / v[0], 4) if v[0] else 0,
                          "top1": round(v[2] / v[0], 4) if v[0] else 0,
                          "flips": v[3]}
                      for k, v in strata.items() if v[0]},
        "glyph_layer_immutability": True,   # 只在候选集内挑，构造保证
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="context-correction 评测")
    ap.add_argument("dataset")
    ap.add_argument("--general-corpus", default=None,
                    help="通用古文语料（低权重分量）")
    ap.add_argument("--book-corpus", default=None,
                    help="本书语料（高权重分量），会自动挖掉测试页")
    ap.add_argument("--sweep", default="0,0.25,0.5,0.75,1.0",
                    help="本书分量的权重取值列表；通用分量取 1-w")
    ap.add_argument("--lam", type=float, default=0.55,
                    help="OCR 项与 LM 项的配比（context_rank.LAMBDA）")
    ap.add_argument("--order", type=int, default=3)
    ap.add_argument("--min-count", type=int, default=2,
                    help="通用语料高阶计数的剪枝阈值")
    ap.add_argument("--gate", type=float, default=None,
                    help="门槛化模式：语义 margin ≥ 此阈才改判（生产口径，"
                         "seed 默认 0.70）；给了本参数就跑 run_gated 而非"
                         "全局重排")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO))
    from open_guji_cv.clustering.lm import InterpolatedLM, UniformLM, train_ngram
    from open_guji_cv.clustering.variants import VariantMap

    vpath = REPO / "config" / "charset" / "variants.tsv"
    vm = VariantMap.load(vpath if vpath.exists() else None)

    root = Path(args.dataset)
    samples = load_samples(root)
    if not samples:
        print("没有可用样本（只有占位目录？）")
        return
    gold_texts = ["".join(sl["gold"] for c in s["columns"] for sl in c["slots"])
                  for s in samples]
    all_gold = "".join(gold_texts)

    provenance: dict = {"lam": args.lam, "order": args.order}

    general_lm = None
    if args.general_corpus:
        raw = Path(args.general_corpus).read_text(encoding="utf-8")
        segs = [vm.normalize_text(x) for x in raw.split("\n") if x.strip()]
        general_lm = train_ngram(segs, args.order, args.min_count)
        provenance["general"] = {
            "path": args.general_corpus,
            "chars": sum(len(x) for x in segs),
            "vocab": len(general_lm.vocab),
            "leak_8gram_vs_test_gold": round(ngram_overlap(all_gold, raw), 6),
        }

    book_lm = None
    if args.book_corpus:
        raw = Path(args.book_corpus).read_text(encoding="utf-8")
        held, removed = heldout_corpus(raw, gold_texts)
        segs = [vm.normalize_text(x) for x in held.split("\n") if x.strip()]
        book_lm = train_ngram(segs, args.order, 1)
        provenance["book"] = {
            "path": args.book_corpus,
            "chars_before": len(raw), "chars_removed_as_holdout": removed,
            "chars_used": sum(len(x) for x in segs),
            "vocab": len(book_lm.vocab),
            "leak_8gram_vs_test_gold": round(ngram_overlap(all_gold, held), 6),
        }
        if removed == 0:
            print("⚠ 一个测试页窗口都没挖掉——本书 LM 可能在背答案，"
                  "下面的数字不可信")

    print(json.dumps(provenance, ensure_ascii=False, indent=1))

    rows = []
    weights = [float(x) for x in args.sweep.split(",") if x.strip() != ""]
    # w = 本书分量权重；w=0 即纯通用，w=1 即纯本书
    for w in weights:
        comps = []
        if general_lm is not None and (1 - w) > 0:
            comps.append((general_lm, 1 - w))
        if book_lm is not None and w > 0:
            comps.append((book_lm, w))
        lm = InterpolatedLM(comps) if comps else UniformLM()
        if args.gate is not None:
            r = run_gated(samples, lm, vm, args.lam, args.gate)
        else:
            r = run_once(samples, lm, vm, args.lam)
        r["book_weight"] = w
        r["lm"] = lm.name
        rows.append(r)

    # 无 LM 的对照（LM 项恒为常数，排序完全由 OCR 概率决定）
    r0 = run_once(samples, UniformLM(), vm, args.lam)
    r0["book_weight"] = None
    r0["lm"] = "uniform"
    rows.insert(0, r0)

    print(f"\n{'本书权重':>8} {'LM':<26} {'top1':>8} {'增益':>8} "
          f"{'救回':>5} {'改坏':>5} {'有害翻转':>9} {'字形层不可改写':>8}")
    for r in rows:
        w = "—" if r["book_weight"] is None else f"{r['book_weight']:.2f}"
        print(f"{w:>8} {r['lm'][:26]:<26} {r['top1']:>7.2%} "
              f"{r['top1_gain']:>+7.2%} {r['rescued']:>5} {r['harmed']:>5} "
              f"{r['harmful_flip_rate']:>8.2%} "
              f"{'是' if r['glyph_layer_immutability'] else '否(!)':>8}")
    print(f"\n基线 top1 {rows[0]['baseline_top1']:.2%} "
          f"({rows[0]['baseline_top1_n']}/{rows[0]['n']})")

    report = {"dataset": str(root.as_posix()), "provenance": provenance,
              "rows": rows}
    dest = Path(args.out) if args.out else root / "report.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"→ {dest}")


if __name__ == "__main__":
    main()
