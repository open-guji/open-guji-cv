# -*- coding: utf-8 -*-
"""人裁事件的写入路径：校验 → 编号 → 带锚 → 落盘 → 登记批次 →（可选）按路由表消费。

原先长在控制台 `console/routers/feedback.py::_api_events` 里，`guji cellvotes write`
反过来 import 控制台的路由去调它。控制台要拆成独立包（doc/design/拆分-控制台独立成包与上网站.md
第二节 R2），所以挪到这里：路由与命令行都调 `write_events`，四个 Store 由调用方传进来
（控制台从 `console/deps.py` 取，命令行按工作区现建）。

逻辑原样搬过来，只把 `HTTPException` 换成 `errors.BadRequest/NotFound`（控制台的
`maps_http` 照旧映射成 400/404）。**不加锁**：控制台进程内并发由路由的 `_EVENTS_LOCK` 管，
跨进程由 `feedback.lock` 管。
"""
from __future__ import annotations

from ..core.spec import page_key
from ..errors import BadRequest, NotFound
from ..eval.colgeom import current_geom, stamp
from ..feedback.anchor import enrich_events
from ..feedback.consumers import route_and_consume
from ..feedback.events import EventTarget, make_event
from ..feedback.harvest import parse_card_id
from ..feedback.routes import RouteTable
from .batches import Batch
from .label_batches import is_label_batch


def product_anchor(products, step: str, ids: dict) -> dict | None:
    """裁决是**对哪一版产物**做的——写进 `target.anchor.product_key`。

    ## 为什么要有

    `Anchor` 设计时就写着「product_key 允许失效，bbox + content_sha 不失效」，
    可实测这三个字段**填充率全是 0%**（2984 条裁决表条目里一条都没有），
    「产物重生后仍可定位」这个核心能力从来没兑现过。

    后果是真实的：2026-09-18 改了 Step3 的 `ink_lam` 重跑全书，切线坐标基准
    随之变化，而金标里没有任何东西能判断「这条裁决是对哪一版产物裁的」——
    只能靠人记得。切线台自己发明了一个补丁（把 `col_h` 塞进 payload，233/233
    条都有，前端 drift 档据此判断裁决是否过期），但那是**私有解法**，
    别的台没有。这里把它提升成通用字段，由写入路径统一填，不靠各台自觉。

    取不到指纹就返回 None（页号解析不出、产物还没跑、step 不产页级产物），
    **不抛异常**——anchor 是锦上添花，不该让裁决写不进去。
    """
    pg = ids.get("page")
    if not step or pg is None:
        return None
    out: dict = {}
    try:
        man = products.manifest(ids.get("book") or "", step)
        rec = man.get(page_key(int(pg))) if man else None
        fp = getattr(rec, "fingerprint", None)
        if fp:
            out["product_key"] = {"step": step, "key": page_key(int(pg)), "fingerprint": fp}
    except Exception:                                    # noqa: BLE001
        pass
    # 换图源（GUJI-748 §六）：事件锚要带产物自己的页表 rev，否则写入口的 rev 闸（RevGate）会把
    # 切线／夹注等非逐格事件整条拒掉（enrich_events 只给 unit=cell 补 source_rev）。
    try:
        rev = products.source_rev(ids.get("book") or "")
        if rev is not None:
            out["source_rev"] = rev
    except Exception:                                    # noqa: BLE001
        pass
    return out or None


def check_cell_review(log, batch: str, events: list[dict]) -> None:
    """格级审阅（GUJI-364b）写入前校验：批次须是 cellreview-<清单 id>，格须在清单里，裁决须合法。
    不合法整批拒掉（400），不写半截。"""
    from ..feedback import candidates as cand
    from ..feedback import cell_review as cr
    if not batch.startswith(cr.BATCH_PREFIX):
        raise BadRequest(f"cell_review 的批次须以 {cr.BATCH_PREFIX} 开头：{batch!r}")
    try:
        path = cand.list_path(batch[len(cr.BATCH_PREFIX):], log.root / "candidates")
    except ValueError as e:
        raise BadRequest(str(e)) from e
    if not path.exists():
        raise NotFound(f"没有这份候选清单：{path.name}")
    _, rows, _ = cr.load(path)
    cands = {r["cell_id"]: r["cands"] for r in rows}
    for row in events:
        cid = row.get("id")
        if cid not in cands:
            raise BadRequest(f"{cid!r} 不在清单里")
        why = cr.check_payload(row, cands[cid])
        if why:
            raise BadRequest(f"{cid}：{why}")


def write_events(log, batches, verdicts, products, *, batch: str, step: str, unit: str = "page",
                 kind: str = "verdict", events: list[dict], request_id: str | None = None,
                 consume: bool = True, reviewer: str | None = None) -> dict:
    """写一批裁决。参数含义见控制台 `EventsIn`；四个 Store：事件日志、批次台账、裁决表、产物仓。"""
    if kind == "cell_review":
        check_cell_review(log, batch, events)
    if request_id and any(e.payload.get("request_id") == request_id for e in log.read(batch)):
        return {"appended": 0, "batch": batch, "duplicate": True, "total": log.latest_seq(batch)}
    base = log.latest_seq(batch)
    evs = []
    for i, row in enumerate(sorted(events, key=lambda r: (r.get("t") or 0, str(r.get("id")))), 1):
        if not row.get("id"):
            continue
        payload = {k: v for k, v in row.items() if k not in ("id", "t")}
        if request_id:
            payload["request_id"] = request_id
        ct = payload.get("client_ts")
        if isinstance(ct, (int, float)) and not isinstance(ct, bool) and 0 < ct < 1e11:
            # 一律毫秒（2026-10-20）：09 月的夹注台发的是秒（float），vol02/03-jiazhu 327 条
            # 与别的台混在一起，按毫秒读会算出 1970 年。1e11 毫秒 = 1973 年，秒数到 5138 年才越界。
            payload["client_ts"] = int(round(ct * 1000))
        # `client_ts` / `dwell_ms` 留在 payload 里：事件的 `ts` 是**收割时间**
        # （历史 324 条只有 4 个不同值），量不出人裁一条要多久。UI 改造的验收
        # 指标就是这个耗时，没有它 D 刀无法证伪。
        ids = parse_card_id(row["id"])
        if kind == "cutline" and ids.get("page") is not None and ids.get("col") is not None:
            # 切线坐标在列图里，列窗几何一变就漂（col_h 还可能不变）；写入时顺手记下页面坐标
            # 与几何签名，评测据此换算到当前列图（eval/colgeom.py）。取不到几何就不记，不挡写入。
            geom = current_geom(products, ids.get("book") or "", ids["page"], ids["col"])
            payload = {**payload, **stamp(payload, geom)}
        evs.append(make_event(batch, base + i, kind,   # type: ignore[arg-type]
                              EventTarget(step=step, unit=unit, key=row["id"],
                                          anchor=product_anchor(products, step, ids), **ids),
                              payload, source_format="server", reviewer=reviewer))
    enrich_events(evs)   # 人裁带锚：重切后靠它找回是哪个字（总览/15）
    n = log.append(evs)
    b = batches.get(batch)
    if b is None:
        # **批次不存在就自动登记**（2026-09-04 修）。控制台的定字裁决直接 POST
        # 到这里，此前只写事件、不建批次，于是「收割」那块的批次下拉是空的，
        # 人裁完了却没法点「按路由表消费」——看着像「必须全部审完才行」，
        # 其实是登记漏了。批次是台账（谁裁的、多少条、消费了没），不是闸。
        b = Batch(id=batch, title=batch, step=step, kind=kind, transport="server", status="open",
                  notes="控制台直连裁决自动登记")
    if b.status == "draft":
        b.status = "open"
    out = {"appended": n, "batch": batch}
    if consume and n and is_label_batch(batch, batches.root):
        # L3 补标签批（`guji label-batch make` 冻结了卡片文件）：**只写事件，不消费**。
        # 路由表会把 cutline/glued/none 事件落进工作区裁决表并把 Step3/Step2 产物标 invalidated——
        # 补标签不该动现行产物；收割走 `guji label-batch harvest`，直接进 dataset。
        out["consume_skipped"] = "L3 补标签批：只写事件，不自动消费（收割用 guji label-batch harvest）"
    elif consume and n:
        # 写完直接消费（见控制台 EventsIn.consume）。**失败不抛**：事件已经落盘，
        # 消费只是把它送进字形库/金标，出了岔子在「收割与消费」那块补跑即可——
        # 让整个写入报错会让人以为裁决没保存，那才是真的坏。
        try:
            table = RouteTable.load(log.root / "routes.yaml")
            # 只消费刚写进来的这几条（见 route_and_consume 的 event_ids）
            res = route_and_consume(log, batch, table, verdicts, event_ids={e.id for e in evs})
            out["consumed"] = [
                {"consumer": x["consumer"], "added": x["added"],
                 "skipped": x["skipped"], "errors": x["errors"][:3]}
                for x in res["results"] if x["events"]]
            out["unrouted"] = res["unrouted"]
        except Exception as exc:                       # noqa: BLE001
            out["consume_error"] = f"{type(exc).__name__}: {exc}"
    # 批次计数只在最后刷一次（原来消费前后各刷一次，一次 0.3 s）；refresh_counts 自己会 save
    batches.refresh_counts(b, log)
    out["total"] = b.n_events
    return out
