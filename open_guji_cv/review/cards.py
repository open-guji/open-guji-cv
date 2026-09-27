# -*- coding: utf-8 -*-
"""定字待审卡片的装配：一格一张，带图块 URL 与库/OCR/上下文三路证据。

从 `console/app.py::api_review_cards` 搬来（控制台重构 C2）。**装配逻辑一行未改**，
只动了三处：函数名、`ProductStore` 改成可注入、三个函数内的延迟 import 提到模块级。

搬出来之后**云端道也能调它**——不是为了显示卡片，是为了
「统计还剩多少待审、抽查自动放行那批、量一刀改动前后的待审率变化」
（方案 §二·第六类：这十条接口没有一条需要人在场，需要人在场的是浏览器里那个页面）。

⚠️ `patch` 字段仍然是 `/api/cache/...` 这种**控制台 URL**。它是给前端用的，
CLI 只看 `id`/`char`/`doubts` 那几列就行；换成别的形状会动到前端，不在本轮。
"""
from __future__ import annotations

from ..core.book import load_book
from ..core.spec import cell_key, page_key
from ..gold.v2_align import align_book
from ..products.store import ProductStore
from ..variant_ledger import BookLedger
from .borrow_first import annotate, first_pick_mode, sort_disagree_first
from .verdict_view import decided_cells


def parse_cells_spec(pages: str, book: str) -> set[str]:
    """`cells:4:1:21,6:8:1` → `{"bxgb:4:1:21", "bxgb:6:8:1"}`（2026-09-17）。

    用户「输入 4:1:21 就显示那张卡」：人裁时报出一个字位要立刻调卡对着看，
    不必先猜它在哪一页。书号可省（省了补 `book`），逗号/空格/中文逗号都当分隔符。

    返回值进 `cards()` 的 `only_ids`，与点名清单 `list:` 同一条通路，因此同样
    **不受 only / 顺序闸 / 已裁去重约束**——点名要看的就得出得来，否则「它已自动
    进库」或「旁边切线没裁」会把它静默吞掉，人对着空面板分不清是没问题还是被吞了。
    """
    raw = pages[len("cells:"):].replace("，", ",").replace(" ", ",")
    ids = {tok if tok.count(":") >= 3 else f"{book}:{tok}"
           for tok in (t.strip() for t in raw.split(",")) if tok}
    if not ids:
        raise ValueError(f"cells: 里没有可用的坐标：{pages!r}")
    bad = sorted(i for i in ids if i.count(":") < 3 or not i.split(":")[1].isdigit())
    if bad:
        raise ValueError(f"坐标要写成 页:列:格（可带书号），这些不对：{bad}")
    return ids


def _ai_view(dr) -> tuple[list[dict] | None, dict | None]:
    """`DecisionRec.groups`/`ai` → 卡片要的精简视图（人审卡按 AI 首组预选，
    2026-09-27，任务书-C-人审卡按AI预选）。

    没有就是 `None`——字段缺失时卡片照旧，不显示 AI 部分（四庫等未接
    Step6-AI 的书）。纯函数，不碰 `load_book`/`align_book`，方便单独测。
    """
    if dr is None:
        return None, None
    groups = [{"id": g.id, "members": list(g.members), "why": g.why}
              for g in dr.groups] or None
    ai = None
    if dr.ai is not None:
        a = dr.ai
        ai = {
            "runs": a.runs,
            "drop": list(a.drop),
            "drop_why": [{"c": x.c, "why": x.why} for x in a.drop_why],
            "rank": [{"group": r.group, "p": r.p, "why": r.why} for r in a.rank],
            "confidence": a.confidence,
            "need_human": a.need_human,
            "conflict_with_img": a.conflict_with_img,
            "runs_top": list(a.runs_top),
        }
    return groups, ai


def cards(book: str, pages: str = "dev_set", limit: int = 400,
          only: str = "review", store: ProductStore | None = None,
          gate_cut: bool = True, skip_decided: bool = True) -> dict:
    """待审卡片：一格一张，带图块 URL、库/OCR/上下文三路证据与疑问。

    `only`：review = 只出人审的（默认）；auto = 只出自动进库的（抽查用）；
    all = 全出。**抽查自动档是必要的**——只看人审那批，永远只能证明
    「拿不准的我确实拿不准」，证不出自动那批有没有错（那正是 100% 准确率
    这个数字要防的自证）。

    `gate_cut`：顺序闸（用户 2026-09-10）——切分线还没 review 的格位先不出字卡。
    被挡下的进返回值的 `blocked`，面板据此显示「还有 N 位等着先看切线」。
    默认开；传 False 可整批看全部（判据 E 抽审、跑评测要用）。

    `skip_decided`（用户 2026-09-16 定）：跳过**全书所有批次**已经裁过的字位，
    于是 `limit` 数的是**净新卡**——载入 30 张就是 30 张真待裁的。以前这里不看
    事件日志，每次都从第一页重数，把上轮裁过的又端出来（实测重复率见
    `verdict_view.decided_cells` 的注释）。传 False 回到旧行为（复核自己裁过的、
    或想改主意时用）。`n_decided` 一并返回，面板显示「全书已裁 N」。

    ⚠️ 点名清单模式（`pages=list:…`）**不受本开关约束**——点名要看的就得出得来，
    与 `only` / 顺序闸同一条纪律：别让人对着空面板猜是没问题还是被吞了。
    """
    st = store or ProductStore()
    bk = load_book(book)
    # 点名清单模式（2026-09-16）：`pages` 填 `list:<名字>`，读 workspace
    # `feedback/lists/<名字>.txt`（一行一个字位 id，`#` 开头是注释），**只出这几张卡**。
    # 与切线面板的 `list:` 同一套约定（`console/routers/cutline.py`），同一个目录。
    # 用途：机器筛出可疑的几十个字（如「这轮重跑后与整理本不一致的」），让人只审这些，
    # 不必按页翻。页范围由清单自己决定——出现在清单里的页才读产物。
    only_ids: set[str] | None = None
    if pages.startswith("cells:"):
        only_ids = parse_cells_spec(pages, book)
        pgs = sorted({int(i.split(":")[1]) for i in only_ids})
    elif pages.startswith("list:"):
        from ..core.workspace import feedback_root
        lp = feedback_root() / "lists" / f"{pages[5:].strip()}.txt"
        if not lp.exists():
            raise FileNotFoundError(f"清单不存在：{lp}")
        # 行尾注释也要剥掉：这些清单是机器生成给人看的，每行都带
        # `vol02:11:9:8    # 意 -> 憲` 这样的说明，不剥的话整行当 id，一张卡也出不来。
        only_ids = {ln.split("#", 1)[0].strip() for ln in lp.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")}
        only_ids.discard("")
        # id 形如 `vol02:11:9:8`（书:页:列:格，末尾可带 sub 字母）→ 取页号
        pgs = sorted({int(i.split(":")[1]) for i in only_ids if i.count(":") >= 3})
    else:
        pgs = bk.resolve_pages(pages)
    # 整理本对应字：用户 2026-09-06「审阅时没看到整理本用的是什么，应该放第一位」。
    # 拿 v2_align 的页对齐（`ref` = 整理本在这一位印的字），锚不上的页没有。
    # 忠于刻本字形：整理本印 即、本书惯刻 卽 时，账本的 preferred 也一并给，卡片并排列出。
    try:
        golds = {c.id: c for g in align_book(book, pgs, st) if g.anchored for c in g.chars}
    except Exception:
        golds = {}
    ledger = BookLedger.load_or_empty()
    out: list[dict] = []
    out_blocked: list[dict] = []
    blocked = cut_pending(book, pgs, st) if gate_cut else {}
    # 全书已裁字位（跨批次）。点名清单模式不去重——见 docstring。
    decided = decided_cells(book) if (skip_decided and only_ids is None) else set()
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
                # 点名清单：只认 id，**不受 only / 顺序闸约束**——点名要看的就得出得来，
                # 否则「这个字自动进库了」或「旁边切线没裁」会把它静默吞掉，人对着空面板
                # 不知道是没问题还是没出卡。
                if only_ids is not None:
                    if r.id not in only_ids:
                        continue
                else:
                    if r.id in decided:
                        continue
                    # 排除名单上的格（非字 / 人复核后仍切坏 / 原刻残）不出定字卡：它们不是
                    # "这是什么字"的问题——非字无字可定，切坏的是 Step3 的打回待办（总览/13）。
                    # 2026-09-20 前靠 `decided` 顺带藏住（seg_defect 事件曾算"裁过"），
                    # seg_defect 不再算裁过之后要显式挡，否则 bxgb 4 个「仍切坏」又冒出来。
                    if "excluded" in (r.doubts or []):
                        continue
                    if only == "review" and r.admit:
                        continue
                    if only == "auto" and not r.admit:
                        continue
                # 顺序闸（用户 2026-09-10 定）：这一位旁边有一条**还没 review 的切线**时，
                # 先别出字卡——先把切分线看过，再来看这个字。粒度是格位，不整页挡。
                _pend = blocked.get((pg, cc.col, r.slot))
                if _pend is not None and only_ids is None:
                    out_blocked.append({"id": r.id, "page": pg, "col": cc.col,
                                        "slot": r.slot, "pending": _pend})
                    continue
                mr, dr = mm.get(r.id), dd.get(r.id)
                groups, ai = _ai_view(dr)
                key = cell_key(pg, cc.col, r.slot) + (r.sub or "")
                gc = golds.get(r.id)
                ref = None
                if gc and gc.ref:
                    pf = ledger.preferred_form(gc.ref)
                    ref = {"char": gc.ref, "op": gc.align_op, "run": gc.op_run,
                           "form": pf if pf and pf != gc.ref else None}
                out.append({
                    "id": r.id, "page": pg, "col": cc.col, "slot": r.slot, "sub": r.sub or "",
                    "patch": f"/api/cache/{book}/char_patch/{key}.png",
                    "admit": r.admit, "channel": r.channel, "char": r.char,
                    # 己/已/巳：按上下文定的建议字（utils/ji_yi_si.py），卡片可直接点
                    "jys": (r.evidence or {}).get("ji_yi_si"),
                    # 整理本在这一位印的字（页对齐给的）；form = 本书惯刻的形（账本 preferred，≠整理本字时才有）
                    "ref": ref,
                    # 「义定形未定」的组内候选与三源证据（variant_form），卡片按它只列组内形
                    "form": (r.evidence or {}).get("form"),
                    "doubts": r.doubts,
                    "db": {"verdict": mr.verdict, "cov": round(mr.cov, 4),
                           "wmax": round(mr.wmax, 1),
                           "candidates": mr.candidates[:5]} if mr else None,
                    "ocr": (r.evidence or {}).get("ocr", []),
                    "ctx": {"char": dr.char, "margin": dr.margin,
                            "source": dr.source,
                            "llm_suggestion": dr.llm_suggestion} if dr else None,
                    # Step6-AI 三层证据（groups=词典分组，ai=AI 排序/排除/把握度）；
                    # 没接这段的书两者都是 None，卡片不显示 AI 部分。
                    "groups": groups,
                    "ai": ai,
                })
                if len(out) >= limit:
                    return _finish(book, bk, st, {"book": book, "cards": out, "truncated": True,
                                                  "blocked": out_blocked,
                                                  "n_decided": len(decided)})
    return _finish(book, bk, st, {"book": book, "cards": out, "truncated": False,
                                  "blocked": out_blocked, "n_decided": len(decided)})


def _finish(book: str, bk, st: ProductStore, res: dict) -> dict:
    """借库书的「AI 首选」改 CNN 原型（2026-09-27，任务书-C-借库书人审首选改CNN原型）。

    书 yaml `params.review.first_pick` 没开（四庫、北行等全部现有书）时**原样返回**，
    返回值与加这一步之前逐字节相同。开了：每张卡挂 `first`（默认首选、像素/CNN
    各自首位、两路是否一致），**两路不一致的排前面**（本次载入的这一批内稳定排序；
    `limit` 截断在排序之前——要全量排序就把 limit 放大，或用 `group=char`）。
    装配见 `review/borrow_first.py`。
    """
    mode = first_pick_mode(bk)
    if mode is None:
        return res
    res["first_pick"] = annotate(book, res["cards"], st, mode, bk=bk)
    res["cards"] = sort_disagree_first(res["cards"])
    return res


def blocking_cutline_cases(book: str, pgs: list[int], st: ProductStore,
                           with_fallback: bool = False) -> list[dict]:
    """顺序闸正在挡住字卡的那批切线用例（原始 case，未展开成格位字典）。

    **只挡多候选的切点**（用户定「只挡多候选切点」）：算法自己拿不准
    （给了 2+ 种切法）的地方才要人先看，单一候选说明算法有把握，不拦。

    ⚠️⚠️ **数据源必须与切线面板用的那批用例逐条相同**，否则闸门会挡下一张
    **面板根本出不了卡**的切点——人被告知「先去切线」，去了却找不到那条。
    实测踩过两次：

    1. 先拿 `eval.touching.r2s_boundaries` 当数据源 → 在 34 张待审卡上命中 **0**。
       r2s 只收「切点有墨、附近无墨谷」的真粘连，而待审字位上的 char/char 切点
       墨量多为 0，投影法本就解得开，压根不进 r2s。
    2. 改成直接读产物「有 2+ 候选就挡」 → 挡住 52 条，与面板能出的 729 条用例
       **交集为 0**。产物里的多候选按 `cut_candidates` 记，面板的用例另有
       「切点有墨 + 附近无墨谷 + 上下都是 char」的过滤，两者不是一回事。

    所以这里调**面板自己那个函数**取用例（r2s + split_char）。面板将来换了
    挑用例的口径，这里跟着变，不会再错位。被 `cut_pending`（按格位展开给
    定字审查用）与 Step7「切分裁决」板块（`scope=blocking` 时直接要这批
    完整 case 拖切线）两处共用。
    """
    from ..console import deps
    from ..eval import touching as T
    from ..utils.cut_select import PENDING_BLOB

    # 2026-09-28 修（C 道，冷缓存下顺序闸静默放行）：面板取用例要读**列图缓存**
    # （`eval.rulers._col_profile`），缓存里没有就把那一列整列跳过——不报错、只是
    # 少了用例，闸门跟着形同虚设。vol03 实测：冷缓存 blocked=0、热缓存 blocked=18，
    # 那 18 格越过「先切线后字符」直接出了字卡。两层修：
    #   ① 先把这些页的列图 materialize 出来（冷缓存时现算，热缓存时只是存在性检查）；
    #   ② 仍然取不到列图的列、或取用例抛了异常——那几列里「本该挡」的多候选切点
    #      一律当阻塞（`fallback` 注明原因），**不再静默放行**。只在 `with_fallback=True`
    #      （字卡顺序闸 `cut_pending`）时加：切线面板 `scope=blocking` 要拿用例画拖线卡，
    #      兜底用例没有几何字段，塞进去面板会坏；面板那边照旧只出能画的用例。
    unavailable = _warm_column_images(book, pgs, st)
    failed: str | None = None
    try:
        cases = (T.r2s_boundaries(book, pgs, st)
                 + T.split_char_boundaries(book, pgs, st))
    except Exception as exc:                       # noqa: BLE001
        cases, failed = [], f"取切线用例失败（{type(exc).__name__}: {exc}）"

    done = T.gold_ids()
    # `read()` 要 batch 名；这里要的是**所有**批次，走 `iter_all()`。
    # 2026-09-12 修：原先写成无参 `read()`，`TypeError` 被下面的裸 except
    # 吞掉，整个循环从未执行过——裁完一条切线，要等有人跑 harvest 把事件
    # 收进 `touching-cuts` 金标，顺序闸才认账；面板「落定 → 字卡放行」这条
    # 即时反馈链一直是哑的。
    try:
        for e in deps.event_log().iter_all():
            if e.kind == "cutline":
                done.add(e.target.key)
    except FileNotFoundError:
        pass    # 没有事件日志（新工作区）不该让整个审查面板挂掉

    # 产物里哪些切点要挡（key = (页, 列, 上格格位) → 候选条数）：多候选的，以及 L2′ 标了 `escalate`
    # 的（2026-09-15，10 卡：所选切法与 U-Net 分歧块 ≥100px——哪怕只有一条候选，算法也没把握，
    # 交人再审；用户原则「拿不准不早下结论」）。
    multi: dict = {}
    where: dict = {}        # 同键 → (切点序号, 下格格位)，兜底阻塞拼用例要
    for pg in pgs:
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            for cp in (getattr(cc, "cut_candidates", None) or []):
                where[(pg, cc.col, cp.slot_above)] = (cp.k, cp.slot_below)
                # 2026-09-15：多候选**不再一律挡**。60 条分层抽样实测（10 卡第十一节）：
                # 所选切法与 U-Net 分歧块 <20px 的 779 条里 0/20 切坏，20–60 的 5%，60–100 的 **35%**。
                # 所以只挡 `dis_unet >= PENDING_BLOB`（60）的，人工省 92%、放行里漏 1.0%。
                # `escalate`（≥100）照旧挡——那是 L2′ 判定「本层拿不准」的。
                if getattr(cp, "escalate", False):
                    multi[(pg, cc.col, cp.slot_above)] = max(len(cp.candidates), 1)
                    continue
                if len(cp.candidates) < 2 or cp.chosen is None:
                    continue
                ch = cp.candidates[cp.chosen]
                d = getattr(ch, "dis_unet", None)
                # 裁判没跑过（dis_unet 缺）时保守挡——没有信息就不该替人放行（用户原则③）
                if d is None or d >= PENDING_BLOB:
                    multi[(pg, cc.col, cp.slot_above)] = len(cp.candidates)

    out = []
    for c in cases:                     # 只走面板真能出卡的那些
        if c["id"] in done:
            continue                    # 已经 review 过了
        n = multi.get((c["page"], c["col"], c["slot_above"]))
        if not n:                       # 单一候选且未升级 = 算法有把握，不拦
            continue
        c = {**c, "n_candidates": n}    # 挂候选条数，供 cut_pending 拼说明
        out.append(c)
    if not with_fallback:
        return out
    return out + _fallback_blocking(book, multi, where, done, out, unavailable, failed)


def _warm_column_images(book: str, pgs: list[int], st: ProductStore) -> set[tuple[int, int]]:
    """把这些页 `row_segment` 里各列的列图 materialize 到缓存；返回**仍取不到**的 (页, 列)。

    热缓存时只是存在性检查（`ImageCache.get` 命中即返回，不重算）。取不到的列交给
    `_fallback_blocking` 兜底当阻塞。
    """
    from ..core.spec import column_key
    from ..core.step import RunContext
    from ..products import kinds as _k  # noqa: F401 — 注册产物种类（单独调用时也要能读 cells）
    from ..products.cache import ImageCache

    cache = ImageCache()
    bad: set[tuple[int, int]] = set()
    ctx = None
    for pg in pgs:
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            if not cc.ok:
                continue
            key = column_key(pg, cc.col)
            if cache.get(book, "column_image", key) is not None:
                continue
            try:
                if ctx is None:
                    ctx = RunContext(load_book(book), st, cache, log=lambda *_: None)
                ctx.materialize("column_image", key)
            except Exception:                      # noqa: BLE001 — 取不到就交给兜底
                bad.add((pg, cc.col))
                continue
            if cache.get(book, "column_image", key) is None:
                bad.add((pg, cc.col))
    return bad


def _fallback_blocking(book: str, multi: dict, where: dict, done: set, have: list[dict],
                       unavailable: set, failed: str | None) -> list[dict]:
    """取不到用例时的保守兜底：本该挡的多候选切点（`multi`）里，列图取不到的列
    （或取用例整体失败时的全部）一律当阻塞。宁可多挡几格，也不让切线没看过的字卡
    静默出来（用户原则「拿不准不早下结论」）。已裁过的、已在面板用例里的不重复。"""
    if not unavailable and not failed:
        return []
    seen = {(c["page"], c["col"], c["slot_above"]) for c in have}
    out = []
    for (pg, col, above), n in sorted(multi.items()):
        if (pg, col, above) in seen or (not failed and (pg, col) not in unavailable):
            continue
        cid = f"{book}:{pg}:{col}:{above}"
        if cid in done:
            continue
        k, below = where.get((pg, col, above), ("?", above + 1))
        out.append({"id": cid, "book": book, "page": pg, "col": col, "bi": k,
                    "slot_above": above, "slot_below": below, "n_candidates": n,
                    "fallback": failed or "列图取不到，切线用例算不出来"})
    return out


def cut_pending(book: str, pgs: list[int], st: ProductStore) -> dict:
    """还等着 review 的切线，按格位索引：`(页, 列, 格位) → 说明`。

    **判据（用户 2026-09-10 定：按「格位」挡）**：一条切线的**上格与下格**都是
    被它切出来的字位——切法改了，这两个字的图块就跟着变。所以这两格的字卡在
    切线 review 完之前不出来，其余格位照常。数据源见 `blocking_cutline_cases`。
    """
    cases = blocking_cutline_cases(book, pgs, st, with_fallback=True)
    out: dict = {}
    for c in cases:
        why = f"格线 {c['col']}:{c['bi']} 有 {c['n_candidates']} 种切法待 review"
        if c.get("fallback"):
            why += f"（{c['fallback']}，保守挡下）"
        # 上格与下格都是被这条切线切出来的字位，两张卡一起挡
        out[(c["page"], c["col"], c["slot_above"])] = why
        out[(c["page"], c["col"], c["slot_below"])] = why
    return out
