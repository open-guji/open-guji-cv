# -*- coding: utf-8 -*-
"""Step0 分页：一张扫描页装着多页原书 → 裁成逻辑页，逻辑页才是管线的「原图」。

为什么先裁、不在 Step1 里认「上下两块」
--------------------------------------
九步管线与八道闸全部建立在「一页一块」的不变量上：`borders` 只有一条上框一条
下框、列号在页内从右数、金标锚点是页内 bbox。一张影印页拼两页原书（北行日錄
那本：上栏一页、下栏一页，各带自己的书口栏线与页码，栏间一条横线）时，
硬让 Step1 表达两个块要改产物模型、改闸、改单位键；而裁开之后什么都不用改，
原书的页码结构（一八三四 / 一八三五）也正好回来了。

做法与 Step0 预清理同一套路（`utils/preclean.py`）：**扫描页永不改写**，逻辑页
落成显式产物（`raw_dir/<logical>.png`，不是缓存、不被 LRU 清），旁边一份
`_split_manifest.json` 记每个逻辑页来自哪张扫描页、裁的是哪个矩形——要回到
扫描页坐标只需加这个偏移。

目前只实现 `two_rows_hline`（上下两栏、栏间一条横线）：

- 分界线：页高 30%～70% 带内、整行墨占比 ≥ `sep_min_frac` 的行段，取墨最多的一段
  （北行日錄 40 页实测 0.74～0.83、厚 6px、y 在 2925～3036 之间漂）；
- 上栏 = [第一段「宽墨行段」上沿 − pad, 分界线上沿 − pad]；
  下栏 = [分界线下沿 + pad, 最后一段宽墨行段下沿 + pad]。「宽」= 该行段的 x 跨度
  ≥ `wide_frac` × 页宽——影印本自己印的阿拉伯页码（3888 宽的页上只占 4%）和
  书口的小字都不算宽，自然被排除在块外；但它们若落在裁剪矩形**里**（书口小字
  与正文同高）就一起进逻辑页，交给 `line_detect` 按列分类；
- 没有分界线的页：整页当上栏，下栏为空；下栏没有宽墨行段（末页只有上栏）：
  下栏写一张与上栏同宽、同高的白图，编号照占（扫描页 k → 逻辑页 2k−1 / 2k，
  编号可预测比省一张白图重要），manifest 标 `empty`。

逻辑页编号：扫描页 k → 上栏 2k−1、下栏 2k。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

MANIFEST_NAME = "_split_manifest.json"


@dataclass
class SplitRec:
    logical: int
    scan: int
    slot: str            # "upper" | "lower"
    x0: int
    y0: int
    x1: int
    y1: int              # 半开区间 [y0, y1)，扫描页像素坐标（左上原点）
    sep_y: float | None  # 分界线中心 y（扫描页坐标），没有为 None
    empty: bool = False  # 这一栏没有正文（白图占位）
    ink: float = 0.0     # 裁出图的墨占比，便于事后核对


def _runs(mask: np.ndarray, minlen: int = 1) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    s: int | None = None
    for i, v in enumerate(mask):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s >= minlen:
                out.append((s, i))
            s = None
    if s is not None and len(mask) - s >= minlen:
        out.append((s, len(mask)))
    return out


def mask_long_vrules(ink: np.ndarray, min_frac: float = 0.5, pad: int = 4) -> np.ndarray:
    """抹掉贯穿 ≥ 一半页高的竖线（书口栏线）。它让每一行都「有墨」，行段分析前必须先抹。"""
    W = ink.shape[1]
    colfrac = ink.mean(axis=0)
    work = ink.copy()
    for a, b in _runs(colfrac >= min_frac, 1):
        work[:, max(0, a - pad):min(W, b + pad)] = False
    return work


def _longest_run(row: np.ndarray) -> int:
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    s = np.flatnonzero(d == 1)
    e = np.flatnonzero(d == -1)
    return int((e - s).max()) if s.size else 0


def find_separator(ink: np.ndarray, band: tuple[float, float] = (0.3, 0.7),
                   sep_min_frac: float = 0.3, gap_min_h: int = 60,
                   line_min_run_frac: float = 0.1) -> tuple[int, int] | None:
    """栏间分界的行区间 [y0, y1)（扫描页坐标）；找不到返回 None。

    三级：① **实线**（整行墨占比 ≥ sep_min_frac 的行段，取墨最多的一段）；② **淡线/断线**
    （扫描页 4 那条：整行墨占比只有 0.02～0.18，但最长连续墨段 ≥ line_min_run_frac 页宽）；
    ③ **白带**：带内最长的一段零墨行（≥ gap_min_h 行），整段当分界区间。②必须在③前面
    ——扫描页 4 的白带在淡线**下方**，先找白带会把淡线裹进上栏，每一列底端多出一条细横条，
    Step3 整页每列多一项（2026-09-14 踩过）。
    """
    H, W = ink.shape[:2]
    rowfrac = ink.mean(axis=1)
    lo, hi = int(H * band[0]), int(H * band[1])
    cands = _runs(rowfrac[lo:hi] >= sep_min_frac, 1)
    if cands:
        a, b = max(cands, key=lambda r: float(rowfrac[lo + r[0]:lo + r[1]].sum()))
        return lo + a, lo + b
    # 印得淡/断的线：整行墨占比只有 0.02～0.18（扫描页 4），但**最长连续墨段**仍有
    # 0.1～0.18 页宽——文字行再密，连续段也不会超过一个字身（≤ 0.03 页宽）。
    is_line = np.zeros(hi - lo, dtype=bool)
    for y in np.flatnonzero(rowfrac[lo:hi] >= 0.01):
        if _longest_run(ink[lo + y]) >= line_min_run_frac * W:
            is_line[y] = True
    lines = _runs(is_line, 1)
    if lines:
        a, b = max(lines, key=lambda r: r[1] - r[0])
        return lo + a, lo + b
    # 「零墨行」的门槛按像素说：0.003 × 3888 ≈ 12px，几粒扫描噪点不至于把白带截断，
    # 而正文行（17 列同时有墨）的行墨占比 ≥ 0.02，隔着一个数量级
    white = _runs(rowfrac[lo:hi] <= 0.003, gap_min_h)
    if not white:
        return None
    a, b = max(white, key=lambda r: r[1] - r[0])
    return lo + a, lo + b


def wide_row_runs(ink: np.ndarray, y0: int, y1: int, wide_frac: float = 0.1,
                  weak_frac: float = 0.02, attach_gap: int = 150,
                  row_min_frac: float = 0.0005, min_h: int = 8,
                  min_density: float = 0.003) -> list[tuple[int, int]]:
    """[y0, y1) 内「正文」的墨行段。

    分两级：**强段** = x 跨度 ≥ wide_frac × 页宽且墨密度 ≥ min_density（一整行字，不会认错）；
    **弱段** = 跨度 ≥ weak_frac × 页宽、密度也够，但只有紧挨着强段块（间隔 ≤ attach_gap）
    才收进来。三种假段各有一道门挡：书口小字/页码（跨度 44～73px < 0.02 × 3888）靠跨度；
    扫描噪点连成的假段（密度 1e-5 量级，正文 0.03～0.08）靠密度；影印本自己印的阿拉伯
    页码（跨度 162px = 0.042 页宽、密度 0.012，都过得了门槛）靠**它离正文块 240px 以上**
    ——而真该收的弱段（末页「獨見李同年」首列比别的列高出一个字，首字单独成段、
    跨度只有一列宽 0.026）离强段只有 22px。跨度门槛的教训：0.4 那版把末页（只剩 7 列，
    跨度 0.33）的首行整个切掉了，0.1 那版切了那个单独的首字，0.02 那版把页码裹了进来。"""
    W = ink.shape[1]
    sub = ink[y0:y1]
    rowfrac = sub.mean(axis=1)
    strong, weak = [], []
    for a, b in _runs(rowfrac > row_min_frac, min_h):
        seg = sub[a:b]
        cols = np.flatnonzero(seg.any(axis=0))
        if not cols.size or float(seg.mean()) < min_density:
            continue
        span = cols[-1] - cols[0] + 1
        if span >= wide_frac * W:
            strong.append((y0 + a, y0 + b))
        elif span >= weak_frac * W:
            weak.append((y0 + a, y0 + b))
    if not strong:
        return []
    lo, hi = strong[0][0], strong[-1][1]
    changed = True
    while changed:                      # 弱段可以接力：一段接上，它外面那段又够近了
        changed = False
        for a, b in weak:
            if (a < lo and lo - b <= attach_gap) or (b > hi and a - hi <= attach_gap):
                lo, hi = min(lo, a), max(hi, b)
                changed = True
    return [(lo, hi)]


def split_two_rows(gray: np.ndarray, *, scan: int, pad: int = 30, sep_pad: int = 20,
                   ink_threshold: int = 128, sep_min_frac: float = 0.3,
                   wide_frac: float = 0.1) -> tuple[list[SplitRec], list[np.ndarray]]:
    """一张扫描页 → [(上栏记录, 下栏记录)], [上栏图, 下栏图]。"""
    H, W = gray.shape[:2]
    ink = mask_long_vrules(gray < ink_threshold)
    sep = find_separator(ink, sep_min_frac=sep_min_frac)
    if sep is None:
        up_lo, up_hi, dn_lo, dn_hi, sep_y = 0, H, H, H, None
    else:
        up_lo, up_hi = 0, sep[0]
        dn_lo, dn_hi = sep[1], H
        sep_y = (sep[0] + sep[1] - 1) / 2.0

    def crop(lo: int, hi: int, slot: str, logical: int) -> tuple[SplitRec, np.ndarray]:
        wide = wide_row_runs(ink, lo, hi, wide_frac=wide_frac)
        if not wide:
            return SplitRec(logical=logical, scan=scan, slot=slot, x0=0, y0=lo, x1=W, y1=lo,
                            sep_y=sep_y, empty=True, ink=0.0), None  # type: ignore[return-value]
        y0 = max(lo, wide[0][0] - pad)
        y1 = min(hi, wide[-1][1] + pad)
        if slot == "upper" and sep is not None:
            y1 = min(y1, sep[0] - sep_pad)
        if slot == "lower" and sep is not None:
            y0 = max(y0, sep[1] + sep_pad)
        img = gray[y0:y1, 0:W]
        rec = SplitRec(logical=logical, scan=scan, slot=slot, x0=0, y0=int(y0), x1=W, y1=int(y1),
                       sep_y=sep_y, empty=False, ink=round(float((img < ink_threshold).mean()), 4))
        return rec, img

    # 分界线是「白带」时（没印横线的页），sep_pad 不必再让：白带本身就是余量
    if sep is not None and float(ink[sep[0]:sep[1]].mean()) < 0.01:
        sep_pad = 0

    up_rec, up_img = crop(up_lo, up_hi, "upper", 2 * scan - 1)
    dn_rec, dn_img = crop(dn_lo, dn_hi, "lower", 2 * scan)
    # 空栏写白图占位：同宽；高取另一栏的高（都空就取半页）
    ref_h = (up_img.shape[0] if up_img is not None else
             dn_img.shape[0] if dn_img is not None else H // 2)
    if up_img is None:
        up_img = np.full((ref_h, W), 255, dtype=np.uint8)
        up_rec.y1 = up_rec.y0 + ref_h
    if dn_img is None:
        dn_img = np.full((ref_h, W), 255, dtype=np.uint8)
        dn_rec.y1 = dn_rec.y0 + ref_h
    return [up_rec, dn_rec], [up_img, dn_img]


def split_book(book, *, pages: list[int] | None = None, force: bool = False,
               log: Callable[[str], None] | None = None) -> list[SplitRec]:
    """按 `book.page_split` 把扫描页裁成逻辑页，写进 `book.raw_dir`，并维护 manifest。

    yaml 写法：

        page_split:
          mode: two_rows_hline
          source_dir: data_full/bxrl/scan     # 扫描页目录，相对 raw_root（同 raw_dir 的解释）
          source_pattern: "{page}.png"
          pad: 30                              # 块外留白
          sep_pad: 20                          # 分界线两侧各让开多少
          sep_min_frac: 0.3                    # 分界线整行墨占比下限
          wide_frac: 0.1                       # 「强正文行段」x 跨度 / 页宽（另有密度门槛与弱段接力，见 wide_row_runs）

    `pages` 是**扫描页**号；None = source_dir 里全部。已有产物且不 `force` 就跳过。
    """
    import cv2
    from ..core.workspace import raw_root

    cfg = dict(book.page_split or {})
    mode = cfg.get("mode", "two_rows_hline")
    if mode != "two_rows_hline":
        raise ValueError(f"page_split.mode 未实现: {mode!r}（目前只有 two_rows_hline）")
    if not cfg.get("source_dir"):
        raise ValueError("page_split 缺 source_dir")
    src_dir = Path(cfg["source_dir"])
    if not src_dir.is_absolute():
        src_dir = raw_root() / src_dir
    pattern = cfg.get("source_pattern", "{page}.png")
    out_dir = Path(book.raw_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = log or (lambda s: print(s, flush=True))

    if pages is None:
        suffix = Path(pattern).suffix
        import re
        num = re.compile(r"(\d+)")
        pages = sorted(int(m.group(1)) for p in src_dir.iterdir()
                       if p.suffix.lower() == suffix.lower() and (m := num.search(p.stem))
                       and pattern.format(page=int(m.group(1))) == p.name)
    mpath = out_dir / MANIFEST_NAME
    manifest: dict = {"mode": mode, "source_dir": str(src_dir), "pages": {}}
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    manifest.setdefault("pages", {})
    done: list[SplitRec] = []
    for scan in pages:
        outs = [out_dir / f"{2 * scan - 1}.png", out_dir / f"{2 * scan}.png"]
        if not force and all(o.exists() for o in outs) and \
                all(str(2 * scan - 1 + i) in manifest["pages"] for i in range(2)):
            log(f"[split] 扫描页 {scan}: 已有逻辑页 {2 * scan - 1}/{2 * scan}，跳过")
            continue
        src = src_dir / pattern.format(page=scan)
        gray = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            log(f"[split] 扫描页 {scan}: 读不到 {src}，跳过")
            continue
        recs, imgs = split_two_rows(gray, scan=scan, pad=int(cfg.get("pad", 30)),
                                    sep_pad=int(cfg.get("sep_pad", 20)),
                                    sep_min_frac=float(cfg.get("sep_min_frac", 0.3)),
                                    wide_frac=float(cfg.get("wide_frac", 0.1)))
        for rec, img, o in zip(recs, imgs, outs):
            cv2.imwrite(str(o), img)
            manifest["pages"][str(rec.logical)] = asdict(rec)
            done.append(rec)
        sep_txt = "无分界线" if recs[0].sep_y is None else f"分界线 y={recs[0].sep_y:.0f}"
        log(f"[split] 扫描页 {scan}: {sep_txt}；上栏 {recs[0].y0}-{recs[0].y1}"
            f"{'（空）' if recs[0].empty else ''}，下栏 {recs[1].y0}-{recs[1].y1}"
            f"{'（空）' if recs[1].empty else ''}")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return done


def load_manifest(raw_dir: str | Path) -> dict[int, SplitRec]:
    """逻辑页 → 来源记录；没有 manifest 返回空字典。"""
    p = Path(raw_dir) / MANIFEST_NAME
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {int(k): SplitRec(**v) for k, v in (d.get("pages") or {}).items()}
