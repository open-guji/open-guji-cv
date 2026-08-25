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

## --with-branches（端到端：same 照旧 + unsure/diff 走 decide_*）

unsure/diff 档实例接 recognize_flow.decide_unsure / decide_diff（候选 =
库 unsure 命中 ∪ OCR top-k + s2t，上下文/LM 融合），margin ≥ 准入阈
（scripts/calibrate_margin.py 标定，2026-08-23 vol02 册内标定值 0.99）
的裁决计入覆盖，阈下计 pending（进审查队列）。多报三个数：

- end2end_coverage : (same + 阈上 context) / n
- end2end_precision: same 与阈上 context 合计的正确率
- pending_ratio    : 阈下 + 无候选的比例

**不改变原有语义**：same 档的四个精度数与硬约束门照旧只看 same 档；
--with-branches 仅在其上追加。注意开启后实例按**阅读顺序**处理（页→
列→idx，上下文窗口需要真前文），与默认的 (page, instance_id) 字符串
序不同，库增长顺序略变，same 档数字可能有极小漂移。

OCR top-k 优先读 calibrate_margin 的缓存 jsonl（--ocr-cache，真 top-k），
缓存没有的实例退化用各书 ocr_carrier.jsonl 的 top1 兜底。

    python scripts/eval_db_match.py ../open-guji-dataset/char-clustering \
        --with-branches --margin-threshold 0.99
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


def load_shard(samples_dir: Path, shard: str, include_excluded: bool = False):
    d = json.loads((samples_dir / shard / "expected.json").read_text(encoding="utf-8"))
    inst = sorted(d["instances"],
                  key=lambda x: (int(x["page"]), x["instance_id"]))
    # 排除名单：切分坏掉的图块既不进库也不当查询——它们量的是切分的账
    if not include_excluded:
        from open_guji_cv.clustering.exclusions import excluded_ids
        ex = excluded_ids()
        n0 = len(inst)
        inst = [x for x in inst if x["instance_id"] not in ex]
        if n0 != len(inst):
            print(f"  [{shard}] 排除名单跳过 {n0 - len(inst)}/{n0} 个实例", flush=True)
    patches = np.zeros((len(inst), 64, 64), np.uint8)
    for i, x in enumerate(inst):
        img = cv2.imread(str(samples_dir / shard / x["crop"]), cv2.IMREAD_GRAYSCALE)
        patches[i] = (img > 127).astype(np.uint8)
    return inst, patches


class BranchConfig:
    """--with-branches 的共享件：LM / 语义映射 / OCR top-k 查找 / 准入阈。

    OCR 查找顺序：calibrate_margin 缓存（真 top-k，原始简体，s2t 在
    decide_* 里做）→ 各书 ocr_carrier.jsonl 的 top1（已 s2t，再过一遍
    traditional_candidates 无害）→ 空（decide 记 no_candidates）。
    """

    def __init__(self, threshold: float, lm, vmap: VariantMap,
                 cache_paths: list[Path], carrier_tmpl: str):
        self.threshold = threshold
        self.lm = lm
        self.vmap = vmap
        self._topk: dict[str, list[tuple[str, float]]] = {}
        for p in cache_paths:
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        r = json.loads(line)
                        self._topk[r["id"]] = [tuple(t) for t in r["topk"]]
        self._carrier_tmpl = carrier_tmpl
        self._carrier_loaded: set[str] = set()

    def topk(self, instance_id: str) -> list[tuple[str, float]]:
        if instance_id in self._topk:
            return self._topk[instance_id]
        book = instance_id.split(":", 1)[0]
        if book not in self._carrier_loaded:
            self._carrier_loaded.add(book)
            p = Path(self._carrier_tmpl.format(book=book))
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        r = json.loads(line)
                        if r.get("char"):
                            self._topk.setdefault(
                                r["id"], [(r["char"], float(r.get("prob", 0.0)))])
        return self._topk.get(instance_id, [])


def run(matcher: GlyphMatcher, inst, patches, feats, tag: str,
        vmap: VariantMap | None = None,
        branches: "BranchConfig | None" = None) -> dict:
    """vmap：语义层精度用（注/註 类异体字形匹配在字形层是正确行为，
    语义归并交 VariantMap——设计 §3 的既有纪律）。

    branches 给定时追加端到端指标（见文件头 --with-branches 节）；
    same 档的指标与硬约束门语义不变。"""
    vmap = vmap or VariantMap.load()
    if branches is not None:
        from open_guji_cv.clustering.ids import parse_id
        from open_guji_cv.clustering.recognize_flow import (ColumnContext,
                                                            decide_diff,
                                                            decide_unsure)
        # 阅读顺序（页→列→idx）：上下文窗口需要真前文
        order = sorted(range(len(inst)),
                       key=lambda i: (int(inst[i]["page"]),
                                      *parse_id(inst[i]["instance_id"])[2:]))
        inst = [inst[i] for i in order]
        patches = patches[order]
        feats = feats[order]
        cc = ColumnContext()
        ctx_n = ctx_ok = ctx_sem_ok = pending = 0
        ctx_wrong = []
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
            if branches is not None:
                _, pg, col, idx = parse_id(x["instance_id"])
                cc.record(pg, col, idx, r.char)
        else:
            if r.guard:
                guards[r.guard] += 1
            per_flag.append(None)
            if branches is not None:
                _, pg, col, idx = parse_id(x["instance_id"])
                ocr = branches.topk(x["instance_id"])
                ctx = cc.window(pg, col, idx)
                if r.verdict == "unsure":
                    d = decide_unsure(r, ocr, context=ctx, lm=branches.lm,
                                      semantic_fn=vmap.semantic)
                else:
                    d = decide_diff(ocr, context=ctx, lm=branches.lm,
                                    semantic_fn=vmap.semantic)
                if d.char is not None:
                    cc.record(pg, col, idx, d.char)   # 阈下也当前最优字
                if d.char is not None and d.margin >= branches.threshold:
                    ctx_n += 1
                    c_ok = d.char == x["char"]
                    ctx_ok += c_ok
                    c_sem = c_ok or vmap.semantic(d.char) == vmap.semantic(x["char"])
                    ctx_sem_ok += c_sem
                    if not c_sem:
                        ctx_wrong.append((x["instance_id"], x["char"],
                                          d.char, round(d.margin, 3)))
                else:
                    pending += 1
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
    if branches is not None:
        e2e_n = matched + ctx_n
        report["branches"] = {
            "margin_threshold": branches.threshold,
            "context_n": ctx_n,
            "context_precision": round(ctx_ok / max(1, ctx_n), 4),
            "context_precision_semantic": round(ctx_sem_ok / max(1, ctx_n), 4),
            "context_mismatches": [
                {"id": a, "gold": g, "pred": p, "margin": m}
                for a, g, p, m in ctx_wrong[:20]],
        }
        report["end2end_coverage"] = round(e2e_n / max(1, n), 4)
        report["end2end_precision"] = round(
            (correct + ctx_ok) / max(1, e2e_n), 4)
        report["end2end_precision_semantic"] = round(
            (sem_correct + ctx_sem_ok) / max(1, e2e_n), 4)
        report["pending_ratio"] = round(pending / max(1, n), 4)
    print(f"[{tag}] 覆盖 {matched}/{n}={report['match_coverage']:.1%}  "
          f"字形精度 {report['match_precision']:.4f}  "
          f"语义精度 {report['match_precision_semantic']:.4f}  "
          f"计门精度 {report['match_precision_gated']:.4f}  "
          f"后半段 {report['coverage_second_half']:.1%}  护栏 {guards}")
    if branches is not None:
        print(f"    端到端: 覆盖 {report['end2end_coverage']:.1%} "
              f"(same {matched} + context {ctx_n})  "
              f"精度 {report['end2end_precision']:.4f} "
              f"(语义 {report['end2end_precision_semantic']:.4f})  "
              f"pending {report['pending_ratio']:.1%}  "
              f"context 精度 {report['branches']['context_precision']:.4f} "
              f"@margin>={branches.threshold}")
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
    ap.add_argument("--cov-high", type=float, default=None,
                    help="same 闸（默认跟随判据的库匹配侧标定，两者都是 0.992）")
    ap.add_argument("--miss-wmax", type=float, default=None,
                    help="12×12 窗口残差闸（默认 MISS_WMAX=12）")
    ap.add_argument("--verify-method", default="elastic",
                    choices=["elastic", "coverage"],
                    help="精验判据（默认 elastic=现行；coverage=旧判据对照）")
    ap.add_argument("--out", default=None, help="报告 JSON 路径")
    ap.add_argument("--include-excluded", action="store_true",
                    help="连排除名单里的坏图块一起量（默认跳过）")
    ap.add_argument("--with-branches", action="store_true",
                    help="unsure/diff 走 decide_*，追加端到端三个数（见文件头）")
    ap.add_argument("--margin-threshold", type=float, default=0.99,
                    help="context 准入阈（calibrate_margin.py 标定值，"
                         "2026-08-23 vol02 册内：0.99）")
    ap.add_argument("--ocr-cache", default=None,
                    help="calibrate_margin 的 OCR top-k 缓存 jsonl（可逗号分隔多个）；"
                         "缓存没有的实例退化用 --carrier-tmpl 的 top1")
    ap.add_argument("--carrier-tmpl",
                    default="output/{book}/phase4_chars/ocr_carrier.jsonl")
    ap.add_argument("--corpus", default="corpus/zongmu_wuyingdian_reference.txt",
                    help="--with-branches 的 LM 语料（本书整理本）")
    args = ap.parse_args()

    branches = None
    if args.with_branches:
        from open_guji_cv.clustering.lm import CharNgramLM
        vm = VariantMap.load()
        lm = CharNgramLM(order=3)
        text = Path(args.corpus).read_text(encoding="utf-8")
        lm.train([vm.normalize_text(s) for s in text.splitlines() if s.strip()])
        cache_paths = [Path(p) for p in args.ocr_cache.split(",")] \
            if args.ocr_cache else []
        branches = BranchConfig(args.margin_threshold, lm, vm,
                                cache_paths, args.carrier_tmpl)

    samples = Path(args.dataset) / "samples"
    wmax_kw = {} if args.miss_wmax is None else {"miss_wmax": args.miss_wmax}
    reports = []

    if args.protocol in ("incremental", "all"):
        for shard in args.shards.split(","):
            inst, patches = load_shard(samples, shard, args.include_excluded)
            m = GlyphMatcher(k=args.k, verify_method=args.verify_method,
                             cov_high=args.cov_high, **wmax_kw)
            feats = m.extract(patches)
            reports.append(run(m, inst, patches, feats, f"incremental/{shard}",
                               branches=branches))

    if args.protocol in ("cross-seed", "all"):
        si, sp = load_shard(samples, args.seed_shard, args.include_excluded)
        qi, qp = load_shard(samples, args.query_shard, args.include_excluded)
        m = GlyphMatcher(k=args.k, verify_method=args.verify_method,
                         cov_high=args.cov_high, **wmax_kw)
        sf = m.extract(sp)
        qf = m.extract(qp)
        for i, x in enumerate(si):
            m.add(x["instance_id"], x["char"], sp[i], feat=sf[i])
        reports.append(run(m, qi, qp, qf,
                           f"cross-seed/{args.query_shard}|db={args.seed_shard}",
                           branches=branches))

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
