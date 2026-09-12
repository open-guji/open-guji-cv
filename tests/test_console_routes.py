# -*- coding: utf-8 -*-
"""控制台 46 条路由的**行为快照**（C0，控制台重构 §九）。

## 这个测试是干什么的

控制台重构（`console/app.py` 1,528 行 → deps/errors/sse ＋ 11 个 router ＋
8 个搬出去的领域模块）的验收判据只有一句：**行为一模一样**。
所以动第一行之前，先把 46 条路由**各调一次**，把结果归一化后落成基线；
之后每推一步跑一遍，比对**零差异**。

**不起 uvicorn、不发 HTTP、不开浏览器**——直接调实现体。
46 条里没有一条接 `Request`、没有一条读 `app.state`（方案 §四 实测），
所以直调拿到的就是真行为。

实现体**从 `app.routes` 里按 `METHOD path` 取**（`route.endpoint`），
不写 `A.api_xxx`。这样 C3 把 46 条打散进 11 个 router、C2 把领域逻辑搬出
`console/` 之后，这个测试**一个字都不用改**——它比对的是「这个 URL 背后
的行为」，不是「这个模块里有没有这个函数名」。请求体模型同理，从实现体的
签名注解里取（`RunRequest`／`BatchCreate`／… 也会跟着 router 搬家）。

## 怎么用

```bash
export GUJI_WORKSPACE=/home/user/siku-zongmu-workspace     # 绝对路径
python -m open_guji_cv pipeline keben_body_v2 vol01 --pages 24,42   # 两页产物
.venv/bin/python -m pytest tests/test_console_routes.py -s -p no:cacheprovider
```

- 基线**不在仓里**（默认 `<临时目录>/guji_console_routes_baseline.json`，
  用 `GUJI_ROUTE_SNAP` 改路径）。理由：它绑定这台机器上的产物与库，
  入库的话别人一跑就红，而且会让 `git status` 不干净。
- 基线不存在 → 本次**落基线**并通过（打印一行提示）。存在 → 逐条比对。
- 重落基线：`GUJI_ROUTE_SNAP_WRITE=1`。
- ⚠️ `pytest` 必须带 `-s`（子会话须知 §五：不带会 `ValueError: I/O operation on closed file`）。

## 三处「天然不可比」怎么处理（方案 §九）

1. **`/api/runs` 系列**带 job id 与时间戳 → `mode="shape"`，**比结构不比值**
   （每个标量换成它的类型名，键与嵌套形状照比）。
2. **二进制响应**（`/api/cache`、`/api/overlay`、`/api/raw`、`/api/cutline/img`）
   → 比 `sha256` 与字节数，不比字节本身。
3. **产物清单里的 `ts`/`elapsed`** 等时间字段 → 换成 `<volatile>`。

## 写路由怎么做到可重复

`EventLog` / `BatchStore` / `GoldStore` 三个默认根目录**都认环境变量**
（`GUJI_FEEDBACK_DIR` / `GUJI_BATCHES_DIR` / `GUJI_DATASET_DIR`）。
本测试在 **import `console.app` 之前**把它们指到一个每次新建的临时沙箱，
于是建批次 / 写事件 / 收割 / 路由这些写操作每跑一次都从同一个空状态出发，
结果稳定，也不碰真台账。**这也是为什么 import 顺序在这里是有意义的，别挪。**
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# ── 沙箱：必须在 import console.app 之前设好（模块级单例在 import 时就构造）──
_SANDBOX_ENV = ("GUJI_FEEDBACK_DIR", "GUJI_BATCHES_DIR", "GUJI_DATASET_DIR")
_SAVED_ENV = {k: os.environ.get(k) for k in _SANDBOX_ENV}
_SANDBOX = Path(tempfile.mkdtemp(prefix="guji_console_snap_"))
os.environ["GUJI_FEEDBACK_DIR"] = str(_SANDBOX / "feedback")
os.environ["GUJI_BATCHES_DIR"] = str(_SANDBOX / "batches")
os.environ["GUJI_DATASET_DIR"] = str(_SANDBOX / "dataset")


@pytest.fixture(scope="module", autouse=True)
def _restore_sandbox_env():
    """本文件跑完把这三个环境变量还原。

    模块级设置是必须的（要赶在 import console.app 之前），但**不还原就会漏给
    后面的测试文件**：pytest 按字母序跑，`test_console_routes` 在 `test_eval_v2`
    之前，于是后者去这个已被删掉的临时沙箱里找金标，报
    「金标路径不存在: /tmp/guji_console_snap_xxxx/dataset/char-normalization」。
    2026-09-10 集成三条分支时实测到——单跑本文件看不见，跑全仓才暴露。
    """
    yield
    for k, v in _SAVED_ENV.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
for _m in [m for m in list(sys.modules) if m.startswith("open_guji_cv.console")]:
    del sys.modules[_m]

import open_guji_cv.console.app as A  # noqa: E402
from open_guji_cv.core.spec import cell_key, page_key  # noqa: E402

def _endpoints() -> dict:
    """{"GET /api/books": 实现体}。C1–C3 怎么搬，这里都取得到。

    ⚠️ **要递归**：C3 之后路由是 `include_router` 进来的，而这版 fastapi
    在 `app.routes` 里放的是 `_IncludedRouter` 包装对象、**不摊平成 APIRoute**。
    只扫一层的话 46 条会变成 0 条（本道实测踩过）。
    """
    from fastapi.routing import APIRoute

    out: dict = {}

    def walk(routes) -> None:
        for r in routes:
            if isinstance(r, APIRoute):
                for m in sorted(r.methods - {"HEAD"}):
                    out[f"{m} {r.path}"] = r.endpoint
            elif hasattr(r, "original_router"):   # fastapi 的 _IncludedRouter 包装
                walk(r.original_router.routes)
            elif hasattr(r, "routes"):            # APIRouter / Mount
                walk(r.routes)

    walk(A.app.routes)
    return out


def _model(fn, name: str = "req"):
    """从实现体签名里取请求体模型类（RunRequest / BatchCreate / …）。

    两个坑：`app.py` 有 `from __future__ import annotations`，注解是**字符串**，
    要 `get_type_hints` 才拿得到类；而 `@maps_http` 之类的装饰器会换掉
    `__globals__`，所以先 `inspect.unwrap` 剥回原函数再解析。
    """
    import inspect
    import typing
    return typing.get_type_hints(inspect.unwrap(fn))[name]


SNAP = Path(os.environ.get("GUJI_ROUTE_SNAP")
            or Path(tempfile.gettempdir()) / "guji_console_routes_baseline.json")
WRITE = os.environ.get("GUJI_ROUTE_SNAP_WRITE") == "1"

#: **有意的行为变化**，比对时放行（但仍然打印出来）。
#:
#: 重构轮的规矩是「行为一模一样」，所以这张表**只能由任务书点名**才加得进来，
#: 且必须写清为什么。目前只有一条：
SANCTIONED = {
    "POST /api/review/rate-history":
        "C2 把 measure() 从 scripts/track_review_rate.py 搬进 eval/rate_history.py 时，"
        "顺带把硬编码的 REPO/output/glyph.db 换成 core.workspace.glyph_db_path()"
        "（后端任务书 §三·2 点名要消掉的）。改之前这条在云端必然抛 "
        "OperationalError: no such table: admissions —— 它当场造一个 0 字节空库再去查表；"
        "改之后正常记一行台账。这是修好了，不是改坏了。",
}

#: 这两条列的是**进程内的全局注册表**（`core.step.STEPS` / `KINDS`）。
#: 别的测试文件会往里注册自己的试验 Step / 产物种类，**注册完不撤**——
#: 单跑本文件是 9 步 13 种，全仓一起跑就变成 13 步 18 种。
#: 那是注册表的进程级污染，不是这两条路由的行为变化，所以：
#: **基线里有的必须原样都在**（少一条、改一条照样报），多出来的只提示不判错。
REGISTRY_ROUTES = ("GET /api/steps", "GET /api/kinds")

BOOK = "vol01"
PAGES = "dev_set"          # 有产物的页集（见模块 docstring 的准备命令）
PAGE = 24
COL, SLOT = 1, 10          # p0024c01s10 是真有字块图的位；slot=1 那一格是空的，
                           # 拿它当样本会让 /api/cache 与 /api/rare 两条都只走 404 分支
JZ_BOOK, JZ_PAGES = "vol02", "jz"   # 夹注段只在 vol02 有
EVAL_ID = "char_drop"      # 真存在的评测器（"column-split" 不是 id，只会得到「没有这个评测器」）
BATCH = "snap-batch"       # 沙箱里现建的批次，不碰真台账

# 时间/耗时类字段：同一份产物两次读出来也可能不同，或与本次重构无关
VOLATILE = {"ts", "elapsed", "harvested_at", "created_at", "updated_at",
            "started_at", "finished_at", "queued_at", "submitted_at", "t"}


# ── 归一化 ───────────────────────────────────────────────────────────
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _norm(v):
    """把返回值压成可比对的纯 JSON 结构。"""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, StreamingResponse
    from starlette.responses import Response

    if isinstance(v, HTTPException):
        return {"__http__": v.status_code, "detail": str(v.detail)}
    if isinstance(v, FileResponse):
        p = Path(v.path)
        return {"__file__": v.media_type, "exists": p.exists(),
                "sha256": _sha(p.read_bytes()) if p.exists() else None}
    if isinstance(v, StreamingResponse):
        # SSE：只取第一帧，别把生成器跑到底（它会一直等任务结束）。
        # ⚠️ starlette 会把**同步**生成器包成 async iterator（iterate_in_threadpool），
        # 所以这里两种都要认——只写 `for chunk in body_iterator` 会 TypeError。
        return {"__stream__": v.media_type,
                "first_frame_kind": _frame_kind(_first_chunk(v.body_iterator))}
    if isinstance(v, Response):
        body = v.body if isinstance(v.body, bytes) else str(v.body).encode()
        return {"__response__": v.media_type, "len": len(body), "sha256": _sha(body)}
    if hasattr(v, "model_dump"):
        return _norm(v.model_dump(mode="json"))
    if isinstance(v, dict):
        # 键一律转成字符串：`/api/status` 的 `steps.<step>.pages` 是 **int 键**，
        # 存进基线 JSON 再读回来就成了 str，不转的话每次都报「差异」。
        # 走 HTTP 时 fastapi 也是这么序列化的，转了才是它真正发出去的形状。
        return {str(k): ("<volatile>" if k in VOLATILE else _norm(x)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, str):
        # 沙箱是每跑一次现建的临时目录，路径里的随机后缀会漏进错误消息
        # （如「金标路径不存在: /tmp/guji_console_snap_xxxx/dataset/…」），
        # 那不是行为差异。归一成固定占位再比。
        return v.replace(str(_SANDBOX), "<sandbox>")
    if isinstance(v, (int, bool)) or v is None:
        return v
    return {"__obj__": type(v).__name__, "repr": repr(v)[:200]}


def _first_chunk(it) -> bytes | None:
    import asyncio
    if hasattr(it, "__anext__"):
        async def _go():
            async for c in it:
                return c
            return None
        chunk = asyncio.run(_go())
    else:
        chunk = next(iter(it), None)
    if chunk is None:
        return None
    return chunk if isinstance(chunk, bytes) else str(chunk).encode()


def _frame_kind(frame: bytes | None) -> str:
    """SSE 第一帧里的 type 字段（line / complete / error / keepalive）。"""
    if not frame:
        return "<none>"
    s = frame.decode("utf-8", errors="replace")
    if s.startswith(":"):
        return "keepalive"
    if s.startswith("data: "):
        try:
            return str(json.loads(s[6:].strip()).get("type"))
        except Exception:                                  # noqa: BLE001
            return "<unparsable>"
    return "<other>"


def _shape(v):
    """比结构不比值：每个标量换成类型名。给 /api/runs 系列用。"""
    if isinstance(v, dict):
        return {k: _shape(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_shape(x) for x in v[:1]] + (["…"] if len(v) > 1 else [])
    return type(v).__name__


def _call(fn, *args, mode: str = "value", **kw):
    from fastapi import HTTPException
    try:
        out = _norm(fn(*args, **kw))
    except HTTPException as e:
        out = _norm(e)
    except Exception as e:                                 # noqa: BLE001
        out = {"__exc__": type(e).__name__, "msg": str(e)[:300]}
    return _shape(out) if mode == "shape" else out


# ── 50 条：逐条调一次 ────────────────────────────────────────────────
def _collect() -> dict:
    """返回 {"METHOD /path": 归一化结果}，共 50 条。"""
    from open_guji_cv.console.jobs import TERMINAL

    EP = _endpoints()
    snap: dict = {}
    ck = cell_key(PAGE, COL, SLOT)
    pk = page_key(PAGE)

    def call(route: str, *args, mode: str = "value", **kw):
        snap[route] = _call(EP[route], *args, mode=mode, **kw)

    # 一 · 注册表（4）＋ 静态（1）
    call("GET /api/books")
    call("GET /api/pipelines")
    call("GET /api/steps")
    call("GET /api/kinds")
    html = EP["GET /"]()
    snap["GET /"] = {"len": len(html), "sha256": _sha(html.encode())}

    # 二 · 状态（1）
    call("GET /api/status", book=BOOK, pages=PAGES)

    # 三 · 管线执行（6）——全部比结构不比值（带 job id 与时间戳）
    run_ep = EP["POST /api/runs"]
    job = run_ep(_model(run_ep)(book=BOOK, pages=str(PAGE)))   # force=False，产物已 fresh
    jid = job["id"]
    snap["POST /api/runs"] = _shape(_norm(job))
    for _ in range(600):                                       # 等它进终态，取消/日志才稳定
        if EP["GET /api/runs/{job_id}"](jid).get("status") in TERMINAL:
            break
        time.sleep(0.2)
    call("GET /api/runs", limit=5, mode="shape")
    call("GET /api/runs/{job_id}", jid, mode="shape")
    call("GET /api/runs/{job_id}/log", jid, mode="shape")
    call("GET /api/runs/{job_id}/log.txt", jid, mode="shape")
    call("POST /api/runs/{job_id}/cancel", jid, mode="shape")

    # 四 · 产物与图像（6）——二进制比 sha256
    call("GET /api/products/{book}/{step}/{key}", BOOK, "border_detect", pk)
    call("GET /api/manifest/{book}/{step}", BOOK, "border_detect")
    call("GET /api/raw/{book}/{page}.png", BOOK, PAGE, scale=0.35)
    call("GET /api/cache/{book}/{kind}/{key}.png", BOOK, "char_patch", ck)
    call("GET /api/overlay/{book}/{step}/{page}.png", BOOK, "border_detect", PAGE)
    call("GET /api/cutline/img/{book}/{page}/{col}.png", BOOK, PAGE, COL, 0, 400)

    # 五 · 审阅批次与事件（8）——沙箱里从空状态起，可重复
    call("GET /api/batches")
    mk = EP["POST /api/batches"]
    call("POST /api/batches",
         _model(mk)(id=BATCH, title="快照批次", step="seed_admit", book=BOOK))
    ev = EP["POST /api/events"]
    call("POST /api/events", _model(ev)(
        batch=BATCH, step="seed_admit", unit="cell", kind="verdict", consume=False,
        events=[{"id": f"{BOOK}:{PAGE}:{COL}:{SLOT}", "v": "confirm",
                 "shape": "一", "reading": "一", "t": 1}]))
    call("GET /api/events", batch=BATCH)
    call("GET /api/batches/{batch_id}", BATCH)
    hv = EP["POST /api/batches/{batch_id}/harvest"]
    call("POST /api/batches/{batch_id}/harvest", BATCH,
         _model(hv)(batch=BATCH, step="seed_admit", unit="cell",
                    content=json.dumps({"id": f"{BOOK}:{PAGE}:{COL}:{SLOT + 1}",
                                        "v": "confirm", "shape": "二", "reading": "二"},
                                       ensure_ascii=False)))
    call("POST /api/batches/{batch_id}/route", BATCH, dry_run=True)
    call("GET /api/batches.md")

    # 六 · 金标（3）——沙箱 dataset 是空的，三条走的是空库分支
    call("GET /api/gold")
    call("POST /api/gold/{shard:path}/migrate", "char-segmentation/instances", dry_run=True)
    call("POST /api/gold/{shard:path}/drift", "char-segmentation/instances", apply=False)

    # 七 · 评测与判据（8）
    call("GET /api/evals")
    call("POST /api/evals/{eval_id}/run", EVAL_ID, timeout=120)
    call("GET /api/quality", book=BOOK, pages=PAGES)
    call("GET /api/rulers", book=BOOK, pages=PAGES)
    call("GET /api/round", book=BOOK, pages=PAGES)
    call("GET /api/review/rate-history", book=BOOK)
    rs = EP["POST /api/review/rate-history"]
    call("POST /api/review/rate-history", _model(rs)(books=BOOK, note="snap"))
    # 没开过 enable_online_llm 就没有日志，has_data:false 是正常态，不是错
    call("GET /api/llm_online_stats", book=BOOK)
    call("GET /api/llm_online_calls/{book}", BOOK)
    call("GET /api/overview_summary", book=BOOK)

    # 八 · 专项审查页（13）
    call("GET /api/review/cards", book=BOOK, pages=PAGES, limit=20)
    call("GET /api/review/column/{book}/{page}/{col}", BOOK, PAGE, COL)
    call("GET /api/review/around/{book}/{page}/{col}/{slot}", BOOK, PAGE, COL, SLOT)
    ab = EP["POST /api/review/around/batch"]
    call("POST /api/review/around/batch",
         _model(ab)(book=BOOK, items=[{"page": PAGE, "col": COL, "slot": SLOT}]))
    call("GET /api/review/context-img/{book}/{page}/{col}/{slot}.png", BOOK, PAGE, COL, SLOT)
    call("GET /api/review/verdicts", batch=BATCH)
    call("GET /api/cutline/cases", book=BOOK, pages=PAGES, limit=5, seed=0, skip_done=False)
    call("GET /api/cutline/verdicts", batch=BATCH)
    call("GET /api/jiazhu/segments", book=JZ_BOOK, pages=JZ_PAGES)
    # ⚠️ 首次要建字体索引（方案 §十一·4 实测 112 秒），之后 0.1 秒。别当它挂了
    call("GET /api/rare/{book}/{page}/{col}/{slot}", BOOK, PAGE, COL, SLOT, k=5)
    rb = EP["POST /api/rare/batch"]
    call("POST /api/rare/batch", _model(rb)(book=BOOK, slots=[f"{PAGE}:{COL}:{SLOT}"], k=3))
    call("GET /api/variants/book", edition="")
    call("GET /api/variants/groups", book=BOOK, pages=PAGES)

    return snap


def _hist_path() -> Path:
    return REPO / "output" / "review_rate_history.jsonl"


def _deep_diff(a, b, path: str = "") -> list[tuple[str, str, str]]:
    """定位到**具体哪个字段**不同，而不是把两坨 JSON 都打出来让人肉眼比。

    重构轮多数差异是某一个字段（少一个 key、多一层嵌套、数值差在小数第四位），
    整块打印看不出来——尤其 `/api/status` 这种一条就一万三千字符的。
    """
    cut = lambda v: json.dumps(v, ensure_ascii=False)[:200]
    if type(a) is not type(b):
        return [(path, f"{type(a).__name__} {cut(a)}", f"{type(b).__name__} {cut(b)}")]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append((f"{path}.{k}", "<缺>", cut(b[k])))
            elif k not in b:
                out.append((f"{path}.{k}", cut(a[k]), "<缺>"))
            else:
                out += _deep_diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [(path, f"{len(a)} 条 {cut(a)}", f"{len(b)} 条 {cut(b)}")]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _deep_diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [(path, cut(a), cut(b))]


def _cleanup(hist_before: bytes | None) -> None:
    """`POST /api/review/rate-history` 在 `output/` 下留两样东西，都要还原。

    1. **0 字节的 `output/glyph.db`**：`scripts/track_review_rate.py` 硬编码
       `REPO/output/glyph.db`，绕过 `core/workspace`，于是当场造一个空库
       （方案 §十一·2）。它被 gitignore 挡着 `git status` 看不见，但下一次跑
       会读到这个空库报 `no such table: admissions`。
    2. **`output/review_rate_history.jsonl`**：那条路由 `open(mod.HIST, "a")`
       追加台账。这个文件**不在 gitignore 里**——不还原的话 `git status` 会脏，
       真机上还会把测试数据混进真台账。
    """
    db = REPO / "output" / "glyph.db"
    if db.exists() and db.stat().st_size == 0:
        db.unlink()
    hist = _hist_path()
    if hist_before is None:
        hist.unlink(missing_ok=True)
    elif hist.read_bytes() != hist_before:
        hist.write_bytes(hist_before)


# ── 测试 ─────────────────────────────────────────────────────────────
def test_route_inventory():
    """50 条路由一条不少、一条不多，且 method+path 逐条对得上。

    C3 把 `app.py` 拆成 11 个 router，最怕的就是**漏挂一个 router**——
    那时快照测试会因为拿不到实现体而报别的错，这条先把账对清楚。

    （原始 46 条是 C3 落定时的数；2026-09-09 加「字形不入库」的跨列/跨页
    上下文与切分前原图，`review.py` 添了 3 条，46 → 49；2026-09-10 加
    `GET /api/llm_online_stats`（线上大模型裁决正确率），49 → 50；2026-09-11
    Step0 预清理专用可视化（数值报告 + 专用叠图 + 前后对比），`products.py`
    添了 4 条，50 → 54；同日边框类裁决（Step1 列探测/抬头/外框外延、Step2
    上下版框核校）从 artifact 迁入控制台，新增 `border_review.py` 3 条，
    54 → 57；另一并行改动把控制台前端换成 Vite React 构建，`registry.py`
    加 `GET /v1/`（旧静态前端兜底）、`spa_fallback.py` 加
    `GET /{full_path:path}`（history 模式路由兜底），57 → 59；另一并行改动
    加 `GET /api/throughput`（吞吐统计）、`GET /api/gate/{book}/summary`
    （闸汇总），59 → 61；2026-09-11 Step5-d 整理本对齐锚定汇总面板，加
    `GET /api/align-ref/{book}/summary`，61 → 62；另一并行改动加
    `GET /api/overview_summary`（总览页轻量摘要），62 → 63；同日 Step6
    大模型调用记录页（overview 下发，展示单次线上大模型调用的输入/输出/
    决定），加 `GET /api/llm_online_calls/{book}`，63 → 64；同日 Step5-c
    OCR 候选板块②聚合数字，`products.py` 加
    `GET /api/ocr-candidates/{book}/summary`，64 → 65；同日另一并行改动
    给 `EvalsPage` 加 `GET /api/align-ref/summary`（book 走 query 参数，
    跟 `/api/align-ref/{book}/summary` 的 path 参数版并存，服务不同页面），
    65 → 66；同日 Step5-a 字形库匹配调试视图（方案见 overview 仓
    Step5-字符识别/08-5a方案-字形库匹配调试视图.md），新增
    `glyph_match.py` 3 条：单点查询 `GET /api/glyph-match/{book}/{page}/{col}/{slot}`、
    候选缩略图 `GET /api/glyph-match/exemplar/{instance_id}.png`、板块②聚合
    `GET /api/glyph-match/{book}/summary`，66 → 69；2026-09-12 总览页「运行
    参数」卡片按书开关 Step5-c OCR候选，`runs.py` 加
    `PUT /api/books/{book}/ocr_candidates`（写回 book yaml），69 → 70。）
    """
    got = sorted(_endpoints())
    assert len(got) == 70, f"路由数变了：{len(got)} 条\n" + "\n".join(got)
    assert got == sorted(EXPECTED_ROUTES), (
        "路由清单变了\n少了：" + str(sorted(set(EXPECTED_ROUTES) - set(got)))
        + "\n多了：" + str(sorted(set(got) - set(EXPECTED_ROUTES))))


def test_route_snapshot():
    """50 条路由各调一次，与基线逐条比对。"""
    if not os.environ.get("GUJI_WORKSPACE"):
        pytest.skip("要 GUJI_WORKSPACE 指向真书工作区（见模块 docstring）")
    if not (REPO / "products" / BOOK / "seed_admit").exists():
        pytest.skip(f"缺 {BOOK} 产物，先跑 "
                    f"python -m open_guji_cv pipeline keben_body_v2 {BOOK} --pages {PAGES}")
    hist = _hist_path()
    hist_before = hist.read_bytes() if hist.exists() else None
    try:
        snap = _collect()
    finally:
        _cleanup(hist_before)
    assert len(snap) == 50, f"只采到 {len(snap)} 条"

    if WRITE or not SNAP.exists():
        SNAP.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True),
                        encoding="utf-8")
        print(f"\n基线已落盘：{SNAP}（49 条）。重构每推一步再跑一次比对。")
        return

    base = json.loads(SNAP.read_text(encoding="utf-8"))
    extra_registered: dict[str, int] = {}
    for k in REGISTRY_ROUTES:
        if not isinstance(base.get(k), list) or not isinstance(snap.get(k), list):
            continue
        ids = {e.get("id") for e in base[k] if isinstance(e, dict)}
        kept = [e for e in snap[k] if not isinstance(e, dict) or e.get("id") in ids]
        if len(kept) != len(snap[k]):
            extra_registered[k] = len(snap[k]) - len(kept)
            snap[k] = kept
    for k, n in extra_registered.items():
        print(f"\n（{k}：另有 {n} 条是别的测试注册进全局注册表的，已排除，见 REGISTRY_ROUTES）")

    changed = [k for k in sorted(set(base) | set(snap))
               if base.get(k, "<缺>") != snap.get(k, "<缺>")]
    for k in changed:
        if k in SANCTIONED:
            print(f"\n──── 有意的变化 {k}\n  {SANCTIONED[k]}")
    diffs = [k for k in changed if k not in SANCTIONED]
    if diffs:
        for k in diffs:
            print(f"\n──── 差异 {k}")
            for path, a, b in _deep_diff(base.get(k), snap.get(k))[:8]:
                print(f"  {path or '<根>'}\n    基线: {a}\n    现在: {b}")
    assert not diffs, f"{len(diffs)}/49 条与基线不同：{diffs}"
    n_ok = 49 - len([k for k in changed if k in SANCTIONED])
    print(f"\n{n_ok}/49 条快照零差异"
          + (f"，另 {49 - n_ok} 条是 SANCTIONED 里点名的有意变化" if n_ok < 49 else "")
          + f"（基线 {SNAP}）")


EXPECTED_ROUTES = [
    "GET /", "GET /api/align-ref/summary", "GET /api/align-ref/{book}/summary",
    "GET /api/batches", "GET /api/batches.md", "GET /api/batches/{batch_id}",
    "GET /api/books", "GET /api/border-review/cards", "GET /api/border-review/img/{book}/{page}.jpg",
    "GET /api/border-review/verdicts",
    "GET /api/cache/{book}/{kind}/{key}.png", "GET /api/cutline/cases",
    "GET /api/cutline/img/{book}/{page}/{col}.png", "GET /api/cutline/verdicts",
    "GET /api/evals", "GET /api/events", "GET /api/gate/{book}/summary",
    "GET /api/glyph-match/exemplar/{instance_id}.png",
    "GET /api/glyph-match/{book}/summary", "GET /api/glyph-match/{book}/{page}/{col}/{slot}",
    "GET /api/gold", "GET /api/jiazhu/segments",
    "GET /api/kinds", "GET /api/llm_online_stats", "GET /api/llm_online_calls/{book}",
    "GET /api/manifest/{book}/{step}", "GET /api/ocr-candidates/{book}/summary",
    "GET /api/overlay/{book}/{step}/{page}.png",
    "GET /api/overview_summary",
    "GET /api/pipelines", "GET /api/preclean/{book}/{page}",
    "GET /api/preclean/{book}/{page}/overlay.png", "GET /api/preclean/{book}/{page}/before.png",
    "GET /api/preclean/{book}/{page}/after.png",
    "GET /api/products/{book}/{step}/{key}", "GET /api/quality",
    "GET /api/rare/{book}/{page}/{col}/{slot}", "GET /api/raw/{book}/{page}.png",
    "GET /api/review/around/{book}/{page}/{col}/{slot}",
    "GET /api/review/cards", "GET /api/review/column/{book}/{page}/{col}",
    "GET /api/review/context-img/{book}/{page}/{col}/{slot}.png",
    "GET /api/review/rate-history", "GET /api/review/verdicts", "GET /api/round",
    "GET /api/rulers", "GET /api/runs", "GET /api/runs/{job_id}", "GET /api/runs/{job_id}/log",
    "GET /api/runs/{job_id}/log.txt", "GET /api/status", "GET /api/steps", "GET /api/throughput",
    "GET /api/variants/book", "GET /api/variants/groups",
    "GET /v1/", "GET /{full_path:path}",
    "POST /api/batches", "POST /api/batches/{batch_id}/harvest", "POST /api/batches/{batch_id}/route",
    "POST /api/events", "POST /api/evals/{eval_id}/run", "POST /api/gold/{shard:path}/drift",
    "POST /api/gold/{shard:path}/migrate", "POST /api/rare/batch", "POST /api/review/around/batch",
    "POST /api/review/rate-history",
    "POST /api/runs", "POST /api/runs/{job_id}/cancel",
    "PUT /api/books/{book}/ocr_candidates",
]


# ── C5：CLI 出口与路由「同参同输出」 ────────────────────────────────
#
# 方案 §二 量出来的那个数字是「本地专属面积 = 0/46」，结论是「控制台能干的事
# 云端道现在就能干，只差一层 CLI 出口」。C5 把那层出口开出来，这条测试就是
# 判据：**同一件事，命令行与路由必须给出同一个答案**。两边各写一份实现的话，
# 迟早只改一边——所以下面每一对都必须落到同一个领域函数上。

CLI_PAIRS = [
    # (子命令 argv, 路由, 路由参数)
    (["check", "quality", BOOK, "--pages", PAGES], "GET /api/quality",
     dict(book=BOOK, pages=PAGES)),
    (["check", "rulers", BOOK, "--pages", PAGES], "GET /api/rulers",
     dict(book=BOOK, pages=PAGES)),
    (["check", "round", BOOK, "--pages", PAGES], "GET /api/round",
     dict(book=BOOK, pages=PAGES)),
    (["check", "rate", BOOK], "GET /api/review/rate-history", dict(book=BOOK)),
    (["cards", "dingzi", BOOK, "--pages", PAGES, "--limit", "20"], "GET /api/review/cards",
     dict(book=BOOK, pages=PAGES, limit=20)),
    (["cards", "jiazhu", JZ_BOOK, "--pages", JZ_PAGES, "--only", "all"],
     "GET /api/jiazhu/segments", dict(book=JZ_BOOK, pages=JZ_PAGES)),
    (["cards", "groups", BOOK, "--pages", PAGES], "GET /api/variants/groups",
     dict(book=BOOK, pages=PAGES)),
    (["rare", BOOK, str(PAGE), str(COL), str(SLOT), "-k", "5"],
     "GET /api/rare/{book}/{page}/{col}/{slot}", dict()),
    (["variants", "book"], "GET /api/variants/book", dict(edition="")),
    (["product", "show", BOOK, "border_detect", "--key", page_key(PAGE)],
     "GET /api/products/{book}/{step}/{key}", dict()),
    (["product", "manifest", BOOK, "border_detect"], "GET /api/manifest/{book}/{step}", dict()),
]


def _cli_json(argv: list[str]) -> dict:
    """跑一条子命令，把它印出来的 JSON 读回来。"""
    import contextlib
    import io as _io

    from open_guji_cv.cli_v2 import COMMANDS_V2, register_subcommands

    ap = argparse.ArgumentParser()
    register_subcommands(ap.add_subparsers(dest="command"))
    args = ap.parse_args(argv)
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        COMMANDS_V2[argv[0]](args)
    return json.loads(buf.getvalue())


def test_cli_matches_routes():
    """C5 的验收：11 对「命令行 vs 路由」逐条同输出。"""
    if not os.environ.get("GUJI_WORKSPACE"):
        pytest.skip("要 GUJI_WORKSPACE 指向真书工作区（见模块 docstring）")
    if not (REPO / "products" / BOOK / "seed_admit").exists():
        pytest.skip(f"缺 {BOOK} 产物")
    EP = _endpoints()
    bad = []
    for argv, route, kw in CLI_PAIRS:
        if route == "GET /api/rare/{book}/{page}/{col}/{slot}":
            want = _norm(EP[route](BOOK, PAGE, COL, SLOT, k=5))
        elif route == "GET /api/products/{book}/{step}/{key}":
            want = _norm(EP[route](BOOK, "border_detect", page_key(PAGE)))
        elif route == "GET /api/manifest/{book}/{step}":
            want = _norm(EP[route](BOOK, "border_detect"))
        else:
            want = _norm(EP[route](**kw))
        got = _norm(_cli_json(argv))
        if got != want:
            bad.append((" ".join(argv), route, _deep_diff(want, got)[:3]))
    for cmd, route, d in bad:
        print(f"\n──── guji {cmd}  ≠  {route}")
        for path, a, b in d:
            print(f"  {path or '<根>'}\n    路由: {a}\n    命令: {b}")
    assert not bad, f"{len(bad)}/{len(CLI_PAIRS)} 对命令行与路由输出不同"
    print(f"\n{len(CLI_PAIRS)}/{len(CLI_PAIRS)} 对「命令行 vs 路由」同输出")


def test_cli_image_exits(tmp_path):
    """图像类三条（product raw / overlay / patch、cache get / column）与路由出**同样的字节**。"""
    if not os.environ.get("GUJI_WORKSPACE"):
        pytest.skip("要 GUJI_WORKSPACE")
    EP = _endpoints()
    ck = cell_key(PAGE, COL, SLOT)
    cases = [
        (["product", "raw", BOOK, "--page", str(PAGE), "--scale", "0.35",
          "--out", str(tmp_path / "raw.png")], EP["GET /api/raw/{book}/{page}.png"],
         (BOOK, PAGE), {"scale": 0.35}, tmp_path / "raw.png"),
        (["product", "overlay", BOOK, "border_detect", "--page", str(PAGE),
          "--scale", "0.35", "--out", str(tmp_path / "ov.png")],
         EP["GET /api/overlay/{book}/{step}/{page}.png"],
         (BOOK, "border_detect", PAGE), {"scale": 0.35}, tmp_path / "ov.png"),
        (["cache", "column", "--book", BOOK, "--page", str(PAGE), "--col", str(COL),
          "--y0", "0", "--y1", "400", "--out", str(tmp_path / "col.png")],
         EP["GET /api/cutline/img/{book}/{page}/{col}.png"],
         (BOOK, PAGE, COL, 0, 400), {}, tmp_path / "col.png"),
    ]
    bad = []
    for argv, ep, a, kw, out in cases:
        _cli_run(argv)
        want = _norm(ep(*a, **kw))["sha256"]
        got = _sha(out.read_bytes())
        if got != want:
            bad.append((" ".join(argv), want, got))
    assert not bad, f"字节不同：{bad}"
    print(f"\n{len(cases)}/{len(cases)} 条图像出口与路由字节相同")


def _cli_run(argv: list[str]) -> None:
    import contextlib
    import io as _io

    from open_guji_cv.cli_v2 import COMMANDS_V2, register_subcommands

    ap = argparse.ArgumentParser()
    register_subcommands(ap.add_subparsers(dest="command"))
    args = ap.parse_args(argv)
    with contextlib.redirect_stdout(_io.StringIO()):
        COMMANDS_V2[argv[0]](args)
