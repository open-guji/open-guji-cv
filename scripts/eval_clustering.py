"""保守聚类 purity benchmark（open-guji-dataset/char-clustering）。

两种模式：

- **默认（冻结模式）**：在数据集里冻结的归一图上重跑一次聚类。归一化改了也
  不影响这个数——它量的是聚类本身。
- `--clusters <clusters.json>`（端到端模式）：直接给管线跑全书的产物打分，
  只取分片里那些实例。归一化改动会反映进来，但要求 `pipeline_version`
  与建集时一致，否则实例编号已经漂了（脚本会报出对不上的个数）。

    python scripts/eval_clustering.py ../open-guji-dataset/char-clustering
    python scripts/eval_clustering.py ../open-guji-dataset/char-clustering \\
        --shard 001-vol01-body --clusters output/vol01/phase5_clusters/clusters.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.cluster_eval import evaluate, format_report
from open_guji_cv.clustering.clusterer import (ClusterParams,
                                               ConservativeClusterer,
                                               has_through_vline)
from open_guji_cv.clustering.features import get_feature


def load_shard(shard_dir: Path) -> dict:
    return json.loads((shard_dir / "expected.json").read_text(encoding="utf-8"))


def cluster_frozen(shard_dir: Path, data: dict, params: ClusterParams
                   ) -> dict[str, str]:
    """在冻结的归一图上跑聚类，返回 实例 → 簇 id。"""
    instances = data["instances"]
    n = len(instances)
    patches = np.zeros((n, 64, 64), dtype=np.uint8)
    hw = np.ones(n, dtype=np.float64)
    ink = np.zeros(n, dtype=np.float64)
    for i, inst in enumerate(instances):
        img = cv2.imread(str(shard_dir / inst["crop"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(shard_dir / inst["crop"])
        patches[i] = (img > 127).astype(np.uint8)
        hw[i] = inst.get("hw_ratio", 1.0)
        ink[i] = inst.get("ink_ratio", 0.0)

    feats = get_feature(params.feature).extract(patches)
    quarantine = np.array([has_through_vline(p) for p in patches])
    result = ConservativeClusterer(params).cluster(patches, feats, hw, ink,
                                                   quarantine=quarantine)
    return {instances[m]["instance_id"]: c.cluster_id
            for c in result.clusters for m in c.members}


def cluster_from_pipeline(path: Path, data: dict) -> tuple[dict[str, str], int]:
    """读管线产物 clusters.json，只留分片里的实例。返回 (映射, 缺失数)。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    want = {i["instance_id"] for i in data["instances"]}
    out = {m: c["cluster_id"] for c in payload["clusters"] for m in c["members"]
           if m in want}
    return out, len(want - set(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="char-clustering 数据集目录")
    ap.add_argument("--shard", default=None, help="只跑这个分片（默认全部）")
    ap.add_argument("--clusters", default=None,
                    help="端到端模式：管线的 phase5_clusters/clusters.json")
    ap.add_argument("--feature", default=None, help="覆盖分片记录的特征后端")
    ap.add_argument("--theta-high", type=float, default=None)
    ap.add_argument("--out", default=None, help="报告 JSON 路径")
    args = ap.parse_args()

    samples = Path(args.dataset) / "samples"
    shards = ([samples / args.shard] if args.shard else
              sorted(p for p in samples.iterdir()
                     if p.is_dir() and (p / "crops").is_dir()))
    if not shards:
        print("没有可评的分片（crops/ 缺失）")
        return

    report = {"mode": "pipeline" if args.clusters else "frozen", "shards": {}}
    for shard_dir in shards:
        data = load_shard(shard_dir)
        params = ClusterParams(feature=args.feature or data.get("feature_backend", "hog"))
        if args.theta_high is not None:
            params.theta_high = args.theta_high

        if args.clusters:
            assignment, missing = cluster_from_pipeline(Path(args.clusters), data)
            if missing:
                print(f"[{shard_dir.name}] 管线产物里找不到 {missing} 个实例"
                      f"——上游重跑过、编号已漂，端到端数字仅供参考")
        else:
            assignment = cluster_frozen(shard_dir, data, params)

        r = evaluate(assignment, data["instances"], data.get("hard_pairs", []))
        r["params"] = params.to_dict()
        r["pipeline_version_at_build"] = data.get("pipeline_version")
        report["shards"][shard_dir.name] = r
        print(format_report(shard_dir.name, r))
        print()

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"→ {args.out}")


if __name__ == "__main__":
    main()
