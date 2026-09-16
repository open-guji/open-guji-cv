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
def api_gold(shard: str | None = None, limit: int = 300, verdicts: bool = False) -> dict:
    """`verdicts=1` 看 workspace 裁决表（feedback/verdicts）而不是测试集仓；两边同格式。"""
    gs = deps.verdict_store() if verdicts else deps.gold_store()
    if shard:
        return {"summary": gs.summary(shard), "carrier": gs.carrier(shard),
                "items": [i.model_dump(mode="json", exclude_none=True)
                          for i in gs.list(shard)][:limit]}
    out = []
    for s in gs.shards():
        d = gs.summary(s)
        d["carrier"] = gs.carrier(s)
        out.append(d)
    return {"shards": out, "source": "verdicts" if verdicts else "dataset"}


@router.post("/api/gold/{shard:path}/import")
def api_gold_import(shard: str, book: str | None = None, pages: str | None = None,
                    stratum: str | None = None, include_uncertain: bool = False,
                    why: str = "", dry_run: bool = True) -> dict:
    """workspace 裁决表 → 测试集仓：唯一往 dataset 写人裁数据的入口，**默认 dry_run**，
    看清清单再 `dry_run=false`。同 CLI `guji gold import`。"""
    from ...gold.transfer import ImportFilter, import_to_dataset, parse_pages
    flt = ImportFilter(book=book, pages=parse_pages(pages), stratum=stratum,
                       include_uncertain=include_uncertain)
    return import_to_dataset(shard, deps.verdict_store(), deps.gold_store(), flt,
                             why=why, dry_run=dry_run).to_dict()



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
