# -*- coding: utf-8 -*-
"""控制台 · 金标。

分片概览 / 载体迁移 / 指纹漂移检查

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from pathlib import Path

import cv2
from fastapi import APIRouter

from .. import deps

router = APIRouter()



@router.get("/api/gold")
def api_gold(shard: str | None = None, limit: int = 300) -> dict:
    if shard:
        return {"summary": deps.gold_store().summary(shard), "carrier": deps.gold_store().carrier(shard),
                "items": [i.model_dump(mode="json", exclude_none=True)
                          for i in deps.gold_store().list(shard)][:limit]}
    out = []
    for s in deps.gold_store().shards():
        d = deps.gold_store().summary(s)
        d["carrier"] = deps.gold_store().carrier(s)
        out.append(d)
    return {"shards": out}



@router.post("/api/gold/{shard:path}/migrate")
def api_gold_migrate(shard: str, dry_run: bool = False) -> dict:
    """旧载体 → items.jsonl。不删旧文件，两边并存。"""
    return deps.gold_store().migrate(shard, dry_run=dry_run)



@router.post("/api/gold/{shard:path}/drift")
def api_gold_drift(shard: str, apply: bool = False) -> dict:
    """图像指纹漂移检查：产物重生后哪些金标还成立。"""
    from ...gold.drift import check_shard, mark_drifted
    root = Path(__file__).resolve().parent.parent.parent

    def image_of(it):
        p = (it.input.get("input") or {}).get("column_image")
        if not p:
            return None
        f = root / str(p).replace("open-guji-cv ", "")
        return cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None

    rep = check_shard(shard, deps.gold_store().list(shard), image_of)
    out = rep.to_dict()
    if apply:
        out["marked_stale"] = mark_drifted(deps.gold_store(), shard, rep)
    return out
