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

import json
import re
from pathlib import Path

from ..core.book import load_book
from ..core.spec import cell_key, page_key
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


DOUBT_NONE = "_none"
"""`doubt` 筛选与计数里的伪码：这张卡一个 doubt 码都没有（只有中文说明或全空）。"""

_DOUBT_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


def doubt_codes(doubts) -> list[str]:
    """卡片 `doubts` 里的**码**（`channel_off`、`occluded` 这种小写标识符）。

    `doubts` 里还混着 `_doubts()` 写的中文说明（「库里没有这个字」「库 unsure(cov=0.123)」），
    那是给人读的一句话、带数值，每张卡都不一样，不能当筛选键——只取码。"""
    return [d for d in (doubts or []) if isinstance(d, str) and _DOUBT_CODE.match(d)]


def parse_doubt_filter(doubt: str) -> frozenset[str] | None:
    """`doubt` 参数 → 选中的码集合（overview#215）。

    - `""`（缺省）→ `None`：不筛、不计数，响应与加这个参数之前逐字节一样；
    - `"*"`（或 `all`）→ 空集：**不筛**，但响应带 `doubt_counts`（前端要先拿到计数才画得出按钮）；
    - `"occluded,channel_off"` → 只出带其中任一码的卡；`_none` = 一个码都没有的卡。
    逗号 / 空格 / 中文逗号都当分隔符（与 `cells:` 同一口径）。"""
    raw = (doubt or "").replace("，", ",").replace(" ", ",")
    toks = [t.strip() for t in raw.split(",") if t.strip()]
    if not toks:
        return None
    if any(t in ("*", "all") for t in toks):
        return frozenset()
    bad = [t for t in toks if t != DOUBT_NONE and not _DOUBT_CODE.match(t)]
    if bad:
        raise ValueError(f"doubt 只认小写码（如 occluded,channel_off）或 * / {DOUBT_NONE}，这些不对：{bad}")
    return frozenset(toks)


# ── 按类别审（overview#247，2026-09-28）────────────────────────────────
#
# 用户：「按原因」升为主导航。doubt 码一张卡可以带好几个（vol03 待审 804 张里 357 张同时带
# replace_align／上下文 margin 不足／库 unsure 三条），按码筛会让同一张卡在好几个按钮下
# 各出现一次、裁完一类别的按钮数不动。所以另立一层**类别**：每张卡只归一类——按下表从上
# 往下第一条命中的（优先级 = 表序）。各类卡片样式与快捷键不同（前端 `reviewClass.ts`），
# 例如「己已巳」只给三选一。
#
# 表序的道理：先挑**卡片形态完全不同**的（印章遮挡有整组确认、己已巳三选一、义定形未定只列组内形），
# 再按「人该看什么」排：整理本冲突 → 形近 → 库里没有（生僻字，要查候选）→ 异体／通道 →
# 对齐改字层 → 其余（库 unsure／上下文 margin 不足这类「只是分数不够」）。

REVIEW_CLASSES: tuple[tuple[str, str, str], ...] = (
    ("occluded", "印章遮挡", "印章／污损遮挡：默认整理本字、字形不入库，可整组确认"),
    ("ji_yi_si", "己已巳", "己／已／巳 刻法不分，按上下文三选一（定的是文意）"),
    ("form_open", "义定形未定", "整理本定得了是哪个字、定不了本书刻哪个形：只在组内形里挑"),
    ("ref_conflict", "与整理本冲突", "上下文或铁证与整理本对位字不同（context_vs_ref / iron_vs_ref / signal_conflict）"),
    ("near_form", "形近字", "形近家族成员（near_form / solo_confusable），对着上下文细看"),
    ("lib_miss", "库里没有", "字形库里没有这个字：多半是生僻字，看「查候选」"),
    ("variant", "异体／通道", "异体间接边、换字取形、本书关掉的通道（variant_indirect / replace_form / channel_off / ref_lib_variant）"),
    ("replace_align", "对齐改字层", "整理本对位来自 replace 段（位置可能错开一两格）"),
    ("other", "其余", "只是分数不够：库 unsure、上下文 margin 不足等"),
)
CLASS_KEYS = tuple(k for k, _l, _h in REVIEW_CLASSES)

_CLS_CODES = {
    "ref_conflict": {"context_vs_ref", "iron_vs_ref", "signal_conflict"},
    "near_form": {"near_form", "solo_confusable"},
    "variant": {"variant_indirect", "replace_form", "channel_off", "ref_lib_variant"},
    "replace_align": {"replace_align"},
}


def card_class(doubts, evidence: dict | None = None, char: str | None = None,
               ref_char: str | None = None, lib_top: str | None = None) -> str:
    """一张待审卡归哪一类：`REVIEW_CLASSES` 表序第一条命中的。纯函数。

    `char` = seed_admit 的字，`ref_char` = 整理本对位字，`lib_top` = 字形库首选——
    三者任一落在 己已巳 一族（或产物已挂 `ji_yi_si` 证据／`ji_yi_si_review` 码）就归「己已巳」。
    """
    from ..utils.ji_yi_si import FAMILY
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    codes = set(doubt_codes(ds))
    ev = evidence or {}
    if "occluded" in codes or ev.get("occluded"):
        return "occluded"
    if ("ji_yi_si_review" in codes or ev.get("ji_yi_si")
            or any(c and c in FAMILY for c in (char, ref_char, lib_top))):
        return "ji_yi_si"
    if "form_open" in codes:
        return "form_open"
    for k in ("ref_conflict", "near_form"):
        if codes & _CLS_CODES[k]:
            return k
    if any(d.startswith("库里没有") for d in ds):
        return "lib_miss"
    for k in ("variant", "replace_align"):
        if codes & _CLS_CODES[k]:
            return k
    return "other"


def parse_class_filter(cls: str) -> str | None:
    """`cls` 参数 → `None`（不分类，响应与改前一样）/ `"*"`（只计数）/ 某个类别键。"""
    c = (cls or "").strip()
    if not c:
        return None
    if c in ("*", "all"):
        return "*"
    if c not in CLASS_KEYS:
        raise ValueError(f"cls 只认 {'/'.join(CLASS_KEYS)} 或 *，得到 {c!r}")
    return c


def _align_ref_maps(st: ProductStore, book: str, pg: int) -> tuple[dict, dict]:
    """一页 `align_ref` 产物 → (`{id: (字, op, run)}` 现役对位，`{id: 字}` 坐标对位)。

    卡片「整理本」一栏与上下文都读它——正是 seed_admit 做准入时用的那份对位
    （#247 起不再绕 `gold.v2_align.align_book`：那条路缺产物时要现建 34 万字的 8-gram
    索引，四庫 vol03 一次载入 6 s／600 MB 全花在这上）。整理本里若混进康熙部首码位
    （⼰ U+2F30 之类），这里一并归一成正字（`utils.radicals.fold_radicals`）。
    """
    from ..utils.radicals import fold_radicals
    ar = st.read(book, "align_ref", page_key(pg), "align_ref")
    if ar is None:
        return {}, {}
    main = ({c.id: (fold_radicals(c.align_char), c.align_op, c.ref_run) for c in ar.chars
             if c.align_char} if ar.anchored else {})
    coord = {c.id: fold_radicals(c.ref_char) for c in (getattr(ar, "coord", None) or [])
             if c.ref_char and c.ref_char != "〓"}   # 逐列本的 PUA 生僻字占位，不当整理本字显示
    return main, coord


def cards(book: str, pages: str = "dev_set", limit: int = 400,
          only: str = "review", store: ProductStore | None = None,
          gate_cut: bool = True, skip_decided: bool = True,
          emb_out: dict | None = None, doubt: str = "", cls: str = "") -> dict:
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

    `emb_out`（#166）：给一个 dict，借库书（开了 `first_pick`）算 CNN 首选时顺手把
    `{卡片 id: r5 embedding}` 填进去，批审组内聚簇复用；不改返回值。

    `doubt`（overview#215）：按 doubt 码筛，语法见 `parse_doubt_filter`。给了（哪怕是 `*`）
    响应就多两项：`doubt_counts`（码 → 卡数）与 `doubt_total`（参与计数的卡数）。计数口径 =
    **过了 only / 已裁去重 / 排除名单 / 顺序闸、还没按 doubt 筛**的那批卡，且**不受 `limit`
    截断**（数到页范围末尾）——按钮上的数是「这个原因一共还有几张」，不是「这一屏里有几张」。
    一张卡带几个码就在几个码下各记一次；一个码都没有的记在 `_none`。
    缺省 `""` 时一行代码路径都不变，返回值与改前逐字节一致。

    `cls`（overview#247）：按**类别**审，类别表与归类规则见 `REVIEW_CLASSES`／`card_class`
    （一张卡只归优先级最高的一类）。`"*"` = 不筛只计数，某个类别键 = 只出这一类。给了就：
    每张卡多一个 `cls` 字段；响应多 `class_counts`（类别 → 张数，口径与 `doubt_counts` 相同：
    过了 only／已裁去重／排除名单／顺序闸，不受 `limit` 截断）、`class_total` 与 `classes`
    （表：键／中文名／说明，按优先级排）。缺省 `""` 时这些都没有。
    """
    sel = parse_doubt_filter(doubt)
    csel = parse_class_filter(cls)
    class_counts: dict[str, int] = {}
    n_cls = 0
    counting = sel is not None
    doubt_counts: dict[str, int] = {}
    n_counted = 0
    full = False                    # 已凑满 limit；还在数的话只数不装
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
    # 读 `align_ref` 产物（`ref` = 整理本在这一位印的字），锚不上的页没有；逐页取，见 `_align_ref_maps`。
    # 忠于刻本字形：整理本印 即、本书惯刻 卽 时，账本的 preferred 也一并给，卡片并排列出。
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
        # 坐标对位（align_ref `coord`，overview#195）：现役对位没给字的格用它补「整理本」一栏
        golds, coord = _align_ref_maps(st, book, pg)
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
                    if not full:
                        out_blocked.append({"id": r.id, "page": pg, "col": cc.col,
                                            "slot": r.slot, "pending": _pend})
                    continue
                if counting:
                    _codes = doubt_codes(r.doubts) or [DOUBT_NONE]
                    n_counted += 1
                    for _c in dict.fromkeys(_codes):
                        doubt_counts[_c] = doubt_counts.get(_c, 0) + 1
                    if sel and not sel.intersection(_codes):
                        continue
                    if full and csel is None:
                        continue
                mr, dr = mm.get(r.id), dd.get(r.id)
                gc = golds.get(r.id)
                _cls = None
                if csel is not None:
                    _lib = (mr.candidates[0][0] if mr and mr.candidates else None)
                    _cls = card_class(r.doubts, r.evidence, r.char,
                                      gc[0] if gc else coord.get(r.id), _lib)
                    n_cls += 1
                    class_counts[_cls] = class_counts.get(_cls, 0) + 1
                    if full or (csel != "*" and _cls != csel):
                        continue
                groups, ai = _ai_view(dr)
                key = cell_key(pg, cc.col, r.slot) + (r.sub or "")
                ref = None
                if gc:
                    pf = ledger.preferred_form(gc[0])
                    ref = {"char": gc[0], "op": gc[1], "run": gc[2],
                           "form": pf if pf and pf != gc[0] else None}
                elif coord.get(r.id):
                    pf = ledger.preferred_form(coord[r.id])
                    ref = {"char": coord[r.id], "op": "coord", "run": 1,
                           "form": pf if pf and pf != coord[r.id] else None}
                # 印章／污损遮挡（Step7 `occluded_gate`）：默认字 = 整理本字（坐标对位优先），
                # 字形一律不入库；`char=None` 且 ref_blank = 整理本这一位是空格（假格），默认「非字」。
                _occ = (r.evidence or {}).get("occluded")
                occluded = ({"char": r.char or "", "via": _occ.get("via"),
                             "ref_blank": bool(_occ.get("ref_blank"))} if _occ else None)
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
                    "occluded": occluded,
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
                    **({"cls": _cls} if _cls is not None else {}),
                })
                if len(out) >= limit:
                    if not counting and csel is None:
                        return _finish(book, bk, st, {"book": book, "cards": out, "truncated": True,
                                                      "blocked": out_blocked,
                                                      "n_decided": len(decided)}, emb_out)
                    full = True             # 计数要数到页范围末尾，卡片不再装
    res = {"book": book, "cards": out, "truncated": full,
           "blocked": out_blocked, "n_decided": len(decided)}
    if counting:
        res["doubt_counts"] = dict(sorted(doubt_counts.items(), key=lambda kv: (-kv[1], kv[0])))
        res["doubt_total"] = n_counted
    if csel is not None:
        res["class_counts"] = {k: class_counts[k] for k in CLASS_KEYS if class_counts.get(k)}
        res["class_total"] = n_cls
        res["classes"] = [{"key": k, "label": lb, "hint": h} for k, lb, h in REVIEW_CLASSES]
    return _finish(book, bk, st, res, emb_out)


def _finish(book: str, bk, st: ProductStore, res: dict, emb_out: dict | None = None) -> dict:
    """借库书的「AI 首选」改 CNN 原型（2026-09-27，任务书-C-借库书人审首选改CNN原型）。

    书 yaml `params.review.first_pick` 没开（四庫、北行等全部现有书）时**原样返回**，
    返回值与加这一步之前逐字节相同。开了：每张卡挂 `first`（默认首选、像素/CNN
    各自首位、两路是否一致），**两路不一致的排前面**（本次载入的这一批内稳定排序；
    `limit` 截断在排序之前——要全量排序就把 limit 放大，或用 `group=char`）。
    装配见 `review/borrow_first.py`。
    """
    # 印章遮挡卡排到一组、放最前（overview#195「并排到一组，方便一次过」）；组内保持原序。
    res["cards"] = sorted(res["cards"], key=lambda c: 0 if c.get("occluded") else 1)
    mode = first_pick_mode(bk)
    if mode is None:
        return res
    kw = {"emb_out": emb_out} if emb_out is not None else {}
    res["first_pick"] = annotate(book, res["cards"], st, mode, bk=bk, **kw)
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
    cases, unavailable, failed = _cutline_cases(book, pgs, st)

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
                where[(pg, cc.col, cp.slot_above)] = (getattr(cp, "k", "?"),
                                                     getattr(cp, "slot_below", cp.slot_above + 1))
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


_CASES_MEM: dict = {}
_CASES_MEM_MAX = 8
_CASES_IRRELEVANT = frozenset({"glyph_match", "ocr_candidates", "rare_candidates", "align_ref",
                               "context_decide", "seed_admit", "page_survey"})
"""识别段的步：切线用例只看切分产物（row_segment 的 cells）与列图，不读它们。键里剔掉——
人裁一条 confirm 就会把那一页的 seed_admit 标失效（manifest 追加一行），不剔的话每提交一批
记忆就作废。只剔**确知无关**的；新加的步默认进键（宁可多算一次，不会读到旧的）。"""


def _cutline_cases(book: str, pgs: list[int], st: ProductStore
                   ) -> tuple[list[dict], set[tuple[int, int]], str | None]:
    """切线用例（r2s + split_char）＋取不到列图的列＋失败说明——带进程内记忆。

    这一段只看产物与列图（列图也是产物派生的），与事件日志无关；可它要把页范围里**每一列**
    的列图读一遍求投影——四庫 vol03 111 页 1788 列，一次 8.8 s（其中 imread 5.4 s）。
    按类别审（#247）每提交一批就自动载入同类下一批，人裁一写入 cards 结果缓存就失效，
    于是每一批都要重付这 8.8 s。所以按（产物 manifest 指纹、列图缓存根、页范围、取用例的
    两个函数本身）记住结果：产物一变指纹就变、自动失效；测试里 monkeypatch 了那两个函数
    也自然换键。**只记完整成功的**——有列取不到列图或取用例抛异常时不记，下次照旧重试
    （冷缓存兜底那条路的语义不变）。
    """
    from ..core.workspace import cache_root
    from ..eval import touching as T
    key = None
    if isinstance(getattr(st, "root", None), Path):     # 假 store（测试替身）没有产物根：不记
        key = (str(st.root), str(cache_root()), book, tuple(pgs),
               json.dumps([x for x in _products_sig(book, st) if x[0] not in _CASES_IRRELEVANT]),
               json.dumps([x for x in _pages_stat_sig(book, st, pgs) if x[0] not in _CASES_IRRELEVANT]),
               T.r2s_boundaries, T.split_char_boundaries)
    hit = _CASES_MEM.get(key) if key is not None else None
    if hit is not None:
        return list(hit), set(), None
    unavailable = _warm_column_images(book, pgs, st)
    failed: str | None = None
    try:
        cases = (T.r2s_boundaries(book, pgs, st)
                 + T.split_char_boundaries(book, pgs, st))
    except Exception as exc:                       # noqa: BLE001
        cases, failed = [], f"取切线用例失败（{type(exc).__name__}: {exc}）"
    if key is not None and not unavailable and failed is None:
        _CASES_MEM[key] = list(cases)
        while len(_CASES_MEM) > _CASES_MEM_MAX:
            _CASES_MEM.pop(next(iter(_CASES_MEM)))
    return cases, unavailable, failed


def _pages_stat_sig(book: str, st: ProductStore, pgs: list[int]) -> list:
    """这些页在各步下的产物文件 (名, 大小, mtime_ns)。manifest 只有跑批器写，手拷产物
    （快照导入之外的临时替换、测试直接 `st.write`）不经过它——再按文件本身兜一层。
    vol03 111 页 × 13 步 ≈ 1400 次 stat，几毫秒。"""
    root = st.root / book
    if not root.is_dir():
        return []
    names = [f"{page_key(p)}.json" for p in pgs]
    return [[d.name, _stat_sig(d / n for n in names)]
            for d in sorted(p for p in root.iterdir() if p.is_dir())]


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
            if not getattr(cc, "ok", True):
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


# ── cards 结果缓存（overview #166，2026-09-28）──────────────────────────
#
# 服务器值守实测：全唐文 v006 按字种批审，`/api/review/cards` 在那台 2 核机上一次
# 冷算 23 s，每换一次书、每刷新一次都要重算（2.3 MB JSON，传输只占 10 s 里的一小段）。
# 这里把**整个响应**按输入指纹落盘，同样的输入第二次直接读回。
#
# 键里有什么（任何一项变了都换键 = 自动失效，不需要谁记得去清）：
# - 请求参数（模式、页范围、only、顺序闸、去重、样例上限、聚簇开关与门槛）与
#   `ProductStore.root`；
# - **产物**：这本书每一步 `_manifest.jsonl` 的内容哈希——每次写产物都往 manifest
#   追加一条（含 sha256 与 `self_hash`），重跑任何一步、显式失效任何一页都会变；
# - **事件水位**：`feedback/events/*.jsonl` 的 (文件名, 大小, mtime_ns)。人裁一写入
#   水位就变，已裁格要从待审里消失、切线裁决要放开顺序闸，都靠它——#166「事件一写入
#   就让相关组失效」；点名清单模式另加清单文件本身；
# - 书 yaml 解析结果、用字账、借库书首选用到的两个字形库的内容指纹（H 道往本书库进了
#   新刻例 → CNN 首选会变）、CNN checkpoint 指纹；`CARDS_CACHE_VERSION`（装配代码改了
#   输出形状时手动加一）。
#
# 读回的是同一份 dict 的 JSON 往返，FastAPI 再序列化出来与现算逐字节相同（测试守着）。
# 命中与否只走响应头（`X-Cards-Cache`，路由层加），**不往响应体里加字段**——四庫、北行
# 的审卡数据要与改前逐字节一致（#166 验收）。

CARDS_CACHE_VERSION = "2"   # 2：整理本对位改读 align_ref 产物（#247）
_CARDS_MEM_MAX = 8
_CARDS_DISK_KEEP = 16
"""每本书磁盘上留几份（按 mtime 留最新的），其余在写新份时顺手删。"""

_cards_mem: "dict[str, dict]" = {}


def _stat_sig(paths) -> list:
    out = []
    for p in paths:
        try:
            s = p.stat()
            out.append([p.name, s.st_size, s.st_mtime_ns])
        except OSError:
            out.append([p.name, None, None])
    return out


def _events_watermark(pages: str) -> list:
    from ..core.workspace import feedback_root
    fr = feedback_root()
    ev = fr / "events"
    sig = _stat_sig(sorted(ev.glob("*.jsonl"))) if ev.is_dir() else []
    if pages.startswith("list:"):
        sig.append(["list"] + _stat_sig([fr / "lists" / f"{pages[5:].strip()}.txt"])[0])
    return sig


def _products_sig(book: str, st: ProductStore) -> list:
    import hashlib
    root = st.root / book
    out = []
    if root.is_dir():
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            m = d / "_manifest.jsonl"
            try:
                h = hashlib.sha1(m.read_bytes()).hexdigest()
            except OSError:
                h = None
            out.append([d.name, h])
    return out


def _inputs_sig(bk) -> dict:
    """产物与事件之外、会改变卡片内容的输入。取不到的项记 None（照样进键）。"""
    import dataclasses
    from ..variant_ledger import ledger_path
    sig: dict = {}
    try:
        sig["book"] = json.dumps(dataclasses.asdict(bk), ensure_ascii=False, sort_keys=True,
                                 default=str)
    except TypeError:
        sig["book"] = repr(bk)
    sig["ledger"] = _stat_sig([ledger_path()])
    from .borrow_first import first_pick_mode, proto_sources, review_db_path
    if first_pick_mode(bk) is not None:
        from ..clustering import cnn_candidates as cc
        from ..steps.glyph_match import db_fingerprint
        own, fb = proto_sources(bk)
        dbs = {"own": own, "borrow": review_db_path(bk) if fb else None}
        for k, p in dbs.items():
            try:
                sig[f"db_{k}"] = db_fingerprint(p) if p and Path(p).exists() else None
            except Exception:           # noqa: BLE001 — 坏库照样进键（记 None），不挡审卡
                sig[f"db_{k}"] = None
        sig["ckpt"] = cc.fingerprint(cc.DEFAULT_CKPT)
    return sig


def cards_cache_key(book: str, req: dict, st: ProductStore | None = None, bk=None) -> str:
    """`req` = 路由收到的全部参数（dict，可 JSON 化）。→ 40 位十六进制键。"""
    import hashlib
    st = st or ProductStore()
    bk = bk or load_book(book)
    doc = {"v": CARDS_CACHE_VERSION, "book": book, "req": req, "root": str(st.root),
           "products": _products_sig(book, st),
           "events": _events_watermark(str(req.get("pages", ""))),
           "inputs": _inputs_sig(bk)}
    return hashlib.sha1(json.dumps(doc, ensure_ascii=False, sort_keys=True,
                                   default=str).encode("utf-8")).hexdigest()


def _cards_cache_dir(book: str) -> Path:
    from ..core.workspace import cache_root
    from ..feedback.events import EventLog
    return Path(cache_root()) / "review_cards" / EventLog.safe_batch_name(book)


def cached_cards(book: str, req: dict, compute, st: ProductStore | None = None
                 ) -> tuple[dict, str]:
    """有就读回，没有就 `compute()` 再落盘。→ `(响应 dict, "mem"|"disk"|"miss")`。

    内存里留最近 `_CARDS_MEM_MAX` 份（进程内热命中不必读盘解析 2 MB JSON），磁盘
    `cache_root()/review_cards/<书>/<键>.json`，每书留最新 `_CARDS_DISK_KEEP` 份。
    缓存写失败（盘满、只读）只是没缓存，不挡返回。
    """
    import os
    st = st or ProductStore()
    key = cards_cache_key(book, req, st)
    if key in _cards_mem:
        return _cards_mem[key], "mem"
    d = _cards_cache_dir(book)
    f = d / f"{key}.json"
    if f.exists():
        try:
            res = json.loads(f.read_text(encoding="utf-8"))
            _remember(key, res)
            return res, "disk"
        except (OSError, ValueError):
            pass                        # 坏缓存当没有，重算覆盖
    res = compute()
    # 以 JSON 往返后的那份为准返回——保证冷、热两次返回的是同一种对象（tuple 都成 list）
    text = json.dumps(res, ensure_ascii=False)
    res = json.loads(text)
    _remember(key, res)
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, f)
        olds = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for p in olds[_CARDS_DISK_KEEP:]:
            p.unlink(missing_ok=True)
    except OSError:
        pass
    return res, "miss"


def _remember(key: str, res: dict) -> None:
    _cards_mem.pop(key, None)
    _cards_mem[key] = res
    while len(_cards_mem) > _CARDS_MEM_MAX:
        _cards_mem.pop(next(iter(_cards_mem)))


def clear_cards_cache(book: str | None = None) -> None:
    """清内存那份（测试、以及想强制重算时用）；磁盘份靠键自然失效。切线用例记忆一并清。"""
    _cards_mem.clear()
    _CASES_MEM.clear()


# ── 预热（#166 加急）：跑批侧把 CNN 原型与每格 embedding 算好落盘，控制台只读盘 ──

def warm_review_cache(book: str, pages: str = "all", store: ProductStore | None = None) -> dict:
    """借库书（开了 `params.review.first_pick`）审卡要用的两份 CNN 缓存一次算好：

    - 本书库 / 借库的逐例 embedding 与按字原型（`borrow_first.ProtoIndex`）；
    - `pages` 范围内**全部格**（不只待审——格在待审/自动档之间会随库变动来回走）的
      查询 embedding（`borrow_first.EmbCache`）。

    之后控制台 cards 冷算只剩非 CNN 部分（v006 实测 ~18 s，峰值 RSS +275~312 MB）。
    没开 first_pick 的书什么都不做。**跑批活**：服务器上用
    `guji-batch .venv/bin/python -m open_guji_cv.review.cards <书> [页]`，别在控制台进程里调。
    幂等：已有的直接读盘，只算缺的。
    """
    import time
    from .borrow_first import first_pick_mode
    bk = load_book(book)
    if first_pick_mode(bk) is None:
        return {"book": book, "skipped": "书 yaml 没开 params.review.first_pick"}
    t = time.time()
    d = cards(book, pages, 10**9, "all", store or ProductStore(), gate_cut=False,
              skip_decided=False)
    fp = d.get("first_pick") or {}
    return {"book": book, "pages": pages, "n_cells": len(d["cards"]),
            "cnn_ready": fp.get("cnn_ready"), "secs": round(time.time() - t, 1)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("用法：python -m open_guji_cv.review.cards <书> [页范围，缺省 all]")
    print(json.dumps(warm_review_cache(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "all"),
                     ensure_ascii=False))
