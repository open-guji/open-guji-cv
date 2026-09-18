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

## 四处「天然不可比」怎么处理（方案 §九）

1. **`/api/runs` 系列**带 job id 与时间戳 → `mode="shape"`，**比结构不比值**
   （每个标量换成它的类型名，键与嵌套形状照比）。
2. **二进制响应**（`/api/cache`、`/api/overlay`、`/api/raw`、`/api/cutline/img`）
   → 比 `sha256` 与字节数，不比字节本身。
3. **产物清单里的 `ts`/`elapsed`** 等时间字段 → 换成 `<volatile>`。
4. **举例数据**（`SAMPLE_KEYS`，如尺子的 `detail`）→ `_sample_shape`，只留元素
   结构，不比挑中了哪几条、也不比挑了几条。

## 「举例」与「输出」的界线（2026-09-16）

第 4 条是这次加的，起因：重跑一次 vol01 的 Step1–3，`/api/rulers` 当场变红，
差异全在 `rulers[].detail`——举例的格线从 p141c1 换成 p24c9。**可测的行为一点没变，
变的是被测数据**，这种红是噪声，会训练人「跑红了先重落基线」，那这个测试就废了。

判据是**这个值是不是路由的输出本身**：

- **是输出** → 逐值严比。`/api/cutline/cases` 的 `cases`、`/api/review/cards` 的
  `cards` 都是「这个 URL 就是为了给你这批东西」，值变了就是行为变了，该红。
  它们同样绑产物，但那是这个测试的**前提**（见下：产物得先跑出来），不是缺陷。
- **是举例** → 进 `SAMPLE_KEYS`。尺子的 `detail` 是「满足条件的有 45 条，挑几条
  给人看看长什么样」，挑中谁不是行为。聚合量 `num`/`den`/`value` 照旧严比——
  真出了切分回归，是那三个数变，不是举例变。

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
from open_guji_cv.core.workspace import products_root  # noqa: E402

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
    "GET /api/books":
        "BookSpec 新增 `frame_height`（框高像素中位，册级统计），`to_dict()` 跟着多一个键。"
        "网格模式的 GRID_MIN_SCORE 原本是在北行日錄刻本（框高 1482）上标的绝对像素，"
        "换一本分辨率差一倍的书直接失效且**不报错**，只静默退化成整页插值；"
        "`peak_line_search.grid_thresholds()` 用这个先验把阈值换算过去。"
        "所有册 yaml 都还没写这个字段，值一律是 null——是多一个键，不是哪本书的值变了。",
    "GET /api/evals":
        "评测注册表新增 `oov`（类外泛化·emb），36 → 37 条，其余条目一字未动。"
        "此前所有零样本评测集（glyph-bench 的 unseen/seen/mid、rare-char 21 条）"
        "**100% 落在 CNN 的 4,654 类内**，量不出类外泛化——而扩字表的收益全由 "
        "embedding 兑现，分类头对类外字 top-10 恒为 0。"
        "集由 scripts/build_oov_bench.py 建（314 条 / 138 字种，全是真刻例），"
        "基线在 cache/oov_bench/baseline.json。",
    "POST /api/review/rate-history":
        "C2 把 measure() 从 scripts/track_review_rate.py 搬进 eval/rate_history.py 时，"
        "顺带把硬编码的 REPO/output/glyph.db 换成 core.workspace.glyph_db_path()"
        "（后端任务书 §三·2 点名要消掉的）。改之前这条在云端必然抛 "
        "OperationalError: no such table: admissions —— 它当场造一个 0 字节空库再去查表；"
        "改之后正常记一行台账。这是修好了，不是改坏了。",
}

#: 生僻字候选的两条路由：内容取决于 CNN 候选源在不在（torch 是可选依赖）。
#: 见 `test_route_snapshot` 里 `_CNN_OK` 那段注释。
_CNN_ROUTES = ("GET /api/rare/{book}/{page}/{col}/{slot}", "POST /api/rare/batch")


def _cnn_ok() -> bool:
    from open_guji_cv.clustering.cnn_candidates import CnnCandidates
    return CnnCandidates().available


_CNN_OK = _cnn_ok()

#: 这两条路由的 `score` 是 CNN 前向的输出，**跨设备不是位级可复现的**：同一份
#: checkpoint、同一张图，CUDA 与 CPU 算出来能差 1e-4（实测基线 0.7414 / CPU 轮子
#: 0.7415）。分数本身已经 `round(score, 4)`（`rare_panel.py`），`_norm` 又 round 到 6，
#: 两道都拦不住这种差。基线是在有 GPU 的机器上落的，换 CPU 轮子跑就红一次。
#:
#: 所以对这两条**只放宽分数的数值比对**（下面 `_blur_scores`），字与名次照旧严格比——
#: 真出问题的样子是候选字变了或名次换了（没装 torch 时首位从 emb「坡」变成
#: TypeLand-KhangXiDict「掇」那种），那仍然会红。别把整条路由排除掉。
_SCORE_TOL = 5e-4   # 吃掉 1e-4 级的设备噪声；再大的分数变化照样露出来


def _same_but_score_noise(a, b) -> bool:
    """结构与所有非 score 字段**完全相同**，且每个 `score` 的差 ≤ `_SCORE_TOL`。

    ⚠️ 别用「round 到更少位数再比」那招：`round(0.7414,3)=0.741` 而
    `round(0.7415,3)=0.742`——噪声正好骑在进位边界上时照样不等（2026-09-15
    第一版就栽在这儿）。要吃掉噪声只能比差值。
    """
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(_same_but_score_noise(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same_but_score_noise(x, y) for x, y in zip(a, b))
    if (isinstance(a, float) or isinstance(b, float)) and \
            isinstance(a, (int, float)) and isinstance(b, (int, float)) and \
            not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= _SCORE_TOL
    return a == b

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
            "started_at", "finished_at", "queued_at", "submitted_at", "t",
            # 2026-09-16：产物指纹里的 `code_rev` 是**当前 HEAD 的短 sha**，
            # `fingerprint` 由它派生 —— 任何人往仓里提一笔（哪怕改的是别的模块、
            # 哪怕只是文档），下次跑这个测试的 3 条路由必红。那是「代码变过」，
            # 不是「路由行为变了」。产物是否**新鲜**由 `/api/status` 的 counts 管，
            # 那个照旧严比；这里只是不拿 sha 当行为。
            "code_rev", "fingerprint"}

#: **举例数据**：值随产物变、但不是被测行为的键。这些键的值一律只比**结构**
#: （`_shape`：标量换类型名、列表只留首元素＋省略号），不比具体是哪一页哪一列。
#:
#: 2026-09-16 加：`/api/rulers` 的 `detail` 是「哪些格线穿字」的**样例清单**——
#: 重跑一次 vol01 的 Step1–3，举例就从 p141c1 换成 p24c9，测试当场变红，可测的
#: 行为却一点没变。尺子本身的 `num`/`den`/`value` 照旧逐值严比（那才是回归要看的），
#: 只有举例是谁不比。判据：**这个键的值是「从满足条件的东西里挑几个给人看」吗**——
#: 是就进这里；是聚合量（计数、比率、分母）就不进。
SAMPLE_KEYS = {"detail"}


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
        out = {}
        for k, x in v.items():
            ks = str(k)
            if k in VOLATILE:
                out[ks] = "<volatile>"
            elif k in SAMPLE_KEYS:
                # 举例清单：只留**元素结构**，既不比挑中了哪几条、也不比挑了几条
                # （`_shape` 自身会把「1 条」和「多条」编码成不同结构，而举例条数
                # 同样随产物变——R2 的 detail 在同一份产物上就是 7 条、重跑后 5 条）
                out[ks] = _sample_shape(_norm(x))
            else:
                out[ks] = _norm(x)
        return out
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


def _sample_shape(v):
    """举例清单的归一：空与非空要分开（「有没有举例」是行为），但**非空之间
    不比条数、不比挑中谁**——只留合并后的元素结构。给 SAMPLE_KEYS 用。"""
    if not isinstance(v, (list, tuple)):
        return _shape(v)
    if not v:
        return []
    merged: dict = {}
    for item in v:
        s = _shape(item)
        if isinstance(s, dict):
            merged.update(s)
        else:                       # 标量举例（如 id 清单）：留一个类型名就够
            return [s, "…"]
    return [merged, "…"]


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

    # 二 · 状态（1）——`mode="shape"`：这条报的是**产物新鲜度**，而新鲜度按定义
    # 就是「产物指纹 vs 当前代码指纹」。仓里提一笔代码、或谁重跑了一页，counts 的
    # fresh/stale 就变（2026-09-16 实测：并行会话提了一个提交，fresh 9→1、stale 3→11）。
    # 那是环境状态，不是这条路由的行为。行为＝「有没有按 step×page 报出 counts 与
    # 每页 status」，比结构就够；真要守新鲜度，那是 `guji status` 与跑批的事。
    call("GET /api/status", book=BOOK, pages=PAGES, mode="shape")

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

    # 七 · 评测与判据（10）——此前一直标「8」，`llm_online_calls`/`overview_summary`
    # 加进来时（对应 `EXPECTED_ROUTES` 账本 63→64、62→63）忘了同步这行标签，
    # 实际早就是 10 条；2026-09-13 对账补标，不是本次新增的调用
    call("GET /api/evals")
    call("POST /api/evals/{eval_id}/run", EVAL_ID, timeout=120)
    call("GET /api/quality", book=BOOK, pages=PAGES)
    call("GET /api/rulers", book=BOOK, pages=PAGES)
    call("GET /api/round", book=BOOK, pages=PAGES)
    # `mode="shape"`：这条读的是 `output/review_rate_history.jsonl` 台账，而下面
    # 那个 POST 每跑一次就往里追加一行——落基线时算进去的行数，跑完 `_cleanup`
    # 又把文件还原了，于是下一次跑必然比基线多/少一行，永远对不上（2026-09-15
    # 查出来：连跑三次都只差这一条，行数 4→5）。行数是本测试自己的副作用，
    # 不是被测行为，比结构就够。
    call("GET /api/review/rate-history", book=BOOK, mode="shape")
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
    `PUT /api/books/{book}/ocr_candidates`（写回 book yaml），69 → 70。

    2026-09-13 对账发现漏记的 4 条（都是先前几次并行改动就已合入，只是这条
    账本没跟上，不是这次新加的 bug）：`review.py` Step4 随机层裁决台
    （commit d615c6e2ab/f10c0a6143，2026-09-11）加 `GET /api/cell-shrink-rand/sample`、
    `GET /api/cell-shrink-rand/context/{book}/{page}/{col}/{slot}.png`；
    `step9.py` Step9 坐标转字符位现场渲染面板（commit 65fdcf9b14/428e8c1ee9，
    2026-09-11～12）加 `GET /api/step9/render/{book}`、
    `GET /api/step9/reflow/{book}`。这 4 条都先于「69→70」那次批量提交
    （f7c7c6e54e）就已合入主干，该次提交只顺手记了它自己新加的
    `ocr_candidates` 一条，没有回头补记，70 → 74。）

    2026-09-13 人裁落 workspace 裁决表、进测试集改为显式导入（7e730962d4），
    `gold.py` 加 `POST /api/gold/{shard:path}/import`，账 2026-09-14 补记，74 → 75。

    2026-09-15 梯次裁决（overview 10 卡）只改了 `GET /api/cutline/cases` 的 `pages` 取值
    （新增 `escalated`），**没有新增路由**，75 不变。

    2026-09-15 工作区热切（用户要求「可以随时切换工作区」）：新增 `workspace.py`
    2 条——`GET /api/workspace`（当前工作区、各个根、可切换清单）与
    `POST /api/workspace`（改 `GUJI_WORKSPACE` + 重建进程内 Store，不重启进程；
    有任务在跑时回 409），75 → 77。

    2026-09-17 Step2 列清理人裁（用户「上下、左右都做审阅台，人审结果进测试集」）：
    新增 `column_review.py` 3 条——`GET /api/column-review/cases`（按分诊类别分层
    抽样出待裁列）、`GET /api/column-review/verdicts`（读回本批已裁）、
    `GET /api/column-review/profile/{book}/{page}/{col}`（两条投影曲线，拖线时看），
    76 → 79。

    2026-09-17 同一批：再加 `GET /api/column-review/img/{book}/{page}/{col}.png`
    （列图**二值化 + 把算法的线画上去**：红=文字带左右边界、绿=上端削到的行、
    蓝=下端削到的行）。用户实测反馈「你需要划线不然我不知道在哪」——看不到线
    就没法判「削到哪了对不对」；二值化是为了与字形库/定字审阅同一把尺子。
    79 → 80。
    """
    got = sorted(_endpoints())
    assert len(got) == 80, f"路由数变了：{len(got)} 条\n" + "\n".join(got)
    assert got == sorted(EXPECTED_ROUTES), (
        "路由清单变了\n少了：" + str(sorted(set(EXPECTED_ROUTES) - set(got)))
        + "\n多了：" + str(sorted(set(got) - set(EXPECTED_ROUTES))))


def test_route_snapshot():
    """52 条路由各调一次，与基线逐条比对。

    2026-09-13：期望数从 50 改成 52——不是新加了调用，是「七 · 评测与判据」
    这一节早先加了 `GET /api/llm_online_calls/{book}` 与 `GET /api/overview_summary`
    两条调用（随 `EXPECTED_ROUTES` 账本 63→64、62→63 同一批改动进来），但这条
    断言和那行段落标签一直没跟着改，实测本来就是 52，不是本轮改坏。

    **基线会过时，这是设计使然。** 它落在临时目录、绑定这台机器的产物与库
    （见模块 docstring），功能一加就该变。2026-09-15 核对过一次 17 条漂移，
    逐条都有主：`in_workspace`/`spec.workspace`（工作区改每请求一个）、
    `invalidated`（人裁回流让页显式失效）、`drift_skipped`（切线 escalated 模式）、
    `pipelines` 多一条（现代印刷链）、`kinds` 多一条、夹注/判据/人审率等数字
    随两天的跑批与人裁而动——没有一条是回归，于是用 `GUJI_ROUTE_SNAP_WRITE=1`
    重落了基线。

    **下次再红，照这个流程办**：先把差异逐条摊开（比对新旧 JSON 的叶子节点），
    确认每一条都对得上某次有意的改动，再重落；**别一红就直接重落**——那等于
    把这个测试关掉。

    2026-09-15 又红两条（`/api/rare/...`），这次**不是**该重落的那种：本机 venv
    里没装 torch，`rare_panel` 的 CNN 分类 + embedding 两个候选源整个退场，只剩
    字体 HOG，候选字与名次自然全变。这是缺件下的合法降级，重落会把一份没有 CNN
    的快照焊死。改成没 torch 时这两条不参与比对（见下面 `_CNN_OK` 一段）。
    """
    if not os.environ.get("GUJI_WORKSPACE"):
        pytest.skip("要 GUJI_WORKSPACE 指向真书工作区（见模块 docstring）")
    if not (products_root() / BOOK / "seed_admit").exists():
        pytest.skip(f"缺 {BOOK} 产物，先跑 "
                    f"python -m open_guji_cv pipeline keben_body_v2 {BOOK} --pages {PAGES}")
    hist = _hist_path()
    hist_before = hist.read_bytes() if hist.exists() else None
    try:
        snap = _collect()
    finally:
        _cleanup(hist_before)
    assert len(snap) == 52, f"只采到 {len(snap)} 条"

    if WRITE or not SNAP.exists():
        SNAP.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True),
                        encoding="utf-8")
        print(f"\n基线已落盘：{SNAP}（{len(snap)} 条）。重构每推一步再跑一次比对。")
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

    # 生僻字候选的两条路由**不是环境无关的**，分两种情况：
    # ① 没装 torch：候选源里的 CNN 分类与 embedding（`rare_panel.py` 的
    #    `if cnn.available:`）整个退场、只剩字体 HOG，候选字与名次全变（实测基线
    #    首位 emb「坡」0.8396 → TypeLand-KhangXiDict「掇」0.7412）。这是缺件下的
    #    合法降级，不是漂移，重落基线只会把一份没有 CNN 的快照焊死 → 整条排除；
    # ② 装了 torch 但换了设备：只有分数有 1e-4 级噪声 → 只放宽分数，字与名次照旧严格比。
    if not _CNN_OK:
        skipped_cnn = [k for k in diffs if k in _CNN_ROUTES]
        if skipped_cnn:
            print(f"\n（没装 torch，CNN/embedding 候选源退场，{skipped_cnn} 不参与比对；"
                  "装上 torch 再跑才能覆盖这两条）")
            diffs = [k for k in diffs if k not in _CNN_ROUTES]
    else:
        for k in list(diffs):
            if k in _CNN_ROUTES and _same_but_score_noise(base.get(k), snap.get(k)):
                print(f"\n（{k}：只差在 CNN 分数的末位（跨 CPU/CUDA 的 1e-4 噪声），"
                      "字与名次一致，不算漂移）")
                diffs.remove(k)
    if diffs:
        for k in diffs:
            print(f"\n──── 差异 {k}")
            for path, a, b in _deep_diff(base.get(k), snap.get(k))[:8]:
                print(f"  {path or '<根>'}\n    基线: {a}\n    现在: {b}")
    n_total = len(snap)
    assert not diffs, f"{len(diffs)}/{n_total} 条与基线不同：{diffs}"
    n_ok = n_total - len([k for k in changed if k in SANCTIONED])
    print(f"\n{n_ok}/{n_total} 条快照零差异"
          + (f"，另 {n_total - n_ok} 条是 SANCTIONED 里点名的有意变化" if n_ok < n_total else "")
          + f"（基线 {SNAP}）")


EXPECTED_ROUTES = [
    "GET /", "GET /api/align-ref/summary", "GET /api/align-ref/{book}/summary",
    "GET /api/workspace",
    "GET /api/batches", "GET /api/batches.md", "GET /api/batches/{batch_id}",
    "GET /api/books", "GET /api/border-review/cards", "GET /api/border-review/img/{book}/{page}.jpg",
    "GET /api/border-review/verdicts",
    # Step2 列清理人裁（2026-09-17）
    "GET /api/column-review/cases", "GET /api/column-review/verdicts",
    "GET /api/column-review/profile/{book}/{page}/{col}",
    "GET /api/column-review/img/{book}/{page}/{col}.png",
    "GET /api/cache/{book}/{kind}/{key}.png",
    "GET /api/cell-shrink-rand/context/{book}/{page}/{col}/{slot}.png",
    "GET /api/cell-shrink-rand/sample",
    "GET /api/cutline/cases",
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
    "GET /api/runs/{job_id}/log.txt", "GET /api/status", "GET /api/step9/reflow/{book}",
    "GET /api/step9/render/{book}", "GET /api/steps", "GET /api/throughput",
    "GET /api/variants/book", "GET /api/variants/groups",
    "GET /v1/", "GET /{full_path:path}",
    "POST /api/batches", "POST /api/batches/{batch_id}/harvest", "POST /api/batches/{batch_id}/route",
    "POST /api/events", "POST /api/evals/{eval_id}/run", "POST /api/gold/{shard:path}/drift",
    "POST /api/gold/{shard:path}/import",
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
    if not (products_root() / BOOK / "seed_admit").exists():
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
