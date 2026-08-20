"""benchmark 运行器：合成数据集上评测各模块，输出统一 JSON 报告。

报告格式：{module, params, dataset, metrics, elapsed_s, git_commit, timestamp}
追加存入 benchmarks/results/，用于跟踪算法/参数改动的指标变化。
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def write_report(report: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"{report['module']}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


def bench_verify(n_chars: int = 30, n_per_char: int = 4, wear: float = 0.5,
                 seed: int = 0) -> dict:
    """verify_pair 的分离度与吞吐：same 对 / diff 对的 f1 分布。"""
    from .synth import make_dataset
    from .verify import verify_pair

    patches, labels = make_dataset(n_chars, n_per_char, seed=seed, wear=wear)
    rng = np.random.default_rng(seed)

    same_pairs, diff_pairs = [], []
    for lab in range(n_chars):
        idx = np.nonzero(labels == lab)[0]
        for i in range(len(idx) - 1):
            same_pairs.append((idx[i], idx[i + 1]))
    while len(diff_pairs) < len(same_pairs):
        a, b = rng.integers(0, len(patches), 2)
        if labels[a] != labels[b]:
            diff_pairs.append((int(a), int(b)))

    t0 = time.perf_counter()
    same_scores = [verify_pair(patches[a], patches[b]).f1 for a, b in same_pairs]
    diff_scores = [verify_pair(patches[a], patches[b]).f1 for a, b in diff_pairs]
    elapsed = time.perf_counter() - t0
    n_calls = len(same_pairs) + len(diff_pairs)

    same_verdicts = sum(
        1 for a, b in same_pairs
        if verify_pair(patches[a], patches[b]).verdict == "same")
    false_same = sum(
        1 for a, b in diff_pairs
        if verify_pair(patches[a], patches[b]).verdict == "same")

    return {
        "module": "verify",
        "params": {"wear": wear, "seed": seed},
        "dataset": {"n_chars": n_chars, "n_per_char": n_per_char,
                    "n_pairs": n_calls},
        "metrics": {
            "same_f1_mean": round(float(np.mean(same_scores)), 4),
            "same_f1_p10": round(float(np.percentile(same_scores, 10)), 4),
            "diff_f1_mean": round(float(np.mean(diff_scores)), 4),
            "diff_f1_p90": round(float(np.percentile(diff_scores, 90)), 4),
            "same_recall": round(same_verdicts / len(same_pairs), 4),
            "false_same": false_same,          # 硬指标：必须为 0
            "pairs_per_sec": round(n_calls / elapsed, 1),
        },
        "elapsed_s": round(elapsed, 3),
        "git_commit": _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def bench_cluster(n_chars: int = 50, n_per_char: int = 10, wear: float = 0.5,
                  feature: str = "hog", seed: int = 0) -> dict:
    """端到端聚类：纯度（硬指标）/ 碎片率 / 吞吐。"""
    from .clusterer import ClusterParams, ConservativeClusterer
    from .features import get_feature
    from .synth import fragmentation, make_dataset, purity

    patches, labels = make_dataset(n_chars, n_per_char, seed=seed, wear=wear)
    feats = get_feature(feature).extract(patches)
    hw = np.ones(len(patches))
    ink = np.array([p.mean() for p in patches])

    params = ClusterParams(feature=feature)
    t0 = time.perf_counter()
    result = ConservativeClusterer(params).cluster(patches, feats, hw, ink)
    elapsed = time.perf_counter() - t0

    members = [c.members for c in result.clusters]
    return {
        "module": "cluster",
        "params": params.to_dict(),
        "dataset": {"n_chars": n_chars, "n_per_char": n_per_char,
                    "wear": wear, "n_instances": len(patches)},
        "metrics": {
            "purity": round(purity(members, labels), 5),      # 硬指标 ≥ 0.999
            "fragmentation": round(fragmentation(members, labels), 3),
            "n_clusters": len(result.clusters),
            "singleton_ratio": result.stats["singleton_ratio"],
            "n_verify_calls": result.n_verify_calls,
            "instances_per_sec": round(len(patches) / elapsed, 1),
        },
        "elapsed_s": round(elapsed, 3),
        "git_commit": _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


BENCHES = {"verify": bench_verify, "cluster": bench_cluster}
