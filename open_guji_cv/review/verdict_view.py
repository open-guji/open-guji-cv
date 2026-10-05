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


def _is_decision(e, pre: str) -> bool:
    """这条事件算不算「对这一格表过态」（`decided_cells` 的口径，不看是否仍有效）。"""
    if e.kind not in DECIDED_KINDS or e.target.unit != "cell" or not e.target.key.startswith(pre):
        return False
    # 「切坏 / 带残留」**不带字**时不是定字裁决（2026-09-20，总览/13 §一·3）：人说的是
    # "这块图先别用"，没说这是什么字。此前把它也算作"裁过"，排除名单撤了之后这些格
    # 回到待审队列，`skip_decided` 却把它们永远藏起来——bxgb 42 个「已裁未放行」里
    # 31 个从没定过字，定字台上也看不见，人以为剩下的无处可做。这类的去处是 Step3
    # 的打回台账，不是这里。
    #
    # **带字就算裁过**（同日用户加的两可档）：人一边说这块图切坏了、一边指出是哪个字，
    # 定字这件事已经做完，不该再出卡；缺陷另走 gold_add 与打回通道。
    p = e.payload or {}
    return not (e.kind == "confirm" and p.get("v") == "seg_defect" and not p.get("shape"))


def _book_bindings(book: str, log, bindings):
    """绑定表 `{event_id: row}`。缺省同 `lookup.human_chars(bind=None)`：读工作区事件日志时现算，
    传入测试日志时不绑（测试直接给 `bindings`）。算不出来退回不绑——与改前一致，不因此把全书
    已裁都当失效端回队列。"""
    if bindings is not None:
        return bindings
    if log is not None:
        return {}
    try:
        from ..feedback.bindings import book_bindings
        return book_bindings(book)
    except Exception:
        return {}


def decided_view(book: str, log: EventLog | None = None,
                 bindings: dict[str, dict] | None = None) -> tuple[set[str], dict[str, dict]]:
    """→ (`decided` 现在仍有效的已裁字位, `stale` 失效老裁决 `{字位: 当时的裁决}`)。

    **只收现在仍然有效的裁决**（overview#403 缺口 A）。Step7 读人裁要过绑定表
    （`feedback/bindings.py::usable`）：老批次事件 `anchor: null`、补不出锚 → `unanchored`、
    `bound=None`，不予采信（防「切分改了、人裁钉在错格上」）。以前这里不看绑定、凡有裁决事件
    就算已裁 → 绑定表说不采信、队列说已裁不出卡，这一格两边都不管、文本出 `[[]]`，对勘才发现
    （vol03 `9:8:4` 09-10 裁「困」）。

    每条裁决事件：有绑定行 → 落到 `usable(row)`（`rebound` 落到新编号；None = 失效）；
    没有绑定行（`skip`／`relabel` 等非 confirm 事件、或事件自带锚点却还没进绑定表、或绑定表
    算不出来）→ 照原编号算有效。一格只要有一条有效裁决就算已裁。

    `stale`：有裁决、但没有一条仍有效的字位 → 最后一条失效裁决读回成定字台的形状
    （同 `review_verdicts`，`{"verdict": {shape, done, ...}, "ts", "batch", "status"}`），
    卡片拿它当预勾——人点一下确认就写出带现行锚点的新事件。
    """
    from ..feedback.bindings import usable
    decided: set[str] = set()
    last_stale: dict[str, tuple] = {}
    pre = f"{book}:"
    try:
        evs = sorted((log or EventLog()).iter_all(), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return decided, {}     # 新工作区还没有事件目录
    rows = _book_bindings(book, log, bindings)
    for e in evs:
        if not _is_decision(e, pre):
            continue
        k = e.target.key
        row = rows.get(e.id)
        if row is None:
            decided.add(k)
            continue
        nk = usable(row)
        if nk:
            decided.add(nk)
        else:
            last_stale[k] = (e, row)
    stale: dict[str, dict] = {}
    for k, (e, row) in last_stale.items():
        if k in decided:
            continue
        v = _verdict_of(e)
        if v is None:
            continue
        stale[k] = {"verdict": v, "ts": e.ts, "batch": e.batch, "status": row.get("status")}
    return decided, stale


def decided_cells(book: str, log: EventLog | None = None,
                  bindings: dict[str, dict] | None = None) -> set[str]:
    """这本书**所有批次**里已经裁过、且**现在仍有效**的字位 id（有效的口径见 `decided_view`）。

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
    return decided_view(book, log, bindings)[0]


def shape_decided_cells(book: str, log: EventLog | None = None) -> dict[str, str]:
    """事件日志里**定过字**的字位 → 最后定的字（不看绑定是否仍有效）。收尾闸用（`closure_gaps`）。

    定字 = `confirm` 事件 `v ∈ {confirm, seg_defect}` 且带 `shape`（同 `lookup.human_chars`
    的口径；非字／原刻残／只说切坏不算）。
    """
    out: dict[str, str] = {}
    pre = f"{book}:"
    try:
        evs = sorted((log or EventLog()).iter_all(), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return out
    for e in evs:
        if e.kind != "confirm" or e.target.unit != "cell" or not e.target.key.startswith(pre):
            continue
        p = e.payload or {}
        if p.get("v") in ("confirm", "seg_defect") and p.get("shape"):
            out[e.target.key] = str(p["shape"])
        elif p.get("v") in ("not_a_char", "damaged"):
            out.pop(e.target.key, None)      # 后来改判非字／原刻残：不再是「定了字」
    return out


def closure_gaps(book: str, pages: list[int], store=None, log: EventLog | None = None) -> list[dict]:
    """收尾不变量（overview#403 缺口 C）：**收尾前必须为空**。

    「事件日志里有定字裁决的格」∩「现行 seed_admit 里 `admit=False` 且文本没出字」。

    这类格是两处状态对不上、又不报错的死角——队列以为裁过了、文本层没采信（缺口 A：
    老裁决绑定失效；缺口 B：排除名单格人给了字），对勘才发现。「出字」看 Step7 记录本身：
    `admit=True`、带 `evidence.human_char`（排除名单格人给的字，缺口 B）、或遮挡格带默认字
    （`occluded` 且 `char`，文本照出），都算出了字。

    → `[{"id", "page", "shape", "excluded"}]`，按页序。没有 Step7 产物的页跳过（那是「过期／缺失」的账）。
    """
    from ..core.spec import page_key
    from ..products.store import ProductStore
    from ..report.slots import ADMIT_KIND, ADMIT_STEP
    shapes = shape_decided_cells(book, log)
    if not shapes:
        return []
    st = store or ProductStore()
    want: dict[int, set[str]] = {}
    for k in shapes:
        try:
            pg = int(k.split(":")[1])
        except (IndexError, ValueError):
            continue
        want.setdefault(pg, set()).add(k)
    out: list[dict] = []
    for pg in pages:
        ids = want.get(pg)
        if not ids:
            continue
        a = st.read(book, ADMIT_STEP, page_key(pg), ADMIT_KIND)
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                if r.id not in ids or r.admit:
                    continue
                ev = r.evidence or {}
                if ev.get("human_char") or (ev.get("occluded") and r.char):
                    continue
                out.append({"id": r.id, "page": pg, "shape": shapes[r.id],
                            "excluded": "excluded" in (r.doubts or [])})
    return out


def defect_only_cells(book: str, log: EventLog | None = None) -> set[str]:
    """最新一条定字裁决是**不带字的** `seg_defect`（只说了「这块图坏了」）的字位。

    这些格不算裁过（见 `decided_cells`），还会回到待审队列。「对齐改字层」网格缺省采信整理本，
    它们要是回到网格，人上次点掉的又成了默认采信——所以网格把它们让给逐张（overview#265）。
    """
    last: dict[str, bool] = {}
    pre = f"{book}:"
    try:
        evs = sorted((log or EventLog()).iter_all(), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return set()
    for e in evs:
        if e.kind not in DECIDED_KINDS or e.target.unit != "cell" or not e.target.key.startswith(pre):
            continue
        p = e.payload or {}
        last[e.target.key] = e.kind == "confirm" and p.get("v") == "seg_defect" and not p.get("shape")
    return {k for k, v in last.items() if v}


def flagged_cells(book: str, log: EventLog | None = None) -> set[str]:
    """最新一条相关事件是 `needs_review`（网格里人点了「要细审」）的字位。

    「对齐改字层」网格缺省采信整理本，点一下只表示「这格有疑问」，不写裁决（噪声／整理本字不对
    等原因留给逐张卡选）。格仍在待审，只是不该再回网格被默认采信，所以网格把它们让给逐张。
    后来写了任何定字裁决（`DECIDED_KINDS`）就不再算——取最新一条，同 `defect_only_cells`。
    """
    last: dict[str, bool] = {}
    pre = f"{book}:"
    try:
        evs = sorted((log or EventLog()).iter_all(), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return set()
    for e in evs:
        if e.target.unit != "cell" or not e.target.key.startswith(pre):
            continue
        if e.kind == "needs_review":
            last[e.target.key] = True
        elif e.kind in DECIDED_KINDS:
            last[e.target.key] = False
    return {k for k, v in last.items() if v}


def _verdict_of(e) -> dict | None:
    """一条定字事件 → 定字台前端的裁决形状（`review_verdicts` 与失效老裁决预勾共用）；不认识的 → None。"""
    p = e.payload or {}
    v = p.get("v") or e.kind
    if v == "not_a_char":
        return {"shape": "", "done": "non"}
    elif v == "skip":
        return {"shape": "", "done": "skip"}
    elif v == "damaged":
        # 原图破损（2026-09-19）：`guess` 要一并读回，否则刷新后括注里的
        # 「最像哪个字」凭空消失，人以为没填过、又填一遍。
        return {"shape": "", "done": "damaged", "guess": p.get("guess") or ""}
    elif v == "seg_defect":
        # 「小注当正文」（overview#265）：事件照旧是 seg_defect，靠 `reason` 读回成前端那一档，
        # 否则刷新后显示成「字形不完整」，人以为标错了又改一遍。
        done = ("jiazhu" if p.get("reason") == "jiazhu_as_main"
                else p.get("quality") or "contaminated")
        return {"shape": p.get("shape") or "", "done": done}
    elif v == "confirm":
        d = {"shape": p.get("shape") or "",
             "done": "1",
             "noGlyphLib": bool(p.get("no_glyph_lib"))}
        # 无匹配（近似字，overview#276）：勾选与 IDS／备注要读回，否则刷新后勾选丢了、人以为没勾
        # 又勾一遍。没带 `approx` 的老事件不加任何键——形状与原来逐字相同。
        if p.get("approx"):
            d.update(approx=True, approxIds=p.get("ids") or "", approxNote=p.get("note") or "")
        return d
    return None


def review_verdicts(batch: str, log: EventLog | None = None) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。

    裁决本来就落成事件了（`/api/events`），但前端只在内存里记 `RV.verdicts`，
    一刷新就空。这个接口把事件读回成同样的形状，载入卡片时合并进去。

    同一 id 多次裁决按 (batch, seq) 升序**后到覆盖**——沿用 seed_queue 的
    纪律，人改主意时最后一次说了算。
    """
    out: dict[str, dict] = {}
    for e in sorted((log or EventLog()).read(batch), key=lambda x: (x.batch, x.seq)):
        d = _verdict_of(e)
        if d is not None:
            out[e.target.key] = d
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
                             "col_h": p.get("col_h"), "cand": p.get("cand"),
                             # 几何签名（2026-09-26，eval/colgeom.py）：比 col_h 准——列窗边线变了列高可以不变
                             "geom_sig": p.get("geom_sig")}
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

    四个前端消费的形状本就不同（定字台要 `{shape, done}`，
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
