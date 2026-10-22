# -*- coding: utf-8 -*-
"""人裁排除名单与事件绑定的核对（GUJI-659）。"""
from __future__ import annotations

from pathlib import Path

from ..clustering.exclusions import load_exclusions
from .bindings import usable


def stale_by_binding(book: str, bindings: dict[str, dict],
                     path: str | Path | None = None) -> list[dict]:
    """人裁排除名单里「当时那格已经不是现在这格」的条目（GUJI-659，D3）。

    名单按实例 id 记，不带锚；重切之后同一个编号可能是另一块图。条目带 `source_event`
    （`crop_exclude` 写入）的，拿那条事件现在的绑定行核对：绑定可用（valid／rebound／
    有依据的 unanchored）且落回原编号才算还对得上，其余（void／review／改绑到别的编号）列出来。
    没有 `source_event` 的老条目没有依据，不在此列。只报告，不改名单——撤条目走
    `scripts/apply_exclusion_recheck.py`。

    `bindings` 是 `feedback.bindings.book_bindings(book)` 的结果（`{event_id: 行}`）。
    """
    out = []
    for iid, r in sorted(load_exclusions(path).items()):
        if r.get("origin") != "human" or not iid.startswith(book + ":"):
            continue
        row = bindings.get(r.get("source_event") or "")
        if row is None:
            continue
        now = usable(row)
        if now != iid:
            out.append({"instance_id": iid, "source_event": r["source_event"], "reason": r.get("reason"),
                        "status": row["status"], "now": now})
    return out
