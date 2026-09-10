# -*- coding: utf-8 -*-
"""控制台 · 管线执行。

状态 / 入队 / 查任务 / 取消 / 日志（SSE 与纯文本）

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .. import deps
from ..jobs import JobSpec
from ..sse import sse
from ...core.book import load_book
from ...core.engine import Engine
from ...core.pipeline import load_pipeline

router = APIRouter()



def _engine(book: str, pipeline: str) -> Engine:
    try:
        return Engine(load_book(book), load_pipeline(pipeline), log=lambda s: None)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e



# ── 状态 ─────────────────────────────────────────────────────────────
@router.get("/api/status")
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
    # 页下拉要能选**任意**页——矩阵按 dev_set 显示是状态视图的口径，
    # 但看产物不该被跑批范围挡住（2026-09-10：跑完 69 页却在页面里选不到）。
    st["all_pages"] = eng.book.all_pages()
    st["params"] = overrides or {}
    running = deps.runner().running()
    st["running"] = running.to_dict() if running else None
    # 当前库来源常驻可见（2026-09-09 教训：漏设 GUJI_WORKSPACE 时完全无提示，
    # 对着仓内示例库跑了一批才在产物指纹里事后发现）——这里跟入队闸同一份判断。
    from ...core.workspace import describe, using_sample_db
    st["workspace"] = {**describe(), "is_sample_db": using_sample_db()}
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
    allow_sample_db: bool = False
    """没设 GUJI_WORKSPACE 时，显式声明「就是要用仓内那份几百条的示例库」
    （2026-09-09：控制台本机重启漏带这个变量，vol02 101-150 页对着示例库
    跑了一遍，status:ok 但库匹配全错——现在漏设直接拒绝入队，得这里勾了
    才放行，同 CLI 的 --allow-sample-db）。"""



@router.post("/api/runs")
def api_run(req: RunRequest) -> dict:
    if req.allow_sample_db:
        import os
        os.environ["GUJI_ALLOW_SAMPLE_DB"] = "1"
    from ...core.workspace import assert_workspace_declared
    try:
        assert_workspace_declared()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
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



@router.get("/api/runs")
def api_runs(limit: int = 50) -> list[dict]:
    return deps.runner().list(limit)



@router.get("/api/runs/{job_id}")
def api_run_get(job_id: str) -> dict:
    job = deps.runner().get(job_id)
    if not job:
        raise HTTPException(404, "没有这个任务")
    return job.to_dict()



@router.post("/api/runs/{job_id}/cancel")
def api_run_cancel(job_id: str) -> dict:
    return {"ok": deps.runner().cancel(job_id)}



@router.get("/api/runs/{job_id}/log")
def api_run_log(job_id: str) -> StreamingResponse:
    return StreamingResponse(sse(deps.runner(), job_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})



@router.get("/api/runs/{job_id}/log.txt")
def api_run_log_text(job_id: str) -> Response:
    path = deps.runner().log_path(job_id)
    if not path.exists():
        raise HTTPException(404, "还没有日志")
    return Response(path.read_text(encoding="utf-8", errors="replace"), media_type="text/plain; charset=utf-8")
