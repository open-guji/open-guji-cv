"""管线**回流**读裁决表：给 Step 用的只读查询，数据源是 workspace 的
`feedback/verdicts/`（`consumers.verdict_store()`），**不是** open-guji-dataset。

三仓边界（2026-09-13）：生产管线运行时只读写 workspace。第一版人裁回流从测试集
仓取金标（cv `78319605cf`，已撤），这里是改到裁决表之后的版本。
"""

from __future__ import annotations

import logging
import sys
from typing import NamedTuple

from ..utils.ji_yi_si import FAMILY as _JYS
from ..utils.row_boundaries import RESOLVED_CHOSEN, ResolvedCut
from .mojibake import is_legal_shape

# 不叫 `log`：`human_chars(book, log=None, …)` 的形参 `log` 是 EventLog 实例，
# 同名会在函数体内把这个 logger 遮住（`log.warning(...)` 变成调 EventLog 不存在的方法）。
_logger = logging.getLogger(__name__)

#: 已经警告过的 (book, key, 值)。`human_chars` 每页调用一次（vol01 206 页），不去重的话
#: 同一条老乱码会重复打印 206 遍（2026-10-08 vol01：56 条 × 206 = 11536 行，淹没真问题）。
_WARNED_BAD_SHAPE: set[tuple[str, str, str]] = set()

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


MANUAL_CELLS_SHARD = "char-segmentation/manual-cells"


def resolved_manual_cells(book: str) -> dict[tuple[int, int], list[dict]]:
    """人工指定整列的格：`(page, col) → [{slot, sub, kind, y0, y1, x0, x1}, …]`（列图坐标）。

    切分算法在这一列上怎么也切不对（职名页雙行相位不齐、压扁密排、正文页挤成半高的卷题）时，
    人对着原图把每个字框定下来，格号（`slot` + `sub`）按定本。`row_segment` 在该页重跑时直接
    采用，不再跑切分；裁决不进指纹，靠该页显式重跑生效（同 `resolved_slots`）。
    卡片 id `book:page:col`，`expected.cells` 是上面那张表，`kind` 取 char / jiazhu_a / jiazhu_b。
    """
    from .consumers import verdict_store
    out: dict[tuple[int, int], list[dict]] = {}
    store = verdict_store()
    try:
        items = store.list(MANUAL_CELLS_SHARD, legacy=False)
    except Exception:  # noqa: BLE001
        # 以前这里静默返回空表：一行格式不对（如 history 少了 ts/change），整个分片作废、所有人工指定的列
        # 悄悄退回自动切分（册2、3 收尾清单 §三，M10·D5）。现在逐行读、跳过坏行并报出来。
        items = _manual_items_lenient(store.items_path(MANUAL_CELLS_SHARD))
    for it in items:
        if it.status != "active" or str(it.anchor.book) != book:
            continue
        page, col = it.anchor.page, it.anchor.col
        cells = it.expected.get("cells")
        if page is None or col is None or not isinstance(cells, list) or not cells:
            print(f"⚠️ manual-cells {it.id}：没有页／列或 cells 为空，这一列不生效", file=sys.stderr)
            continue
        out[(page, col)] = cells
    return out


def resolved_inverted(book: str) -> dict[int, dict]:
    """反色带人审：`page → {"verdict", "rules"}`。实现在 `utils.preclean`（Step 引擎在 L1 要读，不能往上 import）。"""
    from ..utils.preclean import resolved_inverted as _r
    return _r(book)


MANUAL_CELL_KINDS = frozenset({"char", "jiazhu_a", "jiazhu_b"})
MANUAL_CELL_KEYS = ("slot", "kind", "y0", "y1", "x0", "x1")


def _manual_items_lenient(path):
    """逐行读 manual-cells 分片，坏行跳过并在 stderr 报出（不再让一行坏掉整个分片）。"""
    from ..gold.item import GoldItem
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            out.append(GoldItem.model_validate_json(line))
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ manual-cells {path} 第 {n} 行格式不对，这一列不生效：{str(e).splitlines()[0]}", file=sys.stderr)
    return out


def check_manual_cells(path) -> list[str]:
    """逐行检查 manual-cells 分片（`feedback/verdicts/char-segmentation/manual-cells/items.jsonl`），返回问题清单；空＝没问题。

    查：能否解析成金标条目；anchor 有 book／page／col；`expected.cells` 非空，每格有 slot、kind、y0、y1、x0、x1，
    kind 在 char／jiazhu_a／jiazhu_b 里，y0<y1、x0<x1；同一列 slot＋sub 不重复；history 每条有 ts、change、why。"""
    import json as _json
    from ..gold.item import GoldItem
    problems: list[str] = []
    seen: dict[tuple, int] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        where = f"第 {n} 行"
        try:
            raw = _json.loads(line)
        except ValueError as e:
            problems.append(f"{where}：不是 JSON（{e}）")
            continue
        for i, h in enumerate(raw.get("history") or []):
            miss = [k for k in ("ts", "change", "why") if not (isinstance(h, dict) and h.get(k))]
            if miss:
                problems.append(f"{where}：history[{i}] 缺 {'、'.join(miss)}")
        try:
            it = GoldItem.model_validate(raw)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{where}：金标信封不合法（{str(e).splitlines()[0]}）")
            continue
        where = f"第 {n} 行（{it.id}）"
        a = it.anchor
        if not a.book or a.page is None or a.col is None:
            problems.append(f"{where}：anchor 缺 book／page／col")
        else:
            key = (a.book, a.page, a.col)
            if key in seen and it.status == "active":
                problems.append(f"{where}：与第 {seen[key]} 行是同一列（后到的覆盖先到的）")
            seen[key] = n
        cells = it.expected.get("cells")
        if not isinstance(cells, list) or not cells:
            problems.append(f"{where}：expected.cells 为空")
            continue
        slots = set()
        for j, c in enumerate(cells):
            if not isinstance(c, dict):
                problems.append(f"{where}：cells[{j}] 不是对象")
                continue
            miss = [k for k in MANUAL_CELL_KEYS if c.get(k) is None]
            if miss:
                problems.append(f"{where}：cells[{j}] 缺 {'、'.join(miss)}")
                continue
            if c["kind"] not in MANUAL_CELL_KINDS:
                problems.append(f"{where}：cells[{j}] kind={c['kind']!r} 不认识")
            if not (c["y0"] < c["y1"] and c["x0"] < c["x1"]):
                problems.append(f"{where}：cells[{j}] 框不对（y0<y1、x0<x1）")
            sk = (c["slot"], c.get("sub") or "")
            if sk in slots:
                problems.append(f"{where}：cells[{j}] 格号 {c['slot']}{c.get('sub') or ''} 重复")
            slots.add(sk)
    return problems


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


_FORCED_JZ_CACHE: dict = {}

#: 定字台「小注当正文」：这格是 Step3 没拆的雙行小注 → 从中间拆（overview#265）。
JIAZHU_AS_MAIN = "jiazhu_as_main"
#: 反向：「正文当小注」——这格是整宽正文，Step3 把它劈成了 a/b（并进了小注段）→ 别拆（overview#415/#436）。
MAIN_AS_JIAZHU = "main_as_jiazhu"


def resolved_forced_jiazhu(book: str, log=None) -> dict[tuple[int, int], set[int]]:
    """人裁「这一格是雙行小注、从中间拆」：`(page, col) → {slot, …}`（2026-09-30）。

    数据源是事件日志里定字裁决的 `seg_defect` + `reason=jiazhu_as_main`（定字台「小注当正文」，
    overview#265）——人点那个按钮就是在说「这是小注、Step3 没拆」，不用再标一遍。**每格取最新一条
    定字类裁决**：之后又对同一格改判（定了字、判非字、跳过……）就不再强制。只认整格 key
    （`book:页:列:格`）；拆开后的 `…a`/`…b` 子格不是强制对象。

    生效时机同 `resolved_cuts`：裁决不进产物指纹，该页 `row_segment` 重跑才生效；事件消费时
    `routes.py` 那条 `reason=jiazhu_as_main` 规则会把该页 Step3 显式失效。按事件目录的
    (名, mtime, 大小) 缓存，逐页调用不会反复解析全部日志。
    """
    return _resolved_forced(book, JIAZHU_AS_MAIN, False, log)


def resolved_forced_main(book: str, log=None) -> dict[tuple[int, int], set[int]]:
    """人裁「这一格是整宽正文、别拆」：`(page, col) → {slot, …}`（2026-10-06，overview#415/#436）。

    `resolved_forced_jiazhu` 的反向：事件是 `seg_defect` + `reason=main_as_jiazhu`（「正文当小注」）。
    人看到的是**已经劈开的半格**（vol02 p100c4 的 `17a`「匕」、`17b`），所以 key 收 `…a`/`…b`
    子格（也收整格），一律归到整格 slot；同一格两半任一半当前是这条裁决就算。取最新一条的规矩同上：
    之后对**同一个 key** 改判就不再强制；重切成整格后对整格 key 定字（「此」）不撤销它——那正是
    这条裁决要的结果。生效时机、失效路由与 `resolved_forced_jiazhu` 对称（`routes.py`）。
    """
    return _resolved_forced(book, MAIN_AS_JIAZHU, True, log)


def _resolved_forced(book: str, reason: str, allow_sub: bool, log=None) -> dict[tuple[int, int], set[int]]:
    from .events import EventLog
    el = log or EventLog()
    try:
        sig = (str(el.events_dir), tuple(sorted(
            (p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in el.events_dir.glob("*.jsonl"))))
    except OSError:
        return {}
    hit = _FORCED_JZ_CACHE.get((book, sig[0], reason))
    if hit and hit[0] == sig:
        return hit[1]
    pre = f"{book}:"
    last: dict[str, tuple[tuple, bool]] = {}
    try:
        evs = list(el.iter_all())
    except FileNotFoundError:
        return {}
    from .events import counts_as_human
    for e in evs:
        if e.target.unit != "cell" or not e.target.key.startswith(pre) or not counts_as_human(e):
            continue
        p = e.payload or {}
        v = p.get("v") or e.kind
        if e.kind not in ("confirm", "not_a_char", "skip", "relabel") \
                or v not in ("confirm", "not_a_char", "skip", "damaged", "seg_defect", "relabel"):
            continue
        order = (e.ts, e.batch, e.seq)
        k = e.target.key
        if k not in last or order >= last[k][0]:
            last[k] = (order, v == "seg_defect" and p.get("reason") == reason)
    out: dict[tuple[int, int], set[int]] = {}
    for k, (_o, forced) in last.items():
        if not forced:
            continue
        parts = k.split(":")
        if len(parts) != 4:
            continue
        if allow_sub and parts[3][-1:] in ("a", "b"):
            parts[3] = parts[3][:-1]
        if not all(x.lstrip("-").isdigit() for x in parts[1:]):
            continue
        out.setdefault((int(parts[1]), int(parts[2])), set()).add(int(parts[3]))
    _FORCED_JZ_CACHE[(book, sig[0], reason)] = (sig, out)
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
    （`research/verdict_drift_check.py`：人裁时入库的图块 vs 同一编号现在的图块）。
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


def _superseded_events(evs: list, bound: dict[str, dict], pre: str) -> set[str]:
    """R1（`bindings.strict_enabled`）：同一原始格上更晚的定字事件不可用（绑定为 None），
    更早的事件不再顶上——否则新裁被丢后旧裁静默生效（vol02 10-02 shiftfix 批）。
    另：rebound 到别格的事件，若目标格自己有更晚的原生定字事件，也让位。

    只看带 `shape` 的 confirm／seg_defect 事件（与 `human_chars` 取字口径一致）。"""
    from .bindings import usable
    mine = []
    for e in evs:
        p = e.payload or {}
        if (e.kind == "confirm" and e.target.unit == "cell" and e.target.key.startswith(pre)
                and p.get("v") in ("confirm", "seg_defect") and p.get("shape")):
            mine.append(e)
    latest: dict[str, object] = {}
    for e in mine:                       # evs 已按 ts 升序
        latest[e.target.key] = e
    out: set[str] = set()
    for e in mine:
        lt = latest[e.target.key]
        if lt is not e and usable(bound.get(lt.id)) is None:
            out.add(e.id)                # 同格更晚的事件不可用：更早的不顶上
            continue
        u = usable(bound.get(e.id))
        if u and u != e.target.key:
            own = latest.get(u)
            if own is not None and (own.ts, own.batch, own.seq) > (e.ts, e.batch, e.seq):
                out.add(e.id)            # rebound 的落点有更晚的原生事件：让位
    return out


def human_chars(book: str, log=None, stale: dict[str, str] | None = None,
                bind: bool | None = None, lost: dict[str, dict] | None = None) -> dict[str, str]:
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

    **绑丢了的人裁不能悄悄消失**（2026-10-20，GUJI-697）：传 `lost`（一个空 dict）时，绑定后
    不采信的裁决按**原编号**记进去：`{原编号: {"char", "status", "event", "ts"}}`；同一编号之后
    又有可采信的裁决（出现在返回值里）的不记。`seed_admit` 拿它做「人裁绑丢」闸：机器在这一格
    放行的字与人当年裁的不一样，就退回待审并报 warning——人裁永远是最高优先级，绑丢了也不许
    让机器的新放行顶掉（册2 重跑实测 22:6:7 戕→成、64:9:21 止→什）。
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
    from .events import EventLog, counts_as_human, iter_events_readonly
    out: dict[str, tuple[str, str | None]] = {}
    pre = f"{book}:"
    if log is None:
        _require_events_dir(EventLog())
    try:
        # 按**时间**后到覆盖，不按批次名：Step8 复核（`<book>-collate`）改的字要压过更早的
        # Step7 定字，而批次名排序下 `bxgb-list-…-decide` 排在 `bxgb-collate` 后面，
        # 会把复核改好的字盖回去（2026-09-24）。同一秒内再按批次/seq 定序。
        _log = log or EventLog()
        evs = sorted(iter_events_readonly(_log), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return out
    gone = sum(n for d in (getattr(_log, "dropped", None) or {}).values() for b, n in d.items() if b == book)
    if gone:                  # 换图源：旧页号的事件不采信，要看得见（GUJI-748 §六）
        _logger.warning("human_chars(%s)：%d 条事件锚里页表 rev 与册 yaml 的 source_rev 不符，不采信", book, gone)
    superseded: set[str] = set()
    no_patch: list[str] = []
    if bind:
        from .bindings import strict_enabled
        if strict_enabled():
            superseded = _superseded_events(evs, bound, pre)
    for e in evs:
        if e.id in superseded:
            continue
        if e.kind != "confirm" or e.target.unit != "cell" or not e.target.key.startswith(pre):
            continue
        # 看图结论不算人裁定字（overview#428，口径见 `events.counts_as_human`）：混进来的话
        # seed_admit 会当人裁一票定案。
        if not counts_as_human(e):
            continue
        p = e.payload or {}
        if p.get("v") == "figure":
            # 图片格（GUJI-740）：后来判成图形，先前定的字作废（图上没有这个字）
            out.pop(e.target.key, None)
            continue
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
        # 字形字段合法性校验（2026-09-27，H 道乱码普查）：老事件里可能混进乱码
        # （UTF-8 被按 cp1252 误解码再存盘，「内」存成「å†…」，P cross 1717）——
        # 不是单字、也不是合法多码位（IDS/PUA+选择符）就跳过，只记 warning，不
        # 让它原样当"人裁字形"混进文本层，冲乱下游 `report/collate.py` 的逐位
        # 对齐（那正是 vol01 7 页崩溃的根因）。跳过不等于丢数据：机械可还原的
        # 那批走的是追加更正事件（`scripts/mojibake_census.py`），这里只挡
        # 未来/未覆盖到的意外坏数据。
        if isinstance(p.get("shape"), str):      # 老事件里的兼容汉字读出时折掉
            from ..utils.cjk_compat import fold_compat
            p = {**p, "shape": fold_compat(p["shape"])}
        if not is_legal_shape(p["shape"]):
            tag = (book, e.target.key, str(p["shape"]))
            if tag not in _WARNED_BAD_SHAPE:
                _WARNED_BAD_SHAPE.add(tag)
                _logger.warning("human_chars(%s): %s 字形字段不合法，跳过：%r",
                                book, e.target.key, p["shape"])
            continue
        key = e.target.key
        ch = str(p["shape"])
        rd = p.get("reading")
        if ch in _JYS and rd in _JYS:
            ch = rd
        if bind:
            from .bindings import usable
            key = usable(bound.get(e.id)) if e.id in bound else key
            if key is None and (bound.get(e.id) or {}).get("why") == "no_patch":
                no_patch.append(e.target.key)
            if key is None:
                # 挂错格 / 切开合并 / 格没了：不采信，回待审（`lost` 记下，见 docstring）
                if lost is not None:
                    row = bound.get(e.id) or {}
                    lost[e.target.key] = {"char": ch, "status": row.get("status"),
                                          "event": e.id, "ts": e.ts}
                continue
        out[key] = ch
    if lost is not None:
        for k in [k for k in lost if k in out]:
            del lost[k]
    miss = sorted({k for k in no_patch if k not in out})
    if miss and not _env_on("GUJI_ALLOW_LOST_HUMAN"):
        raise RuntimeError(
            f"human_chars({book})：{len(miss)} 条人裁因为现格字块图拿不到（cache/ 里没有、原图也切不出）"
            f"没法认格，会被当成绑丢，例：{', '.join(miss[:5])}。先 `guji source pull {book}`"
            f"（或 `guji cache warm --book {book}`）再跑；确认要丢再设 GUJI_ALLOW_LOST_HUMAN=1。")
    return out


def _env_on(name: str) -> bool:
    import os
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _require_events_dir(log) -> None:
    """工作区事件日志目录不存在 → 报错，不静默当「没人裁过」（2026-10-25，殿本 vol06/10）。

    没设 `GUJI_WORKSPACE`（或 `GUJI_FEEDBACK_DIR`）时 `feedback_root()` 退回仓内 `feedback/`，
    那里没有 `events/`，`iter_all()` 照样返回空——seed_admit 于是把全部人裁当没有，整册结果作废。
    真的是一本没人裁过的新书，设 `GUJI_ALLOW_NO_EVENTS=1`。"""
    if log.events_dir.is_dir() or _env_on("GUJI_ALLOW_NO_EVENTS"):
        return
    raise FileNotFoundError(
        f"人裁事件目录不存在：{log.events_dir}。多半是没设 GUJI_WORKSPACE（读事件看它，不看 GUJI_DATA_HOME），"
        f"或没 `guji db pull`；新书确实没有人裁就设 GUJI_ALLOW_NO_EVENTS=1。")
