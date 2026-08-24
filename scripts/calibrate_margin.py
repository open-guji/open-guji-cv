"""context-margin 准入阈标定（glyph_db_first_design.md §3：context provenance）。

设计 §3 规定：上下文裁决的结果要以 `context` provenance 进库，条件是
margin ≥ 阈——本脚本把这个阈标出来。context-correction 集目前还是空
框架，所以直接在 char-clustering 金标分片上做（金标已知，正好量
「裁决字 == 金标」）：

**协议**：沿 eval_db_match 的册内增量协议跑 002-vol02-body（每实例
先匹配、后带金标进库 = 库上界）；same 档照旧继承；每个 unsure/diff
档实例跑 recognize_flow.decide_*，得 (margin, 裁决字==金标) 对。
处理顺序取**阅读顺序**（页→列→列内 idx）——上下文窗口要求前文已定，
eval_db_match 原有的 (page, instance_id) 字符串序会把 idx=10 排在
idx=2 前面，窗口会漏字。

**OCR**：RapidOcrSource.rec_topk 对**原始灰度图块**跑真 top-k
（分片里只有归一图）。原图块从 pipeline 产物取：materialize_rev(
PIPELINE_REV) 铺出该版 phase4（/tmp 缓存），instance_id 对回
index.jsonl 的 patch_path。结果缓存到 scratchpad jsonl，可断点续跑；
图块缺失/识别为空时退化用 ocr_carrier.jsonl 的现成 top1 兜底。

**LM 语料的循环性（照用，但记在案）**：corpus/zongmu_wuyingdian_
reference.txt 是整理本全书文本，而分片金标本来就是整理本对齐产出的
——LM「见过」正确答案所在的句子。这是既有事实（对齐标注与 LM 共享
同一整理本是这套流程的设计），影响范围：本脚本量出的 margin-精度
曲线对「有同书整理本语料」的场景（前 11 册都有）是如实的；对**没有**
整理本的新书，LM 只能用通用语料，margin 的分离度会变差，届时阈值
需要在 context-correction 集上重标——本脚本输出的阈值只应用于
有本书语料的配置。

**margin 两种定义的对比**（recognize_flow.Decision 采用 softmax 概率
差）：本脚本同时报概率差与对数比 log(p1/p2) 两条曲线（各自在
精度 ≥0.999 下能拿到的最大覆盖 + 秩相关），用数据支撑 docstring 里
的选择。

单进程（4 核机器，onnxruntime 内部已并行，多进程互踩反而慢）。

    ./venv/bin/python scripts/calibrate_margin.py \
        ../open-guji-dataset/char-clustering
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SCRATCH = Path("/tmp/claude-0/-home-user-open-guji-cv/"
               "601db0f8-3aac-51ba-9e83-49d1f06c4bda/scratchpad")

PRECISION_GATE = 0.999          # 设计 §3：context provenance 的准入精度线
THRESH_GRID = [round(t * 0.05, 2) for t in range(20)] + [0.99]


# ── OCR top-k：跑真 top-k，缓存 + 断点续跑 ─────────────────────────

def build_topk_cache(instance_ids: list[str], cache_path: Path,
                     pipeline_rev: str, book: str,
                     carrier_path: Path | None, topk: int) -> dict[str, list]:
    """instance_id → [(char, prob)]（原始 OCR 输出，s2t 交 decide_* 做）。"""
    cache: dict[str, list] = {}
    if cache_path.exists():                       # 断点续跑
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["id"]] = [tuple(t) for t in r["topk"]]
    todo = [i for i in instance_ids if i not in cache]
    if not todo:
        return cache

    import cv2
    from build_clustering_dataset import materialize_rev
    from open_guji_cv.clustering.candidates import RapidOcrSource

    output_root = materialize_rev(pipeline_rev)
    patch_of: dict[str, str] = {}
    with open(output_root / book / "phase4_chars" / "index.jsonl",
              encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                patch_of[r["id"]] = str(
                    output_root / book / "phase4_chars" / r["patch_path"])

    carrier: dict[str, tuple[str, float]] = {}
    if carrier_path and carrier_path.exists():
        for line in carrier_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("char"):
                    carrier[r["id"]] = (r["char"], float(r.get("prob", 0.0)))

    src = RapidOcrSource(topk=topk)
    src._ensure()
    n_carrier = 0
    print(f"OCR top-{topk}: 待跑 {len(todo)}（缓存已有 {len(cache)}）",
          flush=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "a", encoding="utf-8") as f:
        for n, iid in enumerate(todo, 1):
            rows: list[tuple[str, float]] = []
            src_tag = "rec_topk"
            p = patch_of.get(iid)
            gray = cv2.imread(p, 0) if p else None
            if gray is not None:
                rows = src.rec_topk(gray)
            if not rows and iid in carrier:       # 兜底：载体现成 top1
                rows = [carrier[iid]]
                src_tag = "carrier"
                n_carrier += 1
            cache[iid] = rows
            f.write(json.dumps(
                {"id": iid, "topk": [[c, round(pr, 4)] for c, pr in rows],
                 "src": src_tag}, ensure_ascii=False) + "\n")
            if n % 500 == 0:
                f.flush()
                print(f"  {n}/{len(todo)}", flush=True)
    if n_carrier:
        print(f"  载体兜底 {n_carrier} 块")
    return cache


# ── 曲线与阈值 ─────────────────────────────────────────────────────

def curve(samples: list[dict], key: str, grid: list[float]) -> list[dict]:
    """阈上（margin ≥ t）累计 覆盖/精度 曲线。准入是「阈上全收」，
    所以推荐阈要看累计精度；分桶表另报（看分布形状）。"""
    n = len(samples)
    out = []
    for t in grid:
        sel = [s for s in samples if s[key] >= t]
        if not sel:
            out.append({"threshold": t, "n": 0, "coverage": 0.0,
                        "precision": None, "precision_gated": None})
            continue
        ok = sum(s["correct"] for s in sel)
        gated = sum(s["correct"] or s["known_issue"] or s["sem_correct"]
                    for s in sel)
        out.append({"threshold": t, "n": len(sel),
                    "coverage": round(len(sel) / max(1, n), 4),
                    "precision": round(ok / len(sel), 4),
                    "precision_gated": round(gated / len(sel), 4)})
    return out


def buckets(samples: list[dict], key: str, width: float = 0.1) -> list[dict]:
    out = []
    lo = 0.0
    while lo < 1.0 - 1e-9:
        hi = round(lo + width, 2)
        sel = [s for s in samples
               if lo <= s[key] < hi or (hi >= 1.0 and s[key] >= lo)]
        out.append({"bucket": f"[{lo:.1f},{hi:.1f}{']' if hi >= 1.0 else ')'}",
                    "n": len(sel),
                    "precision": round(sum(s["correct"] for s in sel)
                                       / len(sel), 4) if sel else None})
        lo = hi
    return out


def recommend(cur: list[dict], gate: float = PRECISION_GATE):
    """最低的、阈上累计计门精度 ≥ gate 的阈（阈上全收的准入语义）。"""
    for row in cur:
        if row["n"] and row["precision_gated"] is not None \
                and row["precision_gated"] >= gate:
            return row["threshold"]
    return None


def spearman(xs: list[float], ys: list[float]) -> float:
    """两种 margin 定义的秩相关（够粗，只为报告单调一致性）。"""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for k, i in enumerate(order):
            r[i] = k
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    if n < 2:
        return 1.0
    mx = my = (n - 1) / 2
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx)
           * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 1.0


# ── 主流程 ─────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", nargs="?",
                    default="../open-guji-dataset/char-clustering")
    ap.add_argument("--shard", default="002-vol02-body")
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--pipeline-rev", default=None,
                    help="默认取 build_clustering_dataset.PIPELINE_REV")
    ap.add_argument("--corpus",
                    default="corpus/zongmu_wuyingdian_reference.txt")
    ap.add_argument("--carrier",
                    default="output/vol02/phase4_chars/ocr_carrier.jsonl")
    ap.add_argument("--cache", default=str(SCRATCH / "ocr_topk_vol02.jsonl"))
    ap.add_argument("--out", default=str(SCRATCH / "margin_calibration.json"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--topk", type=int, default=5)
    args = ap.parse_args()

    from build_clustering_dataset import PIPELINE_REV
    from eval_db_match import KNOWN_GOLD_ISSUES, load_shard
    from open_guji_cv.clustering.ids import parse_id
    from open_guji_cv.clustering.lm import CharNgramLM
    from open_guji_cv.clustering.match import GlyphMatcher
    from open_guji_cv.clustering.recognize_flow import (ColumnContext,
                                                       decide_diff,
                                                       decide_unsure)
    from open_guji_cv.clustering.variants import VariantMap

    rev = args.pipeline_rev or PIPELINE_REV
    samples_dir = Path(args.dataset) / "samples"
    inst, patches = load_shard(samples_dir, args.shard)
    # 阅读顺序重排（页→列→idx），上下文窗口才拿得到真前文
    order = sorted(range(len(inst)),
                   key=lambda i: (int(inst[i]["page"]),
                                  *parse_id(inst[i]["instance_id"])[2:]))
    inst = [inst[i] for i in order]
    patches = patches[order]

    topk_cache = build_topk_cache(
        [x["instance_id"] for x in inst], Path(args.cache), rev, args.book,
        Path(args.carrier) if args.carrier else None, args.topk)

    vmap = VariantMap.load()
    text = Path(args.corpus).read_text(encoding="utf-8")
    lm = CharNgramLM(order=3)
    lm.train([vmap.normalize_text(s) for s in text.splitlines() if s.strip()])
    print(f"LM: {len(lm.vocab)} 词表（语料 {len(text)} 字符）", flush=True)

    matcher = GlyphMatcher(k=args.k)
    feats = matcher.extract(patches)
    cc = ColumnContext()
    same_n = same_ok = 0
    branch_samples: list[dict] = []
    n = len(inst)
    for i, x in enumerate(inst):
        iid = x["instance_id"]
        _, page, col, idx = parse_id(iid)
        r = matcher.match(patches[i], feat=feats[i])
        if r.verdict == "same":
            same_n += 1
            same_ok += r.char == x["char"]
            cc.record(page, col, idx, r.char)
        else:
            ctx = cc.window(page, col, idx)
            ocr = topk_cache.get(iid, [])
            if r.verdict == "unsure":
                d = decide_unsure(r, ocr, context=ctx, lm=lm,
                                  semantic_fn=vmap.semantic)
            else:
                d = decide_diff(ocr, context=ctx, lm=lm,
                                semantic_fn=vmap.semantic)
            if d.char is not None:
                cc.record(page, col, idx, d.char)
                p1 = d.ranked[0][1]
                p2 = d.ranked[1][1] if len(d.ranked) > 1 else 1e-9
                branch_samples.append({
                    "id": iid, "branch": d.branch, "guard": r.guard,
                    "pred": d.char, "gold": x["char"],
                    "correct": d.char == x["char"],
                    "sem_correct": vmap.semantic(d.char)
                                   == vmap.semantic(x["char"]),
                    "known_issue": iid in KNOWN_GOLD_ISSUES,
                    "margin": round(d.margin, 4),
                    "margin_lr": round(min(50.0, math.log(
                        max(p1, 1e-9) / max(p2, 1e-9))), 4),
                    "used_context": d.used_context})
            else:
                branch_samples.append({
                    "id": iid, "branch": d.branch, "guard": r.guard,
                    "pred": None, "gold": x["char"], "correct": False,
                    "sem_correct": False, "known_issue": False,
                    "margin": 0.0, "margin_lr": 0.0, "used_context": False})
        matcher.add(iid, x["char"], patches[i], feat=feats[i])
        if (i + 1) % 500 == 0:
            print(f"  [{i + 1}/{n}] same {same_n} "
                  f"分支 {len(branch_samples)}", flush=True)

    # ── 汇总 ──
    by_branch = {}
    for br in ("unsure", "diff"):
        sel = [s for s in branch_samples if s["branch"] == br]
        dec = [s for s in sel if s["pred"] is not None]
        by_branch[br] = {
            "n": len(sel), "n_decided": len(dec),
            "top1_acc": round(sum(s["correct"] for s in dec)
                              / len(dec), 4) if dec else None,
            "top1_acc_semantic": round(sum(s["sem_correct"] for s in dec)
                                       / len(dec), 4) if dec else None,
            "with_context": sum(s["used_context"] for s in sel)}
    decided = [s for s in branch_samples if s["pred"] is not None]
    cur = curve(decided, "margin", THRESH_GRID)
    rec = recommend(cur)
    # margin 两定义对比：对数比曲线 + 秩相关 + 各自 gate 下最大覆盖
    lr_grid = sorted({round(s["margin_lr"], 1) for s in decided})
    cur_lr = curve(decided, "margin_lr", lr_grid[::max(1, len(lr_grid) // 25)])
    rec_lr = recommend(cur_lr)
    cov_at = lambda c, t: next((r["coverage"] for r in c
                                if r["threshold"] == t), 0.0)
    rho = spearman([s["margin"] for s in decided],
                   [s["margin_lr"] for s in decided])

    report = {
        "protocol": f"incremental/{args.shard} (库=金标进库上界, "
                    f"阅读顺序, rev={rev})",
        "precision_gate": PRECISION_GATE,
        "same": {"n": same_n, "precision": round(same_ok / max(1, same_n), 4),
                 "coverage": round(same_n / n, 4)},
        "branches": by_branch,
        "margin_curve": cur,
        "margin_buckets": buckets(decided, "margin"),
        "recommended_threshold": rec,
        "margin_lr_comparison": {
            "curve": cur_lr, "recommended_threshold_lr": rec_lr,
            "spearman_vs_margin": round(rho, 4),
            "coverage_at_gate": {
                "margin": cov_at(cur, rec) if rec is not None else 0.0,
                "margin_lr": cov_at(cur_lr, rec_lr)
                             if rec_lr is not None else 0.0}},
        "circularity_note": "LM 语料 = 整理本全书文本，金标即整理本对齐产"
                            "出——曲线只对「有本书整理本语料」的配置有效，"
                            "见文件头。",
        "known_gold_issues_hit": [s["id"] for s in decided
                                  if s["known_issue"]],
        "samples": branch_samples,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    print(f"\nsame 档: 覆盖 {report['same']['coverage']:.1%} "
          f"精度 {report['same']['precision']:.4f}")
    for br, st in by_branch.items():
        print(f"{br} 档: n={st['n']} 已裁决 {st['n_decided']} "
              f"top1 {st['top1_acc']} (语义 {st['top1_acc_semantic']}) "
              f"有上下文 {st['with_context']}")
    print(f"\nmargin 阈上累计曲线（gate={PRECISION_GATE}）:")
    print("  阈值   n     覆盖     精度    计门精度")
    for row in cur:
        if row["n"]:
            print(f"  {row['threshold']:.2f} {row['n']:5d} "
                  f"{row['coverage']:7.1%}  {row['precision']:.4f}  "
                  f"{row['precision_gated']:.4f}")
    print("\nmargin 分桶:")
    for b in buckets(decided, "margin"):
        if b["n"]:
            print(f"  {b['bucket']:12s} n={b['n']:5d} 精度 {b['precision']}")
    print(f"\n推荐准入阈 margin >= {rec}  "
          f"(对数比定义: lr >= {rec_lr}, 秩相关 {rho:.4f}, "
          f"gate 下覆盖 margin {report['margin_lr_comparison']['coverage_at_gate']['margin']:.1%}"
          f" vs lr {report['margin_lr_comparison']['coverage_at_gate']['margin_lr']:.1%})")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
