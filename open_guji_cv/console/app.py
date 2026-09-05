"""控制台 FastAPI 应用。

路由（P0）：
    GET  /api/books  /api/pipelines  /api/steps            注册表
    GET  /api/status?book=&pipeline=&pages=                每步每页 fresh/stale/missing/failed/blocked
    POST /api/runs   GET /api/runs  GET /api/runs/{id}     任务
    POST /api/runs/{id}/cancel   GET /api/runs/{id}/log    取消 / SSE 日志
    GET  /api/products/{book}/{step}/{key}                 数值产物 JSON
    GET  /api/overlay/{book}/{step}/{page}.png             原图叠产物
    GET  /api/raw/{book}/{page}.png                        原图缩略
    GET  /api/cache/{book}/{kind}/{key}.png                缓存图像（缺了现算）
    GET  /                                                 静态前端
"""

from __future__ import annotations

import io
import json
from functools import lru_cache
import threading
import time
import webbrowser
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from .jobs import TERMINAL, JobRunner, JobSpec
from ..feedback.consumers import route_and_consume
from ..feedback.events import EventLog, EventTarget, make_event
from ..feedback.harvest import harvest_text
from ..feedback.routes import RouteTable
from ..gold.store import GoldStore
from ..review.batches import Batch, BatchStore, render_registry_markdown
from ..core.anchor import x_tr_to_tl
from ..core.book import list_books, load_book
from ..core.engine import Engine
from ..core.pipeline import list_pipelines, load_pipeline
from .. import steps as _steps  # noqa: F401  —— 注册全部 Step 与产物种类
from ..core.spec import cell_key, page_key
from ..core.step import STEPS, KINDS, RunContext
from ..products.cache import ImageCache
from ..products.store import ProductStore

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="open-guji-cv 控制台", version="0.1")
runner = JobRunner()
_engines_lock = threading.Lock()


def _engine(book: str, pipeline: str) -> Engine:
    try:
        return Engine(load_book(book), load_pipeline(pipeline), log=lambda s: None)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


# ── 注册表 ───────────────────────────────────────────────────────────
@app.get("/api/books")
def api_books() -> list[dict]:
    return [load_book(b).to_dict() for b in list_books()]


@app.get("/api/pipelines")
def api_pipelines() -> list[dict]:
    return [load_pipeline(p).to_dict() for p in list_pipelines()]


@app.get("/api/steps")
def api_steps() -> list[dict]:
    import open_guji_cv.steps  # noqa: F401
    return [s.describe() for s in STEPS.values()]


@app.get("/api/kinds")
def api_kinds() -> list[dict]:
    import open_guji_cv.steps  # noqa: F401
    return [{"id": k.id, "title": k.title, "storage": k.storage, "unit": k.unit,
             "coord_space": k.coord_space} for k in KINDS.values()]


# ── 状态 ─────────────────────────────────────────────────────────────
@app.get("/api/status")
def api_status(book: str, pipeline: str = "keben_body_v2", pages: str = "dev_set",
               param_json: str = "") -> dict:
    """状态是**相对某套参数**的。

    用参数覆盖跑出来的产物，在默认参数视角下永远显示「过期」——指纹里含参数，
    这是对的。所以查状态时要能带上同一套覆盖，否则跑完照样满屏黄，人会以为没跑成。
    """
    overrides = None
    if param_json:
        try:
            overrides = json.loads(param_json)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"参数 JSON 不合法: {e}") from e
    try:
        eng = Engine(load_book(book), load_pipeline(pipeline), params=overrides,
                     log=lambda s: None)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except KeyError as e:
        raise HTTPException(400, f"参数覆盖里有未知步骤: {e}") from e
    try:
        pg = eng.book.resolve_pages(pages)
    except ValueError as e:
        raise HTTPException(400, f"页号表达式错误: {e}") from e
    st = eng.status(pages=pg)
    st["params"] = overrides or {}
    st["running"] = (runner.running().to_dict() if runner.running() else None)
    return st


# ── 任务 ─────────────────────────────────────────────────────────────
class RunRequest(BaseModel):
    book: str
    pipeline: str = "keben_body_v2"
    from_step: str | None = None
    to_step: str | None = None
    pages: str = "dev_set"
    force: bool = False
    params: dict = {}


@app.post("/api/runs")
def api_run(req: RunRequest) -> dict:
    eng = _engine(req.book, req.pipeline)            # 校验 book / pipeline / 步骤范围
    try:
        eng.pipeline.slice(req.from_step, req.to_step)
        eng.book.resolve_pages(req.pages)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    job = runner.submit(JobSpec(book=req.book, pipeline=req.pipeline, from_step=req.from_step,
                                to_step=req.to_step, pages=req.pages, force=req.force,
                                params=req.params))
    return job.to_dict()


@app.get("/api/runs")
def api_runs(limit: int = 50) -> list[dict]:
    return runner.list(limit)


@app.get("/api/runs/{job_id}")
def api_run_get(job_id: str) -> dict:
    job = runner.get(job_id)
    if not job:
        raise HTTPException(404, "没有这个任务")
    return job.to_dict()


@app.post("/api/runs/{job_id}/cancel")
def api_run_cancel(job_id: str) -> dict:
    return {"ok": runner.cancel(job_id)}


def _tail_log(job_id: str) -> Iterator[bytes]:
    job = runner.get(job_id)
    if not job:
        yield b"data: " + json.dumps({"type": "error", "line": "没有这个任务"}).encode() + b"\n\n"
        return
    path = runner.log_path(job_id)
    pos = 0
    last_beat = time.time()
    while True:
        if path.exists():
            with open(path, "rb") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            for line in chunk.decode("utf-8", errors="replace").splitlines():
                if line.strip():
                    yield b"data: " + json.dumps({"type": "line", "line": line}, ensure_ascii=False).encode() + b"\n\n"
        job = runner.get(job_id)
        if job and job.status in TERMINAL:
            yield b"data: " + json.dumps({"type": "complete", **job.to_dict()}, ensure_ascii=False).encode() + b"\n\n"
            return
        if time.time() - last_beat > 15:
            yield b": keepalive\n\n"
            last_beat = time.time()
        time.sleep(0.4)


@app.get("/api/runs/{job_id}/log")
def api_run_log(job_id: str) -> StreamingResponse:
    return StreamingResponse(_tail_log(job_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/runs/{job_id}/log.txt")
def api_run_log_text(job_id: str) -> Response:
    path = runner.log_path(job_id)
    if not path.exists():
        raise HTTPException(404, "还没有日志")
    return Response(path.read_text(encoding="utf-8", errors="replace"), media_type="text/plain; charset=utf-8")


# ── 产物 ─────────────────────────────────────────────────────────────
@app.get("/api/products/{book}/{step}/{key}")
def api_product(book: str, step: str, key: str) -> dict:
    d = ProductStore().read_raw(book, step, key)
    if d is None:
        raise HTTPException(404, "没有这份产物")
    entry = ProductStore().manifest(book, step).get(key)
    return {"book": book, "step": step, "key": key,
            "manifest": (entry.__dict__ if entry else None), "products": d}


@app.get("/api/manifest/{book}/{step}")
def api_manifest(book: str, step: str) -> dict:
    m = ProductStore().manifest(book, step).all()
    return {k: v.__dict__ for k, v in m.items()}


def _png(img: np.ndarray, scale: float | None = None) -> Response:
    if scale and scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(500, "编码失败")
    return Response(buf.tobytes(), media_type="image/png",
                    headers={"Cache-Control": "max-age=60"})


@app.get("/api/raw/{book}/{page}.png")
def api_raw(book: str, page: int, scale: float = 0.35) -> Response:
    b = load_book(book)
    p = b.raw_path(page)
    if not p.exists():
        raise HTTPException(404, "原图缺失")
    img = cv2.imread(str(p))
    return _png(img, scale)


@app.get("/api/cache/{book}/{kind}/{key}.png")
def api_cache(book: str, kind: str, key: str) -> Response:
    import open_guji_cv.steps  # noqa: F401
    if kind not in KINDS or KINDS[kind].storage != "image_cache":
        raise HTTPException(404, "不是缓存图像种类")
    ctx = RunContext(load_book(book), ProductStore(), ImageCache(), log=lambda s: None)
    try:
        path = ctx.materialize(kind, key)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(404, f"拿不到图像: {e}") from e
    return FileResponse(path, media_type="image/png")


# ── 叠图 ─────────────────────────────────────────────────────────────
def _draw_vline(img: np.ndarray, v: dict, W: int, H: int, color, thick: int = 3) -> None:
    pts = []
    for y in range(0, H, 16):
        if v.get("k2") is None or y <= v["y1"]:
            x = v["x_at_top"] + v["slope"] * y
        elif y <= v["y2"]:
            x = v["x_at_top"] + v["slope"] * v["y1"] + v["k2"] * (y - v["y1"])
        else:
            x = (v["x_at_top"] + v["slope"] * v["y1"] + v["k2"] * (v["y2"] - v["y1"])
                 + v["k3"] * (y - v["y2"]))
        pts.append((int(round(x_tr_to_tl(x, W))), y))
    cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, color, thick)


def _overlay(book: str, step: str, page: int) -> np.ndarray:
    b = load_book(book)
    st = ProductStore()
    img = cv2.imread(str(b.raw_path(page)))
    if img is None:
        raise HTTPException(404, "原图缺失")
    H, W = img.shape[:2]
    d = st.read_raw(book, step, page_key(page))
    if d is None:
        raise HTTPException(404, "没有这份产物")
    if step == "border_detect":
        bd = d["borders"]
        for v in bd["verticals"]:
            _draw_vline(img, v, W, H, (0, 0, 255))
        for h in (bd["top"], bd["bottom"]):
            p0 = (W - 1, int(round(h["y_at_right"])))
            p1 = (0, int(round(h["y_at_right"] + h["slope"] * (W - 1))))
            cv2.line(img, p0, p1, (255, 0, 0), 3)
        for hr in bd.get("head_raise", []):
            cv2.putText(img, f"HR c{hr['col']}", (W // 2, int(hr["inner_y"])), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, (0, 140, 255), 3)
    elif step == "column_warp":
        for c in d["column_windows"]["columns"]:
            _draw_vline(img, c["left_line"], W, H, (0, 0, 255), 2)
            _draw_vline(img, c["right_line"], W, H, (0, 0, 255), 2)
            y0, y1 = int(c["top_y"]), int(c["bottom_y"])
            xr = int(round(x_tr_to_tl(c["right_line"]["x_at_top"], W)))
            cv2.putText(img, f"c{c['col']}", (xr - 60, max(30, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (0, 140, 255), 2)
    elif step == "column_gate":
        gm = d["gate_manifest"]
        for c in gm["columns"]:
            color = (0, 160, 0) if c["admitted"] else (0, 0, 220)
            cv2.putText(img, f"c{c['col']} {'ok' if c['admitted'] else 'x'}", (40 + 250 * (c["col"] - 1), 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
        cv2.putText(img, f"period {gm['period']} ref_w {gm['ref_w']} {' | '.join(gm['reject'])}",
                    (40, H - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 220), 2)
    elif step == "row_segment":
        for col in d["cells"]["columns"]:
            for c in col["cells"]:
                q = c.get("quad_page")
                if not q:
                    continue
                pts = np.array([(int(round(x_tr_to_tl(x, W))), int(round(y))) for x, y in q], dtype=np.int32)
                color = {"char": (0, 160, 0), "blank": (160, 160, 160)}.get(c["kind"], (200, 0, 200))
                cv2.polylines(img, [pts], True, color, 2)
    elif step == "cell_shrink":
        for col in d["char_index"]["columns"]:
            for c in col["chars"]:
                bb = c.get("bbox_page")
                if not bb:
                    continue
                x0, y0, x1, y1 = bb
                X0, X1 = int(round(x_tr_to_tl(x1, W))), int(round(x_tr_to_tl(x0, W)))
                color = (0, 0, 220) if c["flags"] else (0, 160, 0)
                cv2.rectangle(img, (X0, int(y0)), (X1, int(y1)), color, 2)
    else:
        raise HTTPException(404, f"{step} 还没有叠图画法")
    return img


@app.get("/api/overlay/{book}/{step}/{page}.png")
def api_overlay(book: str, step: str, page: int, scale: float = 0.35) -> Response:
    return _png(_overlay(book, step, page), scale)


# ── 反馈：批次 / 事件 / 收割 / 路由 ──────────────────────────────────
_log = EventLog()
_batches = BatchStore()
_gold = GoldStore()


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


@app.get("/api/batches")
def api_batches() -> list[dict]:
    out = []
    for b in _batches.list():
        out.append(_batches.refresh_counts(b, _log).to_dict())
    return out


@app.post("/api/batches")
def api_batch_create(req: BatchCreate) -> dict:
    if _batches.get(req.id):
        raise HTTPException(409, f"批次 {req.id} 已存在")
    b = Batch(**req.model_dump())
    _batches.save(b)
    return b.to_dict()


@app.get("/api/batches/{batch_id}")
def api_batch_get(batch_id: str) -> dict:
    b = _batches.get(batch_id)
    if not b:
        raise HTTPException(404, "没有这个批次")
    b = _batches.refresh_counts(b, _log)
    d = b.to_dict()
    ok, why = b.can_publish()
    d["can_publish"], d["publish_block_reason"] = ok, why
    d["events"] = [e.model_dump(mode="json") for e in _log.read(batch_id)][-200:]
    return d


@app.post("/api/events")
def api_events(req: EventsIn) -> dict:
    """审查页直连写入。seq 从当前最大值续，保证同批不撞号。"""
    base = _log.latest_seq(req.batch)
    evs = []
    for i, row in enumerate(sorted(req.events, key=lambda r: (r.get("t") or 0, str(r.get("id")))), 1):
        if not row.get("id"):
            continue
        payload = {k: v for k, v in row.items() if k not in ("id", "t")}
        # `client_ts` / `dwell_ms` 留在 payload 里：事件的 `ts` 是**收割时间**
        # （历史 324 条只有 4 个不同值），量不出人裁一条要多久。UI 改造的验收
        # 指标就是这个耗时，没有它 D 刀无法证伪。
        from ..feedback.harvest import parse_card_id
        evs.append(make_event(req.batch, base + i, req.kind,   # type: ignore[arg-type]
                              EventTarget(step=req.step, unit=req.unit, key=row["id"],
                                          **parse_card_id(row["id"])),
                              payload, source_format="server"))
    n = _log.append(evs)
    b = _batches.get(req.batch)
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
    _batches.refresh_counts(b, _log)
    _batches.save(b)
    return {"appended": n, "batch": req.batch, "total": len(_log.read(req.batch))}


@app.get("/api/events")
def api_events_list(batch: str | None = None, limit: int = 200) -> list[dict]:
    evs = _log.read(batch) if batch else sorted(_log.iter_all(), key=lambda e: e.order)
    return [e.model_dump(mode="json") for e in evs[-limit:]]


class HarvestIn(BaseModel):
    batch: str
    step: str
    unit: str = "page"
    kind: str = "verdict"
    content: str              # 读回的 HTML / JSONL / 日志文本


@app.post("/api/batches/{batch_id}/harvest")
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
    existing = _log.read(batch_id)
    if existing:
        have = {e.target.key for e in existing}
        base = _log.latest_seq(batch_id)
        fresh = [e for e in evs if e.target.key not in have]
        evs = [make_event(batch_id, base + i, e.kind, e.target, e.payload,
                          e.actor, e.source_format, e.ts)
               for i, e in enumerate(fresh, 1)]
    n = _log.append(evs)
    b = _batches.get(batch_id)
    if b:
        b.status = "harvested" if n or b.n_events else b.status
        import time as _t
        b.harvested_at = _t.time()
        _batches.refresh_counts(b, _log)
    return {"parsed": len(evs), "appended": n, "total": len(_log.read(batch_id))}


@app.post("/api/batches/{batch_id}/route")
def api_route(batch_id: str, dry_run: bool = False) -> dict:
    table = RouteTable.load(_log.root / "routes.yaml")
    out = route_and_consume(_log, batch_id, table, _gold, dry_run=dry_run)
    b = _batches.get(batch_id)
    if b:
        _batches.refresh_counts(b, _log)
    return out


@app.get("/api/gold")
def api_gold(shard: str | None = None, limit: int = 300) -> dict:
    if shard:
        return {"summary": _gold.summary(shard), "carrier": _gold.carrier(shard),
                "items": [i.model_dump(mode="json", exclude_none=True)
                          for i in _gold.list(shard)][:limit]}
    out = []
    for s in _gold.shards():
        d = _gold.summary(s)
        d["carrier"] = _gold.carrier(s)
        out.append(d)
    return {"shards": out}


# ── 定字审查（C2：审查搬进控制台，不再走外部 artifact）────────────────
#
# 用户 2026-09-04 定：「审查也放控制台。之前的审查页需要复用的话，也迁移到
# 控制台。」这一组 API 就是那件事的后端：待审卡片从 `seed_admit` 产物来，
# 裁决直接 POST /api/events（既有接口），再走既有的路由 → glyphdb_admit。
# **不新造协议**——事件信封、批次登记、路由表全部沿用。


@app.get("/api/review/cards")
def api_review_cards(book: str, pages: str = "dev_set", limit: int = 400,
                     only: str = "review") -> dict:
    """待审卡片：一格一张，带图块 URL、库/OCR/上下文三路证据与疑问。

    `only`：review = 只出人审的（默认）；auto = 只出自动进库的（抽查用）；
    all = 全出。**抽查自动档是必要的**——只看人审那批，永远只能证明
    「拿不准的我确实拿不准」，证不出自动那批有没有错（那正是 100% 准确率
    这个数字要防的自证）。
    """
    from ..core.book import load_book
    st = ProductStore()
    bk = load_book(book)
    pgs = bk.resolve_pages(pages)
    out: list[dict] = []
    for pg in pgs:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        m = st.read(book, "glyph_match", page_key(pg), "glyph_match")
        d = st.read(book, "context_decide", page_key(pg), "context_decision")
        if a is None:
            continue
        mm = {r.id: r for cc in (m.columns if m else []) for r in cc.chars}
        dd = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
        for cc in a.columns:
            if not cc.ok:
                continue
            for r in cc.chars:
                if only == "review" and r.admit:
                    continue
                if only == "auto" and not r.admit:
                    continue
                mr, dr = mm.get(r.id), dd.get(r.id)
                key = cell_key(pg, cc.col, r.slot) + (r.sub or "")
                out.append({
                    "id": r.id, "page": pg, "col": cc.col, "slot": r.slot,
                    "patch": f"/api/cache/{book}/char_patch/{key}.png",
                    "admit": r.admit, "channel": r.channel, "char": r.char,
                    "doubts": r.doubts,
                    "db": {"verdict": mr.verdict, "cov": round(mr.cov, 4),
                           "wmax": round(mr.wmax, 1),
                           "candidates": mr.candidates[:5]} if mr else None,
                    "ocr": (r.evidence or {}).get("ocr", []),
                    "ctx": {"char": dr.char, "margin": dr.margin,
                            "source": dr.source} if dr else None,
                })
                if len(out) >= limit:
                    return {"book": book, "cards": out, "truncated": True}
    return {"book": book, "cards": out, "truncated": False}


@app.get("/api/quality")
def api_quality(book: str = "vol01", pages: str = "dev_set") -> dict:
    """**质量看板**：当前准确率 + 缺陷聚集在哪。

    人裁完之后最该回答两个问题——「准了没有」和「下一刀该切哪」。此前两个都
    要手写脚本查，这个接口把它们做成一次调用。

    - **准确率**：拿整理本自动金标（`gold/v2_align`）对当前定字，按通道分层。
      金标只覆盖锚得上的页，所以同时报覆盖率，别拿它当全量准确率。
    - **缺陷聚集**：人裁标的切分缺陷按 页 / 列 / slot 聚。**孤例是个案，
      扎堆才是系统性问题**——v1 时代 `report_intrusions.py` 就是靠列级聚集
      找出「13 列整列偏移」的（手册「版面线侵入」一节）。
    """
    from ..core.book import load_book
    from ..gold.v2_align import align_book
    import collections

    store = ProductStore()
    bk = load_book(book)
    pgs = bk.resolve_pages(pages)

    # ── 准确率（对整理本金标）─────────────────────────────
    golds = align_book(book, pgs, store)
    gold = {c.id: c for g in golds if g.anchored for c in g.chars}
    by_ch: dict[str, list[int]] = {}
    errors: list[dict] = []
    n_total = 0
    for pg in pgs:
        a = store.read(book, "seed_admit", page_key(pg), "seed_admit")
        d = store.read(book, "context_decide", page_key(pg), "context_decision")
        if a is None:
            continue
        dd = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
        for cc in a.columns:
            for r in cc.chars:
                n_total += 1
                g = gold.get(r.id)
                if g is None:
                    continue
                pred = r.char if r.admit else (dd[r.id].char if r.id in dd else None)
                if pred is None:
                    continue
                k = r.channel if r.admit else "人审"
                slot = by_ch.setdefault(k, [0, 0])
                ok = pred == g.shape
                slot[0] += ok
                slot[1] += 1
                if not ok:
                    errors.append({"id": r.id, "pred": pred, "gold": g.shape,
                                   "channel": k, "cov": (r.evidence or {}).get("cov")})
    acc = [{"channel": k, "ok": v[0], "n": v[1], "acc": round(v[0] / v[1], 4)}
           for k, v in sorted(by_ch.items(), key=lambda x: -x[1][1])]
    n_gold = sum(v[1] for v in by_ch.values())
    n_ok = sum(v[0] for v in by_ch.values())

    # ── 缺陷聚集（人裁标的切分问题）───────────────────────
    from ..gold.store import GoldStore
    gs = GoldStore()
    page_c: collections.Counter = collections.Counter()
    col_c: collections.Counter = collections.Counter()
    slot_c: collections.Counter = collections.Counter()
    qual_c: collections.Counter = collections.Counter()
    n_def = 0
    try:
        for it in gs.list("char-segmentation/instances"):
            q = (it.expected or {}).get("quality")
            if q not in ("truncated", "contaminated"):
                continue
            an = it.anchor
            if getattr(an, "book", None) != book or getattr(an, "page", None) not in pgs:
                continue
            n_def += 1
            qual_c[q] += 1
            page_c[an.page] += 1
            if an.col is not None:
                col_c[an.col] += 1
            if an.slot is not None:
                slot_c[an.slot] += 1
    except Exception:
        pass

    def top(c, k=6):
        return [{"key": str(a), "n": b} for a, b in c.most_common(k)]

    return {
        "book": book, "pages": len(pgs),
        "accuracy": {"overall": round(n_ok / n_gold, 4) if n_gold else None,
                      "n_gold": n_gold, "n_total": n_total,
                      "gold_coverage": round(n_gold / n_total, 4) if n_total else None,
                      "by_channel": acc, "errors": errors[:20]},
        "defects": {"n": n_def, "by_quality": top(qual_c),
                     "by_page": top(page_c), "by_col": top(col_c),
                     "by_slot": top(slot_c)},
    }


@app.get("/api/rulers")
def api_rulers(book: str = "vol01", pages: str = "dev_set") -> dict:
    """**四把尺子**：Step 1-4 「离 100% 还差什么」。

    以前这四个数是临时脚本算完抄进 `.claude/doc/*.md` 的快照，文档一滞后
    就没人知道当下真值。改了一刀有没有变好，恰恰要看这四个数的**变化**。

    口径见 `eval/rulers.py`，照抄 pipeline_review 的定义表，不另立标准。
    """
    from ..core.book import load_book
    from ..eval.rulers import measure
    bk = load_book(book)
    return measure(book, bk.resolve_pages(pages), ProductStore())


@app.get("/api/rare/{book}/{page}/{col}/{slot}")
def api_rare_candidates(book: str, page: int, col: int, slot: int,
                        sub: str = "", k: int = 10) -> dict:
    """**生僻字面板**：字体模板 top-k 候选 + 每个候选的 IDS / 频次 / 码点。

    用户的原话：「碰到生僻字，我需要去字统网查阅是否有一致的 unicode 已收字，
    如果没有完全一致的，找最像的，还要看意思是否合适，查词典。」

    这一步要消掉的就是那趟外链之旅。库/OCR/上下文三路都给不出答案时
    （rare-char 集上那 14 条），字体模板 top-10 召回 **78.6%**、命中时中位
    名次 1——人在候选里点一下即可。每个候选带：

    - **IDS 拆字**（⿰言俞 vs ⿰言侖）：对着图一眼就能比结构；
    - **本书频次**：整理本里出现过几次，0 次的多半是异体或刻本特有字；
    - **码点**：要不要造字、是不是扩展区字，看一眼就知道；
    - **zi.tools 深链**：只链接不抓取（该站无授权条款，见
      glyph_db_expansion_research §1）。

    字体候选是**纯形状**证据，没有文本兜底，所以只出候选、永不放行。
    """
    import cv2

    from ..clustering.font_candidates import book_charset, candidates
    from ..clustering.ids_guard import ids_of
    from ..clustering.normalize import normalize_patch
    from ..products.cache import ImageCache
    from ..steps.seed_admit import DEFAULT_CORPUS

    ck = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
    path = ImageCache().get(book, "char_patch", ck)
    if path is None:
        raise HTTPException(404, f"没有字块 {ck}")
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise HTTPException(404, f"字块读不出来 {ck}")
    # ── 两档字表：小表定名次，大表保召回 ──────────────────
    #
    # 字表不能只取整理本用字：**最生僻的字恰恰是整理本里没有的那些**
    # ——刻本刻「㕔」而整理本作「廳」、刻「䙝」而整理本作「褻」，整理本里
    # 频次都是 0，只用整理本字表永远召不回来（实测 㕔 从名次 1 掉到榜外）。
    #
    # 但直接并上异体展开（4636 → 20059 字）会把名次冲垮：多出来的一万五千
    # 个字大多是本书不会出现的罕用形，它们在 HOG 上与正确答案难分伯仲，
    # 于是**top-1 从 43% 掉到 29%**（rare-char 21 条实测）。用户反馈的
    # 「点生僻字查询准确率不高」就是这个。
    #
    # 试过三条都不行，记下来免得重走：
    #   本书频次加权   top3 67% → 33%（要找的字本来就罕见，频次先验反着起作用）
    #   异体身份加权   top3 67% → 62%
    #   相似度闸控扩表 从不触发（小表 top1 分数恒 >0.84，错的时候也高）
    #
    # 有效的是**位次合并**：小表 top3 占据前三名（那里最可能是对的），
    # 其后接大表结果补召回。实测 top1 43% / top10 76%，两头都拿到。
    cs_small, cs_big = _rare_charsets()
    norm = normalize_patch(img)
    a = candidates(norm, cs_small, k=max(k, 10))
    b = candidates(norm, cs_big, k=max(k, 10))
    hits, seen = [], set()
    for h in list(a[:3]) + list(b) + list(a[3:]):
        if h.char in seen:
            continue
        seen.add(h.char)
        hits.append(h)
        if len(hits) >= k:
            break
    freq = _corpus_freq(DEFAULT_CORPUS)
    return {"id": f"{book}:{page}:{col}:{slot}{sub or ''}",
            "candidates": [{
                "char": h.char, "score": round(h.score, 4), "font": h.font,
                "ids": ids_of(h.char),
                "freq": freq.get(h.char, 0),
                "cp": f"U+{ord(h.char):04X}" if len(h.char) == 1 else "",
                "zi": f"https://zi.tools/zi/{h.char}",
            } for h in hits]}


@lru_cache(maxsize=1)
def _rare_charsets() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """两档字表各算一次。元组身份稳定，`font_candidates._index` 的缓存才命中。

    此前每次请求重新拼 `tuple(sorted(big))`，lru_cache 按值哈希本该命中，
    但大表第一次建就是 8 分钟，且进程重启就丢——现在索引本身也落盘了
    （见 font_candidates._index）。
    """
    from ..clustering.font_candidates import book_charset
    from ..steps.seed_admit import DEFAULT_CORPUS
    small = tuple(book_charset(DEFAULT_CORPUS))
    big = set(small)
    try:
        from ..variants import variants_of
        for ch in small:
            big.update(v[0] if isinstance(v, (tuple, list)) else v
                       for v in (variants_of(ch) or ()))
    except Exception:
        pass
    return small, tuple(sorted(big))


def _warm_font_index() -> None:
    """后台线程预热字体索引。首次建大表要几分钟，别让第一个点按钮的人等。"""
    try:
        from ..clustering.font_candidates import warm
        warm(list(_rare_charsets()))
    except Exception:
        pass


@lru_cache(maxsize=2)
def _corpus_freq(path: str) -> dict:
    from collections import Counter
    f = Path(path)
    if not f.exists():
        return {}
    return Counter(ch for ch in f.read_text(encoding="utf-8")
                   if "㐀" <= ch <= "鿿")


@app.get("/api/round")
def api_round(book: str = "vol01", pages: str = "") -> dict:
    """**一轮体检**：四个判据 + 下一批页码，判断跟命令行同一套。

    判据与阈值在 `eval/round_check.py`（唯一事实源），`scripts/round_check.py`
    与这里共用——阈值只写一处，免得过一阵子两边对不上。

    含义与「什么时候修算法」见 `.claude/doc/review_loop_sop.md`：
    绿=继续跑，黄=记着别动算法（样本不够时改算法是在拟合噪声），红=停下修。
    """
    from ..eval import round_check as rc
    from ..core.book import load_book

    out = {"next": rc.next_batch(book)}
    if pages:
        pgs = load_book(book).resolve_pages(pages)
        out.update(rc.check(book, pgs))
    return out


@app.get("/api/review/verdicts")
def api_review_verdicts(batch: str) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。

    裁决本来就落成事件了（`/api/events`），但前端只在内存里记 `RV.verdicts`，
    一刷新就空。这个接口把事件读回成同样的形状，载入卡片时合并进去。

    同一 id 多次裁决按 (batch, seq) 升序**后到覆盖**——沿用 seed_queue 的
    纪律，人改主意时最后一次说了算。
    """
    out: dict[str, dict] = {}
    for e in sorted(_log.read(batch), key=lambda x: (x.batch, x.seq)):
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


@app.get("/api/review/column/{book}/{page}/{col}")
def api_review_column(book: str, page: int, col: int) -> dict:
    """一列的上下文：定字串 + 每格的 slot，供审查页显示「这个字在哪句话里」。

    单看一个裁紧图块判不出形近字——`confusable-context` 154 题实测，字形层
    top-1 只有 64.3%，而 n-gram 95.5%、大模型 98.7%。人也一样需要上下文。

    ## 空位要用库/OCR 兜底填上（2026-09-04 改）

    原先只印 Step6 的定字，弃权位一律「□」。可**待审的位恰恰全是弃权位**
    ——人看到的就是一串「□□□」，等于没有上下文，读文定字也就无从谈起。
    现在逐级兜底：定字 → 库 top1 → OCR top1，并逐位标出它是不是待审、
    以及字从哪来，前端据此把待审位高亮、把兜底字标灰。
    """
    st = ProductStore()
    d = st.read(book, "context_decide", page_key(page), "context_decision")
    m = st.read(book, "glyph_match", page_key(page), "glyph_match")
    o = st.read(book, "ocr_candidates", page_key(page), "ocr_candidates")
    a = st.read(book, "seed_admit", page_key(page), "seed_admit")
    if d is None and m is None:
        return {"text": "", "slots": []}
    dm = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
    om = {r.id: r for cc in (o.columns if o else []) for r in cc.chars}
    am = {r.id: r for cc in (a.columns if a else []) for r in cc.chars}
    src_col = (m.column(col) if m else None) or (d.column(col) if d else None)
    if src_col is None:
        return {"text": "", "slots": []}
    out = []
    for r in sorted(src_col.chars, key=lambda x: (x.slot, x.sub or "")):
        dd, oo, aa = dm.get(r.id), om.get(r.id), am.get(r.id)
        ch, src = None, ""
        if dd is not None and dd.char:
            ch, src = dd.char, (dd.source or "context")
        elif getattr(r, "candidates", None):
            ch, src = r.candidates[0][0], "db"
        elif oo is not None and oo.topk:
            ch, src = oo.topk[0][0], "ocr"
        out.append({"slot": r.slot, "sub": r.sub, "id": r.id,
                    "char": ch, "source": src,
                    # 待审 = seed_admit 没放行；前端据此高亮
                    "review": bool(aa is not None and not aa.admit)})
    return {"text": "".join(x["char"] or "□" for x in out), "slots": out}


@app.post("/api/gold/{shard:path}/migrate")
def api_gold_migrate(shard: str, dry_run: bool = False) -> dict:
    """旧载体 → items.jsonl。不删旧文件，两边并存。"""
    return _gold.migrate(shard, dry_run=dry_run)


@app.post("/api/gold/{shard:path}/drift")
def api_gold_drift(shard: str, apply: bool = False) -> dict:
    """图像指纹漂移检查：产物重生后哪些金标还成立。"""
    from ..gold.drift import check_shard, mark_drifted
    root = Path(__file__).resolve().parent.parent.parent

    def image_of(it):
        p = (it.input.get("input") or {}).get("column_image")
        if not p:
            return None
        f = root / str(p).replace("open-guji-cv ", "")
        return cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None

    rep = check_shard(shard, _gold.list(shard), image_of)
    out = rep.to_dict()
    if apply:
        out["marked_stale"] = mark_drifted(_gold, shard, rep)
    return out


@app.get("/api/evals")
def api_evals() -> list[dict]:
    from ..eval.registry import EVALS, runnable
    out = []
    for s in sorted(EVALS.values(), key=lambda x: x.id):
        ok, why = runnable(s)
        out.append({"id": s.id, "shard": s.shard, "title": s.title, "note": s.note,
                    "runnable": ok, "blocked": why, "needs": list(s.needs)})
    return out


@app.post("/api/evals/{eval_id}/run")
def api_eval_run(eval_id: str, timeout: int = 900) -> dict:
    from ..eval import run_eval
    return run_eval(eval_id, timeout=timeout).to_dict()


@app.get("/api/batches.md", response_class=Response)
def api_batches_md() -> Response:
    md = render_registry_markdown([_batches.refresh_counts(b, _log) for b in _batches.list()])
    return Response(md, media_type="text/markdown; charset=utf-8")


# ── 静态 ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def serve(port: int = 8640, open_browser: bool = True) -> None:
    import uvicorn
    url = f"http://127.0.0.1:{port}/"
    print(f"控制台: {url}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    threading.Thread(target=_warm_font_index, name="font-index-warm",
                     daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
