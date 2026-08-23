"""归一化 golden 回归（char-normalization 数据集的指标层）。

归一化是**纯函数**：同一张图块进去必须得到同一张图出来。所以这一层不是
排行榜，是**回归门**——任一样本超出容差即判失败。

三个指标各管一件事，缺一件就会有一类回归漏网：

| 指标 | 抓什么 | 为什么单看别的不行 |
|---|---|---|
| `pixel_diff_ratio` | 任何像素级改动 | —— |
| `binary_iou` | 墨迹整体位置/大小 | 抗锯齿边缘差几个像素不该判失败 |
| `skeleton_endpoint_delta` | 拓扑：断笔与虚连 | 一处笔画断开只改动几个像素，`pixel_diff_ratio` 看着还在容差内，但字形已经变了——聚类里这就是同字判不成同字的直接原因 |

**分两层报**（making-datasets.md 第六步）：

- `verified` 层：golden 是逐张目视确认过的正确输出 → 严格回归门，必须全过；
- `known_defect` 层：当前输出本身就是错的（笔画被删、残余没去掉），
  **绝不能把错的输出冻成 golden**——那等于把缺陷焊死。这层只记录当前行为，
  修好了就该「失败」，看到失败要去看 `defect` 说的是不是已经修了。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .normalize import skeletonize

_KERNEL_CROSS = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)


def to_binary(img: np.ndarray) -> np.ndarray:
    """PNG（0/255）→ uint8 {0,1}。"""
    return (img > 127).astype(np.uint8)


def pixel_diff_ratio(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.count_nonzero(a != b)) / a.size


def binary_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    return inter / union if union else 1.0


def skeleton_nodes(binary: np.ndarray) -> tuple[int, int]:
    """骨架的 (端点数, 交叉点数)。端点=邻居 1 个，交叉点=邻居 ≥3 个。"""
    skel = skeletonize(binary)
    if not skel.any():
        return 0, 0
    neigh = cv2.filter2D(skel.astype(np.uint8), -1, _KERNEL_CROSS,
                         borderType=cv2.BORDER_CONSTANT)
    on = skel > 0
    return int(np.count_nonzero(on & (neigh == 1))), \
        int(np.count_nonzero(on & (neigh >= 3)))


def skeleton_endpoint_delta(a: np.ndarray, b: np.ndarray) -> int:
    ea, ja = skeleton_nodes(a)
    eb, jb = skeleton_nodes(b)
    return abs(ea - eb) + abs(ja - jb)


@dataclass
class SampleResult:
    sample: str
    status: str                 # verified | known_defect
    pixel_diff_ratio: float
    binary_iou: float
    skeleton_endpoint_delta: int
    passed: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return {"sample": self.sample, "status": self.status,
                "pixel_diff_ratio": round(self.pixel_diff_ratio, 6),
                "binary_iou": round(self.binary_iou, 6),
                "skeleton_endpoint_delta": self.skeleton_endpoint_delta,
                "passed": self.passed, "reasons": self.reasons}


def check_sample(sample_dir: Path, produced: np.ndarray,
                 produced_skeleton: np.ndarray | None = None) -> SampleResult:
    """把当前归一化的输出与冻结的 golden 比。produced 为 uint8 {0,1}。"""
    spec = json.loads((sample_dir / "expected.json").read_text(encoding="utf-8"))
    golden = to_binary(cv2.imread(str(sample_dir / spec["golden"]),
                                  cv2.IMREAD_GRAYSCALE))
    tol = spec.get("tolerance", {})
    max_pdr = tol.get("pixel_diff_ratio", 0.01)
    min_iou = tol.get("binary_iou_min", 0.98)
    max_delta = tol.get("skeleton_endpoint_delta_max", 0)

    pdr = pixel_diff_ratio(golden, produced)
    iou = binary_iou(golden, produced)
    if produced_skeleton is None:
        delta = skeleton_endpoint_delta(golden, produced)
    else:
        gs = to_binary(cv2.imread(str(sample_dir / spec["golden_skeleton"]),
                                  cv2.IMREAD_GRAYSCALE))
        ge, gj = skeleton_nodes(gs)
        pe, pj = skeleton_nodes(produced_skeleton)
        delta = abs(ge - pe) + abs(gj - pj)

    reasons = []
    if pdr > max_pdr:
        reasons.append(f"pixel_diff_ratio {pdr:.4f} > {max_pdr}")
    if iou < min_iou:
        reasons.append(f"binary_iou {iou:.4f} < {min_iou}")
    if delta > max_delta:
        reasons.append(f"skeleton_endpoint_delta {delta} > {max_delta}")

    return SampleResult(sample_dir.name, spec.get("status", "verified"),
                        pdr, iou, delta, not reasons, reasons)


def summarize(results: list[SampleResult]) -> dict:
    """回归门只卡 verified 层；缺陷层单独报，别混进门里。"""
    verified = [r for r in results if r.status == "verified"]
    defects = [r for r in results if r.status == "known_defect"]
    return {
        "gate": {
            "n": len(verified),
            "passed": sum(1 for r in verified if r.passed),
            "failed": [r.to_dict() for r in verified if not r.passed],
            "ok": all(r.passed for r in verified),
        },
        "known_defect": {
            "n": len(defects),
            "unchanged": sum(1 for r in defects if r.passed),
            "changed": [r.to_dict() for r in defects if not r.passed],
        },
        "n_samples": len(results),
    }


def format_report(report: dict) -> str:
    g = report["gate"]
    lines = [f"回归门：{g['passed']}/{g['n']} 通过" + ("" if g["ok"] else "  ← 失败")]
    for f in g["failed"]:
        lines.append(f"  ✗ {f['sample']}: {'; '.join(f['reasons'])}")
    d = report["known_defect"]
    if d["n"]:
        lines.append(f"已知缺陷层：{d['unchanged']}/{d['n']} 行为未变"
                     f"（变了的要去看缺陷是不是修了）")
        for c in d["changed"]:
            lines.append(f"  ~ {c['sample']}: {'; '.join(c['reasons'])}")
    return "\n".join(lines)
