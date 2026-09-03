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
from ..core.spec import page_key
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
def api_status(book: str, pipeline: str = "keben_body_v2", pages: str = "dev_set") -> dict:
    eng = _engine(book, pipeline)
    try:
        pg = eng.book.resolve_pages(pages)
    except ValueError as e:
        raise HTTPException(400, f"页号表达式错误: {e}") from e
    st = eng.status(pages=pg)
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
        from ..feedback.harvest import parse_card_id
        evs.append(make_event(req.batch, base + i, req.kind,   # type: ignore[arg-type]
                              EventTarget(step=req.step, unit=req.unit, key=row["id"],
                                          **parse_card_id(row["id"])),
                              payload, source_format="server"))
    n = _log.append(evs)
    b = _batches.get(req.batch)
    if b:
        if b.status == "draft":
            b.status = "open"
        _batches.refresh_counts(b, _log)
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
def api_gold(shard: str | None = None) -> dict:
    if shard:
        return {"summary": _gold.summary(shard),
                "items": [i.model_dump(mode="json", exclude_none=True)
                          for i in _gold.list(shard)][:300]}
    return {"shards": [_gold.summary(s) for s in _gold.shards()]}


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
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
