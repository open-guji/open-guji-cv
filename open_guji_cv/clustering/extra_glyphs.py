# -*- coding: utf-8 -*-
"""外部真刻本字形源（康熙字典字头切图 / 字统网字形图）→ 64² 归一二值图。

实验用（`.claude/doc/external_glyph_sources_experiment.md`）。两种目录布局：

- ``kangxi:<dir>``            `<dir>/KX1078.020_蚤.png`（`scripts/kangxi_headwords.py run` 的产物，
                              文件名末段 `_<字>.png` 是标签；`_unk.png` 跳过）
- ``zitools:<dir>[:印,楷]``   `<dir>/manifest.tsv`（`overview/scripts/fetch_zitools_glyphs.py`），
                              标签取 `glyph_char` 列（图上真正的字，异体时 ≠ 查询字），
                              可按「書體」列过滤；「當代」标准字形（就是字体）默认排除

全部走 `normalize_patch`——与真刻例同一条归一化路径，不走 `render_char`。
结果按 spec 落盘缓存到 `cache/extra_glyphs/<sha>.npz`。
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from .normalize import normalize_patch

CACHE = Path("cache/extra_glyphs")


def _iter_kangxi(d: Path, only: set[str] | None = None):
    """only 给了就只收这些文件名（交叉验证通过的白名单，见 scripts/kangxi_crossval.py）。"""
    for p in d.glob("KX*.png"):
        stem = p.stem
        ch = stem.rsplit("_", 1)[-1]
        if ch == "unk" or len(ch) != 1:
            continue
        if only is not None and p.name not in only:
            continue
        yield ch, p


def _iter_zitools(d: Path, styles: set[str] | None):
    man = d / "manifest.tsv"
    with open(man, encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 8 or parts[7].startswith("rows="):
                continue
            _q, gch, dyn, style, _src, _k, _id, rel = parts[:8]
            if dyn == "當代":
                continue
            if styles and style not in styles:
                continue
            if len(gch) != 1:
                continue
            yield gch, d / rel


def parse_spec(spec: str):
    """kangxi:<dir>[@<白名单文件>] | zitools:<dir>[:書體,...]"""
    kind, rest = spec.split(":", 1)
    styles = None
    only_file = None
    if kind == "kangxi" and "@" in rest:
        rest, only_file = rest.rsplit("@", 1)
        return kind, Path(rest), only_file
    # 路径里含 `D:/`，所以从右边找过滤段：最后一段全是中文/逗号才是 styles
    parts = rest.split(":")
    if len(parts) > 1 and all(ord(c) > 0x2E80 or c == "," for c in parts[-1]):
        styles = set(parts[-1].split(","))
        rest = ":".join(parts[:-1])
    return kind, Path(rest), styles


def load_extra_glyphs(spec: str, charset=None, size: int = 64,
                      max_per_char: int = 0) -> dict[str, list[np.ndarray]]:
    """spec → {字: [64² uint8 {0,1}, ...]}。charset 给了就只留字表内的字。"""
    kind, d, styles = parse_spec(spec)
    only = None
    if kind == "kangxi" and isinstance(styles, str):     # 白名单文件路径
        only = set(Path(styles).read_text(encoding="utf-8").split())
        styles = f"only{len(only)}"
    # 目录还在增长（抓取/切图进行中）时缓存要跟着失效：key 里带 manifest 大小 / 文件数
    stamp = (d / "manifest.tsv").stat().st_size if kind == "zitools" else len(list(d.glob("KX*.png")))
    key = hashlib.sha1(f"{kind}|{d}|{sorted(styles) if isinstance(styles, set) else styles}|{size}|{stamp}".encode("utf-8")).hexdigest()[:16]
    cache = CACHE / f"{key}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        out: dict[str, list[np.ndarray]] = defaultdict(list)
        for ch, img in zip(z["chars"].tolist(), z["imgs"]):
            out[ch].append(img)
    else:
        it = _iter_kangxi(d, only) if kind == "kangxi" else _iter_zitools(d, styles)
        out = defaultdict(list)
        for ch, p in it:
            # Windows 下 cv2.imread 吃不了非 ASCII 路径（字统网目录名是汉字），走 imdecode
            try:
                buf = np.fromfile(str(p), dtype=np.uint8)
            except OSError:
                continue
            img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE) if buf.size else None
            if img is None or img.size == 0:
                continue
            try:
                n = normalize_patch(img, size=size)
            except Exception:  # noqa: BLE001
                continue
            if not n.any():
                continue
            out[ch].append(n.astype(np.uint8))
        CACHE.mkdir(parents=True, exist_ok=True)
        chars = [c for c, lst in out.items() for _ in lst]
        imgs = np.stack([im for lst in out.values() for im in lst]) if chars else np.zeros((0, size, size), np.uint8)
        np.savez_compressed(cache, chars=np.array(chars), imgs=imgs)
    if charset is not None:
        cs = set(charset)
        out = {c: v for c, v in out.items() if c in cs}
    if max_per_char:
        out = {c: v[:max_per_char] for c, v in out.items()}
    return dict(out)


def load_many(specs, charset=None, size: int = 64) -> dict[str, list[np.ndarray]]:
    merged: dict[str, list[np.ndarray]] = defaultdict(list)
    for s in specs or []:
        for c, v in load_extra_glyphs(s, charset, size).items():
            merged[c].extend(v)
    return dict(merged)
