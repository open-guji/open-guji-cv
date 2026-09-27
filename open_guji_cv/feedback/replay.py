"""`glyph-db rebuild` 之后按人裁事件补放「db 里有、真源里还没有」的刻例（2026-09-27，值守 #115 查出的隐患）。

## 为什么要补
控制台裁决是当场进 `glyph.db` 的，真源 `output/glyph_store/` 要等 `glyph_store_sync` 定时器
（30 分钟一次）导出才跟上。两次导出之间谁 `glyph-db rebuild`（从真源重建库），这段时间审进库的格
就丢了——事件还在 `feedback/events/`，库里没了。

## 为什么不重放全部历史
历史事件里有后来被体检撤掉的刻例（`glyph_audit` evict、排除名单、`scripts/evict_*.py`）：从头重放会把
它们复活。所以只重放**水位线之后**的事件。水位线 = 真源 `admissions.jsonl` 里最晚的 `admitted_at`
——导出那一刻库里已有的最新一条准入；比它新的事件（留 `margin` 秒余量，已在库的格 `admit_instance`
幂等跳过）就是还没导出的。

## 重放什么
- `confirm`（`v == "confirm"`）人裁：走控制台同一条消费器 `glyphdb_admit`（改判撤旧进新、`no_glyph_lib`、
  非单字拦截都照旧）；
- `glyph_audit`（体检撤库/改判）**只报条数、不自动重放**：那个消费器还往 `glyph_selfcheck/` 台账追加记录，
  重放会写重复行；水位线后有体检裁决时按报告手动 `route_and_consume` 那几条；
- **不**重放机器刻例（`actor == "model"` 或 `payload.source == "auto"`：它们由 `book_lib_auto` 写库，
  `glyphdb_admit` 会把它们记成人裁）；
- **不**重放 `book_lib_sync` 进库闸拦下的（消费记账里 note 以 `book_lib_sync gated` 开头）。

真源里没有任何准入行（新库）时不重放，只报告——没有水位线就分不出哪些是历史。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def store_watermark(store_dir: str | Path) -> datetime | None:
    """真源里最晚一条准入的时间；没有准入行返回 None。"""
    f = Path(store_dir) / "admissions.jsonl"
    if not f.exists():
        return None
    best = None
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            t = _parse(json.loads(line).get("admitted_at"))
            if t and (best is None or t > best):
                best = t
    return best


def _gated_ids(log) -> set[str]:
    p = log.consumed_dir / "glyphdb_admit.jsonl"
    out = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                if str(d.get("note", "")).startswith("book_lib_sync gated"):
                    out.add(d["event"])
    return out


def replay_after_rebuild(db_path: str | Path, store_dir: str | Path, feedback_root: str | Path,
                         margin_s: int = 300, dry_run: bool = False) -> dict:
    """rebuild 之后调用：把水位线之后的人裁 confirm / glyph_audit 事件补进库。返回摘要。"""
    from .events import EventLog
    wm = store_watermark(store_dir)
    log = EventLog(Path(feedback_root))
    rep: dict = {"watermark": wm.isoformat() if wm else None, "margin_s": margin_s}
    if wm is None:
        rep["skipped"] = "真源没有准入行，没有水位线，不重放"
        return rep
    if not log.events_dir.exists():
        rep["skipped"] = "没有 feedback/events"
        return rep
    since = wm - timedelta(seconds=margin_s)
    gated = _gated_ids(log)
    confirms, audits = [], []
    for e in sorted(log.iter_all(), key=lambda x: (x.ts, x.order)):
        t = _parse(e.ts)
        if t is None or t < since or e.id in gated:
            continue
        if e.kind == "confirm" and (e.payload.get("v") or "confirm") == "confirm":
            if e.actor == "model" or e.payload.get("source") == "auto":
                continue
            confirms.append(e)
        elif e.kind == "glyph_audit":
            audits.append(e)
    rep.update(confirm=len(confirms), glyph_audit=len(audits))
    if audits:
        rep["glyph_audit_not_replayed"] = [e.id for e in audits][:50]
    if dry_run or not confirms:
        return rep
    from .consumers import glyphdb_admit
    r = glyphdb_admit([(e, None) for e in confirms], db_path=str(db_path))
    rep["admit"] = {"added": r.added, "updated": r.updated, "no_lib": r.no_lib,
                    "skipped": r.skipped, "errors": r.errors[:20]}
    return rep
