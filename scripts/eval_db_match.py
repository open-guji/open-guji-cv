"""字形库匹配基准（glyph_db_first_design.md §5：库匹配是 G4 的新位置）。

在 char-clustering 金标分片上跑 `GlyphMatcher` 的两种协议：

- **册内增量**（incremental）：库从 0 长起，逐页处理；每个实例先匹配、
  后带金标进库（金标进库 = 兜底分支最终解决的上界）。
- **跨册种子**（cross-seed）：另一册全量当初始库，再册内增量。

指标（沿设计 §5 的表）：

- `match_coverage`：same 档（完美匹配）覆盖率；
- `match_precision`：same 档继承字 == 金标的比例，**硬约束 ≥ 0.999**
  （对应 purity 在旧评测里的位置）；
- 护栏统计：never_match / conflict 各拦下多少次（拦下的不算覆盖，
  它们本来就该走候选+上下文分支）；
- 后半段覆盖率：库热起来之后的水平（覆盖率-库规模曲线的粗粒度读法）。

    python scripts/eval_db_match.py ../open-guji-dataset/char-clustering
    python scripts/eval_db_match.py ../open-guji-dataset/char-clustering \
        --protocol cross-seed --seed-shard 001-vol01-body --query-shard 002-vol02-body
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.clustering.match import GlyphMatcher  # noqa: E402
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402


# 已记账的金标标签问题（与 normalize 回归门的 known_defect 同思路：不进
# 硬约束门，但每轮照报——金标修好后从这里删）。定性见 g3g4_error_analysis
# §5 与 char-clustering README。
KNOWN_GOLD_ISSUES: dict[str, str] = {
    "vol01:23:7:12": "羣/詳：OCR 错认 + 语料邻近同字序 → spurious equal，金标为錯",
}


def load_shard(samples_dir: Path, shard: str):
    d = json.loads((samples_dir / shard / "expected.json").read_text(encoding="utf-8"))
    inst = sorted(d["instances"],
                  key=lambda x: (int(x["page"]), x["instance_id"]))
    patches = np.zeros((len(inst), 64, 64), np.uint8)
    for i, x in enumerate(inst):
        img = cv2.imread(str(samples_dir / shard / x["crop"]), cv2.IMREAD_GRAYSCALE)
        patches[i] = (img > 127).astype(np.uint8)
    return inst, patches


def run(matcher: GlyphMatcher, inst, patches, feats, tag: str,
        vmap: VariantMap | None = None) -> dict:
    """vmap：语义层精度用（注/註 类异体字形匹配在字形层是正确行为，
    语义归并交 VariantMap——设计 §3 的既有纪律）。"""
    vmap = vmap or VariantMap.load()
    n = len(inst)
    matched = correct = sem_correct = 0
    guards = {"never_match": 0, "conflict": 0}
    wrong = []
    per_flag = []                                # True=命中, None=未命中
    for i, x in enumerate(inst):
        r = matcher.match(patches[i], feat=feats[i])
        if r.verdict == "same":
            matched += 1
            ok = r.char == x["char"]
            correct += ok
            sem_ok = ok or vmap.semantic(r.char) == vmap.semantic(x["char"])
            sem_correct += sem_ok
            if not sem_ok:
                wrong.append((x["instance_id"], x["char"], r.char, r.matched_id))
            per_flag.append(True)
        else:
            if r.guard:
                guards[r.guard] += 1
            per_flag.append(None)
        matcher.add(x["instance_id"], x["char"], patches[i], feat=feats[i])
        if (i + 1) % 1000 == 0:
            print(f"  [{tag}] {i + 1}/{n} 覆盖 {matched / (i + 1):.1%} "
                  f"精度 {correct / max(1, matched):.4f}", flush=True)
    half = n // 2
    mh = sum(1 for f in per_flag[half:] if f)
    unaccounted = [w for w in wrong if w[0] not in KNOWN_GOLD_ISSUES]
    gated = sem_correct + (len(wrong) - len(unaccounted))
    report = {
        "tag": tag, "n": n,
        "match_coverage": round(matched / max(1, n), 4),
        "match_precision": round(correct / max(1, matched), 4),
        "match_precision_semantic": round(sem_correct / max(1, matched), 4),
        "match_precision_gated": round(gated / max(1, matched), 4),
        "n_matched": matched, "n_correct": correct,
        "coverage_second_half": round(mh / max(1, n - half), 4),
        "guards": guards,
        "mismatches": [{"id": a, "gold": g, "pred": p, "matched": m}
                       for a, g, p, m in wrong],
    }
    print(f"[{tag}] 覆盖 {matched}/{n}={report['match_coverage']:.1%}  "
          f"字形精度 {report['match_precision']:.4f}  "
          f"语义精度 {report['match_precision_semantic']:.4f}  "
          f"计门精度 {report['match_precision_gated']:.4f}  "
          f"后半段 {report['coverage_second_half']:.1%}  护栏 {guards}")
    for w in report["mismatches"][:8]:
        known = "（已记账金标问题）" if w["id"] in KNOWN_GOLD_ISSUES else ""
        print(f"    错配 {w['id']}: 金标 {w['gold']} ← 继承 {w['pred']} "
              f"({w['matched']}){known}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="char-clustering 数据集目录")
    ap.add_argument("--protocol", choices=("incremental", "cross-seed", "all"),
                    default="all")
    ap.add_argument("--shards", default="001-vol01-body,002-vol02-body",
                    help="incremental 协议要跑的分片（逗号分隔）")
    ap.add_argument("--seed-shard", default="001-vol01-body")
    ap.add_argument("--query-shard", default="002-vol02-body")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default=None, help="报告 JSON 路径")
    args = ap.parse_args()

    samples = Path(args.dataset) / "samples"
    reports = []

    if args.protocol in ("incremental", "all"):
        for shard in args.shards.split(","):
            inst, patches = load_shard(samples, shard)
            m = GlyphMatcher(k=args.k)
            feats = m.extract(patches)
            reports.append(run(m, inst, patches, feats, f"incremental/{shard}"))

    if args.protocol in ("cross-seed", "all"):
        si, sp = load_shard(samples, args.seed_shard)
        qi, qp = load_shard(samples, args.query_shard)
        m = GlyphMatcher(k=args.k)
        sf = m.extract(sp)
        qf = m.extract(qp)
        for i, x in enumerate(si):
            m.add(x["instance_id"], x["char"], sp[i], feat=sf[i])
        reports.append(run(m, qi, qp, qf,
                           f"cross-seed/{args.query_shard}|db={args.seed_shard}"))

    # 硬约束量在「计门精度」：语义层（异体字形匹配是正确行为）+ 已记账
    # 金标问题豁免（KNOWN_GOLD_ISSUES，逐条带定性依据）。字形/语义精度
    # 照报不豁免——豁免只对门，不对数字。
    hard_fail = [r for r in reports if r["match_precision_gated"] < 0.999]
    if args.out:
        Path(args.out).write_text(
            json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {args.out}")
    if hard_fail:
        print(f"硬约束失败（precision < 0.999）: {[r['tag'] for r in hard_fail]}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
