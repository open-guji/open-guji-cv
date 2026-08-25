# -*- coding: utf-8 -*-
"""匹配判据的**操作点**基准（glyph-match/pairs）。

    PYTHONPATH=. python scripts/eval_match_pairs.py ../open-guji-dataset/glyph-match/pairs
    # 换判据对照 / 存分数供反复扫阈值：
    PYTHONPATH=. python scripts/eval_match_pairs.py <集> --method coverage
    PYTHONPATH=. python scripts/eval_match_pairs.py <集> --dump scores.npz
    PYTHONPATH=. python scripts/eval_match_pairs.py <集> --from-dump scores.npz

triplets 量排序，本集量**阈值**：在硬约束 `precision ≥ 0.999` 下，闸能
放行多少真同字对。主输出就是这一条——**硬约束下的最大 recall 与对应
闸值**，外加 PR 曲线和分层。

## 两条读数纪律

1. **precision 依赖同异字先验，三个来源绝不能混着报。** `knn` 是生产真
   去验的对群（headline 看它），`random` 是与特征无关的无偏层，
   `near_form` 是形近硬负例——它们的先验差着数量级，合起来的 precision
   没有任何意义。
2. **比值必须连分母一起读。** precision 从 1.0 掉到 0.998 可能不是退步，
   是放行的对多了。所以每个数都带分子分母。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.exclusions import excluded_ids  # noqa: E402
from open_guji_cv.clustering.verify import (COV_LOW, ELASTIC_COV_HIGH,  # noqa: E402
                                            MISS_WMAX, verify_pair,
                                            verify_pair_cov,
                                            verify_pair_elastic)

VERIFY = {"elastic": verify_pair_elastic, "coverage": verify_pair_cov,
          "overlap": verify_pair}
PRECISION_FLOOR = 0.999      # 硬约束：错标进库会沿簇批量扩散
SWEEP = np.round(np.arange(0.95, 1.0005, 0.0005), 4)


def score_all(root: Path, method: str) -> tuple[list[dict], np.ndarray, np.ndarray]:
    data = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    pats: dict[str, np.ndarray] = {}
    for r in data["instances"]:
        img = cv2.imread(str(root / r["crop"]), cv2.IMREAD_GRAYSCALE)
        pats[r["instance_id"]] = (img > 127).astype(np.uint8)
    meta = {r["instance_id"]: r for r in data["instances"]}
    pairs = [json.loads(l) for l in
             (root / data["pairs_file"]).read_text(encoding="utf-8").splitlines()]
    verify = VERIFY[method]
    cov = np.empty(len(pairs))
    wmax = np.empty(len(pairs))
    for k, p in enumerate(pairs):
        v = verify(pats[p["a"]], pats[p["b"]])
        cov[k], wmax[k] = v.f1, v.diff_blob_ratio
        p["ink_bucket"] = max(meta[p["a"]]["ink_bucket"],
                              meta[p["b"]]["ink_bucket"])
        p["tier"] = ("degraded" if "degraded" in
                     (meta[p["a"]]["tier"], meta[p["b"]]["tier"]) else "clean")
        if k % 10000 == 0:
            print(f"  {k}/{len(pairs)}", flush=True)
    return pairs, cov, wmax


def relabel(root: Path, cached: list[dict]) -> list[dict]:
    """拿数据集现在的金标重算 dump 里每一对的 label 与分层，顺序必须对上。"""
    data = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    meta = {r["instance_id"]: r for r in data["instances"]}
    fresh = [json.loads(l) for l in
             (root / data["pairs_file"]).read_text(encoding="utf-8").splitlines()]
    if len(fresh) != len(cached) or any(
            f["a"] != c["a"] or f["b"] != c["b"] for f, c in zip(fresh, cached)):
        raise SystemExit("dump 与数据集的对序对不上——重新打分（去掉 --from-dump）")
    for p in fresh:
        p["label"] = ("same" if meta[p["a"]]["char"] == meta[p["b"]]["char"]
                      else "diff")
        p["ink_bucket"] = max(meta[p["a"]]["ink_bucket"], meta[p["b"]]["ink_bucket"])
        p["tier"] = ("degraded" if "degraded" in
                     (meta[p["a"]]["tier"], meta[p["b"]]["tier"]) else "clean")
    return fresh


def pr(is_same: np.ndarray, passed: np.ndarray
       ) -> tuple[int, int, int, float | None, float | None]:
    """→ (tp, fp, 同字对总数, precision, recall)。

    分母为 0 时返回 None 而不是 0.0——一个都没放行时 precision 是**无定义**，
    印成 0.0000 会被读成「全错」；同理没有同字对时 recall 无定义。
    """
    tp = int((passed & is_same).sum())
    fp = int((passed & ~is_same).sum())
    pos = int(is_same.sum())
    return (tp, fp, pos,
            (tp / (tp + fp)) if tp + fp else None,
            (tp / pos) if pos else None)


def fmt(v: float | None) -> str:
    return "  —   " if v is None else f"{v:.4f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--method", default="elastic", choices=list(VERIFY))
    ap.add_argument("--cov-high", type=float, default=None)
    ap.add_argument("--miss-wmax", type=float, default=MISS_WMAX)
    ap.add_argument("--dump", default=None, help="把逐对分数存成 npz")
    ap.add_argument("--from-dump", default=None, help="跳过打分，直接读 npz")
    ap.add_argument("--out", default=None, help="报告 JSON")
    ap.add_argument("--include-excluded", action="store_true",
                    help="连排除名单里的坏图块一起量（默认跳过）")
    args = ap.parse_args()
    root = Path(args.dataset)
    gate = args.cov_high if args.cov_high is not None else ELASTIC_COV_HIGH

    if args.from_dump:
        z = np.load(args.from_dump, allow_pickle=True)
        cov, wmax = z["cov"], z["wmax"]
        # dump 只是**分数**缓存。标签和分层一律从数据集现读——金标改判过
        # （relabel_history）而缓存里还压着旧 label 的话，报出来的
        # precision/recall 是错的，而且错得无声无息。
        pairs = relabel(Path(args.dataset), list(z["pairs"]))
    else:
        pairs, cov, wmax = score_all(root, args.method)
        if args.dump:
            np.savez_compressed(args.dump, pairs=np.array(pairs, dtype=object),
                                cov=cov, wmax=wmax)
            print(f"→ 分数已存 {args.dump}")

    report: dict = {"method": args.method, "cov_high": gate,
                    "miss_wmax": args.miss_wmax, "n_pairs": len(pairs)}

    # 排除名单：切分坏掉的图块不参与量匹配——不然量的是「匹配 + 切分损伤」
    # 的混合物。默认跳过，`--include-excluded` 可以把旧口径量回来对照。
    ex = frozenset() if args.include_excluded else excluded_ids()
    keep = np.array([p["a"] not in ex and p["b"] not in ex for p in pairs])
    n_drop = int((~keep).sum())
    if n_drop:
        pairs = [p for p, k in zip(pairs, keep) if k]
        cov, wmax = cov[keep], wmax[keep]
        print(f"排除名单跳过 {n_drop} 对（{n_drop/len(keep):.1%}），"
              f"剩 {len(pairs)} 对参与评测")
    report["n_pairs_excluded"] = n_drop
    report["n_pairs"] = len(pairs)

    is_same = np.array([p["label"] == "same" for p in pairs])
    origin = np.array([p["origin"] for p in pairs])
    print(f"\n=== 判据 {args.method}  操作点 cov≥{gate} & wmax≤{args.miss_wmax} ===")
    passed = (cov >= gate) & (wmax <= args.miss_wmax)
    for og in sorted(set(origin.tolist())):
        m = origin == og
        tp, fp, pos, p_, r_ = pr(is_same[m], passed[m])
        print(f"  [{og:<9}] precision {fmt(p_)} ({tp}/{tp+fp})   "
              f"recall {fmt(r_)} ({tp}/{pos})")
        report[og] = {"precision": p_ and round(p_, 5), "tp": tp, "fp": fp,
                      "recall": r_ and round(r_, 5), "n_same": pos}

    # 主输出：硬约束下的最大 recall（在 knn 层上定——那是生产的先验）
    m = origin == "knn"
    best = None
    for g in SWEEP:
        ok = (cov >= g) & (wmax <= args.miss_wmax)
        tp, fp, pos, p_, r_ = pr(is_same[m], ok[m])
        if p_ is not None and p_ >= PRECISION_FLOOR and r_ is not None \
                and (best is None or r_ > best[2]):
            best = (float(g), p_, r_, tp, fp, pos)
    if best:
        g, p_, r_, tp, fp, pos = best
        print(f"\n主指标 · knn 层 precision ≥ {PRECISION_FLOOR} 下的最大 recall："
              f"\n  闸 {g}  →  precision {p_:.5f} ({tp}/{tp+fp})   "
              f"recall {r_:.4f} ({tp}/{pos})")
        report["best_operating_point"] = {
            "cov_high": g, "precision": round(p_, 5), "recall": round(r_, 5),
            "tp": tp, "fp": fp, "n_same": pos}
    else:
        print(f"\n主指标：扫遍 {SWEEP[0]}~{SWEEP[-1]} 都达不到 "
              f"precision ≥ {PRECISION_FLOOR}")
        report["best_operating_point"] = None

    # 分层（只在 knn 层内分，别跨来源合）
    for key in ("ink_bucket", "tier", "book"):
        print(f"\n  分层 {key}（knn 层，操作点 {gate}）")
        rows: dict[str, list] = defaultdict(list)
        for k, p in enumerate(pairs):
            if p["origin"] == "knn":
                rows[p[key]].append(k)
        sub = {}
        for name, idx in sorted(rows.items()):
            ii = np.array(idx)
            tp, fp, pos, p_, r_ = pr(is_same[ii], passed[ii])
            print(f"    {name:<12} precision {fmt(p_)} ({tp}/{tp+fp})   "
                  f"recall {fmt(r_)} ({tp}/{pos})")
            sub[name] = {"precision": p_ and round(p_, 5),
                         "recall": r_ and round(r_, 5),
                         "tp": tp, "fp": fp, "n_same": pos}
        report[f"by_{key}"] = sub

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
