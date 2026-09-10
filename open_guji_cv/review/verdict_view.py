# -*- coding: utf-8 -*-
"""把事件读回成「这一批已经裁过哪些字位」——**刷新页面不该重审一遍**。

从 `console/app.py` 的 `api_review_verdicts` ＋ `api_cutline_verdicts` 搬来
（控制台重构 C2）。两条本来就是同一件事的两种 kind，合到一个模块里。
逻辑一行未改，只动了函数名与 `EventLog` 改成可注入。

同一 id 多次裁决按 (batch, seq) 升序**后到覆盖**——沿用 seed_queue 的纪律，
人改主意时最后一次说了算。
"""
from __future__ import annotations

from ..feedback.events import EventLog


def review_verdicts(batch: str, log: EventLog | None = None) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。

    裁决本来就落成事件了（`/api/events`），但前端只在内存里记 `RV.verdicts`，
    一刷新就空。这个接口把事件读回成同样的形状，载入卡片时合并进去。

    同一 id 多次裁决按 (batch, seq) 升序**后到覆盖**——沿用 seed_queue 的
    纪律，人改主意时最后一次说了算。
    """
    out: dict[str, dict] = {}
    for e in sorted((log or EventLog()).read(batch), key=lambda x: (x.batch, x.seq)):
        p = e.payload
        v = p.get("v") or e.kind
        if v == "not_a_char":
            out[e.target.key] = {"shape": "", "reading": "", "done": "non"}
        elif v == "skip":
            out[e.target.key] = {"shape": "", "reading": "", "done": "skip"}
        elif v == "seg_defect":
            out[e.target.key] = {"shape": p.get("shape") or "",
                                 "reading": p.get("reading") or "",
                                 "done": p.get("quality") or "contaminated"}
        elif v == "confirm":
            out[e.target.key] = {"shape": p.get("shape") or "",
                                 "reading": p.get("reading") or p.get("shape") or "",
                                 "done": "1"}
    return {"batch": batch, "n": len(out), "verdicts": out}


def cutline_verdicts(batch: str, log: EventLog | None = None) -> dict:
    """读回本批已拖过的切线（刷新不重做；同 id 后到覆盖）。"""
    out: dict[str, dict] = {}
    for e in sorted((log or EventLog()).read(batch), key=lambda x: (x.batch, x.seq)):
        if e.kind != "cutline":
            continue
        p = e.payload
        out[e.target.key] = {"y": p.get("y"), "verdict": p.get("verdict"), "polyline": p.get("polyline")}
    return {"batch": batch, "n": len(out), "verdicts": out}
