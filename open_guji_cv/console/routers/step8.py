# -*- coding: utf-8 -*-
"""控制台 · Step8 对勘与复核。

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step8-落库反馈/
04-扩为对勘与复核中枢-设计.md` 与 `05-差异三层分类与复核裁决台UI.md`。

Step8 原本只有三个落库出口，而那三件事**全在 Step7 的裁决提交里顺手做掉了**
（人点一下，事件写入、路由、落库一气呵成）。真正缺位置的是**全局复核**：
Step7 只知道「机器确不确定」，不知道「机器对不对」——后者只有与独立证人
逐字对勘能答，而那是整册级的活，Step7 的页级契约装不下。

## 读已有产物，不现跑

对勘一次 ~100 s，不能每次开页面都跑。这里只读 `reports/<book>/` 下最新那份
JSON；要重跑走 `guji collate`（或前端的「重新对勘」按钮，走 `/api/step8/collate`）。

**不进管线**：同 Step9，整册级不满足 `run_page(ctx, page)` 契约。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from ... import feedback as _fb  # noqa: F401  确保事件/路由模块已加载
from ...core.workspace import reports_root
from ...report.tiers import TIER_LABEL, pair_index, tier_counts
from .. import deps
from ..errors import maps_http

router = APIRouter()


def _latest(book: str) -> Path | None:
    d = reports_root() / book
    files = sorted(d.glob("collation_*.json")) if d.exists() else []
    return files[-1] if files else None


def _load(book: str) -> dict:
    p = _latest(book)
    if p is None:
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["_file"] = p.name
    return doc


def _book_conventions(book: str) -> set:
    """`books/<id>.yaml` 的 `char_conventions` → `{(刻本形, 证人形)}`。"""
    try:
        from ...core.book import load_book
        rows = getattr(load_book(book), "char_conventions", None) or []
        return {tuple(r["pair"]) for r in rows if r.get("pair")}
    except Exception:
        return set()


def _denied() -> set:
    """`variants.deny.tsv` → `{(刻本形, 证人形)}`。人推翻过的关系图边。"""
    from ...feedback.collate_consumers import DENY_REL, _repo_path
    p = _repo_path(DENY_REL)
    out = set()
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                parts = ln.split("\t")
                if len(parts) >= 2:
                    out.add((parts[0], parts[1]))
    return out


def _decided(book: str) -> set:
    """已复核过的字对（`collate_ok` / `char_convention` / `variant_deny`）。

    按**字对**记，不按字位：一次裁决定的就是这一对的全部实例。
    """
    out = set()
    for e in deps.event_log().iter_all():
        if e.kind in ("collate_ok", "char_convention", "variant_deny"):
            pair = (e.payload or {}).get("pair")
            if pair and len(pair) == 2:
                out.add(tuple(pair))
    return out


@router.get("/api/step8/overview/{book}")
@maps_http
def api_step8_overview(book: str) -> dict:
    """对勘结论 + 三层计数 + 证人无此段。**不现跑**，读最新那份 JSON。"""
    doc = _load(book)
    if not doc:
        return {"book": book, "has_report": False,
                "hint": "还没有对勘产物，点「重新对勘」或跑 `guji collate`"}
    diffs = doc.get("diffs") or []
    idx = pair_index(diffs, conventions=_book_conventions(book), denied=_denied())
    decided = _decided(book)
    for r in idx:
        r["decided"] = tuple(r["pair"]) in decided
    summary = doc.get("summary") or {}
    n_equal = sum(w.get("n_equal", 0) for w in (summary.get("by_witness") or {}).values())
    n_slots = sum(p.get("n_slots", 0) for p in
                  (w for pg in (doc.get("page_stats") or [])
                   for w in (pg.get("witnesses") or {}).values()))
    return {
        "book": book, "has_report": True, "file": doc.get("_file"),
        "built_at": doc.get("built_at"), "pages": doc.get("pages"),
        "n_slots": n_slots, "n_equal": n_equal,
        "unanchored": doc.get("unanchored"),
        "tiers": tier_counts(idx),
        "tier_label": TIER_LABEL,
        "n_decided": sum(1 for r in idx if r["decided"]),
        "absent_runs": summary.get("absent_runs") or [],
        # 增删聚合不了（没有「对应的另一个字」），单独给个数
        "gaps": sum(1 for d in diffs if str(d.get("kind", "")).startswith(("missing", "extra"))),
    }


@router.get("/api/step8/pairs/{book}")
@maps_http
def api_step8_pairs(book: str, tier: str = "", undecided: bool = True,
                    limit: int = 200) -> dict:
    """按字对聚合的复核队列。

    `tier` 空 = 全部；`undecided` 只看没复核过的。
    **按对返回，不按条**——同一字对的判断几乎总是相同的，逐条问等于把同一个
    问题问 N 遍（`𠊓→傍` 一对就占 24 条）。
    """
    doc = _load(book)
    if not doc:
        return {"book": book, "pairs": [], "has_report": False}
    idx = pair_index(doc.get("diffs") or [], conventions=_book_conventions(book),
                     denied=_denied())
    decided = _decided(book)
    rows = []
    for r in idx:
        r["decided"] = tuple(r["pair"]) in decided
        if tier and r["tier"] != tier:
            continue
        if undecided and r["decided"]:
            continue
        rows.append(r)
    return {"book": book, "has_report": True, "total": len(rows),
            "pairs": rows[:limit], "truncated": len(rows) > limit}
