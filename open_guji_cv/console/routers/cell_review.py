# -*- coding: utf-8 -*-
"""控制台 · 格级审阅（GUJI-364b）：清单读取与 TSV 导出，只读。

- `GET /api/cell-review/{清单 id}`：清单、每格的候选字与已落裁决、四档计数。
- `GET /api/cell-review/{清单 id}.tsv`：导出（UTF-8 带 BOM，一行一格，行数 = 清单行数）。

写入不在这里：前端照常 `POST /api/events`（`kind=cell_review`，批次 `cellreview-<清单 id>`），
校验在 `console/routers/feedback.py` 的 `_check_cell_review`；领域逻辑在 `feedback/cell_review.py`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from open_guji_cv.console_api import candidates as cand
from open_guji_cv.console_api import cell_review as cr

router = APIRouter(dependencies=[Depends(require_reviewer)])


def _path(list_id: str):
    try:
        path = cand.list_path(list_id, deps.event_log().root / "candidates")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not path.exists():
        raise HTTPException(404, f"没有这份候选清单：{path.name}")
    return path


# 注意：`.tsv` 路由必须排在 JSON 路由前面——清单 id 允许带点，JSON 路由会把 `x.tsv` 也吃掉。
@router.get("/api/cell-review/{list_id}.tsv", response_class=Response)
@maps_http
def api_cell_review_tsv(list_id: str) -> Response:
    _, rows, _ = cr.load(_path(list_id))
    dec = cr.latest(deps.event_log(), list_id)
    body = cr.tsv(rows, dec).encode("utf-8")
    return Response(body, media_type="text/tab-separated-values; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="cell-review-{list_id}.tsv"'})


@router.get("/api/cell-review/{list_id}")
@maps_http
def api_cell_review(list_id: str) -> dict:
    meta, rows, problems = cr.load(_path(list_id))
    dec = cr.latest(deps.event_log(), list_id)
    cells = []
    for r in sorted(rows, key=lambda r: cr.order_key(r["cell_id"])):
        cells.append({**r, **(cand.parse_cell(r["cell_id"]) or {}), "decision": dec.get(r["cell_id"])})
    tally = {v: 0 for v in cr.VERDICTS}
    for c in cells:
        if c["decision"] and c["decision"]["verdict"] in tally:
            tally[c["decision"]["verdict"]] += 1
    tally["todo"] = len(cells) - sum(tally[v] for v in cr.VERDICTS)
    return {"id": list_id, "meta": meta, "problems": problems, "batch": cr.batch_of(list_id),
            "kind": cr.KIND, "step": cr.STEP, "verdicts": list(cr.VERDICTS),
            "tally": tally, "cells": cells}
