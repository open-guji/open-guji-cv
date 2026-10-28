"""控制台 · 插图块画框（GUJI-737 收尾，2026-10-24）。领域逻辑在 `feedback/figures.py`。

人在页图上拖框、写一句说明，存成一条页级 `figure_region` 事件（键 `figure:<册>:<页>`，一页一条，后到整页覆盖）。
Step9 导出（`scripts/export_guji_format.py`）读它，写 char 图列、cord `marks.figure`、fig.json 并裁图。
这里只多一层校验（框在页内、列号算得出、列不重叠），写入仍走 `/api/events` 同一条路径（同锁、同批次台账）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import deps
from ..auth import Identity, require_reviewer
from ..errors import maps_http
from open_guji_cv.console_api import figures as F

router = APIRouter(dependencies=[Depends(require_reviewer)])


class RegionsIn(BaseModel):
    regions: list[dict]
    """[{box: [x, y, w, h]（canvas 像素）, col?, span?, alt?, fig?}]；空表 = 撤掉本页全部插图块。"""


def batch_name(book: str) -> str:
    return f"figure-region-{book}"


def _all(book: str) -> dict[int, list[dict]]:
    return F.resolved_figure_regions(book, log=deps.event_log())


@router.get("/api/figure-region/{book}")
@maps_http
def api_figure_region_pages(book: str) -> dict:
    """本册画过插图块的页：`{pages: {页: [块…]}}`（撤掉的页不列）。"""
    return {"book": book, "pages": {str(p): r for p, r in _all(book).items()}}


@router.get("/api/figure-region/{book}/{page}")
@maps_http
def api_figure_region_page(book: str, page: int) -> dict:
    """一页：尺寸、各列横向范围（画辅助线、算列号用）、现有插图块。"""
    W, H, cols = F.page_columns(deps.product_store(), book, page)
    return {"book": book, "page": page, "width": W, "height": H, "columns": cols,
            "regions": _all(book).get(page, [])}


@router.post("/api/figure-region/{book}/{page}")
@maps_http
def api_figure_region_save(book: str, page: int, req: RegionsIn,
                           identity: Identity = Depends(require_reviewer)) -> dict:
    """存本页插图块（整页覆盖）。列号没给就按框算；算不出、框不合法、列重叠都回 400，不写。"""
    from .feedback import _EVENTS_LOCK, EventsIn, _api_events
    W, H, cols = F.page_columns(deps.product_store(), book, page)
    try:
        regions = F.normalize_regions(req.regions, cols, W, H)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    ev = EventsIn(batch=batch_name(book), step="export", unit="page", kind="figure_region",
                  events=[{"id": F.region_key(book, page), "regions": regions}], consume=False)
    with _EVENTS_LOCK:
        out = _api_events(ev, identity.email)
    return {**out, "page": page, "regions": _all(book).get(page, [])}
