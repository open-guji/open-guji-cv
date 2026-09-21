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
FONT_ORDER = ("iming", "jigmo", "kangxi", "genmin")
# genmin 2026-09-21 本机实测**留下**（闸：unseen 严格 / oov 都不掉；r5，同机同代码同日复跑）：
#   三套字体          unseen 严格 emb 96.9 / hog 77.5   oov emb top-1 73.2 / top-10 90.4
#   + genmin 三套     unseen 严格 emb 97.0 / hog 79.3   oov emb top-1 74.5 / top-10 91.7
# 全部持平或涨；HOG 那路涨最多（模板多了三种写法）。数字与过程在
# structure_aware_recognition_design.md §13。曾一度误判要拿掉——那是被
# eval_zero_shot_fusion.py 的旧缺省 checkpoint 骗了（同一节有记）。
"""模板字体，按优先级。

- `iming` I.Ming 一点明朝体：传承字形（旧字形），用字习惯与刻本最吻合
- `jigmo` 字雲（CC0）：覆盖 Unicode 全部汉字，兜底
- `kangxi` **TypeLand 康熙字典体**（2026-09-08 加，`external_glyph_sources_experiment.md` §5.11）：
  摹康熙字典的商业字体，bench 1,958 字种覆盖 **100%**。实测加进模板后 unseen 严格
  top-1 **95.9 → 96.4**，比自切康熙扫描图（96.0）还高——不是它更还原刻本，而是
  **覆盖率 100% vs 76%**。**注意它不能单用**：只留它、去掉 iming/jigmo 会掉到 94.5%，
  多套字体「同字多写法取平均」的作用它一套顶不了。
  ⚠️ 商业字体（字语 TypeLand），字形轮廓受版权保护，与公版古籍扫描图性质不同；
  进可分发产物前须确认授权。
- `genmin` **源流／源雲／源樣明體 2.100**（2026-09-21 加；SIL OFL 1.1，`fonts/genmin/LICENSE.txt`）：
  ButTaiwan 基于思源宋体做的三套传承字形明朝体，基本区 + 扩A 全覆盖（cmap 35,349 字）、
  扩B 只 2,135。三套档在仓里躺了很久却没进 `FONT_ORDER`、全仓零引用
  （`rare_char_matching_survey.md` G7）。
  ⚠️ **接进来时没量过**（当时的机器没有 torch）——先跑
  `scripts/eval_zero_shot_fusion.py --split unseen --emb` 与 `scripts/eval_oov.py`
  对照 r5 基线（unseen 严格 96.9 / oov 314 条 73.2），掉了就把这一项拿掉。已知先例：
  多套字体「同字多写法取平均」有用（只留康熙体 96.4 → 94.5），但三套同源字体会不会
  把均值拉向思源宋体的骨架，没人量过。字体集已进指纹（`font_set_fingerprint`），
  加减字体会让 emb 索引与 `rare_candidates` 产物自动过期，不会静默沿用旧模板。"""
NORM = 64


@dataclass
class FontHit:
    char: str
    score: float
    font: str

    def as_tuple(self) -> tuple[str, float]:
        return (self.char, self.score)


#: 引擎仓根（`…/open-guji-cv`）——字体随仓走，不随调用方的 cwd 走。
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _font_files(root: str = "fonts") -> list[str]:
    """字体文件清单。

    **按引擎仓定位，不按调用方的 cwd**（2026-09-17）。`root` 缺省是相对路径
    `fonts`，原先直接 glob 它——运行时 cwd 常常是**工作区**（北行日錄、四庫
    各自一个目录），那里没有 `fonts/`，于是返回空列表：HOG 候选悄悄变空，
    embedding 模板也建不出来（它同样调这个函数取字体）。
    与 `cnn_candidates._resolve_default_ckpt` 2026-09-15 那次是同一类病：
    **仓内资源用相对路径找，换个 cwd 就静默失效**。

    显式传绝对路径的照用；传相对路径时先认 cwd（本机旧习惯），再认引擎仓。
    """
    cands = [Path(root)] if Path(root).is_absolute() else [Path(root), _REPO_ROOT / root]
    for base in cands:
        out: list[str] = []
        for name in FONT_ORDER:
            for ext in ("*.ttf", "*.otf"):   # 康熙体是 otf，只 glob ttf 会静默漏掉
                out.extend(sorted(glob.glob(str(base / name / ext))))
        if out:
            return out
    return []


INDEX_DIR = Path("cache/font_index")


def font_set_fingerprint(root: str = "fonts") -> str:
    """模板字体集的指纹：每个字体档 `名字:大小:mtime` 拼起来哈希；一个都没有 → "nofonts"。

    2026-09-21 加。此前只有 HOG 索引键（`_index_key`）带字体档，embedding 索引键
    （`cnn_candidates._emb_index`）与 `rare_candidates` 产物指纹（`full_fingerprint`）
    **都不带**——于是 `FONT_ORDER` 加一套字体、或换掉 `fonts/` 里的档，emb 索引照旧
    命中旧缓存、产物照旧显示新鲜，模板其实一张没变。与「阈值不进指纹」
    （`steps/rare_candidates.py` 2026-09-17）同一类静默失效，现在三处共用这一把尺子。
    """
    import hashlib
    files = _font_files(root)
    if not files:
        return "nofonts"
    h = hashlib.sha1()
    for f in files:
        st = Path(f).stat()
        h.update(f"{Path(f).name}:{st.st_size}:{int(st.st_mtime)}|".encode())
    return h.hexdigest()[:12]


def _index_key(charset: tuple[str, ...], root: str, backend: str) -> str:
    import hashlib
    h = hashlib.sha1()
    h.update(backend.encode())
    h.update(font_set_fingerprint(root).encode())
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


_NORM_CACHE: dict[int, np.ndarray] = {}


def _row_norms(mat: np.ndarray) -> np.ndarray:
    """模板矩阵的行模长，按矩阵身份缓存（`_index` 的 lru_cache 保证同一批查询同一个对象）。"""
    key = id(mat)
    v = _NORM_CACHE.get(key)
    if v is None or v.shape[0] != mat.shape[0]:
        v = np.linalg.norm(mat, axis=1)
        v[v == 0] = 1.0
        if len(_NORM_CACHE) > 8:
            _NORM_CACHE.clear()
        _NORM_CACHE[key] = v
    return v


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
    # 模板矩阵的行模长只跟索引有关，**每次查询重算是白烧**：大表 8 万行 × 每次
    # 0.1s，占了单次查询的一大半（2026-09-07 实测 HOG 大表 239ms，审查页预取因此
    # 每张卡要等 0.35s）。按矩阵对象 id 缓存一份，索引本身有 lru_cache 保证不变。
    norms = _row_norms(mat)
    sims = (mat @ q) / (norms * qn)
    return _topk_from_sims(sims, keys, k)


def _topk_from_sims(sims: np.ndarray, keys: list[tuple[str, str]], k: int) -> list[FontHit]:
    """一行相似度 → 去重（同字取最高分字体）后的 top-k `FontHit`，`candidates()`
    与 `candidates_batch()` 共用（批处理版只是把这段循环搬到每行上跑）。"""
    best: dict[str, FontHit] = {}
    pool = min(len(sims), max(64, k * 8))
    cand = np.argpartition(-sims, pool - 1)[:pool]
    for i in cand[np.argsort(-sims[cand])]:
        ch, fname = keys[int(i)]
        s = float(sims[int(i)])
        if ch not in best or s > best[ch].score:
            best[ch] = FontHit(ch, s, fname)
        if len(best) >= k * 3:
            break
    return sorted(best.values(), key=lambda h: -h.score)[:k]


def candidates_batch(patches: list[np.ndarray], charset: list[str] | tuple[str, ...],
                     k: int = 10, root: str = "fonts",
                     backend: str = "hog") -> list[list[FontHit]]:
    """`candidates()` 的批量版：一页多个字块一次性对模板矩阵做矩阵-矩阵乘法。

    ## 为什么要批：矩阵-向量乘法 vs 矩阵-矩阵乘法

    `candidates()` 逐字调用时，每次都是 (80240×1764) 大字体模板矩阵对一个
    1764 维查询向量做矩阵-向量乘法（GEMV）。BLAS 的 GEMV 路径吃不满 CPU
    缓存——**同一批查询共享同一个模板矩阵**，改成矩阵-矩阵乘法（GEMM，
    80240×1764 对 1764×N）后模板矩阵的每一行只需要从内存搬一次，不是
    搬 N 次，实测一页量级（N≈60）快 4 倍（15.3ms/字 → 3.5ms/字，
    2026-09-10 用户要求做的第二轮生僻字候选提速）。

    结果与逐次调用 `candidates()` 完全一致（同一份归一化、同一份索引、
    同一套去重/截断逻辑），只是把「一次一个」的 IO 模式换成「一次一批」。
    """
    from .features import get_feature

    mat, keys = _index(tuple(charset), root, backend)
    if mat.shape[0] == 0 or not patches:
        return [[] for _ in patches]
    feat = get_feature(backend)
    Q = feat.extract(np.stack(patches).astype(np.uint8))          # (N, D)
    qn = np.linalg.norm(Q, axis=1)
    qn[qn == 0] = 1.0
    norms = _row_norms(mat)
    # (rows, D) @ (D, N) → (rows, N)；除以外积 (rows, N) 的行列模长
    sims = (mat @ Q.T) / (norms[:, None] * qn[None, :])
    return [_topk_from_sims(sims[:, j], keys, k) for j in range(sims.shape[1])]


def book_charset(corpus_path: str, extra: list[str] | None = None) -> list[str]:
    """本书字表：整理本出现过的汉字 + 额外补充。

    不用全 Unihan——十万字既慢，又会把本书不可能出现的字塞进候选。
    """
    text = Path(corpus_path).read_text(encoding="utf-8")
    cs = {ch for ch in text if "㐀" <= ch <= "鿿" or "\U00020000" <= ch <= "\U0002ffff"}
    cs.update(extra or [])
    return sorted(cs)
