"""四把尺子：Step 1-4 「离 100% 还差什么」的常驻度量。

以前这四个数是临时脚本算完、抄进 `.claude/doc/*.md` 的快照。文档会滞后，
而「改了一刀有没有变好」恰恰要看这四个数的**变化**，所以固化成模块，
由控制台 `/api/rulers` 调用。口径照抄 `pipeline_review_2026-09-03.md`
的定义表，不另立标准——换了口径就没法跟历史数比。

| # | 量什么 | 目标 |
|---|---|---|
| R1 | 过闸且 DP 有解的列占比 | 正文页 100% |
| R2 | 格线所在行墨占比 > 0.02 的格线比例 | 能分开的 → 0；真粘连标 flag |
| R3 | 首格之上仍有成段字墨的列数 | 0 |
| R4 | 本字墨落在紧框外 ≥20px 的字位比例 | 0 |

## ⚠️ R2 要把「可改善」和「真粘连」分开报

剩下的穿字里有一批是字与字的笔画在扫描上**物理相连**（vol02/181 c1
「授經圖皆」挤成一团），任何墨谷判据都找不到零墨行。把这类算进错误，
分子永远清不了零，看数的人会以为算法还有救。所以 R2 报两个数：
**可改善**（存在更优切点却没切中）才是要修的，**真粘连**标 flag 交人审。

## ⚠️ R4 不能用连通体量，会低估 10 倍

字被切掉的那部分，按定义就**不再和主体连通**了——拿「本字连通体落在框外」
去量，切得越狠越量不到。实测同一批数据：连通体法报 2px，真值 21px。
正确做法是量**紧框边界与版框线内沿之间的墨**（`_clipped_ink`），并且
把版框线自身的墨排除掉，否则每一列都会被那条线判成「被切」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# R2：格线处墨占比超过这个值就算「穿字」（口径同 step3_error_survey）
INK_ON_LINE = 0.02
# R2：真粘连判据——格线两侧都找不到墨谷，最优切点的墨占比仍高于此
STUCK_FLOOR = 0.02
# R4：框外墨连续这么多像素才算「被切」，低于此是噪点/框线残渣
CLIP_MIN_PX = 20
# R4：判定墨的二值阈（0~1，列图已归一化）
INK_TH = 0.35


@dataclass
class Ruler:
    key: str
    title: str
    num: int = 0
    den: int = 0
    unit: str = "%"
    goal: str = "0"
    note: str = ""
    detail: list[dict] = field(default_factory=list)

    @property
    def value(self) -> float | None:
        return None if not self.den else round(100.0 * self.num / self.den, 2)

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "num": self.num,
                "den": self.den, "value": self.value, "unit": self.unit,
                "goal": self.goal, "note": self.note,
                "detail": self.detail[:20]}


def _col_profile(store, book: str, pg: int, col: int) -> np.ndarray | None:
    """列图的行墨占比曲线。取不到就返回 None（该列不参与 R2/R3/R4）。"""
    import cv2
    from ..products.cache import ImageCache
    path = ImageCache().get(book, "column_image", f"p{pg:04d}c{col:02d}")
    if path is None:
        return None
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return (img < int(INK_TH * 255)).mean(axis=1).astype(np.float64)


def _runs_over(mask: np.ndarray) -> list[tuple[int, int]]:
    """连续 True 段 → [(起, 止))。"""
    if not mask.any():
        return []
    d = np.diff(mask.astype(np.int8))
    s = list(np.flatnonzero(d == 1) + 1)
    e = list(np.flatnonzero(d == -1) + 1)
    if mask[0]:
        s = [0] + s
    if mask[-1]:
        e = e + [len(mask)]
    return list(zip(s, e))


def measure(book: str, pages: list[int], store=None) -> dict:
    """跑四把尺子。只读产物，不改任何东西。"""
    from ..products import kinds as _kinds   # noqa: F401  先注册产物种类
    from ..core.step import page_key
    from ..products.store import ProductStore
    store = store or ProductStore()

    r1 = Ruler("R1", "列产出率（过闸且 DP 有解）", unit="%", goal="100%",
               note="分母是过了 Step2 交接闸的列")
    r2 = Ruler("R2", "格线穿字（可改善）", goal="0",
               note="存在更优切点却没切中的格线；真粘连另计")
    # 2026-09-05 用户：「R2s 从现在起不该被忽略，可以单独存在——但是也要优化」。
    # 它不再是"不算错"的备注项：单独报、带明细、有目标线（dev_set 2.63% 起步，
    # 黄 3% / 红 5%，见 round_check 的 limits）。真粘连的切法要靠识别引导，
    # 不靠墨谷，实验与路线见 .claude/doc/step3_touching_and_jiazhu.md。
    r2s = Ruler("R2s", "格线穿字（真粘连）", goal="<2%",
                note="两侧都无墨谷；投影法到此为止，要靠识别引导切分")
    r3 = Ruler("R3", "首格之上仍有成段字墨的列", goal="0",
               note="抬头列少算一格的信号")
    r4 = Ruler("R4", "紧框被切的字位", goal="0",
               note="框外连续墨 ≥%dpx；已排除版框线自身" % CLIP_MIN_PX)

    for pg in pages:
        gate = store.read(book, "column_gate", page_key(pg), "gate_manifest")
        cells = store.read(book, "cell_shrink", page_key(pg), "cells")
        if cells is None:
            cells = store.read(book, "row_segment", page_key(pg), "cells")
        if gate is None:
            continue
        ci = store.read(book, "cell_shrink", page_key(pg), "char_index")
        ci_cols = {c.col: c for c in ci.columns} if ci else {}
        admitted = gate.admitted_columns()
        r1.den += len(admitted)
        solved = {c.col for c in (cells.columns if cells else []) if c.ok}
        r1.num += sum(1 for c in admitted if c.col in solved)
        for c in admitted:
            if c.col not in solved:
                r1.detail.append({"page": pg, "col": c.col, "why": "无解"})

        for cc in (cells.columns if cells else []):
            if not cc.ok:
                continue
            prof = _col_profile(store, book, pg, cc.col)
            if prof is None:
                continue
            h = len(prof)

            # ── R2：每条内部格线看是否穿字 ─────────────────
            for b in cc.boundaries[1:-1]:
                y = int(round(b))
                if not (0 <= y < h):
                    continue
                r2.den += 1
                r2s.den += 1
                if prof[y] <= INK_ON_LINE:
                    continue
                # 附近有没有更好的切点？有 → 可改善；没有 → 真粘连
                lo, hi = max(0, y - 12), min(h, y + 13)
                best = float(prof[lo:hi].min()) if hi > lo else float(prof[y])
                if best <= STUCK_FLOOR:
                    r2.num += 1
                    r2.detail.append({"page": pg, "col": cc.col,
                                      "y": y, "ink": round(float(prof[y]), 3),
                                      "best": round(best, 3)})
                else:
                    r2s.num += 1
                    r2s.detail.append({"page": pg, "col": cc.col,
                                       "y": y, "ink": round(float(prof[y]), 3),
                                       "best": round(best, 3)})

            # ── R3：首格之上还有没有成段字墨 ────────────────
            r3.den += 1
            top = int(round(cc.boundaries[0])) if cc.boundaries else 0
            head = prof[:top]
            if len(head):
                # 版框线是细横线，字墨是成段的：只认厚度 > period/4 的墨段
                thick = max(6, int((cc.period or 40) / 4))
                runs = [(s, e) for s, e in _runs_over(head > INK_ON_LINE)
                        if e - s >= thick]
                if runs:
                    r3.num += 1
                    r3.detail.append({"page": pg, "col": cc.col,
                                      "runs": [[int(s), int(e)] for s, e in runs[:3]]})

            # ── R4：紧框外还剩多少墨 ───────────────────────
            # ⚠️ 紧框在 char_index.bbox_col，**不在 cells**。cells 里的
            # y0/y1 就是格线本身，拿它当紧框窗口恒为 0，R4 永远报 0。
            cic = ci_cols.get(cc.col) if ci_cols else None
            # 紧框 ←→ 格：按 slot 对应，别按几何找最近格线。
            # 「找最近边界」在空格位/夹注处会抓到隔壁的线，窗口一下子跨过
            # 整个邻字，报出一堆 ~110px 的假被切（110px 正好一个字高）。
            slot_cell = {c.slot: c for c in cc.cells}
            for ch in (cic.chars if cic else []):
                cell = slot_cell.get(getattr(ch, "slot", None))
                if cell is None:
                    continue
                r4.den += 1
                n = _clipped_ink(prof, ch.bbox_col, cell, h)
                if n >= CLIP_MIN_PX:
                    r4.num += 1
                    r4.detail.append({"page": pg, "col": cc.col,
                                      "slot": getattr(ch, "slot", None),
                                      "px": int(n)})

    return {"book": book, "n_pages": len(pages),
            "rulers": [x.to_dict() for x in (r1, r2, r2s, r3, r4)]}


def _clipped_ink(prof: np.ndarray, bbox, cell, h: int) -> int:
    """紧框上下缘之外、仍属于**本字**的最长连续墨（像素）。

    `bbox` 是 `char_index.bbox_col`（列图坐标 x0,y0,x1,y1），
    `cell` 是**同一 slot** 的 `CellRec`，它的 y0/y1 就是这一格的上下格线。

    ## 窗口只能开到本格的格线

    走过两次弯路，都会把 R4 报成十几到二十几个百分点（真值 0.83%）：

    1. 窗口开到 `border_top/border_bottom`（版框）→ 扫过整个邻字；
    2. 按几何「找最近的 boundary」→ 空格位/夹注处会抓到隔壁的线。

    两次的症状一模一样：一堆 ~110px 的「被切」，而 110px 正是一个整字的
    高度。被切的笔画一定紧挨紧框，厚度是笔画级，不会有整字那么厚。
    所以窗口严格取「本格格线 → 紧框边缘」。

    ## 还要掐掉版框线自身

    首/末格的格线就是版框线，那条线本身有墨。只有墨段**紧贴紧框**
    （离紧框 ≤2px）才算被切掉的笔画；贴着格线那头的是框线残渣。
    """
    _x0, y0f, _x1, y1f = bbox
    y0, y1 = int(round(y0f)), int(round(y1f))
    g0, g1 = int(round(cell.y0)), int(round(cell.y1))
    out = 0
    a, b = max(0, g0), max(0, min(h, y0))          # 上缘窗口
    if b - a > 0:
        for s0, e0 in _runs_over(prof[a:b] > INK_ON_LINE):
            if e0 >= (b - a) - 2:
                out = max(out, e0 - s0)
    a, b = max(0, min(h, y1)), min(h, g1)          # 下缘窗口
    if b - a > 0:
        for s0, e0 in _runs_over(prof[a:b] > INK_ON_LINE):
            if s0 <= 2:
                out = max(out, e0 - s0)
    return out
