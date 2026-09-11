"""接生产评测：`oracle_llm` 策略（外部 LLM 答案表）vs 纯 `gated_ngram` 基线。

承接 `Step6-上下文裁决/方案-外部LLM.md`——那一道只建了「LLM 单独准确率」
评测集（`run_llm_context_eval.py` 的 `report_*.json`，答案表覆盖 100 题、
只跟 100 题内部比），**没有把答案表接进 `run_gated` 算 top1_gain /
harmful_flip_rate**。本脚本补上这一步，在 `context-correction` 全量
1,681 槽位上跑，口径与 `eval_context_correction.py::run_gated` 一致
（同一套生产语料/权重/门槛，答案表覆盖不到的槽位由 `oracle_llm` 的
`fallback=GatedNgram` 接住，行为与纯基线完全相同——这就是为什么可以
在全量槽位上直接比，而不需要只看那 100 题）。

用法（答案表已在仓里，见 `output/llm_context_evalset/report_*.json`）：

    PYTHONPATH=. python scripts/eval_oracle_llm.py \\
        ../open-guji-dataset/context-correction \\
        --answers output/llm_context_evalset/report_qwen_qwen-plus_candidates.json \\
        --general-corpus corpus/external/daizhige_zhaoling.txt \\
        --book-corpus corpus/zongmu_wuyingdian_reference.txt

可以传多份 `--answers`（不同 provider/model），逐份跑，方便横向比。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

import sys  # noqa: E402
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import eval_context_correction as ecc  # noqa: E402


def load_answer_table(report_path: Path) -> tuple[dict[str, str], dict]:
    """从 `run_llm_context_eval.py` 的报告 json 里取答案表。

    只收 `llm_answer_in_candidates=True` 的行——`OracleLLM` 自己也会拦
    候选外的答案（铁律 1），这里提前过滤只是让报告里的『答案表覆盖数』
    准确，不依赖 OracleLLM 的静默丢弃。解析失败（`llm_parse_ok=False`）
    的行同样不进答案表，等同于「这题弃权，交回 gated_ngram」。
    """
    data = json.loads(report_path.read_text(encoding="utf-8"))
    answers: dict[str, str] = {}
    for row in data["rows"]:
        if row.get("llm_parse_ok") and row.get("llm_answer_in_candidates"):
            answers[row["id"]] = row["llm_parsed_char"]
    meta = {
        "provider": data.get("provider"), "model": data.get("model"),
        "prompt_version": data.get("prompt_version"),
        "report_n": data.get("n"),
        "report_llm_accuracy": data.get("llm_accuracy"),
        "answers_usable": len(answers),
    }
    return answers, meta


def run_oracle(samples: list[dict], decider, margin: float) -> dict:
    """`oracle_llm` 版本的 `run_gated`：口径逐条抄 `ecc.run_gated`，
    只把策略换成外部传入的 `decider`（`oracle_llm`，带 `GatedNgram`
    fallback），margin 门槛与人工介入判定不变——答案表命中时
    `confidence=1.0 >= margin` 恒真，未命中时 `decider` 已经在内部
    退回 `GatedNgram`，两条路径最终都要过同一道 margin 门槛，
    不因为换了策略就放宽纪律。
    """
    strata: dict[str, list[int]] = {"human": [0, 0, 0, 0], "align": [0, 0, 0, 0]}
    rescued = harmed = flips = oracle_hits = 0
    for s in samples:
        for col in s["columns"]:
            ctx: list[str] = []
            for sl in col["slots"]:
                cands = sl["candidates"]
                if not cands:
                    continue
                g = sl["gold"]
                base = cands[0]["char"]
                priors = {c["char"]: c["prob"] for c in cands}
                res = decider.decide(priors, context=tuple(ctx[-4:]),
                                     item_id=sl["instance_id"])
                pick, m = res.surface, res.margin
                if sl["instance_id"] in decider.answers:
                    oracle_hits += 1
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
                ctx.append(g)
    n = sum(v[0] for v in strata.values())
    base_ok = sum(v[1] for v in strata.values())
    new_ok = sum(v[2] for v in strata.values())
    return {
        "n": n, "gate_margin": margin, "oracle_hits": oracle_hits,
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
        "glyph_layer_immutability": True,   # OracleLLM 只在候选内选，构造保证
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset")
    ap.add_argument("--answers", action="append", required=True,
                    help="run_llm_context_eval.py 产出的报告 json，可传多份")
    ap.add_argument("--general-corpus",
                    default=str(REPO / "corpus" / "external" / "daizhige_zhaoling.txt"))
    ap.add_argument("--book-corpus",
                    default=str(REPO / "corpus" / "zongmu_wuyingdian_reference.txt"))
    ap.add_argument("--book-weight", type=float, default=0.9)
    ap.add_argument("--gate", type=float, default=0.70)
    ap.add_argument("--lam", type=float, default=0.55)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from open_guji_cv.clustering.lm import InterpolatedLM, UniformLM, train_ngram
    from open_guji_cv.clustering.variants import VariantMap
    from open_guji_cv.clustering.context_step import build_strategy

    root = Path(args.dataset)
    samples = ecc.load_samples(root)
    if not samples:
        print("没有可用样本（只有占位目录？）")
        return
    gold_texts = ["".join(sl["gold"] for c in s["columns"] for sl in c["slots"])
                 for s in samples]

    vpath = REPO / "config" / "charset" / "variants.tsv"
    vm = VariantMap.load(vpath if vpath.exists() else None)

    provenance: dict = {"book_weight": args.book_weight, "gate": args.gate}
    general_lm = None
    if args.general_corpus:
        raw = Path(args.general_corpus).read_text(encoding="utf-8")
        segs = [vm.normalize_text(x) for x in raw.split("\n") if x.strip()]
        general_lm = train_ngram(segs, 3, 2)
        provenance["general_corpus"] = args.general_corpus
    book_lm = None
    if args.book_corpus:
        raw = Path(args.book_corpus).read_text(encoding="utf-8")
        held, removed = ecc.heldout_corpus(raw, gold_texts)
        segs = [vm.normalize_text(x) for x in held.split("\n") if x.strip()]
        book_lm = train_ngram(segs, 3, 1)
        provenance["book_corpus"] = args.book_corpus
        provenance["book_chars_removed_as_holdout"] = removed
        if removed == 0:
            print("⚠ 一个测试页窗口都没挖掉——本书 LM 可能在背答案，下面数字不可信")
    comps = []
    if general_lm is not None and (1 - args.book_weight) > 0:
        comps.append((general_lm, 1 - args.book_weight))
    if book_lm is not None and args.book_weight > 0:
        comps.append((book_lm, args.book_weight))
    lm = InterpolatedLM(comps) if comps else UniformLM()

    # 基线：纯 gated_ngram（不带任何外部 LLM 答案）
    baseline = ecc.run_gated(samples, lm, vm, args.lam, args.gate)

    reports = []
    for ans_path in args.answers:
        answers, meta = load_answer_table(Path(ans_path))
        # lam 显式传给 build_strategy：它内部给 oracle_llm 建 fallback 用的是
        # 模块默认 LAMBDA(0.65)，不传就会跟基线的 args.lam(0.55) 口径对不上
        decider = build_strategy("oracle_llm", answers=answers,
                                 semantic_fn=vm.semantic, lm=lm, lam=args.lam)
        result = run_oracle(samples, decider, args.gate)
        reports.append({"answers_source": ans_path, **meta, "result": result})

    out = {
        "dataset": str(root.as_posix()),
        "provenance": provenance,
        "baseline_gated_ngram": baseline,
        "oracle_llm_reports": reports,
    }
    print(json.dumps({"provenance": provenance}, ensure_ascii=False, indent=1))
    print(f"\n{'集合':<28} {'n':>6} {'top1':>8} {'增益':>8} {'救回':>5} "
          f"{'改坏':>5} {'有害翻转':>9} {'覆盖题数':>8}")

    def _row(label: str, r: dict, covered: int | None = None):
        cov = "—" if covered is None else str(covered)
        print(f"{label:<28} {r['n']:>6} {r['top1']:>7.2%} {r['top1_gain']:>+7.2%} "
             f"{r['rescued']:>5} {r['harmed']:>5} {r['harmful_flip_rate']:>8.2%} {cov:>8}")

    _row("baseline (gated_ngram)", baseline)
    for rep in reports:
        label = f"oracle_llm ({rep['provider']}/{rep['model']}/{rep['prompt_version']})"
        _row(label, rep["result"], rep["answers_usable"])

    dest = Path(args.out) if args.out else REPO / "output" / "llm_context_evalset" / "oracle_llm_report.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {dest}")


if __name__ == "__main__":
    main()
