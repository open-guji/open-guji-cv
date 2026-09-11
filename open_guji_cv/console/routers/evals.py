# -*- coding: utf-8 -*-
"""控制台 · 评测与判据。

评测器 / 质量看板 / 四把尺子 / 一轮体检 / 人审率台账

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel

from .. import deps
from ..errors import maps_http
from ...eval import rate_history
from ...eval.quality import quality

router = APIRouter()



@router.get("/api/evals")
def api_evals() -> list[dict]:
    from ...eval.registry import EVALS, runnable
    out = []
    for s in sorted(EVALS.values(), key=lambda x: x.id):
        ok, why = runnable(s)
        out.append({"id": s.id, "shard": s.shard, "title": s.title, "note": s.note,
                    "runnable": ok, "blocked": why, "needs": list(s.needs)})
    return out



@router.post("/api/evals/{eval_id}/run")
def api_eval_run(eval_id: str, timeout: int = 900) -> dict:
    from ...eval import run_eval
    return run_eval(eval_id, timeout=timeout).to_dict()



@router.get("/api/quality")
def api_quality(book: str = "vol01", pages: str = "dev_set") -> dict:
    """质量看板：当前准确率 ＋ 缺陷聚集在哪。判准在 `eval/quality.py`（C2 搬出去的），
    与 `eval/rulers.py`、`eval/round_check.py` 同级。"""
    return quality(book, pages, deps.product_store())



@router.get("/api/rulers")
def api_rulers(book: str = "vol01", pages: str = "dev_set") -> dict:
    """**四把尺子**：Step 1-4 「离 100% 还差什么」。

    以前这四个数是临时脚本算完抄进 `.claude/doc/*.md` 的快照，文档一滞后
    就没人知道当下真值。改了一刀有没有变好，恰恰要看这四个数的**变化**。

    口径见 `eval/rulers.py`，照抄 pipeline_review 的定义表，不另立标准。
    """
    from ...core.book import load_book
    from ...eval.rulers import measure
    bk = load_book(book)
    return measure(book, bk.resolve_pages(pages), deps.product_store())



@router.get("/api/round")
def api_round(book: str = "vol01", pages: str = "") -> dict:
    """**一轮体检**：四个判据 + 下一批页码，判断跟命令行同一套。

    判据与阈值在 `eval/round_check.py`（唯一事实源），`scripts/round_check.py`
    与这里共用——阈值只写一处，免得过一阵子两边对不上。

    含义与「什么时候修算法」见 `.claude/doc/review_loop_sop.md`：
    绿=继续跑，黄=记着别动算法（样本不够时改算法是在拟合噪声），红=停下修。
    """
    from ...eval import round_check as rc
    from ...core.book import load_book

    out = {"next": rc.next_batch(book)}
    if pages:
        pgs = load_book(book).resolve_pages(pages)
        out.update(rc.check(book, pgs))
    return out



@router.get("/api/throughput")
def api_throughput(book: str = "vol01", pages: str = "", all_pages: bool = True) -> dict:
    """吞吐量三件套：逐页输入输出 / 自动放行通道占比 / 各步 performance。

    只读现有产物聚合，不重跑管线、不重新计时——见 `eval/throughput.py` 头注。
    `all_pages=True`（默认）统计全书已有产物的页；传 `pages` 则改统计那个子集
    （如 `dev_set`），此时 `all_pages` 自动失效。
    """
    from ...eval import throughput as tp
    p = None if (all_pages and not pages) else (pages or "dev_set")
    return tp.full_report(book, p, deps.product_store())


@router.get("/api/llm_online_stats")
def api_llm_online_stats(book: str = "") -> dict:
    """线上外部大模型（Step6 `context_decide.enable_online_llm`）的真实
    正确率——`eval/llm_online_accuracy.py` 把线上调用日志
    （`output/llm_online_calls/<book>.jsonl`）跟人审最终判定（反馈事件）
    拼起来算，供控制台状态矩阵旁露一眼。开关本身在「运行」面板，见
    `context_decide.py` 模块头【2026-09-10】——默认关闭，没开过就是
    「还没有日志」，不是接口坏了。
    """
    from pathlib import Path

    from ...eval.llm_online_accuracy import compute_report

    log_dir = Path("output") / "llm_online_calls"
    if not log_dir.exists() or not any(log_dir.glob("*.jsonl")):
        return {"has_data": False, "n_total_calls": 0}
    report = compute_report(log_dir, book or None)
    report["has_data"] = True
    return report



@router.get("/api/review/rate-history")
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



@router.post("/api/review/rate-history")
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
