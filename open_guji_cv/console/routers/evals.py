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


@router.get("/api/overview_summary")
def api_overview_summary(book: str = "vol01") -> dict:
    """总览页用的轻量摘要：总进度 + 待办 + 异常数据。

    刻意只拼**读产物就有、不用跑重判据**的几样（人审率台账 ~0.7s、三道闸汇总
    各 ~0.05s、align-ref 锚定 ~0.06s），全书全跑一遍 `round.check`（判据A-F）
    要 10+ 秒（判据D 生僻字候选要读 CNN/字体候选），总览页一进来就等 10 秒
    不合理——完整判据体检留给「统计数据」页手动点，这里只给"有没有事要看"。
    """
    from ...gates.query import GATES, gate_summary
    from ...eval import round_check as rc
    from ...steps.align_ref import align_ref_summary

    st = deps.product_store()
    rate = rate_history.measure(book, st) or {}

    gates_out = []
    for gid in GATES:
        try:
            g = gate_summary(book, None, st, gate=gid)
        except Exception:  # noqa: BLE001  闸没跑过这本书时，别把整个摘要拖垮
            continue
        blocked = sum(1 for p in g["pages"] if p["status"] == "page_blocked")
        gates_out.append({"gate": gid, "n_pages": len(g["pages"]), "n_blocked": blocked,
                          "tier_totals": g["tier_totals"]})

    align = align_ref_summary(book, None, st)

    return {
        "book": book,
        "rate": rate,               # 判据B：人审率台账当下快照
        "next": rc.next_batch(book),  # 待办：下一批要跑的正文页
        "gates": gates_out,         # 异常：三道闸各自的整页拦截数与列级拒因分层
        "align_ref": {"n_pages": align["n_pages"], "n_anchored": align["n_anchored"],
                      "n_not_anchored": align["n_not_anchored"], "n_missing": align["n_missing"]},
    }


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


@router.get("/api/llm_online_calls/{book}")
def api_llm_online_calls(book: str, page: int = 0, limit: int = 200) -> dict:
    """逐条线上大模型调用明细——`llm_online_stats` 只给聚合数字，这里给
    Step6 展示页看「某一次调用具体问了什么、模型答了什么」用。

    直接读 `<book>.jsonl` 原始行（`context_decide.py::_log_llm_call` 写的
    那些字段，逐条原样透出，不做聚合/口径转换），按 `page` 过滤、按 `ts`
    倒序（最近的调用排前面），`limit` 做简单分页——一册跑几百条不算多，
    不做游标分页。
    """
    from pathlib import Path

    from ...eval.llm_online_accuracy import load_online_calls

    log_dir = Path("output") / "llm_online_calls"
    rows = load_online_calls(log_dir, book)
    if page:
        rows = [r for r in rows if r.get("page") == page]
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    total = len(rows)
    return {"book": book, "page": page or None, "total": total,
            "rows": rows[:limit]}



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
