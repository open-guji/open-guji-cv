"""图片格与插图块的人裁读出（GUJI-740，2026-10-24）：Step9 导出写 char `fig`、cord `marks.figure`、fig.json 用。

设计见 book-text `docs/design/2026-10-图片格与插图设计.md` §五，格式见 guji-format spec 09（guji-fig v0.1）。

两种图，两条来路：

| | 人怎么定 | 事件 | 落到哪 | 本模块 |
|---|---|---|---|---|
| **图片格**（一格是图形，不是字） | 定字台／网站精校票 `choice=figure` | `confirm`，`payload.v="figure"`、`alt` | `crop_exclude` 进排除名单，理由 `figure`；Step7 照排除格处理（不进库、不出卡），`report/slots` 占位出 □ | `figure_cells` |
| **插图块**（占几列、半页、整页） | 控制台在页上画框 | `figure_region`（页级，一页一条，后到覆盖） | 不配消费者，不让产物过期 | `resolved_figure_regions` |

`figure_region` 的单位键 `figure:<册>:<页>`，payload：

    {"regions": [{"box": [x, y, w, h], "col": 3, "span": 4, "alt": "河圖", "fig": "p52-fig1"}, …]}

- `box`：canvas 像素（与 book-text cord 同一坐标），左上原点；
- `col`：图块右边第一列的列号（cv 物理列号，同格位 key 的「列」）；`span`：占几列（缺省 1）；
- `alt`：说明，可空（导出写「图形符号」）；`fig`：图 id，可空（导出按 `p<页>-fig<n>` 起）；
- 同一页再画一次就整页覆盖；`regions: []` 撤掉本页全部插图块。
"""
from __future__ import annotations

from pathlib import Path

#: 人定是图时没写说明的，导出写这个（spec 09 §3.2）
DEFAULT_ALT = "图形符号"


def _alt_of(rec: dict) -> str:
    for tag in rec.get("evidence") or []:
        if isinstance(tag, str) and tag.startswith("alt="):
            return tag[4:]
    return ""


def figure_cells(book: str, exclusions_path: str | Path | None = None, log=None) -> dict[str, str]:
    """本册判成图片格的格 → 说明：`{裸 id（vol05:148:2:14）: alt}`（没写说明的是空串）。

    「是不是图」以排除名单为准（Step7、`report/slots` 读的就是它，三处同口径）；说明取这一格最新一条
    `v=figure` 事件的 `alt`（后来改过说明的以事件为准），没有事件可读时取名单 evidence 里的 `alt=`。"""
    from ..clustering.exclusions import default_path, load_exclusions
    pre = f"{book}:"
    ex = load_exclusions(str(exclusions_path) if exclusions_path else default_path())
    out = {k: _alt_of(r) for k, r in ex.items() if k.startswith(pre) and r.get("reason") == "figure"}
    if not out:
        return out
    from .events import EventLog, counts_as_human, iter_events_readonly, replay_key
    try:
        evs = sorted(iter_events_readonly(log or EventLog()), key=replay_key)
    except FileNotFoundError:
        return out
    for e in evs:
        if e.kind != "confirm" or e.target.key not in out or not counts_as_human(e):
            continue
        p = e.payload or {}
        if p.get("v") == "figure" and p.get("alt"):
            out[e.target.key] = str(p["alt"])
    return out


def region_key(book: str, page: int) -> str:
    return f"figure:{book}:{page}"


def resolved_figure_regions(book: str, log=None) -> dict[int, list[dict]]:
    """本册各页的插图块：`{页: [{box, col, span, alt, fig?}, …]}`。每页取最新一条 `figure_region`。"""
    from .events import EventLog, counts_as_human, iter_events_readonly, replay_key
    try:
        evs = sorted(iter_events_readonly(log or EventLog()), key=replay_key)
    except FileNotFoundError:
        return {}
    pre = f"figure:{book}:"
    last: dict[int, list[dict]] = {}
    for e in evs:
        if e.kind != "figure_region" or not e.target.key.startswith(pre) or not counts_as_human(e):
            continue
        tail = e.target.key[len(pre):]
        if not tail.isdigit():
            continue
        regs = []
        for r in (e.payload or {}).get("regions") or []:
            box = r.get("box")
            if not (isinstance(box, list) and len(box) == 4 and isinstance(r.get("col"), int)):
                raise ValueError(f"{e.id}：插图块要有 box=[x,y,w,h] 与整数 col，收到 {r}")
            regs.append({"box": [float(v) if not float(v).is_integer() else int(v) for v in box],
                         "col": int(r["col"]), "span": int(r.get("span") or 1), "alt": str(r.get("alt") or ""),
                         **({"fig": str(r["fig"])} if r.get("fig") else {})})
        last[int(tail)] = sorted(regs, key=lambda r: r["col"])
    return {pg: regs for pg, regs in sorted(last.items()) if regs}
