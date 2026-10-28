# -*- coding: utf-8 -*-
"""控制台 · 审阅批次与事件。

批次台账 / 裁决回传 / 收割 / 按路由表消费

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .. import deps
from ..auth import Identity, require_admin, require_reviewer
from ..cli import run_guji
from ..errors import maps_http
from open_guji_cv.console_api import enrich_events as _anchor_events
from open_guji_cv.console_api import make_event, replay_key
from open_guji_cv.console_api import harvest_text
from open_guji_cv.console_api import Batch, render_registry_markdown
from open_guji_cv.console_api import write_events

router = APIRouter(dependencies=[Depends(require_reviewer)])



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
    request_id: str | None = None
    """幂等键（2026-09-28，部署重启期间前端暂存重试用）。同一批次里已有带这个 id 的事件
    → 整个请求当作重复：不再写、不再消费，回 `duplicate: true`。id 落在每条事件的
    `payload.request_id` 上，所以进程重启后仍能判重（第一次其实写成功了、只是响应丢了）。"""
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



@router.post("/api/batches", dependencies=[Depends(require_admin)])
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



_EVENTS_LOCK = __import__("threading").Lock()


@router.post("/api/events")
@maps_http
def api_events(req: EventsIn, identity: Identity = Depends(require_reviewer)) -> dict:
    """审查页直连写入。seq 从当前最大值续，保证同批不撞号。

    **整段串行**（2026-09-26）：FastAPI 把同步路由放进线程池并发跑，而这里「取最大 seq → 追加」
    与消费里金标的「整读 → 合并 → 整写」都是读改写。切线台改成回车先跳下一张、不等写入返回后，
    人连按回车就有几个 POST 同时在跑——实测 vol02 两分钟里丢了 9 条金标（事件与记账都在，
    裁决表里没有：两次 upsert 读到同一版文件，后写的覆盖了先写的）。"""
    with _EVENTS_LOCK:
        return _api_events(req, identity.email)


def _api_events(req: EventsIn, reviewer: str | None = None) -> dict:
    """写入逻辑在 cv 的 `review/event_write.py`（命令行 `guji cellvotes write` 也调它）；这里只递四个 Store。"""
    return write_events(deps.event_log(), deps.batch_store(), deps.verdict_store(), deps.product_store(),
                        reviewer=reviewer, **req.model_dump())



@router.get("/api/events")
def api_events_list(batch: str | None = None, limit: int = 200) -> list[dict]:
    evs = deps.event_log().read(batch) if batch else sorted(deps.event_log().iter_all(), key=replay_key)
    return [e.model_dump(mode="json") for e in evs[-limit:]]



class HarvestIn(BaseModel):
    batch: str
    step: str
    unit: str = "page"
    kind: str = "verdict"
    content: str              # 读回的 HTML / JSONL / 日志文本



@router.post("/api/batches/{batch_id}/harvest", dependencies=[Depends(require_admin)])
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
    _anchor_events(evs)   # 人裁带锚：重切后靠它找回是哪个字（总览/15）
    n = deps.event_log().append(evs)
    b = deps.batch_store().get(batch_id)
    if b:
        b.status = "harvested" if n or b.n_events else b.status
        import time as _t
        b.harvested_at = _t.time()
        deps.batch_store().refresh_counts(b, deps.event_log())
    return {"parsed": len(evs), "appended": n, "total": len(deps.event_log().read(batch_id))}



@router.post("/api/batches/{batch_id}/route", dependencies=[Depends(require_admin)])
def api_route(batch_id: str, dry_run: bool = False) -> dict:
    """按路由表消费一批事件：走命令行 `guji events route`（会写裁决表，设计第五节）。"""
    out = run_guji("events", "route", batch_id, *(["--dry-run"] if dry_run else []))
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
