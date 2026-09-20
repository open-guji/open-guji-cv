"""管线**回流**读裁决表：给 Step 用的只读查询，数据源是 workspace 的
`feedback/verdicts/`（`consumers.verdict_store()`），**不是** open-guji-dataset。

三仓边界（2026-09-13）：生产管线运行时只读写 workspace。第一版人裁回流从测试集
仓取金标（cv `78319605cf`，已撤），这里是改到裁决表之后的版本。
"""

from __future__ import annotations

from typing import NamedTuple

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
