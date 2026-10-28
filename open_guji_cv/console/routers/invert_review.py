# -*- coding: utf-8 -*-
"""控制台 · Step0 反色带候选审卡（2026-10-22）。领域逻辑在 `review/invert_cards.py`。

裁决走已有的 `/api/events`（kind=`inverted_band`，payload: verdict / rules / question），不新增写入端点。
"""
from __future__ import annotations

import json

import cv2
from fastapi import APIRouter, Depends, HTTPException, Response

from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from open_guji_cv.console_api import load_book
from open_guji_cv.console_api import invert_cards as ic

router = APIRouter(dependencies=[Depends(require_reviewer)])


@router.get("/api/invert-review/cards")
@maps_http
def api_invert_review_cards(book: str, pages: str = "all", decided: bool = False) -> dict:
    """有反色带候选的页。`decided=true` 连点过「否」的也列出来（改判用）。"""
    pg = load_book(book).resolve_pages(pages)
    cs = ic.cards(deps.product_store(), book, pg, include_decided=decided)
    return {"book": book, "pages": pages, "n": len(cs), "cards": cs}


@router.get("/api/invert-review/preview")
@maps_http
def api_invert_review_preview(book: str, page: int, which: str = "before", rules: str = "") -> Response:
    """修前／修后预览（JPEG）。`rules` 是 JSON 规则表；空 = 用本页候选的建议修法。"""
    if which not in ("before", "after"):
        raise HTTPException(400, "which 只能是 before / after")
    rs = json.loads(rules) if rules else [c for card in ic.cards(deps.product_store(), book, [page], include_decided=True)
                                          for c in card["rules"]]
    if not rs:
        raise HTTPException(404, f"{book} p{page} 没有反色带候选")
    img = ic.preview(book, page, rs, which)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(500, "编码失败")
    return Response(content=buf.tobytes(), media_type="image/jpeg")
