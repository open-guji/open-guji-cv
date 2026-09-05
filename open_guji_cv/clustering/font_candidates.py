# -*- coding: utf-8 -*-
"""L1 字体模板候选：库里没样本的字，用字体渲染图召回 top-k **候选**。

## 定位：只出候选，永不放行

`glyph_db_expansion_research.md` §6.2 实测过一条硬结论——**字体渲染字形不能
当精确字形判据**：四套字体的「对/错」f1 分布完全重叠，没有阈值能把它们分开，
`GlyphKnnSource` 因此被锁死在 `kinds=("woodblock",)`。那个结论**依然成立且
必须遵守**，本模块不去挑战它。

但那条结论量的是「能不能自动放行」，本模块要回答的是另一个问题：
**当库、OCR、上下文三路都给不出正确答案时，字体模板能不能把答案捞进 top-10，
让人在候选里点一下，而不用去字统网查？**

这两件事的门槛差着数量级：放行要 precision ≥ 0.999，召回只要人愿意扫十个。

## 为什么它对生僻字管用，而库不管用

库的覆盖是**按本书用字频次**长出来的：整理本 4593 字种里，出现 ≤3 次的
1801 字种有 1551 个库里一个例都没有。字体不一样——I.Ming + Jigmo 1/2/3
覆盖 Unihan 十万字，**生僻字和常用字一视同仁**。所以两者的强弱正好互补：
库在高频字上准（kNN top1 对金标 99.5%），字体在低频字上有。

## 用哪些字体、为什么

- **I.Ming**（IPA Font License）：传承字形/旧字形，用字习惯与刻本最吻合，
  优先级最高；
- **Jigmo 1/2/3**（CC0）：覆盖到 Ext-B/C/D，䙝 㕔 这种才有。

字表从**整理本用字 + IDS 表**取，不是拿全 Unihan 十万字硬跑——后者既慢又
会把一堆本书不可能出现的字塞进候选。

## 与 IDS 护栏的关系

这里正是 `ids_guard` 该上场的地方（见 `tests/test_ids_guard.py` 里那条负结果
记录）：字体候选是**纯形状**证据，没有文本兜底，形近对必须降档交人。
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

# 传承字形优先——刻本用的是旧字形
FONT_ORDER = ("iming", "jigmo")
NORM = 64


@dataclass
class FontHit:
    char: str
    score: float
    font: str

    def as_tuple(self) -> tuple[str, float]:
        return (self.char, self.score)


def _font_files(root: str = "fonts") -> list[str]:
    out: list[str] = []
    for name in FONT_ORDER:
        out.extend(sorted(glob.glob(str(Path(root) / name / "*.ttf"))))
    return out


INDEX_DIR = Path("cache/font_index")


def _index_key(charset: tuple[str, ...], root: str, backend: str) -> str:
    import hashlib
    h = hashlib.sha1()
    h.update(backend.encode())
    for f in _font_files(root):
        st = Path(f).stat()
        h.update(f"{Path(f).name}:{st.st_size}:{int(st.st_mtime)}".encode())
    h.update("".join(charset).encode("utf-8"))
    return h.hexdigest()[:16]


@lru_cache(maxsize=4)
def _index(charset: tuple[str, ...], root: str = "fonts",
           backend: str = "hog") -> tuple[np.ndarray, list[tuple[str, str]]]:
    """字表 × 字体 → (特征矩阵, [(字, 字体名)])。

    特征后端与 `GlyphMatcher` 用同一个（默认 hog）——两边可比才有意义。
    渲染失败（字体没这个字）的直接跳过，所以同一个字可能只有部分字体有。

    ## ⚠️ 必须落盘，不能只靠 lru_cache

    2026-09-05 用户点「查生僻字」一直显示「查询中」——实测一次请求 **483 秒**。
    两档字表里的大表 20,059 字 × 4 字体要渲染八万张图再提 HOG，而 lru_cache
    的键是 charset 元组，进程一重启（或调用方每次重新拼元组）就全部重来。
    现在按「字表 + 字体文件指纹」落到 `cache/font_index/<key>.npz`，
    第二次起毫秒级；换字体或字表自动失效。
    """
    from .features import get_feature
    from .synth import render_char

    key = _index_key(charset, root, backend)
    f = INDEX_DIR / f"{key}.npz"
    if f.exists():
        z = np.load(f, allow_pickle=False)
        keys = [(c, fn) for c, fn in zip(z["chars"].tolist(), z["fonts"].tolist())]
        return z["mat"], keys

    feat = get_feature(backend)
    mats: list[np.ndarray] = []
    keys: list[tuple[str, str]] = []
    for path in _font_files(root):
        fname = Path(path).stem
        for ch in charset:
            try:
                img = render_char(ch, path, size=NORM)
            except Exception:
                continue
            if img is None or not img.any():
                continue
            mats.append(img.astype(np.uint8))
            keys.append((ch, fname))
    if not mats:
        return np.zeros((0, 1), dtype=np.float32), []
    mat = feat.extract(np.stack(mats)).astype(np.float32)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(f, mat=mat,
             chars=np.array([c for c, _ in keys]),
             fonts=np.array([fn for _, fn in keys]))
    return mat, keys


def warm(charsets: list[tuple[str, ...]], root: str = "fonts",
         backend: str = "hog") -> None:
    """服务启动时预热——首次建大表要几分钟，别让第一个点按钮的人等。"""
    for cs in charsets:
        _index(tuple(cs), root, backend)


def candidates(patch: np.ndarray, charset: list[str] | tuple[str, ...],
               k: int = 10, root: str = "fonts",
               backend: str = "hog") -> list[FontHit]:
    """字块 → 字体模板 top-k 候选（按余弦相似度）。

    `patch` 是**已归一化**的 64² 二值图（`normalize_patch` 的输出），与建索引
    时的渲染图同一口径；传灰度原图会因为尺度/笔宽不同而全线失配。

    同一个字被多套字体命中时只留分最高的那次——候选列表要给人看，
    不该出现「䙝(jigmo3) 䙝(jigmo2)」这种重复。
    """
    from .features import get_feature

    mat, keys = _index(tuple(charset), root, backend)
    if mat.shape[0] == 0:
        return []
    q = get_feature(backend).extract(patch[None, ...].astype(np.uint8))[0]
    qn = float(np.linalg.norm(q)) or 1.0
    norms = np.linalg.norm(mat, axis=1)
    norms[norms == 0] = 1.0
    sims = (mat @ q) / (norms * qn)
    best: dict[str, FontHit] = {}
    for i in np.argsort(-sims):
        ch, fname = keys[int(i)]
        s = float(sims[int(i)])
        if ch not in best or s > best[ch].score:
            best[ch] = FontHit(ch, s, fname)
        if len(best) >= k * 3:          # 多扫一些再截断，避免同字挤掉不同字
            break
    return sorted(best.values(), key=lambda h: -h.score)[:k]


def book_charset(corpus_path: str, extra: list[str] | None = None) -> list[str]:
    """本书字表：整理本出现过的汉字 + 额外补充。

    不用全 Unihan——十万字既慢，又会把本书不可能出现的字塞进候选。
    """
    text = Path(corpus_path).read_text(encoding="utf-8")
    cs = {ch for ch in text if "㐀" <= ch <= "鿿" or "\U00020000" <= ch <= "\U0002ffff"}
    cs.update(extra or [])
    return sorted(cs)
