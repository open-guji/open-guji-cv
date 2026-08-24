# -*- coding: utf-8 -*-
"""匹配三元组基准：同字形必须比形近异字更匹配。

    PYTHONPATH=. python scripts/eval_match_triplets.py \
        ../open-guji-dataset/glyph-match/triplets

对每个三元组 (anchor, same, other)：patch → normalize_patch →
verify_pair_cov 两侧，判 cov(anchor,same) > cov(anchor,other)。
报各子集排序正确率与平均 margin（cov_same - cov_other）。

- **hard**：构建时算法的已知失败（体检 rival 旗 + 人工白名单确认），
  基线≈0 是设计使然，这个数就是匹配算法优化的靶子；
- **control**：良例抽样，**不得回退**——为修 hard 把 control 改坏
  是净亏。
改归一化/特征/verify 任何一层后都该跑一遍。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_cov  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="glyph-match/triplets 目录")
    ap.add_argument("--report", action="store_true",
                    help="逐条输出（排查用）")
    args = ap.parse_args()
    root = Path(args.dataset)
    triplets = json.loads((root / "expected.json").read_text(encoding="utf-8"))

    norms: dict[str, np.ndarray] = {}

    def norm_of(iid: str) -> np.ndarray:
        if iid not in norms:
            p = root / "patches" / (iid.replace(":", "_") + ".png")
            gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            norms[iid] = normalize_patch(gray)
        return norms[iid]

    stats: dict[str, dict] = {}
    for t in triplets:
        a = norm_of(t["anchor"])
        cs = float(verify_pair_cov(a, norm_of(t["same"])).f1)
        co = float(verify_pair_cov(a, norm_of(t["other"])).f1)
        s = stats.setdefault(t["subset"], {"n": 0, "correct": 0, "margins": []})
        s["n"] += 1
        s["correct"] += int(cs > co)
        s["margins"].append(cs - co)
        if args.report:
            mark = "✓" if cs > co else "✗"
            print(f'{mark} {t["subset"]:<8} {t["anchor"]:<15} '
                  f'「{t["char"]}」same {cs:.3f} vs '
                  f'「{t["other_char"]}」other {co:.3f}')

    out = {}
    for sub, s in sorted(stats.items()):
        out[sub] = {
            "n": s["n"],
            "rank_acc": round(s["correct"] / s["n"], 4),
            "mean_margin": round(float(np.mean(s["margins"])), 4),
        }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
