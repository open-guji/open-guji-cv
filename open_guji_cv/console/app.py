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
import re
from functools import lru_cache
import threading
import time
import webbrowser
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import deps
from .errors import maps_http
from .jobs import JobSpec
from .sse import sse
from ..clustering.rare_panel import (rare_batch, rare_for, rare_patch,
                                     warm_font_index)
from ..errors import EncodeFailed, ImageMissing, NotFound
from ..eval import rate_history
from ..eval.quality import quality
from ..render.overlay import overlay
from ..review.cards import cards
from ..review.group_view import group_view
from ..review.jiazhu_cards import jiazhu_segments
from ..review.verdict_view import cutline_verdicts, review_verdicts
from ..feedback.consumers import route_and_consume
from ..feedback.events import EventTarget, make_event
from ..feedback.harvest import harvest_text
from ..feedback.routes import RouteTable
from ..review.batches import Batch, render_registry_markdown
from ..core.anchor import x_tr_to_tl
from ..core.book import list_books, load_book
from ..core.engine import Engine
from ..core.pipeline import list_pipelines, load_pipeline
from .. import steps as _steps  # noqa: F401  —— 注册全部 Step 与产物种类
from ..core.spec import cell_key, page_key
from ..core.step import STEPS, KINDS, RunContext

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="open-guji-cv 控制台", version="0.1")
# 允许离线页面回传裁决（2026-09-06）：`scripts/build_char_review.py` 出的按字复核页是
# 单文件 HTML，用 file:// 打开，origin 是 "null"，向 127.0.0.1 发 POST 会被 CORS 拦下
# （preflight 没有 Access-Control-Allow-Origin）。控制台本来就只绑回环地址、只给本机用，
# 放开跨域不扩大暴露面——不放开的话，那些页面就只能看不能改判。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 含 file:// 的 "null" origin
    allow_credentials=False,  # 与 allow_origins=* 不能并存，也用不到 cookie
    allow_methods=["*"],
    allow_headers=["*"],
)
# 前端不再是单文件：`static/index.html` 2,331 行切成 `static/js/*.js` ＋ `static/css/*.css`
# 之后，那些文件要有人来发。此前只有 `GET /` 把 index.html 读成文本返回，没有任何
# 静态挂载——切分后的 js/css 会全部 404。挂在 /static 下，`index.html` 用
# `<script type="module" src="/static/js/main.js">` 引入。
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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
    running = deps.runner().running()
    st["running"] = running.to_dict() if running else None
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
    job = deps.runner().submit(JobSpec(
        book=req.book, pipeline=req.pipeline, from_step=req.from_step,
        to_step=req.to_step, pages=req.pages, force=req.force, params=req.params))
    return job.to_dict()


@app.get("/api/runs")
def api_runs(limit: int = 50) -> list[dict]:
    return deps.runner().list(limit)


@app.get("/api/runs/{job_id}")
def api_run_get(job_id: str) -> dict:
    job = deps.runner().get(job_id)
    if not job:
        raise HTTPException(404, "没有这个任务")
    return job.to_dict()


@app.post("/api/runs/{job_id}/cancel")
def api_run_cancel(job_id: str) -> dict:
    return {"ok": deps.runner().cancel(job_id)}


@app.get("/api/runs/{job_id}/log")
def api_run_log(job_id: str) -> StreamingResponse:
    return StreamingResponse(sse(deps.runner(), job_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/runs/{job_id}/log.txt")
def api_run_log_text(job_id: str) -> Response:
    path = deps.runner().log_path(job_id)
    if not path.exists():
        raise HTTPException(404, "还没有日志")
    return Response(path.read_text(encoding="utf-8", errors="replace"), media_type="text/plain; charset=utf-8")


# ── 产物 ─────────────────────────────────────────────────────────────
@app.get("/api/products/{book}/{step}/{key}")
def api_product(book: str, step: str, key: str) -> dict:
    d = deps.product_store().read_raw(book, step, key)
    if d is None:
        raise HTTPException(404, "没有这份产物")
    entry = deps.product_store().manifest(book, step).get(key)
    return {"book": book, "step": step, "key": key,
            "manifest": (entry.__dict__ if entry else None), "products": d}


@app.get("/api/manifest/{book}/{step}")
def api_manifest(book: str, step: str) -> dict:
    m = deps.product_store().manifest(book, step).all()
    return {k: v.__dict__ for k, v in m.items()}


def _png(img: np.ndarray, scale: float | None = None) -> Response:
    if scale and scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise EncodeFailed("编码失败")
    return Response(buf.tobytes(), media_type="image/png",
                    headers={"Cache-Control": "max-age=60"})


@app.get("/api/raw/{book}/{page}.png")
@maps_http
def api_raw(book: str, page: int, scale: float = 0.35) -> Response:
    b = load_book(book)
    p = b.raw_path(page)
    if not p.exists():
        raise ImageMissing("原图缺失")
    img = cv2.imread(str(p))
    return _png(img, scale)


@app.get("/api/cache/{book}/{kind}/{key}.png")
def api_cache(book: str, kind: str, key: str) -> Response:
    import open_guji_cv.steps  # noqa: F401
    if kind not in KINDS or KINDS[kind].storage != "image_cache":
        raise HTTPException(404, "不是缓存图像种类")
    ctx = RunContext(load_book(book), deps.product_store(), deps.image_cache(),
                     log=lambda s: None)
    try:
        path = ctx.materialize(kind, key)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(404, f"拿不到图像: {e}") from e
    return FileResponse(path, media_type="image/png")


# ── 叠图 ─────────────────────────────────────────────────────────────
@app.get("/api/overlay/{book}/{step}/{page}.png")
@maps_http
def api_overlay(book: str, step: str, page: int, scale: float = 0.35) -> Response:
    return _png(overlay(book, step, page, deps.product_store()), scale)


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


@app.get("/api/batches")
def api_batches() -> list[dict]:
    out = []
    for b in deps.batch_store().list():
        out.append(deps.batch_store().refresh_counts(b, deps.event_log()).to_dict())
    return out


@app.post("/api/batches")
def api_batch_create(req: BatchCreate) -> dict:
    if deps.batch_store().get(req.id):
        raise HTTPException(409, f"批次 {req.id} 已存在")
    b = Batch(**req.model_dump())
    deps.batch_store().save(b)
    return b.to_dict()


@app.get("/api/batches/{batch_id}")
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


@app.post("/api/events")
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
        from ..feedback.harvest import parse_card_id
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


@app.get("/api/events")
def api_events_list(batch: str | None = None, limit: int = 200) -> list[dict]:
    evs = deps.event_log().read(batch) if batch else sorted(deps.event_log().iter_all(), key=lambda e: e.order)
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


@app.post("/api/batches/{batch_id}/route")
def api_route(batch_id: str, dry_run: bool = False) -> dict:
    table = RouteTable.load(deps.event_log().root / "routes.yaml")
    out = route_and_consume(deps.event_log(), batch_id, table, deps.gold_store(),
                            dry_run=dry_run)
    b = deps.batch_store().get(batch_id)
    if b:
        deps.batch_store().refresh_counts(b, deps.event_log())
    return out


@app.get("/api/gold")
def api_gold(shard: str | None = None, limit: int = 300) -> dict:
    if shard:
        return {"summary": deps.gold_store().summary(shard), "carrier": deps.gold_store().carrier(shard),
                "items": [i.model_dump(mode="json", exclude_none=True)
                          for i in deps.gold_store().list(shard)][:limit]}
    out = []
    for s in deps.gold_store().shards():
        d = deps.gold_store().summary(s)
        d["carrier"] = deps.gold_store().carrier(s)
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

    装配在 `review/cards.py`（C2 搬出去的，云端道与 CLI 直接能调）。
    """
    return cards(book, pages, limit, only, deps.product_store())


@app.get("/api/quality")
def api_quality(book: str = "vol01", pages: str = "dev_set") -> dict:
    """质量看板：当前准确率 ＋ 缺陷聚集在哪。判准在 `eval/quality.py`（C2 搬出去的），
    与 `eval/rulers.py`、`eval/round_check.py` 同级。"""
    return quality(book, pages, deps.product_store())


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
    return measure(book, bk.resolve_pages(pages), deps.product_store())


@app.get("/api/rare/{book}/{page}/{col}/{slot}")
@maps_http
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

    img = rare_patch(book, page, col, slot, sub, deps.image_cache())
    if img is None:
        raise ImageMissing(f"没有字块 p{page:04d}c{col:02d}s{slot}{sub or ''}")
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
    return {"id": f"{book}:{page}:{col}:{slot}{sub or ''}",
            "candidates": rare_for(img, k)}


class RareBatchIn(BaseModel):
    """一次问一批字位的生僻字候选。"""
    book: str
    slots: list[str]        # ["71:1:5", "71:2:3a", ...]（page:col:slot[a|b]）
    k: int = 3


@app.post("/api/rare/batch")
def api_rare_batch(req: RareBatchIn) -> dict:
    """**批量版**（2026-09-07）：一次问一批字位，字表与 CNN 索引只热一次。

    引擎在 `clustering/rare_panel.py`（C2 搬出去的）。实测一页（约 30 个待审位）
    从 ~10s 降到 ~2s。
    """
    return rare_batch(req.book, req.slots, req.k, deps.image_cache())


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


@app.get("/api/review/rate-history")
def api_rate_history(book: str = "") -> dict:
    """人审率台账（`eval/rate_history.py` 的历史 ＋ SEED）。

    体检页的 B 行只报**当下这一跑**，而这条线最该回答的是纵向问题：一册从零开始审，
    掉得多快、拐点在哪。台账把每次重跑记一行，这里读出来给前端画趋势。

    C2 之前这里是用 `importlib.spec_from_file_location` 反射进
    `scripts/track_review_rate.py` 的——全仓唯一一处「路由 import scripts/」。
    """
    rows = [r for r in rate_history.history() if not book or r.get("book") == book]
    rows.sort(key=lambda r: (r.get("book", ""), r.get("ts") or r.get("date", "")))
    return {"rows": rows}


class RateSnapIn(BaseModel):
    books: str = "vol01,vol02"
    note: str = ""


@app.post("/api/review/rate-history")
@maps_http
def api_rate_snapshot(req: RateSnapIn) -> dict:
    """记一行台账（体检页的「记一笔」按钮）。重跑完顺手点，别再事后翻聊天记录。"""
    st = deps.product_store()
    out = []
    rate_history.HIST.parent.mkdir(parents=True, exist_ok=True)
    with open(rate_history.HIST, "a", encoding="utf-8") as f:
        for b in [x.strip() for x in req.books.split(",") if x.strip()]:
            rec = rate_history.measure(b, st)
            if rec is None:
                continue
            if req.note:
                rec["note"] = req.note
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.append(rec)
    return {"added": out}


@app.get("/api/review/verdicts")
def api_review_verdicts(batch: str) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。装配在 `review/verdict_view.py`。"""
    return review_verdicts(batch, deps.event_log())


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
    st = deps.product_store()
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


# ── 拖切线：粘连格线的理想切点金标 ─────────────────────────────────
#
# 用户 2026-09-05：「先让我添加一些金标，确定理想位置，再想算法。」
# R2s（真粘连）格线两侧都没有墨谷，投影法无解；要优化它先得有"该切在哪"的金标。
# 卡片 = 上下两格的列图裁片 + 一条可拖的横线（初值 = 现役切点）；裁决落 `cutline`
# 事件 → gold_add → char-segmentation/touching-cuts。坐标系 = 现役 Step2 列图。
_cutline_expected_cache: dict = {}


@app.get("/api/cutline/cases")
def api_cutline_cases(book: str = "vol01", pages: str = "body", limit: int = 250,
                      seed: int = 0, batch: str | None = None, skip_done: bool = True,
                      kind: str = "r2s") -> dict:
    """切线用例。pages='body' = page-type 金标判为正文的页（职名/目录页稍后）。

    `kind`：`r2s` 真粘连（切点有墨、附近无墨谷，投影法无解）；`split_char`
    切进字里（一矮一高 + 切点落在字**内部**的零墨空隙，2026-09-08 新增，
    见 `eval/touching.split_char_boundaries`）；`all` 两者都出。
    """
    from ..eval import touching as T

    bk = load_book(book)
    if pages == "body":
        pg = [p for p in T.body_pages(book)]
    else:
        pg = bk.resolve_pages(pages)
    st = deps.product_store()
    if kind == "split_char":
        cases = T.split_char_boundaries(book, pg, st)
    elif kind == "all":
        cases = T.r2s_boundaries(book, pg, st) + T.split_char_boundaries(book, pg, st)
    else:
        cases = T.r2s_boundaries(book, pg, st)
    n_all = len(cases)
    done: set[str] = set()
    if skip_done:
        done |= T.gold_ids()
        if batch:
            done |= {e.target.key for e in deps.event_log().read(batch) if e.kind == "cutline"}
    cases = [c for c in cases if c["id"] not in done]
    picked = T.pick_cases(cases, limit, seed=seed)
    # 期望字：整理本对齐金标（按页缓存，对齐 60 页约 1 分钟）
    key = (book, tuple(sorted({c["page"] for c in picked})))
    if key not in _cutline_expected_cache:
        T.attach_expected(picked, book, st)
        _cutline_expected_cache[key] = {c["id"]: (c.get("char_above", ""), c.get("char_below", "")) for c in picked}
    else:
        for c in picked:
            c["char_above"], c["char_below"] = _cutline_expected_cache[key].get(c["id"], ("", ""))
    for c in picked:
        pad = 6
        c["crop_y0"] = max(0, c["y0"] - pad)
        c["crop_y1"] = min(c["col_h"], c["y1"] + pad)
        c["img"] = (f"/api/cutline/img/{book}/{c['page']}/{c['col']}.png"
                    f"?y0={c['crop_y0']}&y1={c['crop_y1']}")
    return {"book": book, "pages": pg, "n_r2s": n_all, "n_done": len(done),
            "n": len(picked), "cases": picked}


@app.get("/api/cutline/img/{book}/{page}/{col}.png")
@maps_http
def api_cutline_img(book: str, page: int, col: int, y0: int = 0, y1: int = 0) -> Response:
    """列图的一段（上下两格 + 边距），1:1 像素，前端在上面叠可拖的横线。"""
    from ..core.spec import column_key

    path = deps.image_cache().get(book, "column_image", column_key(page, col))
    if path is None:
        raise ImageMissing("没有列图")
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("列图读不出来")
    h = img.shape[0]
    y0 = max(0, min(h - 1, y0)); y1 = max(y0 + 1, min(h, y1 or h))
    ok, buf = cv2.imencode(".png", img[y0:y1])
    if not ok:
        raise EncodeFailed("编码失败")
    return Response(content=buf.tobytes(), media_type="image/png")


@app.get("/api/jiazhu/segments")
def api_jiazhu_segments(book: str = "vol02", pages: str = "jz",
                        only: str = "all", batch: str | None = None) -> dict:
    """夹注**段**卡：一张卡 = 一段雙行小注，不是一格一张。装配在 `review/jiazhu_cards.py`。

    一段版本注 5–19 字，人一眼能读整句；逐格出卡等于把一句话拆成十几道题。
    `only`：all（默认）| review 只出含待审格的段 | auto 只出全自动的段（抽查用）。
    """
    return jiazhu_segments(book, pages, only, batch,
                           deps.product_store(), deps.event_log())


@app.get("/api/cutline/verdicts")
def api_cutline_verdicts(batch: str) -> dict:
    """读回本批已拖过的切线（刷新不重做；同 id 后到覆盖）。装配在 `review/verdict_view.py`。"""
    return cutline_verdicts(batch, deps.event_log())


@app.post("/api/gold/{shard:path}/migrate")
def api_gold_migrate(shard: str, dry_run: bool = False) -> dict:
    """旧载体 → items.jsonl。不删旧文件，两边并存。"""
    return deps.gold_store().migrate(shard, dry_run=dry_run)


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

    rep = check_shard(shard, deps.gold_store().list(shard), image_of)
    out = rep.to_dict()
    if apply:
        out["marked_stale"] = mark_drifted(deps.gold_store(), shard, rep)
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


@app.get("/api/variants/book")
@maps_http
def api_variants_book(edition: str = "") -> dict:
    """本书用字账（只读）：`config/variants/books/<edition>.json` 原样返回。

    账本由 `scripts/build_book_variants.py` 从产物 + glyph.db + 整理本语料派生，
    这里不算任何东西——控制台只是把「这本书用哪个异体」摆出来看
    （variant_strategy.md §3.2；`variant_ledger.py` 有字段说明）。
    """
    import json

    from ..variant_ledger import DEFAULT_EDITION, ledger_path

    ed = edition or DEFAULT_EDITION
    p = ledger_path(ed)
    if not p.exists():
        raise NotFound(
            f"没有用字账 {p.name}——先跑 python scripts/build_book_variants.py --edition {ed}")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/variants/groups")
@maps_http
def api_variants_groups(book: str, pages: str = "dev_set", edition: str = "",
                        limit_tiles: int = 400) -> dict:
    """组视图（variant_strategy.md §5.1）：按异体组把字位摊成「列 = 形、格 = 图块」。

    装配在 `review/group_view.py`（C2 搬出去的）——**判据 E 的分母就在那里算**。
    """
    return group_view(book, pages, edition, limit_tiles, deps.product_store())


@app.get("/api/batches.md", response_class=Response)
def api_batches_md() -> Response:
    store = deps.batch_store()
    md = render_registry_markdown([store.refresh_counts(b, deps.event_log())
                                   for b in store.list()])
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
    threading.Thread(target=warm_font_index, name="font-index-warm",
                     daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
