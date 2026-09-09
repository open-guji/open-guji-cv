# -*- coding: utf-8 -*-
"""控制台 · 审阅批次与事件。

批次台账 / 裁决回传 / 收割 / 按路由表消费

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .. import deps
from ...feedback.consumers import route_and_consume
from ...feedback.events import EventTarget, make_event
from ...feedback.harvest import harvest_text
from ...feedback.routes import RouteTable
from ...review.batches import Batch, render_registry_markdown

router = APIRouter()



# ── 反馈：批次 / 事件 / 收割 / 路由 ──────────────────────────────────


class BatchCreate(BaseModel):
    id: str
    title: str
    step: str
    kind: str = "verdict"
    book: str | None = None
    transport: str = "server"
    url: str | None = None
    shard: str | None = None
    cards_ref: str | None = None
    n_cards: int = 0
    options: list[str] = []
    notes: str = ""



class EventsIn(BaseModel):
    """审查页 server 模式回传的一批裁决。"""
    batch: str
    step: str
    unit: str = "page"
    kind: str = "verdict"
    events: list[dict]        # [{id, verdict, t, ...}]
    consume: bool = True
    """写完就按路由表消费（2026-09-05 用户定：「审查完了就自动消费吧，有必要再点一次吗」）。

    **批次是台账，不是闸**——事件既然已经落盘，再要人点一次「按路由表消费」只是重复动作，
    而且批次一多（组视图按组分批，一轮下来十几个）就得一个个点。消费本身是幂等的：
    `EventLog.pending` 按消费者记账，`admit_instance` 有主键幂等闸，重复调用不会重复进库。

    传 `consume=false` 可以只写不消费（外部审查页回传、想先「试算」看看的场合）。
    消费失败不影响写入结果——事件已经在盘上，「收割与消费」那块随时能补跑。
    """



@router.get("/api/batches")
def api_batches() -> list[dict]:
    out = []
    for b in deps.batch_store().list():
        out.append(deps.batch_store().refresh_counts(b, deps.event_log()).to_dict())
    return out



@router.post("/api/batches")
def api_batch_create(req: BatchCreate) -> dict:
    if deps.batch_store().get(req.id):
        raise HTTPException(409, f"批次 {req.id} 已存在")
    b = Batch(**req.model_dump())
    deps.batch_store().save(b)
    return b.to_dict()



@router.get("/api/batches/{batch_id}")
def api_batch_get(batch_id: str) -> dict:
    b = deps.batch_store().get(batch_id)
    if not b:
        raise HTTPException(404, "没有这个批次")
    b = deps.batch_store().refresh_counts(b, deps.event_log())
    d = b.to_dict()
    ok, why = b.can_publish()
    d["can_publish"], d["publish_block_reason"] = ok, why
    d["events"] = [e.model_dump(mode="json") for e in deps.event_log().read(batch_id)][-200:]
    return d



@router.post("/api/events")
def api_events(req: EventsIn) -> dict:
    """审查页直连写入。seq 从当前最大值续，保证同批不撞号。"""
    base = deps.event_log().latest_seq(req.batch)
    evs = []
    for i, row in enumerate(sorted(req.events, key=lambda r: (r.get("t") or 0, str(r.get("id")))), 1):
        if not row.get("id"):
            continue
        payload = {k: v for k, v in row.items() if k not in ("id", "t")}
        # `client_ts` / `dwell_ms` 留在 payload 里：事件的 `ts` 是**收割时间**
        # （历史 324 条只有 4 个不同值），量不出人裁一条要多久。UI 改造的验收
        # 指标就是这个耗时，没有它 D 刀无法证伪。
        from ...feedback.harvest import parse_card_id
        evs.append(make_event(req.batch, base + i, req.kind,   # type: ignore[arg-type]
                              EventTarget(step=req.step, unit=req.unit, key=row["id"],
                                          **parse_card_id(row["id"])),
                              payload, source_format="server"))
    n = deps.event_log().append(evs)
    b = deps.batch_store().get(req.batch)
    if b is None:
        # **批次不存在就自动登记**（2026-09-04 修）。控制台的定字裁决直接 POST
        # 到这里，此前只写事件、不建批次，于是「收割」那块的批次下拉是空的，
        # 人裁完了却没法点「按路由表消费」——看着像「必须全部审完才行」，
        # 其实是登记漏了。批次是台账（谁裁的、多少条、消费了没），不是闸。
        b = Batch(id=req.batch, title=req.batch, step=req.step,
                  kind=req.kind, transport="server", status="open",
                  notes="控制台直连裁决自动登记")
    if b.status == "draft":
        b.status = "open"
    deps.batch_store().refresh_counts(b, deps.event_log())
    deps.batch_store().save(b)
    out = {"appended": n, "batch": req.batch, "total": len(deps.event_log().read(req.batch))}
    if req.consume and n:
        # 写完直接消费（见 EventsIn.consume）。**失败不抛**：事件已经落盘，
        # 消费只是把它送进字形库/金标，出了岔子在「收割与消费」那块补跑即可——
        # 让整个 POST 报错会让人以为裁决没保存，那才是真的坏。
        try:
            table = RouteTable.load(deps.event_log().root / "routes.yaml")
            res = route_and_consume(deps.event_log(), req.batch, table, deps.gold_store())
            out["consumed"] = [
                {"consumer": x["consumer"], "added": x["added"],
                 "skipped": x["skipped"], "errors": x["errors"][:3]}
                for x in res["results"] if x["events"]]
            out["unrouted"] = res["unrouted"]
            b2 = deps.batch_store().get(req.batch)
            if b2:
                deps.batch_store().refresh_counts(b2, deps.event_log())
                deps.batch_store().save(b2)
        except Exception as exc:                       # noqa: BLE001
            out["consume_error"] = f"{type(exc).__name__}: {exc}"
    return out



@router.get("/api/events")
def api_events_list(batch: str | None = None, limit: int = 200) -> list[dict]:
    evs = deps.event_log().read(batch) if batch else sorted(deps.event_log().iter_all(), key=lambda e: e.order)
    return [e.model_dump(mode="json") for e in evs[-limit:]]



class HarvestIn(BaseModel):
    batch: str
    step: str
    unit: str = "page"
    kind: str = "verdict"
    content: str              # 读回的 HTML / JSONL / 日志文本



@router.post("/api/batches/{batch_id}/harvest")
def api_harvest(batch_id: str, req: HarvestIn) -> dict:
    """喂 Artifact 读回的 HTML（或旧格式文本）→ 解析 → 事件入库。

    收割器从 seq=1 开始编号；若这批已有事件（server 模式先写过、或上一轮收割过），
    直接追加会撞号被当成重复而丢掉。所以按 **target.key** 去重：已在库里的 key 跳过，
    新 key 从当前最大 seq 往后续。
    """
    try:
        evs = harvest_text(req.content, batch_id, req.step, req.unit, req.kind)  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    existing = deps.event_log().read(batch_id)
    if existing:
        have = {e.target.key for e in existing}
        base = deps.event_log().latest_seq(batch_id)
        fresh = [e for e in evs if e.target.key not in have]
        evs = [make_event(batch_id, base + i, e.kind, e.target, e.payload,
                          e.actor, e.source_format, e.ts)
               for i, e in enumerate(fresh, 1)]
    n = deps.event_log().append(evs)
    b = deps.batch_store().get(batch_id)
    if b:
        b.status = "harvested" if n or b.n_events else b.status
        import time as _t
        b.harvested_at = _t.time()
        deps.batch_store().refresh_counts(b, deps.event_log())
    return {"parsed": len(evs), "appended": n, "total": len(deps.event_log().read(batch_id))}



@router.post("/api/batches/{batch_id}/route")
def api_route(batch_id: str, dry_run: bool = False) -> dict:
    table = RouteTable.load(deps.event_log().root / "routes.yaml")
    out = route_and_consume(deps.event_log(), batch_id, table, deps.gold_store(),
                            dry_run=dry_run)
    b = deps.batch_store().get(batch_id)
    if b:
        deps.batch_store().refresh_counts(b, deps.event_log())
    return out



@router.get("/api/batches.md", response_class=Response)
def api_batches_md() -> Response:
    store = deps.batch_store()
    md = render_registry_markdown([store.refresh_counts(b, deps.event_log())
                                   for b in store.list()])
    return Response(md, media_type="text/markdown; charset=utf-8")
