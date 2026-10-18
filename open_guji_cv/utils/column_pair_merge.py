"""窄对合并（Step1 后处理；overview GUJI-155／208ax，设计见 overview `设计-切分-Eren.md` §七）。

**病**：书级 `expected_cols=9`，遇到只有 8 列的页，Step1 凑够 10 条竖线，会在某一列中间塞一条多余的线，
把一整列劈成两条窄列（线穿字心：vol04 p80／p217、vol07 p128；或落在雙行夹注的缝上：vol07 p130）。
窄对的两个宽度之和≈一条正常列（实测 0.99–1.03 倍页中位列宽）。

**做法**：探完后检查「相邻两条内部窄列、宽度和≈一列」；是则用 `expected_cols−1` 重探，
且只在「新线集＝旧线集去掉一条、重探结果无异常列」时接受。

**硬触发条件**（缺一不触发）：
- 两条都是**页内部**列——不是第 1 列也不是最末列。边缘单窄列（vol05 p55、p123，vol04 p63）用
  `expected_cols−1` 重探**也会「干净」**，但那是把真列丢了（p55 真有 9 列），所以边缘列绝不能触发；
- 相邻的**一对**，各 <0.7×页中位列宽，和在 0.85–1.15 倍；
- 其余正文列都在 0.8–1.2 倍；页上恰有一对（两对以上＝页面本身有毛病，不碰）。

纯函数，不读图、不依赖 `border_geometry`（这个模块只列进 `border_detect` 的 `code_deps`——
`border_geometry` 是三个步骤的 `code_deps`，逻辑放进去会让三步全册过期）。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .column_types import classify_columns


#: `line_index` 合并列、闸1 manifest 上的旗名（旗文本是「旗名：说明」）。三处（Step1 打旗、闸1 认旗、闸2 认旗）
#: 都走这里，不各自写字符串前缀。`pair_merged_inconsistent` 是闸1 发现「有旗但列数不自洽」时留的提示，
#: 它的名字以 `pair_merged` 开头但**不是**合并旗——所以认旗一律比整段旗名，不用 `startswith`。
PAIR_MERGED_FLAG = "pair_merged"
PAIR_MERGED_INCONSISTENT_FLAG = "pair_merged_inconsistent"


def flag_name(flag: str) -> str:
    return flag.split("：", 1)[0]


def has_pair_merged(flags) -> bool:
    """旗列表里有没有合并旗（整段旗名＝`pair_merged`）。"""
    return any(flag_name(f) == PAIR_MERGED_FLAG for f in flags)


@dataclass(frozen=True)
class PairMergeParams:
    narrow_ratio: float = 0.7      # 窄列：< 此比例 × 页中位列宽
    sum_lo: float = 0.85           # 窄对宽度和 / 页中位 的下限
    sum_hi: float = 1.15           # 上限
    rest_lo: float = 0.8           # 其余正文列 / 页中位 的下限
    rest_hi: float = 1.2           # 上限
    line_tol: float = 8.0          # 新线对得上旧线的容差（px）
    clean_lo: float = 0.7          # 重探结果里正文列 / 中位 的下限
    clean_hi: float = 1.3          # 上限
    min_body_cols: int = 5         # 页上正文列太少时不判


def line_xs(res) -> list[float]:
    """竖线在版框中高处的 x（右→左，与 `border_detect.run_page` 里量列宽同一口径）。"""
    top_y = float(res.top.y_at(0.0)) if res.top is not None else 0.0
    bot_y = float(res.bottom.y_at(0.0)) if res.bottom is not None else float(res.height - 1)
    y_mid = (top_y + bot_y) / 2.0
    return [float(v.x_at(y_mid)) for v in res.verticals]


def find_narrow_pair(xs: list[float], *, leaf_layout: str = "single",
                     th: PairMergeParams = PairMergeParams()) -> int | None:
    """页上的「窄对」：返回这一对**第一条**的列号（1 起）；没有或不唯一返回 None。"""
    cols = classify_columns(xs, leaf_layout=leaf_layout)
    n = len(cols)
    body = [c for c in cols if c.kind == "body"]
    if len(body) < th.min_body_cols:
        return None
    med = statistics.median(c.width for c in body)
    if med <= 0:
        return None
    hits: list[int] = []
    for a, b in zip(cols, cols[1:]):
        if a.kind != "body" or b.kind != "body":
            continue
        if a.col == 1 or b.col == n:            # 硬条件：页首／页末列不触发
            continue
        if a.width >= th.narrow_ratio * med or b.width >= th.narrow_ratio * med:
            continue
        if not th.sum_lo <= (a.width + b.width) / med <= th.sum_hi:
            continue
        rest = [c.width for c in body if c.col not in (a.col, b.col)]
        if all(th.rest_lo * med <= w <= th.rest_hi * med for w in rest):
            hits.append(a.col)
    return hits[0] if len(hits) == 1 else None


def accept_merge(old_xs: list[float], new_xs: list[float], new_cols: int, *,
                 leaf_layout: str = "single", th: PairMergeParams = PairMergeParams()) -> bool:
    """重探结果能不能收：列数＝new_cols、新线集＝旧线集去掉一条（逐条 ±line_tol）、无异常列。"""
    if len(new_xs) != new_cols + 1 or len(old_xs) - len(new_xs) != 1:
        return False
    used: set[int] = set()
    for x in new_xs:
        j = min((k for k in range(len(old_xs)) if k not in used),
                key=lambda k: abs(old_xs[k] - x), default=None)
        if j is None or abs(old_xs[j] - x) > th.line_tol:
            return False
        used.add(j)
    body = [c.width for c in classify_columns(new_xs, leaf_layout=leaf_layout) if c.kind == "body"]
    if not body:
        return False
    med = statistics.median(body)
    return all(th.clean_lo * med <= w <= th.clean_hi * med for w in body)


def merge_narrow_pair(res, cols: int, detect, *, leaf_layout: str = "single",
                      th: PairMergeParams = PairMergeParams()):
    """后处理入口。`detect(n_cols)` 是用 n_cols 重探的回调。

    返回 `(结果, 列数, 合并列号|None)`：没触发或重探不被接受就原样返回 `(res, cols, None)`，
    **此时一个字节都不改**（也不调 `detect`）。"""
    xs = line_xs(res)
    if len(xs) != cols + 1:
        return res, cols, None
    pair = find_narrow_pair(xs, leaf_layout=leaf_layout, th=th)
    if pair is None:
        return res, cols, None
    res2 = detect(cols - 1)
    if accept_merge(xs, line_xs(res2), cols - 1, leaf_layout=leaf_layout, th=th):
        return res2, cols - 1, pair
    return res, cols, None
