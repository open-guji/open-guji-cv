"""管线**回流**读裁决表：给 Step 用的只读查询，数据源是 workspace 的
`feedback/verdicts/`（`consumers.verdict_store()`），**不是** open-guji-dataset。

三仓边界（2026-09-13）：生产管线运行时只读写 workspace。第一版人裁回流从测试集
仓取金标（cv `78319605cf`，已撤），这里是改到裁决表之后的版本。
"""

from __future__ import annotations

from typing import NamedTuple

from ..utils.ji_yi_si import FAMILY as _JYS
from ..utils.row_boundaries import RESOLVED_CHOSEN, ResolvedCut

TOUCHING_CUTS_SHARD = "char-segmentation/touching-cuts"
CUT_KINDS = ("straight", "seam_narrow", "seam_wide", "unet_seam", "period_up", "period_dn")   # 后三种 = L3 扩池（2026-09-15）


def _resolve(expected: dict) -> ResolvedCut | None:
    """一条 touching-cuts 裁决 → 能收敛成什么；收不了返回 None。

    | 裁决 | 收敛到 | 护栏 |
    |---|---|---|
    | `cand` ∈ CUT_KINDS（Step7 裁决台 `confirmed`、切线卡 `cand`）| 那个 kind | 有 `y_old` 就按它 |
    | `ok`（现役直线切点就对）| `straight` | `y_old`（= 当时的直线 y）|
    | `seam_ok`（现役折线缝就对）| 池里与人看到的折线一致的那条（`RESOLVED_CHOSEN` + `seam_ref`=polyline）| `y_old`，没有则 `y`；折线偏差 ≤ RESOLVED_SEAM_TOL |
    | `moved` 无 cand（人拖到别处）| — | 候选池里没有「人挪到的位置」|
    | `overlap` / `idk` | — | 真难例，留给人 |

    护栏的意思：裁决是对着**当时**的切点做的，现役直线 y 与 `y_old` 差超过
    `RESOLVED_Y_TOL` 就不是同一条格线，不套（`_apply_resolved_cut` 里比）。
    """
    verdict = expected.get("verdict")
    cand = expected.get("cand")
    y_old = expected.get("y_old")
    if verdict in ("overlap", "idk"):
        return None
    if cand in CUT_KINDS:
        return ResolvedCut(cand, None if y_old is None else float(y_old))
    if verdict == "ok" and y_old is not None:
        return ResolvedCut("straight", float(y_old))
    if verdict == "seam_ok":
        y_ref = y_old if y_old is not None else expected.get("y")
        poly = expected.get("polyline")
        return ResolvedCut(RESOLVED_CHOSEN, None if y_ref is None else float(y_ref),
                           seam_ref=poly if poly and len(poly) >= 2 else None)
    return None


SLOT_COUNT_SHARD = "char-segmentation/column-slots"


class ResolvedColumn(NamedTuple):
    """人裁给的列级版式覆盖。

    `uniform=False` 表示这一列**字距不均匀**（刻工前疏后密之类），DP 的等距
    先验要放宽——见 `row_boundaries.NONUNIFORM_LAM` 的标定记录。缺省 True：
    2026-09-20 之前写的裁决没有这个键，等距是版式常识，不该因为加了新键就
    把历史裁决的含义改掉。
    """
    n_slots: int
    uniform: bool = True


def resolved_slots(book: str) -> dict[tuple[int, int], ResolvedColumn]:
    """已裁决的逐列版式覆盖：`(page, col) → ResolvedColumn(n_slots, uniform)`。

    数据源、生效时机跟 `resolved_cuts` 完全同一套路（见该函数 docstring）——
    `row_segment` 在该页重跑时按这张表覆盖 `effective_body_slots` 算出的
    `n_body_col`；裁决不进指纹，靠 `product_invalidate` 显式失效驱动重跑。

    卡片 id 是 `book:page:col`（三段，`review/slot_count_cards.py`），
    `parse_card_id` 走的是既有 `bxgb:3:1` 模式（Step2 列清理同一条正则，
    2026-09-17 加），anchor 里没有 `slot` 字段——这里不需要它。
    """
    from .consumers import verdict_store
    out: dict[tuple[int, int], int] = {}
    try:
        items = verdict_store().list(SLOT_COUNT_SHARD, legacy=False)
    except Exception:
        return out
    for it in items:
        if it.status != "active" or str(it.anchor.book) != book:
            continue
        page, col = it.anchor.page, it.anchor.col
        if page is None or col is None:
            continue
        n = it.expected.get("n_slots")
        if isinstance(n, int) and n > 0:
            uni = it.expected.get("uniform")
            out[(page, col)] = ResolvedColumn(n, True if uni is None else bool(uni))
    return out


SOLO_NOTE_SHARD = "char-segmentation/solo-notes"


def resolved_solo_notes(book: str) -> dict[tuple[int, int], set[int]]:
    """人裁「这一格是單行小注」：`(page, col) → {slot, …}`。

    `jiazhu_split.solo_notes` 纯几何量到头的那一型——干扰墨恰好落在左半，与「左半
    空着」这个核心信号正面冲突（bxgb `p3c4s5`「覿」，见 overview Step3-12 预案）。
    判据不会为它举手，只能人指出来。卡片 id `book:page:col:slot`，`expected.kind`
    只认 `jiazhu_solo`；生效时机同 `resolved_cuts`（裁决不进指纹，该页重跑才生效）。
    """
    from .consumers import verdict_store
    out: dict[tuple[int, int], set[int]] = {}
    try:
        items = verdict_store().list(SOLO_NOTE_SHARD, legacy=False)
    except Exception:
        return out
    for it in items:
        if it.status != "active" or str(it.anchor.book) != book:
            continue
        a = it.anchor
        if a.page is None or a.col is None or a.slot is None:
            continue
        if it.expected.get("kind") == "jiazhu_solo":
            out.setdefault((a.page, a.col), set()).add(a.slot)
    return out


def resolved_cuts(book: str) -> dict[tuple[int, int, int], ResolvedCut]:
    """已裁决、可收敛的切点：`(page, col, slot_above) → ResolvedCut`。判据见 `_resolve`。

    生效时机：`segment_column` 在**该页重跑**时按这张表收敛候选。裁决不进产物指纹
    （指纹是步骤级参数，塞进去会让全书 Step3 及下游一起过期）；改为 cutline 事件
    消费时把该页 `row_segment` 显式失效（`consumers.product_invalidate`），下次跑批
    只重算裁过的页。Step7 顺序闸另按事件日志即时放行（`review/cards.py`）。
    """
    from .consumers import verdict_store
    out: dict[tuple[int, int, int], ResolvedCut] = {}
    try:
        items = verdict_store().list(TOUCHING_CUTS_SHARD, legacy=False)
    except Exception:
        return out
    for it in items:
        if it.status != "active" or str(it.anchor.book) != book:
            continue
        page, col, slot = it.anchor.page, it.anchor.col, it.anchor.slot
        if page is None or col is None or slot is None:
            continue
        r = _resolve(it.expected)
        if r is not None:
            out[(page, col, slot)] = r
    return out


def resolved_pins(book: str, store=None) -> dict[tuple[int, int, int], float]:
    """人**拖过或认可过**的切线：`(page, col, slot_above) → 当前列图里的 y`（2026-09-26）。

    `resolved_cuts` 只认「选某条候选」「现役就对」两类——人把线拖到别处（`moved`、没选候选）
    的裁决只进金标，Step3 重跑照旧切在原处，人白拖（vol02 179:1:18「百」首横、140:9:8「舊」
    下半，用户：「这两个会影响识字」）。这里把它们变成**钉住的格线**：`segment_column` 用人给的
    位置替换 DP 那一条（`pinned_cuts`），缝照常在新位置附近找。

    只收带页面坐标的裁决（`page_x/page_y`，09-26 起写入时自动记，见 eval/colgeom.py），
    按**当前**列窗几何换算成行号——老裁决的 `y` 是对哪版列图拖的已无从知道（vol02 一批
    漂了 20–50px 而 col_h 不变），套上去可能把线钉到字身上，不收。
    """
    from ..eval.colgeom import current_geom
    from ..products.store import ProductStore
    from .consumers import verdict_store
    st = store or ProductStore()
    out: dict[tuple[int, int, int], float] = {}
    try:
        items = verdict_store().list(TOUCHING_CUTS_SHARD, legacy=False)
    except Exception:
        return out
    for it in items:
        ex = it.expected
        # `ok` 也收（2026-09-26）：人对着**钉住后的线**又按了回车，后到的 `ok` 覆盖了先前的 `moved`，
        # 若只认 `moved`，钉子就此丢了、重跑又退回 DP 那条（vol02 179:1:19 等 6 条实测退回 25–41px）。
        # `ok` 的 y 就是人当时看到并认可的位置，钉上去与现状一致时什么都不变。
        if it.status != "active" or str(it.anchor.book) != book or ex.get("verdict") not in ("moved", "ok"):
            continue
        if ex.get("cand") or ex.get("page_y") is None:
            continue
        a = it.anchor
        if a.page is None or a.col is None or a.slot is None:
            continue
        g = current_geom(st, book, a.page, a.col)
        if g is None:
            continue
        out[(a.page, a.col, a.slot)] = g.page_to_row(float(ex["page_x"]), float(ex["page_y"]))[0]
    return out


def stale_human_marks(book: str) -> dict[str, str]:
    """字形库里已撤下的人裁：`{裸 id: 撤下时刻 YYYYMMDD 或 YYYYMMDDTHHMM（UTC）}`（`admissions.provenance='human_stale_<日期>'`）。

    撤法见 `scripts/check_stale_human.py`（重字签名）与 2026-09-25 的漂移检查
    （`scripts/experiments/verdict_drift_check.py`：人裁时入库的图块 vs 同一编号现在的图块）。
    库读不到就当没有——事件侧的人裁照旧生效，不因为这张表缺席就全部作废。
    """
    import sqlite3

    from ..core.workspace import glyph_db_path
    out: dict[str, str] = {}
    try:
        con = sqlite3.connect(str(glyph_db_path()))
        rows = con.execute("SELECT instance_id, provenance FROM admissions "
                           "WHERE provenance LIKE 'human_stale_%'").fetchall()
    except Exception:
        return out
    for iid, prov in rows:
        key = iid[3:] if iid.startswith("v2:") else iid
        if key.startswith(book + ":"):
            out[key] = prov.rsplit("_", 1)[-1]
    # 没进字形库的人裁（勾了不入库、或 v1 编号）改不了 provenance，另记一张作废表：
    # `<feedback>/lists/stale_verdicts.tsv`，每行 `字位id<TAB>撤下时刻<TAB>原因`（2026-09-25 加）。
    from ..core.workspace import feedback_root
    try:
        path = feedback_root() / "lists" / "stale_verdicts.tsv"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            key, cut = line.split("\t")[:2]
            if key.startswith(book + ":"):
                out[key] = max(out.get(key, ""), cut.strip())
    except (FileNotFoundError, OSError, ValueError):
        pass
    return out


def human_chars(book: str, log=None, stale: dict[str, str] | None = None,
                bind: bool | None = None) -> dict[str, str]:
    """人在定字台上定过的字 → `{裸 id: 字}`，同一位**后到覆盖**。

    只有字形（2026-09-26 取消读法）。唯一的例外是**老事件**里的 己/已/巳：当时允许「看着像 X、
    读作 Y」两栏分填，Y 才是人按上下文定的字——本族字形本就不分（`utils/ji_yi_si.py`），取 Y。

    2026-09-20 补的缺口：Step7 此前只从字形库拿人裁（`seed_admit._human_shapes`，
    `provenance='human'`），而人勾了「字形不入库」的裁决根本不进库——bxgb 11 个「已裁未放行」
    里 5 个（一/吏/邢/太/伋）就是这样：人明明定了字，Step7 一直当没裁过，文本层照旧出阙文，
    定字台又因 `skip_decided` 不再出卡，成了两边都不管的死角。

    「不入库」说的是**这块图不当范本**（切坏/残/不典型），不是"这个字没定"。文本采信要走
    事件日志，进库才看字形库——两件事两条路。只认 `kind=confirm ∧ payload.v=confirm` 且带
    `shape` 的事件；`not_a_char` / `damaged` / `seg_defect` 各有各的去处（排除名单、打回台账）。

    与 `_human_shapes` 同一条警告：切分改了，旧裁决就钉在了错的格上——这里同样不查几何。
    **但要认字形库里的撤下标记**（2026-09-25 补）：某一位在库里被撤成 `human_stale_<日期>`，
    那天及以前的事件就作废（否则撤了库里那份，事件这条路又把旧裁决原样送回来）；
    撤下之后再裁的事件照常生效。`stale` 缺省从字形库读（`stale_human_marks`），测试可直接传。

    **重绑定**（2026-09-25，总览/15）：`bind` 为真时每条裁决先过绑定表（`feedback/bindings.py`）——
    按锚在现行切分里找回它现在对应的格：原格仍是那个字照用，整列顺移了改绑到新编号，
    切开/合并/找不到的不采信（回待审）。缺省 `bind=None` = 读工作区事件日志时开、传入测试日志时关。
    """
    if stale is None:
        stale = stale_human_marks(book)
    if bind is None:
        bind = log is None
    bound: dict[str, dict] = {}
    if bind:
        try:
            from .bindings import book_bindings
            bound = book_bindings(book, log)
        except Exception:
            bound = {}            # 绑定表算不出来就退回按编号（与 09-25 之前一致），不因此丢掉全部人裁
    from .events import EventLog
    out: dict[str, tuple[str, str | None]] = {}
    pre = f"{book}:"
    try:
        # 按**时间**后到覆盖，不按批次名：Step8 复核（`<book>-collate`）改的字要压过更早的
        # Step7 定字，而批次名排序下 `bxgb-list-…-decide` 排在 `bxgb-collate` 后面，
        # 会把复核改好的字盖回去（2026-09-24）。同一秒内再按批次/seq 定序。
        evs = sorted((log or EventLog()).iter_all(), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return out
    for e in evs:
        if e.kind != "confirm" or e.target.unit != "cell" or not e.target.key.startswith(pre):
            continue
        p = e.payload or {}
        # `seg_defect` 带着字也算定了字（2026-09-20 用户定）：「有噪声 / 字形不完整」说的是
        # **这块图**的毛病，人同时看得出是哪个字时，那个字不该被丢——文本照样出字，
        # 缺陷照样反馈给 Step3（`gold_add` 那边本来就留着 shape，见 consumers.py）。
        # 没填字的 seg_defect 仍然只是缺陷，不在这里出现。
        if p.get("v") not in ("confirm", "seg_defect") or not p.get("shape"):
            continue
        cut = stale.get(e.target.key)
        # 撤下标记可以只到日（human_stale_20260917）或到分钟（human_stale_20260925T0712，同一天撤了又重裁时要用）
        if cut and e.ts.replace("-", "").replace(":", "")[:len(cut)] <= cut:
            continue
        key = e.target.key
        if bind:
            from .bindings import usable
            key = usable(bound.get(e.id)) if e.id in bound else key
            if key is None:
                continue                  # 挂错格 / 切开合并 / 格没了：不采信，回待审
        ch = str(p["shape"])
        rd = p.get("reading")
        if ch in _JYS and rd in _JYS:
            ch = rd
        out[key] = ch
    return out
