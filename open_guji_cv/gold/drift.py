"""金标漂移检查：产物重生之后，哪些金标还成立、哪些要重看。

**不新造判据**——沿用 `scripts/migrate_column_warp_gold.py` 已经标定过的那一套：
主判据是**图像指纹**「人当时看的那张图还在不在」，容差 `FP_TOL=6.0` 灰阶
（列图横向平移 1~3px 时指纹差 ≈0，正是要留用的）。

为什么不用内容哈希：哈希对 1px 平移就变，而平移恰恰是「图其实没变」的常见情形。
为什么不用「算法现在还判得对吗」：那是循环论证，会让金标永远测不出算法错。

三种结论：
    keep     图没变，人裁照旧成立
    recheck  图变了，回去重看（**不猜**，也不自动改判）
    nofp     没有指纹可比（老样本），一律判需重看
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

FP_TOL = 6.0                       # 指纹平均绝对差容差（灰阶），来自 migrate_column_warp_gold
FP_SIZE = (32, 24)                 # 端裁剪图指纹 (w, h)
COL_FP_SIZE = (24, 96)             # 整列图指纹——列又高又窄，纵向多给点


def fingerprint(crop: np.ndarray, size: tuple[int, int] = FP_SIZE) -> str:
    small = cv2.resize(crop, size, interpolation=cv2.INTER_AREA)
    return base64.b64encode(small.astype(np.uint8).tobytes()).decode()


def fp_diff(stored: str, img: np.ndarray, size: tuple[int, int] = FP_SIZE) -> float:
    a = np.frombuffer(base64.b64decode(stored), dtype=np.uint8).reshape(size[1], size[0])
    b = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return float(np.abs(a.astype(int) - b.astype(int)).mean())


@dataclass
class DriftReport:
    shard: str
    keep: list[str] = field(default_factory=list)
    recheck: list[tuple[str, float]] = field(default_factory=list)
    nofp: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)      # 图拿不到了

    def to_dict(self) -> dict:
        n = len(self.keep) + len(self.recheck) + len(self.nofp) + len(self.missing)
        return {"shard": self.shard, "n": n, "keep": len(self.keep),
                "recheck": [{"id": i, "fp_diff": d} for i, d in self.recheck],
                "nofp": self.nofp, "missing": self.missing}


def check_shard(shard: str, items, image_of: Callable[[object], np.ndarray | None],
                fp_field: str = "column_fingerprint",
                fp_size: tuple[int, int] = COL_FP_SIZE,
                tol: float = FP_TOL) -> DriftReport:
    """对一个分片跑漂移检查。

    `image_of(item)` 给出该条金标**当前**对应的图（拿不到返回 None）；
    `fp_field` 是条目 input 里存指纹的字段名。
    """
    rep = DriftReport(shard)
    for it in items:
        stored = (it.input or {}).get(fp_field)
        if not stored:
            rep.nofp.append(it.id)
            continue
        try:
            img = image_of(it)
        except Exception:   # noqa: BLE001
            img = None
        if img is None:
            rep.missing.append(it.id)
            continue
        d = fp_diff(stored, img, fp_size)
        if d <= tol:
            rep.keep.append(it.id)
        else:
            rep.recheck.append((it.id, round(d, 1)))
    return rep


def mark_drifted(store, shard: str, rep: DriftReport, why: str = "") -> int:
    """把 recheck / missing 的条目标成 stale（不改 expected，等人重看）。"""
    ids = [i for i, _ in rep.recheck] + rep.missing
    if not ids:
        return 0
    return store.mark_stale(shard, ids, why or f"图像指纹变了（容差 {FP_TOL}），需重看")
