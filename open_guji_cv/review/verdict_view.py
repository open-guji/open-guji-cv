# -*- coding: utf-8 -*-
"""把事件读回成「这一批已经裁过哪些字位」——**刷新页面不该重审一遍**。

从 `console/app.py` 的 `api_review_verdicts` ＋ `api_cutline_verdicts` 搬来
（控制台重构 C2）。两条本来就是同一件事的两种 kind，合到一个模块里。
逻辑一行未改，只动了函数名与 `EventLog` 改成可注入。

同一 id 多次裁决按 (batch, seq) 升序**后到覆盖**——沿用 seed_queue 的纪律，
人改主意时最后一次说了算。
"""
from __future__ import annotations

from ..feedback.events import EventLog


#: 算「这个字位已经裁过了」的动作。`relabel`（改判字）也算——人已经对它表过态。
#: `cutline` 不在此列：那是切线裁决，`unit` 是 boundary，key 形状却与字位一样
#: （`bxgb:39:19:12`），只按 key 去重会把没裁过的字位误当已裁。必须按 kind 过滤。
DECIDED_KINDS = frozenset({"confirm", "not_a_char", "skip", "seg_defect", "relabel"})


def decided_cells(book: str, log: EventLog | None = None) -> set[str]:
    """这本书**所有批次**里已经裁过的字位 id。

    给定字审查的载入用（用户 2026-09-16）：以前后端不看事件、只按页序数满
    `limit` 就返回，前端再把已裁的隐藏掉——于是每次载入都从第一页重数，稳定
    地把上轮裁过的那批又端出来，真正的新卡只剩零星几张。

    **必须跨批次**。实测（bxgb，2026-09-16）：四个批次的已裁字位是完全包含关系，
    `1-30` 的 76 个字位在其余三批里各被重裁了一遍，`bxgb:3:1:19` 累计裁了 13 次，
    1620 条 confirm 事件只覆盖 312 个不同字位。只按当前批次去重救不了这个——
    换个 pages 范围批次名就变了，老裁决全部不算数。

    按 key 前缀认书：事件的 `target.book` 实测多为 None（写入方没填），而 key
    形如 `<book>:<页>:<列>:<格>`，前缀是可靠的。
    """
    out: set[str] = set()
    pre = f"{book}:"
    try:
        evs = (log or EventLog()).iter_all()
    except FileNotFoundError:
        return out     # 新工作区还没有事件目录
    for e in evs:
        if e.kind not in DECIDED_KINDS:
            continue
        if e.target.unit != "cell":
            continue
        k = e.target.key
        if k.startswith(pre):
            out.add(k)
    return out


def review_verdicts(batch: str, log: EventLog | None = None) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。

    裁决本来就落成事件了（`/api/events`），但前端只在内存里记 `RV.verdicts`，
    一刷新就空。这个接口把事件读回成同样的形状，载入卡片时合并进去。

    同一 id 多次裁决按 (batch, seq) 升序**后到覆盖**——沿用 seed_queue 的
    纪律，人改主意时最后一次说了算。
    """
    out: dict[str, dict] = {}
    for e in sorted((log or EventLog()).read(batch), key=lambda x: (x.batch, x.seq)):
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
                                 "done": "1",
                                 "noGlyphLib": bool(p.get("no_glyph_lib"))}
    return {"batch": batch, "n": len(out), "verdicts": out}


def cutline_verdicts(batch: str, log: EventLog | None = None) -> dict:
    """读回本批已拖过的切线（刷新不重做；同 id 后到覆盖）。"""
    out: dict[str, dict] = {}
    for e in sorted((log or EventLog()).read(batch), key=lambda x: (x.batch, x.seq)):
        if e.kind != "cutline":
            continue
        p = e.payload
        # col_h：前端 drift 档据此判断这条裁决是不是对**当前**坐标系裁的（老批次里的历史事件
        # 坐标系已过期，不能拿来当「已裁」，更不能把旧折线画到新图上——2026-09-14 实锤）。
        # cand：「选切分方案」裁决选中的候选，刷新后恢复选中态。
        out[e.target.key] = {"y": p.get("y"), "verdict": p.get("verdict"), "polyline": p.get("polyline"),
                             "col_h": p.get("col_h"), "cand": p.get("cand")}
    return {"batch": batch, "n": len(out), "verdicts": out}


def verdicts_by_question(batch: str, question: str | None = None,
                         log: EventLog | None = None) -> dict:
    """通用读回：本批（可按 question 过滤）已裁条目的**原始 payload**。

    ## 为什么要有这一个

    此前「读回本批已裁」有**四份实现、四种返回形状**：本模块两个函数、
    `console/routers/column_review.py`、`slot_count_review.py`、
    `border_review.py`（内含 3 分支）。新增一个裁决台就要再抄一遍，
    而每一份都各自决定「怎么算已裁」「返回什么键」，抄漏一条就是一个静默 bug。

    ## 为什么返回原始 payload 而不是统一形状

    四个前端消费的形状本就不同（定字台要 `{shape, reading, done}`，
    列清理台要 `{side_verdict, top_class, bot_class}`）。硬统一成一种形状
    要改写全部前端——那是阶段三裁决台改造的事。这里统一的是**接口与去重
    规则**，形状仍由各 question 自己决定：给回原始 payload，前端取自己要的键。

    ## 去重

    同一 `(question, key)` 多次裁决按 `(batch, seq)` 升序**后到覆盖**
    ——沿用 seed_queue 的纪律，人改主意时最后一次说了算。

    **按 question 而不是 key 去重**是必须的：切线裁决与定字裁决的 key 形状
    完全一样（都是 `bxgb:39:19:12`），只按 key 去重会把没裁过的字位误当已裁
    （这正是 `DECIDED_KINDS` 那条注释记的坑）。`question` 比 `kind` 更精确
    ——`kind=verdict` 底下有三个不同的问题。

    没带 `question` 的历史事件按 `kind` 兜底归类，不丢。
    """
    out: dict[str, dict] = {}
    for e in sorted((log or EventLog()).read(batch), key=lambda x: (x.batch, x.seq)):
        p = dict(e.payload or {})
        q = p.get("question") or e.kind          # 历史事件没有 question，用 kind 兜底
        if question is not None and q != question:
            continue
        out[e.target.key] = p
    return {"batch": batch, "question": question, "n": len(out), "verdicts": out}
