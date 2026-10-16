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

## `admit_candidate`（待纳入裁决，2026-09-28 overview#201，事件类型来自 C #176）
控制台「字形库 → 待纳入」的裁决落 `kind="admit_candidate"`（`v: admit|reject|unclear`，`admit`
带 `shape`），路由表**故意不配消费者**——进库只走这里（人裁状态单写者）。口径：

- 同一格裁多次按**最新一条**算（`ts`、`(batch, seq)` 排序）；最新一条 `v == "admit"` 才进库，
  `reject` / `unclear` 不进库。先收后改判「不收」的格只报出来（`admit_then_reject`），**不自动撤**：
  撤例走体检事件，这里不越权；
- 进库改写成 `confirm` 的形状交给 `glyphdb_admit`（同一消费器、同一套闸：非单字拦截、改判撤旧进新、
  `no_glyph_lib`、机器副本撤掉），事件 id / 批次原样带进 `evidence`，库里查得到出处；
- **不按水位线一刀切**：这种事件在线上从来没被消费过，水位线前的照样得进。改用消费记账：
  进过库的记进 `consumed/glyphdb_admit.jsonl`（note `admit_candidate replay`），以后只在水位线之后
  （rebuild 可能丢了它）才重放，水位线之前已记账的不再碰——体检撤掉的不会复活；
- `actor == "model"` 的不重放（与 confirm 同口径）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .events import counts_as_human


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


CANDIDATE_KIND = "admit_candidate"
CANDIDATE_NOTE = "admit_candidate replay"


def _as_confirm(e):
    """`admit_candidate`(v=admit) → `glyphdb_admit` 认得的 confirm 事件（id / batch / target 不变）。"""
    p = dict(e.payload or {})
    shape = p.get("shape") or p.get("char")
    p.update(v="confirm", shape=shape, candidate=True)
    return e.model_copy(update={"kind": "confirm", "payload": p})


def latest_candidate_verdicts(log) -> dict:
    """每格最新一条 `admit_candidate`（人裁）：{target.key: event}。"""
    latest: dict = {}
    for e in sorted(log.iter_all(), key=lambda x: (x.ts, x.order)):
        if e.kind != CANDIDATE_KIND or e.actor == "model" or not counts_as_human(e):
            continue
        if (e.payload or {}).get("v") not in ("admit", "reject", "unclear"):
            continue
        latest[e.target.key] = e
    return latest


def replay_admit_candidates(db_path: str | Path, feedback_root: str | Path,
                            watermark: datetime | None = None, margin_s: int = 300,
                            dry_run: bool = False) -> dict:
    """把待纳入裁决里「收」的格送进库（口径见模块头 `admit_candidate` 一节）。返回摘要。"""
    from .events import EventLog
    log = EventLog(Path(feedback_root))
    rep: dict = {"verdicts": 0, "admit": 0, "reject": 0, "unclear": 0,
                 "already_consumed": 0, "to_admit": 0}
    if not log.events_dir.exists():
        return rep
    latest = latest_candidate_verdicts(log)
    done = log.consumed_ids("glyphdb_admit")
    since = watermark - timedelta(seconds=margin_s) if watermark else None
    admitted_before = {}
    for e in log.iter_all():
        if e.kind == CANDIDATE_KIND and e.id in done:
            admitted_before[e.target.key] = e.id
    todo, flipped = [], []
    for key, e in latest.items():
        v = e.payload["v"]
        rep["verdicts"] += 1
        rep[v] += 1
        if v != "admit":
            if key in admitted_before:
                flipped.append(key)
            continue
        if e.id in done:
            t = _parse(e.ts)
            # 已记账：只在水位线之后（导出前 rebuild 可能丢了它）才补放
            if since is None or t is None or t < since:
                rep["already_consumed"] += 1
                continue
        todo.append(e)
    rep["to_admit"] = len(todo)
    if flipped:
        rep["admit_then_reject"] = sorted(flipped)
    if dry_run or not todo:
        return rep
    from .consumers import glyphdb_admit
    r = glyphdb_admit([(_as_confirm(e), None) for e in todo], db_path=str(db_path))
    rep["result"] = {"added": r.added, "updated": r.updated, "no_lib": r.no_lib,
                     "skipped": r.skipped, "errors": r.errors[:20]}
    # 消费失败的（缓存里没图块、字形不是单字…）不记账，下回还会再试
    ok = [e for e in todo if not any(m.startswith(e.target.key + ":") for m in r.errors)]
    fresh = [e for e in ok if e.id not in done]
    log.mark_consumed("glyphdb_admit", fresh, note=CANDIDATE_NOTE)
    return rep


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
            # 看图结论（source=vision，overview#428）同样不重放进库
            if e.actor == "model" or not counts_as_human(e) or e.payload.get("source") == "auto":
                continue
            confirms.append(e)
        elif e.kind == "glyph_audit":
            audits.append(e)
    rep.update(confirm=len(confirms), glyph_audit=len(audits))
    if audits:
        rep["glyph_audit_not_replayed"] = [e.id for e in audits][:50]
    if confirms and not dry_run:
        from .consumers import glyphdb_admit
        r = glyphdb_admit([(e, None) for e in confirms], db_path=str(db_path))
        rep["admit"] = {"added": r.added, "updated": r.updated, "no_lib": r.no_lib,
                        "skipped": r.skipped, "errors": r.errors[:20]}
    rep["admit_candidate"] = replay_admit_candidates(db_path, feedback_root, watermark=wm,
                                                     margin_s=margin_s, dry_run=dry_run)
    return rep


def main(argv: list[str] | None = None) -> int:
    """不重建、只补放待纳入裁决：`python -m open_guji_cv.feedback.replay [--dry-run]`。
    库 / 事件目录按工作区解析（`GUJI_WORKSPACE`，同控制台）。"""
    import argparse
    ap = argparse.ArgumentParser(description="待纳入裁决（admit_candidate）进库")
    ap.add_argument("--db", default=None, help="glyph.db；缺省按工作区")
    ap.add_argument("--feedback", default=None, help="feedback 目录；缺省按工作区")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from ..core.workspace import feedback_root, glyph_db_path
    rep = replay_admit_candidates(glyph_db_path(a.db), a.feedback or feedback_root(),
                                  dry_run=a.dry_run)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
