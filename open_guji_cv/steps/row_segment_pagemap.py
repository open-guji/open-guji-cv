# -*- coding: utf-8 -*-
"""Step3 的自动配页（`RowSegmentParams.page_map`）：边跑边生成本册的逐列格位表，不再离线补表。

开着（`strict`／`loose`）时 Step3 开跑前（`RowSegmentStep.prepare`）读全册 Step2 的列窗口与原图，
每页量 9×23 格墨量（`utils/page_align.slot_ink`），和 daizhige 全书半叶对齐（`utils/page_align.align`），
得出本册「页 → 半叶」与格位表，叠上人核过的 `layout_overrides.jsonl`，存进 Step3 产物目录
`products/<册>/row_segment/_page_map.json` 复用；各页 `run_page` 读它当 `layout_prior` 的表。

- **复用**：缓存键 ＝ 全册列窗口产物 sha ＋ daizhige 源文件 ＋ 本册钉页 ＋ 算法版本，都没变就不重算。
- **人工兜底**：`corpus/daizhige/page_pins.jsonl` 一行一页 `{"vol", "page", "dzg": "0001-3561h0" 或 null, "why"}`，
  当硬约束；`layout_overrides.jsonl` 照旧改格。
- **配不准**：得分低（`page_align.LOW_SCORE`）或没配上的页不带先验，照无先验切。`strict` 时整册
  配不上（正文页没配准的超过 max(2, `STRICT_MAX_BAD`)，或有字页平均得分低于 `STRICT_MIN_MEAN`）直接报错拦下；`loose` 只记进报告。
  跨度里漏配的有字半叶（缺扫）只记报告、日志提醒，不拦：vol11 真缺扫 12 个半叶，配页本身是对的。
- **指纹**：Step3 参数里只记 `page_map_fingerprint`（daizhige 源文件＋本册钉页、改格＋算法版本），
  不再是整张中心库表的 sha，别的册加表、改格不牵连本册。配页结果是这些输入与列窗口的确定函数；
  列窗口一变，那页本来就过期。

设计与评审：Claude Doc「格位表自动生成方案」（2026-10-25，Sheldon 定：不加步骤、放 Step3 产物、
严格程度做书级设置）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

#: 改对齐算法或指纹口径时加一：所有开着 page_map 的册 Step3 判过期、配页重算
ALGO_VERSION = 1
CACHE_NAME = "_page_map.json"
PINS_NAME = "page_pins.jsonl"
OVERRIDES_NAME = "layout_overrides.jsonl"
#: strict：正文页（框里有墨格 ≥ TEXT_MIN_CELLS）没配上或不确定的，超过 max(2, 3%) 就拦
STRICT_MAX_BAD = 0.03
#: strict：配到有字半叶的页平均得分低于这个也拦。殿本配对的册 0.97–0.99；vol11 起点配错到
#: 卷四十五时是 0.93（各页都「配得上」，只是全是满页之间的将就）
STRICT_MIN_MEAN = 0.95
TEXT_MIN_CELLS = 10

_HALVES: dict[tuple, tuple] = {}


def _dz_dir() -> Path:
    from ..core.workspace import corpus_path
    return Path(corpus_path("daizhige"))


def _file_sig(paths) -> tuple:
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p.exists())


def has_source() -> bool:
    from ..utils.daizhige import source_files
    d = _dz_dir()
    return d.is_dir() and bool(source_files(d))


def _halves():
    """全书半叶、占格矩阵、空/牌记标记、daizhige 内容 sha。进程内按文件签名缓存。"""
    from ..utils.daizhige import NCOL, build_halves, column_layout, source_files
    from ..utils.page_align import occupancy
    files = source_files(_dz_dir())
    key = _file_sig(files)
    if key not in _HALVES:
        hs = build_halves(files)
        O = np.stack([occupancy([(c["no"] % NCOL, lay) for c in h.cols
                                 if (lay := column_layout(c))]) for h in hs])
        empty = ~O.reshape(len(hs), -1).any(axis=1)
        cover = np.array([h.cover for h in hs])
        sha = hashlib.sha256()
        for f in files:
            sha.update(f.read_bytes())
        _HALVES.clear()
        _HALVES[key] = (hs, O, empty, cover, sha.hexdigest()[:16])
    return _HALVES[key]


def _book_lines(name: str, book: str) -> list[dict]:
    p = _dz_dir() / name
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get("vol") == book:
                out.append(r)
    return out


def fingerprint(book: str) -> str:
    """Step3 参数指纹里代表「格位表」的那一项（见模块头）。"""
    if not has_source():
        return ""
    sha = hashlib.sha256()
    sha.update(f"v{ALGO_VERSION}|{_halves()[4]}|".encode())
    for name in (PINS_NAME, OVERRIDES_NAME):
        sha.update(json.dumps(_book_lines(name, book), ensure_ascii=False, sort_keys=True).encode())
    return sha.hexdigest()[:16]


def _page_columns(win, width: int) -> list[tuple[float, float, float, float]]:
    """列窗口（规范空间：右上原点，x 向左）→ 图像坐标每列 (x_left, x_right, 版框上, 版框下)，从右到左。"""
    out = []
    for c in sorted(win.columns, key=lambda c: c.col):
        ym = (c.border_top_y + c.border_bottom_y) / 2
        xl = width - c.left_line.to_vline().x_at(ym)
        xr = width - c.right_line.to_vline().x_at(ym)
        out.append((min(xl, xr), max(xl, xr), c.border_top_y, c.border_bottom_y))
    return out


def _cache_path(ctx) -> Path:
    return ctx.store.step_dir(ctx.book.id, "row_segment") / CACHE_NAME


def _inputs(ctx) -> tuple[str, list[int], str]:
    """（列窗口产物所在步，本册有列窗口的页，缓存键）。"""
    from ..core.spec import page_key
    sid = ctx.producer("column_windows").spec.id
    keys = ctx.store.keys(ctx.book.id, sid)
    pages = sorted(int(k[1:]) for k in keys)
    sha = hashlib.sha256()
    sha.update(fingerprint(ctx.book.id).encode())
    for p in pages:
        sha.update(f"{p}:{ctx.store.sha(ctx.book.id, sid, page_key(p))}|".encode())
    return sid, pages, sha.hexdigest()[:16]


def ensure(ctx, strategy: str) -> dict:
    """本册配页结果（缓存里有且输入没变就直接读）。`strict` 时整册配不上抛 ValueError。"""
    sid, pages, key = _inputs(ctx)
    path = _cache_path(ctx)
    d = None
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            d = None
    if d is not None and d.get("key") == key and "summary" in d:
        _check(d["summary"], strategy, ctx.book.id)
        return d
    d = build(ctx, sid, pages, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    s = d["summary"]
    ctx.log(f"配页 {ctx.book.id}：{s['pages']} 页配上 {s['mapped']}，平均得分 {s['mean_score']}，"
            f"不确定 {len(s['unsure_pages'])}，"
            f"卷 {s['rolls'][:1]}…{s['rolls'][-1:]}，漏配有字半叶 {len(s['missing_halves'])}，"
            f"重复扫描 {s['dup_pages']}（{path}）")
    _check(s, strategy, ctx.book.id)
    return d


def _check(summary: dict, strategy: str, book: str) -> None:
    if strategy != "strict":
        return
    bad, n_text = summary["bad_text_pages"], max(1, summary["text_pages"])
    mean = summary.get("mean_score", 1.0)
    if len(bad) > max(2, STRICT_MAX_BAD * n_text) or mean < STRICT_MIN_MEAN:
        raise ValueError(
            f"{book} 自动配页没配上（page_map: strict）：正文页没配准 {len(bad)}/{n_text}（{bad[:20]}），"
            f"有字页平均得分 {mean:.3f}（要 ≥ {STRICT_MIN_MEAN}）。"
            f"看 Step3 产物目录的 {CACHE_NAME}；配错的页在中心库 corpus/daizhige/{PINS_NAME} 钉上，"
            "或书 yaml 改 params.row_segment.page_map: loose（配不准的页不带先验照切）")


def build(ctx, sid: str, pages: list[int], key: str) -> dict:
    from ..core.spec import page_key
    from ..utils.daizhige import (
        SHORT_CHARS,
        apply_overrides,
        half_kind,
        half_layout_rows,
    )
    from ..utils.page_align import N_EXTRA, align, binarize, slot_ink
    hs, O, empty, cover, _ = _halves()
    by_key = {h.key: h.idx for h in hs}
    pins = {}
    for r in _book_lines(PINS_NAME, ctx.book.id):
        pins[int(r["page"])] = by_key.get(r["dzg"]) if r.get("dzg") else None
    raws, grids, inks = [], [], []
    for p in pages:
        win = ctx.store.read(ctx.book.id, sid, page_key(p), "column_windows")
        gray = ctx.raw_page(p)
        inks.append(float((gray < 128).mean()))
        if win is None or len(win.columns) != O.shape[1]:
            raws.append(None)
            grids.append(None)
            continue
        g = slot_ink(gray, _page_columns(win, gray.shape[1]))
        raws.append(g)
        grids.append(binarize(g))
    res = align(pages, grids, inks, O, empty, cover, pins=pins, raw=raws)
    rows, layout = [], []
    for p in pages:
        mt = res.matches[p]
        row = {"vol": ctx.book.id, "page": p, "half": mt.half, "how": mt.how,
               "score": round(mt.score, 3), "confident": mt.confident}
        if mt.half is not None:
            h = hs[mt.half]
            row.update(dzg=h.key, dzg_page=h.page, roll=h.roll, dzg_kind=half_kind(h), dzg_chars=h.nchars)
            if mt.confident and not h.cover:
                layout.extend(half_layout_rows(h, ctx.book.id, p))
        rows.append(row)
    layout = apply_overrides(layout, _dz_dir() / OVERRIDES_NAME, {ctx.book.id})
    used = sorted(mt.half for mt in res.matches.values() if mt.half is not None)
    text = [p for p, g in zip(pages, grids) if g is not None and int(g[:, N_EXTRA:].sum()) >= TEXT_MIN_CELLS]
    bad = [p for p in text if res.matches[p].half is None or not res.matches[p].confident]
    missing, rolls = [], []
    if used:
        u = set(used)
        missing = [hs[i].key for i in range(used[0], used[-1] + 1)
                   if i not in u and not hs[i].cover and hs[i].nchars > SHORT_CHARS]
        for i in range(used[0], used[-1] + 1):
            if hs[i].roll and hs[i].roll not in rolls:
                rolls.append(hs[i].roll)
    sc = [mt.score for mt in res.matches.values() if mt.half is not None and not empty[mt.half]]
    summary = {"pages": len(pages), "mapped": len(used), "text_pages": len(text),
               "mean_score": round(float(np.mean(sc)), 4) if sc else 0.0,
               "bad_text_pages": bad, "unsure_pages": [r["page"] for r in rows if r["half"] is not None
                                                       and not r["confident"]],
               "unmapped_pages": [r["page"] for r in rows if r["half"] is None],
               "missing_halves": missing, "dup_pages": res.dups, "rolls": rolls,
               "half_span": [hs[used[0]].key, hs[used[-1]].key] if used else []}
    return {"key": key, "version": ALGO_VERSION, "summary": summary, "rows": rows, "layout": layout}


_LAYOUT_MEMO: dict[tuple, dict] = {}


def layout_for(ctx, strategy: str) -> dict[tuple[int, int], dict]:
    """本册格位表 {(页, 列): 行}，同 `row_segment.load_layout`。逐页调用：缓存文件在就直接读
    （输入新不新由 `prepare` 起跑前查过一次），不在才现算。"""
    path = _cache_path(ctx)
    if not path.exists():
        ensure(ctx, strategy)
    st = path.stat()
    mk = (str(path), st.st_mtime_ns, st.st_size)
    if mk not in _LAYOUT_MEMO:
        d = json.loads(path.read_text(encoding="utf-8"))
        _LAYOUT_MEMO.clear()
        _LAYOUT_MEMO[mk] = {(int(r["page"]), int(r["col"])): r for r in d["layout"]}
    return _LAYOUT_MEMO[mk]
