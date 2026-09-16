"""`rare-char` 测试集的载入口：把冻结的条目和**当下**的字块图对上。

分出来是因为 items.jsonl 里的 `input.patch` 是 **2026-09-04 建集那天的绝对路径**
（`D:\\workspace\\open-guji-cv\\cache\\vol01\\char_patch\\*.png`）。2026-09-13 三仓
边界改动把派生缓存挪去了 workspace（`GUJI_WORKSPACE/cache/`，见
`core.workspace.cache_root`），冻结路径于是全部失效——`cv2.imread` 一律返回
None，三条用例静默退化成「一条样本都没读到」，`hit/n` 变成 `0/0`。

所以**别信 `input.patch`，认 `patch_key`**：key（`p0137c05s19`）是稳定标识，
交给 `ImageCache` 按当下的 cache_root 现算路径。冻结路径只当兜底（万一有人把
集子连图一起归档到别处）。

`load_items()` 只返回图还在的条目，并保证条目数对得上——读不到图时抛错而不是
让调用方拿着空列表往下算，否则又会退化成 0/0 那种假通过/假失败。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

DATASET = Path("../open-guji-dataset/rare-char/items.jsonl")


def available() -> bool:
    return DATASET.exists()


def resolve_patch(item: dict) -> Path | None:
    """按 patch_key 在当下的 cache_root 里找字块图；找不到再退回冻结路径。"""
    from open_guji_cv.products.cache import ImageCache

    key = item["input"].get("patch_key")
    book = item["anchor"]["book"]
    if key:
        p = ImageCache().get(book, "char_patch", key)
        if p is not None:
            return p
    frozen = item["input"].get("patch")
    if frozen and Path(frozen).exists():
        return Path(frozen)
    return None


def load_items(require_patch: bool = True) -> list[tuple[dict, np.ndarray]]:
    """读集子，返回 `(条目, 灰度图)`。

    `require_patch=True` 时，只要有一条读不出图就抛 FileNotFoundError——宁可红成
    「图找不到」，也不要退化成「样本数 0」那种看不出病因的断言失败。
    """
    import cv2

    items = [json.loads(line) for line in
             DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    out: list[tuple[dict, np.ndarray]] = []
    missing: list[str] = []
    for it in items:
        p = resolve_patch(it)
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p else None
        if img is None:
            missing.append(it.get("id") or it["input"].get("patch_key", "?"))
            continue
        out.append((it, img))
    if missing and require_patch:
        raise FileNotFoundError(
            f"rare-char {len(missing)}/{len(items)} 条读不到字块图（缓存里没有，"
            f"cache_root={_cache_root()}）：{missing[:5]}。"
            "字块缓存是可重建的派生物，跑 "
            "`python -m open_guji_cv pipeline keben_body_v2 vol01` 重建，"
            "或把 GUJI_WORKSPACE 指到有 cache/<book>/char_patch/ 的工作区。")
    return out


def _cache_root() -> str:
    from open_guji_cv.core.workspace import cache_root
    return str(cache_root())
