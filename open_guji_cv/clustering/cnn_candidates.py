# -*- coding: utf-8 -*-
"""CNN 候选源：`scripts/train_glyph_cnn.py` 训出的分类器，对字表打分取 top-k。

## 它在候选栈里的位置

零样本评测（`eval_zero_shot_fusion.py`，unseen 1,327 条，异体算对）：

| | top-1 | top-5 | top-10 |
|---|---|---|---|
| HOG 字体检索 | 75.5% | 91.9% | 94.7% |
| CNN 分类 | 72.4% | 95.3% | 97.6% |
| **RRF 融合** | **86.7%** | **97.2%** | **98.3%** |

两者错得不一样：HOG 看整体轮廓，CNN 被部件多标签头逼着看局部；倒数排名融合
（RRF，只看名次不看分数——余弦与 softmax 量纲不同）top-1 比任一单源高 11 个点。
rare-char 21 条上 CNN 单独 top-10 100%。

## 纪律

- **只出候选，不放行**——与字体模板同一条红线。它对 unseen 字的 top-1 只有 72%，
  离 precision ≥0.999 的放行门槛差几个数量级；
- 模型是外部可变状态：checkpoint 路径 + mtime 进指纹（`fingerprint()`），
  换了模型产物要过期——与 glyph.db、语料同一套做法。
"""

from __future__ import annotations

import hashlib
import os

# CPU 推理反活锁（2026-09-27，任务书-R-rare挂死）：容器环境下 torch/OpenBLAS 默认按
# `os.cpu_count()` 开 intra-op 线程池，`rare_for_batch` 对整页字块逐批调用小张量/小矩阵
# 运算，触发线程池忙醒忙睡的 futex 活锁（`strace` 实测：两个线程池地址间来回
# `FUTEX_WAKE_PRIVATE`，CPU 300%+ 但零进度，几分钟不会自己恢复）。
#
# 只设环境变量不够——OpenBLAS/MKL 的线程池只在各自库**第一次**跑并行运算时才读一次
# 这些变量，读过之后再改 `os.environ` 不生效（实测：同进程内先跑一次矩阵乘法、再设
# `OPENBLAS_NUM_THREADS`，前后耗时几乎相同）。所以必须在**本模块 import 时**、也就是
# 在任何 `import numpy`/`import torch`/`import cv2` 真正触发线程池之前设好——`cnn_candidates`
# 是 Step5-b 候选栈里最先被 import 的一个（`rare_candidates.run_page` 先 import 它，
# 再 import 会牵出 `font_candidates` 的 `rare_panel`），这里设最早。
# 用 `setdefault` 不覆盖调用方已经显式设置的值。
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")
del _var

from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

try:  # pragma: no cover - cv2 总已安装，防御性写法与其余延迟 import 一致
    import cv2 as _cv2
    _cv2.setNumThreads(1)
except Exception:
    pass


def _resolve_default_ckpt() -> Path:
    """checkpoint 不可重建（重训要 GPU + 数小时），2026-09-09 起进 Git，
    落在 `models/glyph_cnn_r4/`（`/cache/` 整体 gitignore，云端 clone 拿不到）。
    本机若还有旧路径 `cache/glyph_cnn_r4/best.pt`，优先用它——不强迫已有工作区搬文件，
    也不改变本机现役 checkpoint 的 mtime（会让 fingerprint 变、下游产物被判 stale）。
    """
    # **按引擎仓定位，不按调用方的 cwd**（2026-09-15）：checkpoint 随引擎仓走
    # （`models/` 进 Git），而运行时的 cwd 常常是工作区——北行日錄实测：从
    # `beixingrilu-workspace` 下跑，两个相对路径都不存在，`cnn.available` 悄悄变成
    # False，生僻字面板于是**返回空候选而不报错**（CNN 不可用时本该退回 HOG，
    # 但 `_fuse` 走的是「两边都空 → 空列表」那条路）。控制台碰巧在引擎仓下起，
    # 所以网页上是好的、脚本里是空的，差一个 cwd。
    here = Path(__file__).resolve().parents[2]          # …/open-guji-cv
    # r5 优先（2026-09-17 起现役，见下方 DEFAULT_CKPT 文档）；找不到才退回 r4。
    for rel in ("models/glyph_cnn_r5/best.pt",
                "cache/glyph_cnn_r4/best.pt", "models/glyph_cnn_r4/best.pt"):
        for base in (Path.cwd(), here):                 # 先认 cwd（本机旧习惯），再认引擎仓
            cand = base / rel
            if cand.exists():
                return cand
    return here / "models/glyph_cnn_r5/best.pt"


DEFAULT_CKPT = _resolve_default_ckpt()
"""现役 checkpoint。

**2026-09-17 起 `glyph_cnn_r5`**（`research/metric_loss/`，结论正本在 overview
`Step5-字符识别/5b-生僻字候选/06-给embedding加独立度量损失.md` §九）。
r5 与 r4 **同一份配方、同一份数据，只把训练轮数 160 → 60**：

| 指标（类外 314 条真刻例 `cache/oov_bench`） | r4 | **r5** |
|---|---|---|
| emb top-1 | 67.8% | **73.2%** |
| emb top-10 | 89.2% | **90.4%** |
| unseen 1,327 emb top-1（严格，护栏） | 95.4% | **96.9%** |
| unseen 1,327 cls top-1（严格，护栏） | 94.0% | **96.8%** |

长训练在**拿类外泛化换类内精度**：类外能力 3 个 epoch 就到顶，后段 epoch 只涨
`seen_test`。度量损失（ArcFace / CosFace / 纯余弦头）在真刻例上**一律为负**，
三个配置同向，已证伪、不采纳。

⚠️ **`FORM_EMB_GAP` 必须跟着 r5 改成 0.03**（见 `variant_form.py` 那行注释）：
r5 的组内定形 top1−top2 差比 r4 小 3.8 倍（0.048 vs 0.184），沿用 0.12 会让
`fixed_form` 放行率从 76.1% 塌到 **0.6%**（通道等于关掉）。改 0.03 后是 77.4% 零错。

**换 checkpoint 会让下游产物过期**（路径 + mtime 进 `fingerprint()`），相关页要重跑。
旧 checkpoint 保留在 `models/glyph_cnn_r4/` 可随时切回；
切回时 `HOG_WEIGHT`/`EMB_WEIGHT`/`FORM_EMB_GAP` 都要一起还原。"""
def _resolve_gw_catalog() -> Path:
    """GlyphWiki 变体形目录（`scripts/build_glyphwiki_catalog.py` 的产物，不进 git）：
    先认 cwd，再认引擎仓——与 `_resolve_default_ckpt` 同一条口径。找不到 → 引擎仓路径（不存在）。"""
    here = Path(__file__).resolve().parents[2]
    for base in (Path.cwd(), here):
        cand = base / "cache/glyphwiki/catalog_64.npz"
        if cand.exists():
            return cand
    return here / "cache/glyphwiki/catalog_64.npz"


GW_CATALOG = _resolve_gw_catalog()
"""第六套模板档：GlyphWiki 的未收/异体字形（中华字海、教育部字典、大漢和、IDS 命名……），
kage 渲染成 64² 图，每形挂一个关联字。**每字取 max、单独一档、不混进字体均值**
（oov_bench 实测：max 池化 top-1 75.8 → 81.5，混进均值 → 66.2；设计稿 §13 ⑤）。
文件缺席时整条路静默不参与（`gw_catalog_fingerprint()` 为空、`full_fingerprint` 不变）。"""

GW_ENABLED = False
"""模块级总开关，**缺省关**——评测脚本（`eval_oov.py --no-gw`）与不带 `ctx.book` 的老调用方走它。
**2026-09-22** 7 万字表实测 oov_bench emb top-1 74.5 → 77.7、top-5 89.8 → 91.1、top-10 91.7
不变；但 unseen 严格 top-10 100.0 → 99.8（掉 3 条，top-1 98.0 不变）——当时任务卡的闸是
「unseen 严格 / oov 都不掉」，差这 0.2 没开。

**2026-09-27（T4 变体形转正）**：按书开的口子已接（`font.gw_variant.enabled`，见
`book_gw_variant()`），产线走 `emb_topk_batch(gw_enabled=…)`/`full_fingerprint(gw_enabled=…)`
显式传参，不再依赖这个模块全局；此处仍留 `False` 当"没配置 `gw_variant` 的书"的兜底，
与加这个开关之前逐位相同。评测：`eval_oov.py --no-gw` 对照；`scripts/eval_t4_variant.py`
对照 158 条异体分歧子集；设计稿 §13 ⑥。"""


_GW_CATALOG_FILE_FP_CACHE: dict[tuple[str, int, int], str] = {}


def _gw_catalog_content_fingerprint(p: Path) -> str:
    """单个目录文件的**内容**指纹（sha256 前 12 位），按 `(路径, mtime_ns, 大小)` 缓存——
    与 `_real_proto_file_fingerprint`/`utils.cut_select.ckpt_fingerprint` 同一个写法。"""
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    fp = _GW_CATALOG_FILE_FP_CACHE.get(key)
    if fp is None:
        from ..products.store import sha256_file
        fp = sha256_file(p)[:12]
        _GW_CATALOG_FILE_FP_CACHE[key] = fp
    return fp


def gw_catalog_fingerprint(path: str | Path = GW_CATALOG, enabled: bool | None = None) -> str:
    """GlyphWiki 目录指纹：**按内容**（sha256），不按 `(大小, mtime)`（T4 变体形转正，
    2026-09-27）——同 `real_proto_fingerprint` 那次改的理由：云端算好的目录运到别的机器，
    文件内容一字不差，mtime 却对不上，会被判过期。

    `enabled=None`（缺省）时看模块级 `GW_ENABLED`；按书配置调用时传显式的书级开关
    （见 `book_gw_variant`）。**关着（不管模块级还是书级）一律返回空串**——这不是新行为，
    是补一个此前就该有的短路：`full_fingerprint()` 曾经不管 `GW_ENABLED` 一律把这段
    fingerprint 并进去（`_gw_index` 用不用是另一回事），关着的书只要本机 `cache/glyphwiki/`
    目录内容一变，`rare_candidates` 就被判过期——跟 `params_hash`/`self_hash` 不对齐
    同一类坑（见 `core/step.py::_with_book_real_proto` 那次）。"""
    en = GW_ENABLED if enabled is None else enabled
    if not en:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return _gw_catalog_content_fingerprint(p)


def book_gw_variant(font: dict | None) -> bool:
    """册配置 `font.gw_variant` → `enabled`（T4 变体形模板转正，2026-09-27）。

    yaml 形状：`font: {gw_variant: {enabled: bool}}`。缺省 `enabled=False`——不给这段
    配置的书（包括现役十册四庫、没重跑过的旧产物）行为与这块新配置加入前逐位相同。
    与 `book_real_proto` 同一条口径，只是这里没有 `stores`：GlyphWiki 目录是引擎仓级的
    单一资源（`cache/glyphwiki/catalog_64.npz`，`scripts/build_glyphwiki_catalog.py` 生成，
    不进 git），不像真刻例那样按书各指各的库。"""
    cfg = (font or {}).get("gw_variant") or {}
    return bool(cfg.get("enabled", False))


REAL_PROTO_ENABLED = False
"""真刻例多原型档总开关（R2 / T11，2026-09-26）。缺省关：跨书统一真刻例库还不存在
（`rare_char_matching_survey.md` G3），启用前先看 `REAL_PROTO_SPECS` 指了哪几本书、
闸过没过（任务书「过了闸也只出候选、不进放行；开关缺省值由协调者看了数再定」）。

补的是 `_emb_index` 模板只有字体渲染均值这个结构缺口：每字模板改成
「字体均值 ⊕ 该字真刻例聚类的 k≤3 个原型」，与 `GW_ENABLED` 那档同一套接线
（max 融合、指纹带 stamp、开关缺省关），模板源换成本仓能读到的 `glyph_store`
目录而不是 GlyphWiki 渲染图。"""

REAL_PROTO_SPECS: tuple[str, ...] = ()
"""真刻例来源，`store:<glyph_store 目录>` 列表，缺省空。每个目录须是某本书
`output/glyph_store`（`instances/*.jsonl` + `patches/<instance_id 把 : 换成 _>.png`
那个布局，见 `glyph_db.py` 的 `instances` 表：patch 是原始裁块，不是归一化图）。"""

REAL_PROTO_K = 3
"""每字最多聚几个原型（任务书「k≤3」）。"""

REAL_PROTO_LABEL_STATUSES: frozenset = frozenset({"human"})
"""只认这些 `label_status` 的实例——`align`/`match`/`context` 都是算法标的，
只有 `human` 是人工确认过的真刻例（`feedback/bindings.py:132` 同一口径）。"""
RRF_K = 60


def book_real_proto(font: dict | None) -> tuple[bool, tuple[str, ...]]:
    """册配置 `font.real_proto` → `(enabled, specs)`（5-b 开关转正，2026-09-26）。

    yaml 形状：`font: {real_proto: {enabled: bool, stores: [<相对书目录的 glyph_store
    路径>, ...]}}`；`stores` 缺省 `["output/glyph_store"]`（这册书自己的库）。相对路径
    按当前 `workspace_root()` 解释（没设 `GUJI_WORKSPACE` 就按引擎仓——与
    `core.workspace.glyph_store_path` 同一条口径），拼成 `_iter_real_exemplars` 认的
    `store:<目录>` 形式。缺省 `enabled=False`——不给这段配置的书（包括现役十册四庫、
    没重跑过的旧产物）行为与这块新配置加入前逐位相同。

    `rare_candidates.py::RareCandidatesStep.run_page` 用它把 `CnnCandidates` 的真刻例
    来源从模块全局（`REAL_PROTO_ENABLED`/`REAL_PROTO_SPECS`，仍留给评测脚本用）
    改成**按书**、实例级传参，两本书可以各开各的、各指各的库，不再互相牵连。
    """
    cfg = (font or {}).get("real_proto") or {}
    enabled = bool(cfg.get("enabled", False))
    stores = cfg.get("stores") or ["output/glyph_store"]
    from ..core.workspace import workspace_root
    base = workspace_root() or Path(__file__).resolve().parents[2]
    specs = []
    for s in stores:
        p = Path(s)
        if not p.is_absolute():
            p = base / p
        specs.append(f"store:{p}")
    return enabled, tuple(specs)


def _iter_real_exemplars(store_dir: Path, label_statuses: frozenset = REAL_PROTO_LABEL_STATUSES):
    """`glyph_store` 目录 -> 逐条 yield (char, instance_id, patch 文件路径)。

    扫 `instances/*.jsonl`，只收 `label_status` 在白名单里、`label` 是单字的行；
    图从 `patches/` 按 instance_id（把 `:` 换成 `_`）找，缺文件的跳过。
    """
    import json

    inst_dir = store_dir / "instances"
    if not inst_dir.exists():
        return
    for jf in sorted(inst_dir.glob("*.jsonl")):
        with open(jf, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d.get("label_status") not in label_statuses:
                    continue
                ch = d.get("label")
                if not ch or len(ch) != 1:
                    continue
                iid = d.get("instance_id")
                if not iid:
                    continue
                p = store_dir / "patches" / (iid.replace(":", "_") + ".png")
                if p.exists():
                    yield ch, iid, p


def load_real_exemplars(specs: tuple = REAL_PROTO_SPECS, charset=None):
    """spec 列表 -> {字: [(instance_id, 64² 二值归一图), ...]}。

    全部走 `normalize_patch`——与真刻例同一条归一化路径，跟 `extra_glyphs.load_extra_glyphs`
    同一条纪律（`instances` 表存的是原始裁块，不是已归一化图）。**不落盘缓存**：真刻例池
    比 GlyphWiki 小两个量级，CPU 全量前向本身就是秒级，落盘缓存反而引入「书变了但 key
    没变」的新鲜度坑。
    """
    import cv2

    from .normalize import normalize_patch

    cs = set(charset) if charset is not None else None
    out: dict = defaultdict(list)
    for spec in specs or ():
        if not spec.startswith("store:"):
            continue
        d = Path(spec.split(":", 1)[1])
        if not d.exists():
            continue
        for ch, iid, p in _iter_real_exemplars(d):
            if cs is not None and ch not in cs:
                continue
            try:
                buf = np.fromfile(str(p), dtype=np.uint8)
                img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE) if buf.size else None
            except OSError:
                img = None
            if img is None or img.size == 0:
                continue
            try:
                norm = normalize_patch(img)
            except Exception:  # noqa: BLE001
                continue
            if not norm.any():
                continue
            out[ch].append((iid, norm.astype(np.uint8)))
    return dict(out)


_REAL_PROTO_FILE_FP_CACHE: dict[tuple[str, int, int], str] = {}


def _real_proto_file_fingerprint(jf: Path) -> str:
    """单个 `instances/*.jsonl` 的**内容**指纹（sha256 前 12 位），按 `(路径, mtime_ns,
    大小)` 缓存避免重复读盘——跟 `utils.cut_select.ckpt_fingerprint` 同一个写法。"""
    st = jf.stat()
    key = (str(jf), st.st_mtime_ns, st.st_size)
    fp = _REAL_PROTO_FILE_FP_CACHE.get(key)
    if fp is None:
        from ..products.store import sha256_file
        fp = sha256_file(jf)[:12]
        _REAL_PROTO_FILE_FP_CACHE[key] = fp
    return fp


def _portable_store_label(spec: str) -> str:
    """`store:<绝对路径>` → 进哈希的可移植标签：在工作区根（没设则引擎仓根）之下就写
    `store:<相对路径>`，否则原样。

    2026-09-29（K#238c）：`book_real_proto` 把相对路径拼成绝对路径才交给这里，绝对路径
    进了哈希，云端 `/home/user/...` 与服务器 `/srv/...` 同内容也算出不同指纹，
    `rare_candidates` 永远对不上。内容指纹（`_real_proto_file_fingerprint`）本来就跨机器
    一致，路径前缀是唯一的机器差异。"""
    from ..core.workspace import workspace_root
    d = Path(spec.split(":", 1)[1])
    base = workspace_root() or Path(__file__).resolve().parents[2]
    try:
        return "store:" + d.relative_to(base).as_posix()
    except ValueError:
        return spec


def real_proto_fingerprint(specs: tuple = REAL_PROTO_SPECS, enabled: bool | None = None) -> str:
    """真刻例模板集指纹：每个 store 目录 `instances/*.jsonl` 的**内容** sha256 拼起来。
    目录缺席的 spec 不参与，一个都不参与（或总开关关着）时返回空串。

    `enabled=None`（缺省）时看模块级 `REAL_PROTO_ENABLED`——评测脚本走这条，与此前
    逐位相同。按书配置调用时传显式的书级开关（见 `book_real_proto`），不再看模块全局。

    **按内容算，不按 `(大小, mtime)`**（2026-09-27，CV 总管 review 指出）：mtime 是各
    机器 checkout 的时间，云端算好的产物运到服务器、文件内容一字不差，mtime 却对不上，
    `rare_candidates` 会被判过期——跟 09-27 `ckpt_fingerprint`／`corpus_fingerprint`
    那次（cv `078a13d`）同一个坑，见 `utils.cut_select.ckpt_fingerprint` 模块注释。"""
    en = REAL_PROTO_ENABLED if enabled is None else enabled
    if not en:
        return ""
    parts = []
    for spec in specs or ():
        if not spec.startswith("store:"):
            continue
        d = Path(spec.split(":", 1)[1]) / "instances"
        if not d.exists():
            continue
        for jf in sorted(d.glob("*.jsonl")):
            parts.append(f"{_portable_store_label(spec)}/{jf.name}:{_real_proto_file_fingerprint(jf)}")
    if not parts:
        return ""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _farthest_point_protos(vecs: np.ndarray, ids: list, k: int):
    """余弦空间最远点采样：从一个字的全部真刻例 embedding 里挑 <=k 个彼此最不像的做原型。

    不用 KMeans——n 通常个位数到几十，重点是覆盖类内形态分布的极端（磨损、断笔、
    异写），不是求形心；第一个点取离全体均值最远的（离群锚点），后续每次挑「离已选
    原型集合最近距离」最大的那个（增量 k-center，贪心 2-近似）。n<=k 时全部保留。
    """
    n = vecs.shape[0]
    if n <= k:
        return [vecs[i] for i in range(n)], list(ids)
    mean = vecs.mean(0)
    mean = mean / (np.linalg.norm(mean) + 1e-9)
    d0 = 1.0 - vecs @ mean
    chosen = [int(np.argmax(d0))]
    min_d = 1.0 - vecs @ vecs[chosen[0]]
    while len(chosen) < k:
        nxt = int(np.argmax(min_d))
        if nxt in chosen:
            break
        chosen.append(nxt)
        min_d = np.minimum(min_d, 1.0 - vecs @ vecs[nxt])
    return [vecs[i] for i in chosen], [ids[i] for i in chosen]


_CKPT_FP_CACHE: dict[tuple[str, int, int], str] = {}


def fingerprint(path: str | Path = DEFAULT_CKPT) -> str:
    """checkpoint 指纹：**按内容**（sha256 前 12 位），不按 `(路径, mtime)`
    （2026-09-27，任务书-R-rare冷启动内存与索引预建）——同 `real_proto_fingerprint`/
    `gw_catalog_fingerprint`/`utils.cut_select.ckpt_fingerprint` 那几次同一个坑：
    云端建好的 `emb_*.npz`/`gw_*.npz` 运到服务器，`best.pt` 内容一字不差，mtime
    却对不上（换机器 checkout 的时间），旧写法（sha1(路径:大小:mtime)）会让这份
    预建索引在服务器上**永远不命中**，白白预建。

    按 `(路径, mtime_ns, 大小)` 缓存 sha256 结果，避免同进程内每次实例化
    `CnnCandidates`/每次查指纹都重读 19MB 的权重文件。"""
    p = Path(path)
    if not p.exists():
        return "nockpt"
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    fp = _CKPT_FP_CACHE.get(key)
    if fp is None:
        from ..products.store import sha256_file
        fp = sha256_file(p)[:12]
        _CKPT_FP_CACHE[key] = fp
    return fp


def build_emb_matrix(net, dev, cs: tuple[str, ...], extra: dict, render_char,
                     log=None, log_every: int = 1000) -> tuple[np.ndarray, list[str]]:
    """`_emb_index` 冷启动那段重活的独立函数体：字表 → (字体渲染 ∪ 真刻本图) →
    网络前向 → 单位化 embedding，逐字均值。抽成模块函数（2026-09-27，任务书-
    R-rare冷启动内存与索引预建）有两个原因：

    1. **进度日志**：建 2.7–7 万字的索引单核 5–25 分钟、此前零输出，跑批看着
       像卡死（`总调度/服务器工单/1715`「5 分钟里没写出 emb_*.npz」就是这么
       被判定成问题的）。现在每 `log_every` 字打一行，`ctx.log`/`print` 都能接。
    2. **给 `guji cache build-rare-index` 复用**：预建命令与产线用同一份逻辑，
       不会走出两条实现、结果不一致。

    这一步的内存实测**没有能收敛到 ≤1.2G 目标的进程内改法**（`gc.collect`+
    `malloc_trim`、关 mkldnn、固定 batch 形状都试过、都不改变增长曲线，见
    `_emb_index` 模块头）——真正的解法是别在服务器上跑这段，靠预建+分发。
    """
    import torch
    from .font_candidates import _font_files

    fonts = _font_files()
    vecs, names = [], []
    n_render_fail = 0
    with torch.no_grad():
        for i, ch in enumerate(cs):
            ims = []
            for fp in fonts:
                try:
                    im = render_char(ch, fp, size=64)
                except Exception:
                    continue
                if im is not None and im.any():
                    ims.append(im.astype(np.uint8))
            ims += extra.get(ch, [])
            if not ims:
                n_render_fail += 1
                continue
            x = torch.tensor(np.stack(ims)[:, None].astype(np.float32), device=dev)
            e, _, _ = net(x)
            v = e.mean(0)
            vecs.append((v / (v.norm() + 1e-9)).cpu().numpy())
            names.append(ch)
            if log is not None and (i + 1) % log_every == 0:
                log(f"guji cache build-rare-index：{i + 1}/{len(cs)} 字"
                   f"（{n_render_fail} 字全部字体渲染失败）")
    mat = np.stack(vecs).astype(np.float32) if vecs else np.zeros((0, 256), np.float32)
    if log is not None:
        log(f"guji cache build-rare-index：完成，{len(names)}/{len(cs)} 字建出模板"
           f"（{n_render_fail} 字全部字体渲染失败）")
    return mat, names


def _save_emb_index(f: Path, mat: np.ndarray, names: list[str]) -> None:
    """embedding 索引原子落盘，**存 float32**（2026-09-27 CV 总管定：R 道试过
    float16 落盘，200 条压测查询 top-1 变 1%、top-10 集合变 8.5%；体积省一半
    约 35MB 不值得换候选不逐位一致，改回 float32，与改前产物逐位相同）。

    先写临时文件再原子改名：中途被打断（Ctrl-C / 进程被杀）不会留下只建了
    一半的索引冒充完整缓存。⚠️ `np.savez` 会给不以 .npz 结尾的路径**自动补**
    .npz 后缀，所以临时文件必须自己以 .npz 结尾，否则 savez 写的是
    `x.tmp.npz`、replace 找的是 `x.tmp`。"""
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp.npz")
    np.savez(tmp, mat=mat.astype(np.float32), chars=np.array(names))
    os.replace(tmp, f)


def _build_net(n_cls: int, n_comp: int, d: int = 256, n_struct: int = 0, n_slot: int = 0):
    """与 train_glyph_cnn.Net 同构；结构改了这里要同步（用 checkpoint 里的维度校验）。

    `n_struct` / `n_slot` > 0 时多两个头（Step A，2026-09-21）：结构头（顶层算符 18 类）
    与槽位部件头（`部件@槽` 多标签）。r4/r5 checkpoint 没有这两个键，传 0 即原网络，
    `forward` 的三元组返回值不变——老调用方一个都不用改；新头走 `heads()`。"""
    import torch.nn as nn
    import torch.nn.functional as F

    class Block(nn.Module):
        def __init__(self, i, o, s):
            super().__init__()
            self.c1 = nn.Conv2d(i, o, 3, s, 1, bias=False)
            self.b1 = nn.BatchNorm2d(o)
            self.c2 = nn.Conv2d(o, o, 3, 1, 1, bias=False)
            self.b2 = nn.BatchNorm2d(o)
            self.sc = (nn.Sequential(nn.Conv2d(i, o, 1, s, bias=False), nn.BatchNorm2d(o))
                       if (s != 1 or i != o) else nn.Identity())

        def forward(self, x):
            y = F.relu(self.b1(self.c1(x)))
            y = self.b2(self.c2(y))
            return F.relu(y + self.sc(x))

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.stem = nn.Sequential(nn.Conv2d(1, 32, 3, 1, 1, bias=False), nn.BatchNorm2d(32), nn.ReLU())
            self.l1 = Block(32, 64, 2)
            self.l2 = Block(64, 128, 2)
            self.l3 = Block(128, 256, 2)
            self.l4 = Block(256, 256, 2)
            self.emb = nn.Linear(256 * 16, d)
            self.cls = nn.Linear(d, n_cls)
            self.comp = nn.Linear(d, n_comp)
            self.struct = nn.Linear(d, n_struct) if n_struct > 0 else None
            self.slot = nn.Linear(d, n_slot) if n_slot > 0 else None

        def forward(self, x):
            x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
            e = F.normalize(self.emb(x.flatten(1)), dim=1) * 16.0
            return e, self.cls(e), self.comp(e)

        def heads(self, x):
            """全部头：dict(emb, cls, comp, struct?, slot?)。"""
            e, lg, cp = self.forward(x)
            out = {"emb": e, "cls": lg, "comp": cp}
            if self.struct is not None:
                out["struct"] = self.struct(e)
            if self.slot is not None:
                out["slot"] = self.slot(e)
            return out

    return Net()


class CnnCandidates:
    """懒加载；没有 checkpoint 或没装 torch 时 `available` 为 False，调用方跳过。"""

    _EMB_CACHE_MAX = 4
    """`_emb_cache` 最多留几档字表的 embedding 矩阵——见该属性在 `__init__` 里的
    文档。一本书正常只有基集＋升级档两档，4 是留出的余量，不是精确值。"""

    def __init__(self, ckpt: str | Path = DEFAULT_CKPT, device: str | None = None,
                 probe: str | Path | None = None):
        self.ckpt = Path(ckpt)
        self.device = device
        self._net = None
        self._probe = None
        self._probe_path = Path(probe) if probe else None
        self._gw: tuple | None = None          # (G 单位向量, related 字数组, names, sources)，整目录，按 checkpoint+目录指纹落盘
        self._gw_cs: tuple | None = None       # (charset 身份, G_sub, rel_row_idx, names_sub, src_sub)
        self.last_gw_prov: list[dict] = []
        """最近一次 `emb_topk_batch` 里 GlyphWiki 模板赢过字体均值的字位：每个查询一个
        `{字: (gw 名, 来源, 余弦)}`，与输入一一对应。`rare_for_batch` 紧跟着读它给候选加 `gw` 字段。"""
        """外挂结构头（Step A′，2026-09-22）：`scripts/probe_struct_heads.py` 在冻结主干的
        embedding 上训出的 `probe_<arch>.pt`。挂上后 `has_struct_heads` 为真、
        `struct_probs_batch` / `slot_probs_batch` 走它——主干与 checkpoint 一根毛不动，
        unseen / oov 定义上不变。checkpoint 自带结构头（r6 那种）时以 checkpoint 为准。"""
        self._classes: list[str] = []
        self._cidx: dict[str, int] = {}
        self._comps: list[str] = []
        self._struct_classes: list[str] = []
        self._slot_labels: list[str] = []
        self._emb_cache: list[tuple] = []
        """`_emb_index` 的内存缓存：`[(charset, mat, names), ...]`，最多留
        `_EMB_CACHE_MAX` 份，LRU（命中的挪到末尾，满了从头淘汰）。见该方法模块头
        「2026-09-10 修」——没有它，逐字调用会把 `load_many` 的目录扫描/npz
        解压重复付一遍，而不是只算一次 key 就命中磁盘缓存。

        **2026-09-28 从单槽改成小容量 LRU**（CV 总管报：服务器 `rare_candidates`
        单进程内存随页数线性上涨，任务书-R 追加件）：原来单槽缓存只留「最近一档」，
        而 `rare_panel.rare_for_batch` 的阶梯（基集→升级档）**在同一页内先后查两档
        字表**——两档字表对象在一本书的所有页里都稳定（`book_charsets` 的
        `lru_cache`），但单槽缓存放不下两个，于是每一页都要把上一页缓存的那一档
        挤掉、从磁盘重读另一档（unicode-cjk-a 基集矩阵约 28MB／unicode-ext-b
        升级档约 44MB），来回颠簸。实测（生产大字表、40 页合成基准）：RSS 从
        建索引刚完成的 708MB 到第 2 页跳到 738MB 后打平，不是持续攀升，但这种
        大块反复 alloc/free 的模式会顶住 glibc malloc arena 不易缩回，与服务器
        「涨到 3.17G 被节流」的现象吻合。留够两档（缺省 4，给以后可能出现的
        第三档留余量）后，同一本书跑多少页都只在最开始各建一次，不用 `is` 键
        的普通 dict——**存对象本身、线性扫描 `is` 比对**（与 `_fwd_cache` 同一个
        写法，理由见其文档：只存 `id()` 整数会被垃圾回收后复用的地址撞车；这里
        `charset` 由 `book_charsets` 的 lru_cache 一直强引用着，其实不会被回收，
        但还是照抄这个更安全的写法，不留后患）。"""
        self._real_slots: list[tuple[tuple, tuple | None]] = []
        """`_real_index` 的内存缓存：`[(key, 结果), ...]`，按最近使用排、最多
        `_REAL_CACHE_MAX` 档。真刻例池比 GlyphWiki 小两个量级（千级 vs 万级），
        **不落盘**——见该方法文档。

        2026-10-06（overview#429）从单档改成两档：`rare_for_batch` 每页先查基集、
        有字位走升级档时再查升级档，单档缓存于是被升级档挤掉，下一页回到基集要重建——
        四庫 vol04 基集那份前向约 30 秒（升级档 0.4 秒），p62–82 里 21 页有 4 页
        各多花 30 秒，整册约多 18 分钟。两档后同一本书只各建一次，候选逐位不变。
        `_real_cs`（属性）仍是最近一档；测试里 `cnn._real_cs = None` 清空整份缓存。"""
        self._fwd_cache: tuple[list, tuple] | None = None
        """最近一批 `self._net(x)` 的原始前向结果缓存：`(norm_patches 那个 list
        对象本身, (e, lg, cp))`。`topk_batch`/`emb_topk_batch` 原来对同一批字块图
        各自独立跑一次前向（网络本身不看 charset，两边算的是同一件事），
        `rare_panel.rare_for_batch` 对基集字表先后调两次、升级档子集再调第三次——
        改成只留「最近一批」，同一个 list 对象（调用方按页组批，同一页内对象不变）
        内的后续调用直接复用，换新批次自动作废（2026-09-28，任务书-R-rare前向
        去重与测试隔离，K 引擎卡手 #54 cross 单）。单槽缓存，不是无界字典——
        `shared()` 是进程级单例，页与页之间批次不同，留多份没有意义。

        ⚠️ **必须存对象本身、用 `is` 比对，不能只存 `id(norm_patches)` 这个整数**
        （与 `_emb_cache` 存 `charset` 本身、`is charset` 比对同一个写法）：
        `norm_patches` 是调用方每次新建的临时 list，一用完就被垃圾回收，
        CPython 会把同一块内存地址迅速分配给下一个不相关的新 list——只存
        整数 id 撞上了这个坑：`rare_panel.rare_for` 连续单张调用时，每次都建一个
        长度 1 的临时列表，前一个刚被回收、下一个几乎必然撞到同一个 id，于是
        第二张图直接读到了第一张图的缓存，`rare_for` 与 `rare_for_batch` 排序
        对不上（2026-09-28 用真实 `rare_for` 循环调用复现、原地修复）。存对象
        本身相当于多持一份强引用，只要这个缓存还活着，Python 就不会把它的地址
        腾给别的对象，`is` 比较因此安全。"""
        self.last_real_prov: list[dict] = []
        """最近一次 `emb_topk_batch` 里真刻例原型赢过字体均值的字位：每个查询一个
        `{字: (instance_id, 余弦)}`，与 `last_gw_prov` 同一套用法（R2/T11，2026-09-26）。"""

    @property
    def available(self) -> bool:
        if not self.ckpt.exists():
            return False
        try:
            import torch  # noqa: F401
        except Exception:
            return False
        return True

    def _ensure(self) -> bool:
        if self._net is not None:
            return True
        if not self.available:
            return False
        import torch
        # 与模块头的环境变量同一件事的第二道保险：`torch.set_num_threads` 是运行期
        # API，随时调用都生效（不像 env var 只在线程池第一次建立时读一次），
        # 覆盖"本模块 import 前已有别的代码把 torch 线程池跑起来了"这一种情况。
        torch.set_num_threads(1)
        ck = torch.load(self.ckpt, map_location="cpu", weights_only=False)
        self._classes = list(ck["classes"])
        self._cidx = {c: i for i, c in enumerate(self._classes)}
        self._comps = list(ck.get("comps") or [])
        self._struct_classes = list(ck.get("struct_classes") or [])
        self._slot_labels = list(ck.get("slot_labels") or [])
        net = _build_net(len(self._classes), len(ck["comps"]),
                         n_struct=len(self._struct_classes), n_slot=len(self._slot_labels))
        net.load_state_dict(ck["state"])
        net.eval()
        dev = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._net = net.to(dev)
        self._dev = dev
        return True

    def topk(self, norm_patch: np.ndarray, charset, k: int = 10) -> list[tuple[str, float]]:
        """归一化 64² 二值图 → 字表内 top-k (char, prob)。字表外的字不会出现。"""
        if not self._ensure():
            return []
        import torch
        idx = [self._cidx[c] for c in charset if c in self._cidx]
        if not idx:
            return []
        with torch.no_grad():
            x = torch.tensor(norm_patch[None, None].astype(np.float32), device=self._dev)
            _, lg, _ = self._net(x)
            sub = lg[0][torch.tensor(idx, device=self._dev)]
            pr = torch.softmax(sub, 0)
            top = pr.topk(min(k, len(idx)))
        return [(self._classes[idx[int(i)]], float(p)) for p, i in zip(top.values, top.indices)]

    @property
    def comps(self) -> list[str]:
        """部件袋头的词表（训练时 `ids_guard.components` 出现 ≥3 字的部件）。未加载时空。"""
        return list(self._comps) if self._ensure() else []

    # ── 外挂结构头（Step A′）──
    def attach_probe(self, path: str | Path | None) -> bool:
        """挂 / 换外挂头；传 None 摘掉。文件不存在或主干指纹对不上 → 不挂、返回 False。"""
        self._probe = None
        self._probe_path = Path(path) if path else None
        return self._ensure_probe()

    def _ensure_probe(self) -> bool:
        if self._probe is not None:
            return True
        if not self._probe_path or not self._probe_path.exists() or not self._ensure():
            return False
        import torch
        import torch.nn as nn
        pk = torch.load(self._probe_path, map_location="cpu", weights_only=False)
        if pk.get("backbone") and pk["backbone"] != fingerprint(self.ckpt):
            _warn_emb_down(f"外挂结构头 {self._probe_path.name} 是给主干 {pk['backbone']} 训的，"
                           f"现役主干是 {fingerprint(self.ckpt)}，不挂")
            return False
        d = 256
        n_s, n_l = len(pk["struct_classes"]), len(pk["slot_labels"])
        if pk.get("arch") == "mlp":
            h = int(pk.get("hidden", 512))
            head = nn.ModuleDict({"trunk": nn.Sequential(nn.Linear(d, h), nn.ReLU(), nn.Dropout(0.2)),
                                  "struct": nn.Linear(h, n_s), "slot": nn.Linear(h, n_l)})
        else:
            head = nn.ModuleDict({"struct": nn.Linear(d, n_s), "slot": nn.Linear(d, n_l)})
        head.load_state_dict(pk["state"]); head.eval()
        self._probe = (head, float(pk.get("scale", 16.0)), list(pk["struct_classes"]), list(pk["slot_labels"]))
        return True

    def _probe_logits(self, norm_patches: list[np.ndarray]):
        import torch
        head, scale, _, _ = self._probe
        e = torch.tensor(self.embed(norm_patches) * scale)
        with torch.no_grad():
            h = head["trunk"](e) if "trunk" in head else e
            return head["struct"](h), head["slot"](h)

    @property
    def has_struct_heads(self) -> bool:
        """有没有结构头 / 槽位头：checkpoint 自带（r6 那种）或外挂探针（Step A′）。r4/r5 裸跑没有。"""
        if self._ensure() and bool(self._struct_classes) and bool(self._slot_labels):
            return True
        return self._ensure_probe()

    @property
    def slot_labels(self) -> list[str]:
        if self._ensure() and self._slot_labels:
            return list(self._slot_labels)
        return list(self._probe[3]) if self._ensure_probe() else []

    @property
    def struct_source(self) -> str:
        """'ckpt' / 'probe:<文件名>' / ''——报数与产物指纹用。"""
        if self._ensure() and self._struct_classes:
            return "ckpt"
        return f"probe:{self._probe_path.name}" if self._ensure_probe() else ""

    def struct_probs_batch(self, norm_patches: list[np.ndarray]) -> list[dict[str, float]]:
        """归一化图 → {顶层算符: 概率}（结构头 softmax）。没有结构头 → 全空字典。"""
        if not self.has_struct_heads or not norm_patches:
            return [{} for _ in norm_patches]
        import torch
        if self._struct_classes:
            with torch.no_grad():
                x = torch.tensor(np.stack(norm_patches)[:, None].astype(np.float32), device=self._dev)
                pr = torch.softmax(self._net.heads(x)["struct"], 1).cpu().numpy()
            names = self._struct_classes
        else:
            st, _ = self._probe_logits(norm_patches)
            pr = torch.softmax(st, 1).numpy(); names = self._probe[2]
        return [{c: float(p) for c, p in zip(names, row)} for row in pr]

    def slot_probs_batch(self, norm_patches: list[np.ndarray]) -> list[dict[str, float]]:
        """归一化图 → {部件@槽: 概率}（槽位头 sigmoid）。键与 `ids_struct.slot_keys_of` 同口径。"""
        if not self.has_struct_heads or not norm_patches:
            return [{} for _ in norm_patches]
        import torch
        if self._slot_labels:
            with torch.no_grad():
                x = torch.tensor(np.stack(norm_patches)[:, None].astype(np.float32), device=self._dev)
                pr = torch.sigmoid(self._net.heads(x)["slot"]).cpu().numpy()
            names = self._slot_labels
        else:
            _, sl = self._probe_logits(norm_patches)
            pr = torch.sigmoid(sl).numpy(); names = self._probe[3]
        return [{c: float(p) for c, p in zip(names, row)} for row in pr]

    def comp_probs_batch(self, norm_patches: list[np.ndarray]) -> list[dict[str, float]]:
        """归一化 64² 图 → {部件: 存在概率}（部件袋头 sigmoid）。

        2026-09-21 加，M0 零训练结构重排用（`ids_struct.struct_rerank`）。这个头
        训练时就在（`train_glyph_cnn.py` 的 `comp` 多标签 BCE），推理一直没读过它。
        口径：词表是 **一级部件**（`ids_guard.components`），不是 `ids_struct` 的停集
        词表——拿它打分时 `components_of` 必须传 `ids_guard.components`。
        """
        if not self._ensure() or not norm_patches or not self._comps:
            return [{} for _ in norm_patches]
        import torch
        with torch.no_grad():
            x = torch.tensor(np.stack(norm_patches)[:, None].astype(np.float32),
                             device=self._dev)
            _, _, cp = self._net(x)                      # (N, n_comp) logits
            pr = torch.sigmoid(cp).cpu().numpy()
        return [{c: float(p) for c, p in zip(self._comps, row)} for row in pr]

    def _forward_batch(self, norm_patches: list[np.ndarray]):
        """跑一次 `self._net(x)`，返回未转 numpy 的 `(e, lg, cp)`。

        同一批（同一个 `norm_patches` list 对象）内的后续调用直接命中 `self._fwd_cache`，
        不重新前向——`__init__` 里 `_fwd_cache` 的文档有完整背景（**必须用 `is`
        比对持有的对象本身，不能只存 `id()` 整数**）。"""
        if self._fwd_cache is not None and self._fwd_cache[0] is norm_patches:
            return self._fwd_cache[1]
        import torch
        with torch.no_grad():
            x = torch.tensor(np.stack(norm_patches)[:, None].astype(np.float32),
                             device=self._dev)
            out = self._net(x)
        self._fwd_cache = (norm_patches, out)
        return out

    def topk_batch(self, norm_patches: list[np.ndarray], charset, k: int = 10
                   ) -> list[list[tuple[str, float]]]:
        """`topk()` 的批量版：一页多个字块一次前向，见 `emb_topk_batch` 模块头
        「2026-09-10」一节——同样的道理，网络前向也是一次一批比一次一个快。
        """
        if not self._ensure():
            return [[] for _ in norm_patches]
        import torch
        idx = [self._cidx[c] for c in charset if c in self._cidx]
        if not idx or not norm_patches:
            return [[] for _ in norm_patches]
        idx_t = torch.tensor(idx, device=self._dev)
        _, lg, _ = self._forward_batch(norm_patches)
        with torch.no_grad():
            sub = lg[:, idx_t]                           # (N, len(idx))
            pr = torch.softmax(sub, 1)
            top = pr.topk(min(k, len(idx)), dim=1)
        out = []
        for values, indices in zip(top.values, top.indices):
            out.append([(self._classes[idx[int(i)]], float(p))
                        for p, i in zip(values, indices)])
        return out

    # ── embedding 检索（第三源）────────────────────────────────────
    #
    # 2026-09-05 实测（unseen 1,327，异体算对）：分类头 83.9 / 96.8 / 98.2，
    # **embedding 对字体模板做余弦检索 91.9 / 98.1 / 98.6**——同一个网络，换一种
    # 读法就高 8 个点。原因：unseen 类的分类头权重只在字体渲染上训过，是一组
    # 线性权重；而 embedding 检索比的是「查询图的 256-d 向量」与「该字 4 张字体
    # 渲染向量的均值」的夹角，归一化空间里的度量比线性头泛化得好（CCR-CLIP 一路
    # 的结论）。rare-char 21 条 top-5 100%。
    #
    # 模板向量按「checkpoint 指纹 + 字表」落盘（cache/glyph_cnn/emb_<key>.npz），
    # 4,636 字 × 4 字体首建约 1 分钟，之后毫秒级。

    def emb_index_key(self, charset) -> tuple[str, Path, dict]:
        """`_emb_index` 用来定位磁盘缓存的 `(key, npz路径, extra字典)`，抽出来给
        `guji cache build-rare-index` 复用——预建命令与产线必须算出**同一个 key**，
        不然预建的文件产线永远碰不到（2026-09-27，任务书-R-rare冷启动内存与索引预建）。
        """
        import hashlib
        from .font_candidates import font_set_fingerprint

        cs = tuple(charset)
        extra: dict = {}
        try:
            from .extra_glyphs import load_many
            specs = [sp for sp in EMB_EXTRA_SPECS if _spec_ready(sp)]
            if specs:
                extra = load_many(specs, cs)
        except Exception:
            extra = {}
        # 键里带字体集（2026-09-21）：此前不带，`FONT_ORDER` 加字体后照旧命中旧索引，
        # 见 `font_candidates.font_set_fingerprint` 模块头。
        key = hashlib.sha1((fingerprint(self.ckpt) + font_set_fingerprint() + "".join(cs)
                            + "|".join(sorted(extra))).encode("utf-8")).hexdigest()[:16]
        return key, self.ckpt.parent / f"emb_{key}.npz", extra

    def _emb_index(self, charset) -> tuple[np.ndarray, list[str]]:
        """归一化 64² 图 → 字表 embedding 索引 `(mat, names)`，按 charset 记忆化。

        ## 2026-09-10 修：逐字调用把每页拖慢了 100 倍

        `rare_for` 对页里**每一个字**都调一次 `emb_topk`→`_emb_index`，而
        charset（两档字表之一）整页、整本书都不变。改之前这里每次都先跑一遍
        `load_many`（扫 `kangxi` 源目录的全部文件、解压 `zitools` 的大 npz）
        只为了拼缓存 key，磁盘缓存命中与否是**之后**才判断的——于是「查磁盘
        缓存」本身比缓存要省的活还贵。实测 vol01 单页 179 字从预期的毫秒级
        变成 88s（`open_guji_cv.clustering.extra_glyphs.load_extra_glyphs`
        的目录 glob + zlib 解压吃掉了几乎全部时间，见 cProfile：14 次调用
        8.75s，`_read1`/`decompress` top）。

        现在按 `charset` 的对象身份（`_rare_charsets()` 返回稳定元组，同一
        进程内是同一个 tuple 对象，`is` 比较比整表 `==` 更快也更严格）在实例
        上记一次，同一整理本/字表跑一遍只算一次 key、只探一次磁盘缓存，
        换字表（不同书）会自然重算。

        ## 2026-09-27：冷启动峰值 2.4G＋（任务书-R-rare冷启动内存与索引预建）

        全新容器（磁盘缓存不在）第一次对 2.7–7 万字建这份索引，服务器上实测
        单进程 RSS 峰值 2.41 GiB、5 分钟还在涨（`总调度/服务器工单/1715`）。
        量清楚的结论（`profile_coldstart.py`，unicode-cjk-a 27,584 字 / unicode-ext-b
        42,720 字分别单独量过，见任务书 done 单）：这不是某个无界缓存一次性占住
        不放（`gc.collect()`+`malloc_trim(0)` 每 200 字打一次几乎不改变曲线，
        `torch.backends.mkldnn.enabled=False`、固定 batch 形状也都不改变曲线），
        而是**逐字前向 + 字体渲染在几万次迭代上的真实、缓慢的线性堆积**
        （量出来约 5~9 KB/字的稳态斜率，前 2000 字有一次性的更陡爬升，随后转平）；
        没有发现能把它降到目标 ≤1.2G 的进程内改法。

        能落地的两件事：①**把这份索引挪到云端一次性预建**（`guji cache
        build-rare-index`），随快照/Release 分发给服务器，服务器直接命中磁盘
        缓存、连这个函数的建索引分支都不必进——这是唯一真正让服务器峰值归零
        的办法；②本函数仍然做的三件小事——建索引期间**每 1000 字打一行进度**
        （此前 5~25 分钟零输出，看着像卡死）、落盘仍存 float32（试过 float16，
        候选会变，已弃）、`fingerprint()` 改内容指纹（见该函数文档）使预建的
        文件在服务器上真的能命中。**这三件不改变冷启动峰值**，需要真降内存
        只能走①。
        """
        for i, (cs_obj, mat, names) in enumerate(self._emb_cache):
            if cs_obj is charset:
                if i != len(self._emb_cache) - 1:            # LRU：命中的挪到末尾
                    self._emb_cache.append(self._emb_cache.pop(i))
                return mat, names

        from .synth import render_char

        cs = tuple(charset)
        key, f, extra = self.emb_index_key(cs)
        if f.exists():
            z = np.load(f, allow_pickle=False)
            mat, names = z["mat"], z["chars"].tolist()
            # 历史遗留的空缓存（2026-09-17 之前可能已落盘）不当数，重建一次。
            if mat.shape[0] == 0:
                try:
                    f.unlink()
                except OSError:
                    pass
            else:
                # 落盘是 float32（见 `_save_emb_index`）；astype 对老缓存或手工
                # 放进来的文件兜底，保证查询路一律 float32。
                mat = mat.astype(np.float32)
                self._emb_cache_put(charset, mat, names)
                return mat, names
        from ..utils.inline_index import forbid_inline_build
        forbid_inline_build("CNN embedding", len(cs), f)
        mat, names = build_emb_matrix(self._net, self._dev, cs, extra, render_char,
                                      log=lambda s: print(s, flush=True))
        # **空索引绝不落盘**（2026-09-17）。此前无条件 savez：建索引失败（模板目录
        # 缺失、渲染全挂、中途被打断）会把 (0, 256) 存进缓存，之后 `f.exists()`
        # 永远命中，`emb_topk`/`emb_topk_batch` 于是**静默返回空**——不报错、
        # 产物里也看不出，整条 embedding 路就此永久死掉，候选退化成分类头独撑
        # （分类头对 classes 外的字是硬零，北行日錄 top-10 因此只有 79.1%）。
        # 与 2026-09-15「cnn.available 悄悄变 False」同一个病根：降级路径不出声。
        if mat.shape[0] == 0:
            raise RuntimeError(
                f"embedding 索引建成 0 行（字表 {len(cs)} 字）——字体模板或渲染全部失败，"
                f"不落盘。检查 fonts/ 目录与 EMB_EXTRA_SPECS。")
        _save_emb_index(f, mat, names)
        self._emb_cache_put(charset, mat, names)
        return mat, names

    def _emb_cache_put(self, charset, mat: np.ndarray, names: list[str]) -> None:
        """写入 `_emb_cache`（LRU，见该属性文档）：满了先从头淘汰最久未用的一档。"""
        self._emb_cache.append((charset, mat, names))
        while len(self._emb_cache) > self._EMB_CACHE_MAX:
            self._emb_cache.pop(0)

    def embed(self, norm_patches: list[np.ndarray]) -> np.ndarray:
        """归一化 64² 图 → 单位化 embedding (N, 256)。不可用时 (0, 256)。
        给 IDS 兜底检索用（`rare_panel.ids_fallback`）：字集是查询临时定的，不走
        `_emb_index` 的按字表落盘缓存。"""
        if not self._ensure() or not norm_patches:
            return np.zeros((0, 256), np.float32)
        import torch
        with torch.no_grad():
            x = torch.tensor(np.stack(norm_patches)[:, None].astype(np.float32),
                             device=self._dev)
            e, _, _ = self._net(x)
            return (e / (e.norm(dim=1, keepdim=True) + 1e-9)).cpu().numpy()

    def emb_topk(self, norm_patch: np.ndarray, charset, k: int = 10) -> list[tuple[str, float]]:
        """归一化 64² 二值图 → 与字体模板 embedding 的余弦 top-k。"""
        if not self._ensure():
            _warn_emb_down("checkpoint 不可用")
            return []
        import torch
        mat, names = self._emb_index(charset)
        if mat.shape[0] == 0:
            _warn_emb_down(f"索引 0 行（字表 {len(tuple(charset))} 字）")
            return []
        with torch.no_grad():
            x = torch.tensor(norm_patch[None, None].astype(np.float32), device=self._dev)
            e, _, _ = self._net(x)
            q = e[0]
            q = (q / (q.norm() + 1e-9)).cpu().numpy()
        sims = mat @ q
        order = np.argsort(-sims)[:k]
        return [(names[int(i)], float(sims[int(i)])) for i in order]

    def emb_topk_batch(self, norm_patches: list[np.ndarray], charset, k: int = 10,
                       real_exclude_ids: frozenset = frozenset(),
                       real_proto: tuple[bool, tuple[str, ...]] | None = None,
                       gw_enabled: bool | None = None,
                       ) -> list[list[tuple[str, float]]]:
        """`emb_topk()` 的批量版：网络前向与模板矩阵检索都改一次一批。

        `real_exclude_ids`：真刻例多原型档（R2/T11）评测时的留一法摘除集合，
        产线（非评测）传空集。见 `_real_index` 文档。

        `real_proto`（5-b 开关转正，2026-09-26）：`(enabled, specs)`，按书配置调用时传
        `cnn_candidates.book_real_proto(ctx.book.font)` 的结果，覆盖模块级
        `REAL_PROTO_ENABLED`/`REAL_PROTO_SPECS`。`None`（缺省）时走模块级——评测脚本
        （`eval_oov.py` 等直接改 `_cc.REAL_PROTO_ENABLED`）与此前调用方式逐位相同。

        `gw_enabled`（T4 变体形转正，2026-09-27）：按书配置调用时传
        `cnn_candidates.book_gw_variant(ctx.book.font)`，覆盖模块级 `GW_ENABLED`。
        `None`（缺省）时走模块级——与加这个形参之前逐位相同。

        ## 2026-09-10 生僻字候选提速第二轮：批处理网络前向 + 矩阵-矩阵乘法

        与 `font_candidates.candidates_batch` 同一个道理：`rare_for` 原先
        对页里每个字都单独调一次 `emb_topk`——CNN 前向单独跑一次、跟模板矩阵
        的余弦检索也单独做一次矩阵-向量乘法（GEMV）。这一页所有字块一起
        过网络（一次前向吃满 batch，torch 本身就支持）、检索也改成矩阵-矩阵
        乘法（GEMM）——两处都是"同一份模板/同一张网络，换一批输入"，批处理
        没有精度代价，只是把 IO/调度开销摊到一批里。
        """
        if not self._ensure():
            _warn_emb_down("checkpoint 不可用")
            return [[] for _ in norm_patches]
        mat, names = self._emb_index(charset)
        if mat.shape[0] == 0 and norm_patches:
            _warn_emb_down(f"索引 0 行（字表 {len(tuple(charset))} 字）")
        if mat.shape[0] == 0 or not norm_patches:
            return [[] for _ in norm_patches]
        e, _, _ = self._forward_batch(norm_patches)
        return self._emb_topk_from_query(e, mat, names, charset, k,
                                         real_exclude_ids, real_proto, gw_enabled)

    def emb_topk_batch_subset(self, norm_patches_full: list[np.ndarray], idx: list[int],
                              charset, k: int = 10,
                              real_exclude_ids: frozenset = frozenset(),
                              real_proto: tuple[bool, tuple[str, ...]] | None = None,
                              gw_enabled: bool | None = None,
                              ) -> list[list[tuple[str, float]]]:
        """升级档子集复用（`rare_panel.rare_for_batch` 的 escalate）：`idx` 是
        `norm_patches_full`（与之前那次 `topk_batch`/`emb_topk_batch` 传的**同一个**
        list 对象）里要重算的字位下标，换一档字表（`charset`）重查。

        直接切上一次前向缓存里的 embedding（`self._fwd_cache`），不对这个子集重新跑
        `self._net(x)`——同一批图先前已经在基集字表那次调用里前向过一遍，子集不该
        再算第三遍（2026-09-28，任务书-R-rare前向去重与测试隔离，K 引擎卡手 #54
        cross 单：warm-cache 实测 `topk_batch` 1.95s + `emb_topk_batch` 1.93s，
        几乎是同一件事算了两遍，加上升级档子集就是第三遍）。

        缓存没命中（`norm_patches_full` 不是上一次前向缓存的那个 list 对象，比如
        调用方没有先调 `topk_batch`/`emb_topk_batch`）时退回对子集单独前向——
        正确性不受影响，只是拿不到这次的省时；这是防御性兜底，不是常态路径。
        """
        if not self._ensure():
            _warn_emb_down("checkpoint 不可用")
            return [[] for _ in idx]
        if not idx:
            return []
        mat, names = self._emb_index(charset)
        if mat.shape[0] == 0:
            _warn_emb_down(f"索引 0 行（字表 {len(tuple(charset))} 字）")
            return [[] for _ in idx]
        import torch
        if self._fwd_cache is not None and self._fwd_cache[0] is norm_patches_full:
            e_full, _, _ = self._fwd_cache[1]
            e_sub = e_full[torch.tensor(list(idx), device=self._dev)]
        else:
            sub_patches = [norm_patches_full[i] for i in idx]
            e_sub, _, _ = self._forward_batch(sub_patches)
        return self._emb_topk_from_query(e_sub, mat, names, charset, k,
                                         real_exclude_ids, real_proto, gw_enabled)

    def _emb_topk_from_query(self, e, mat: np.ndarray, names: list[str], charset, k: int,
                             real_exclude_ids: frozenset,
                             real_proto: tuple[bool, tuple[str, ...]] | None,
                             gw_enabled: bool | None,
                             ) -> list[list[tuple[str, float]]]:
        """`emb_topk_batch`/`emb_topk_batch_subset` 共用的检索尾段：给定已经算好的
        查询 embedding `e`（torch tensor，未归一化，(N, 256)）与目标字表的模板矩阵
        `(mat, names)`，做归一化＋矩阵检索＋gw/real 融合，返回逐图 top-k。网络前向
        由调用方做完，这里不碰 `self._net`——`emb_topk_batch` 原有的这段逻辑一字未改，
        只是从「拿到 norm_patches 就现跑前向」改成「拿已经算好的 e」。"""
        import torch
        with torch.no_grad():
            Q = e / (e.norm(dim=1, keepdim=True) + 1e-9)
            Q = Q.cpu().numpy()
        sims = mat @ Q.T                                   # (rows, N)
        self.last_gw_prov = [{} for _ in range(Q.shape[0])]
        gw_on = GW_ENABLED if gw_enabled is None else gw_enabled
        gw = self._gw_index(charset, names) if gw_on else None
        if gw is not None:
            G, rows_idx, gnames, gsrc = gw
            sg = G @ Q.T                                   # (n_gw, N)
            for j in range(sims.shape[1]):
                best = np.full(sims.shape[0], -2.0, np.float32)
                np.maximum.at(best, rows_idx, sg[:, j])
                win = best > sims[:, j]
                if win.any():
                    # 记来源：该字位上赢了字体均值的那张 gw 模板
                    for r in np.where(win)[0]:
                        cand = np.where(rows_idx == r)[0]
                        b = cand[int(np.argmax(sg[cand, j]))]
                        self.last_gw_prov[j][names[int(r)]] = (str(gnames[b]), str(gsrc[b]), float(sg[b, j]))
                    sims[:, j] = np.maximum(sims[:, j], best)
        self.last_real_prov = [{} for _ in range(Q.shape[0])]
        if real_proto is not None:
            r_enabled, r_specs = real_proto
        else:
            r_enabled, r_specs = REAL_PROTO_ENABLED, REAL_PROTO_SPECS
        real = self._real_index(charset, names, real_exclude_ids, specs=r_specs) if r_enabled else None
        if real is not None:
            R, r_rows_idx, r_iids = real
            sr = R @ Q.T                                   # (n_real, N)
            for j in range(sims.shape[1]):
                best = np.full(sims.shape[0], -2.0, np.float32)
                np.maximum.at(best, r_rows_idx, sr[:, j])
                win = best > sims[:, j]
                if win.any():
                    for r in np.where(win)[0]:
                        cand = np.where(r_rows_idx == r)[0]
                        b = cand[int(np.argmax(sr[cand, j]))]
                        self.last_real_prov[j][names[int(r)]] = (str(r_iids[b]), float(sr[b, j]))
                    sims[:, j] = np.maximum(sims[:, j], best)
        out = []
        for j in range(sims.shape[1]):
            order = np.argsort(-sims[:, j])[:k]
            out.append([(names[int(i)], float(sims[i, j])) for i in order])
        return out

    def _gw_index(self, charset, names: list[str]):
        """GlyphWiki 变体形模板（`GW_CATALOG`）→ 限定到当前字表：
        `(G, rows_idx, gnames, gsrc)`，`rows_idx[i]` 是第 i 张模板的关联字在字体索引 `names` 里的行号。
        整目录的 embedding 按 checkpoint + 目录指纹落盘一次（`<ckpt 目录>/gw_<key>.npz`），
        关联字不在字体索引里的模板不参与（v1：只给已有字体行的字加模板）。目录缺席 → None。"""
        if self._gw_cs is not None and self._gw_cs[0] is charset:
            return self._gw_cs[1]
        if not GW_CATALOG.exists():
            return None
        import torch
        if self._gw is None:
            # `_gw_index` 只在调用方已经判定 gw 打开时才跑（见 `emb_topk_batch`），
            # 这里显式传 `enabled=True`——不看模块级 `GW_ENABLED`，否则「书级开、模块级关」
            # 这个此前不存在的组合会把落盘缓存 key 算成空指纹（内容变了也不换文件名）。
            key = hashlib.sha1((fingerprint(self.ckpt) + gw_catalog_fingerprint(enabled=True)).encode()).hexdigest()[:16]
            f = self.ckpt.parent / f"gw_{key}.npz"
            z = np.load(GW_CATALOG, allow_pickle=False)
            gnames, grel, gsrc = z["names"], z["related"], z["source"]
            if f.exists():
                G = np.load(f, allow_pickle=False)["emb"]
            else:
                imgs = z["imgs"]
                vecs = []
                with torch.no_grad():
                    for i in range(0, len(imgs), 256):
                        x = torch.tensor(imgs[i:i + 256][:, None].astype(np.float32), device=self._dev)
                        e, _, _ = self._net(x)
                        vecs.append((e / (e.norm(dim=1, keepdim=True) + 1e-9)).cpu().numpy())
                G = np.concatenate(vecs).astype(np.float32) if vecs else np.zeros((0, 256), np.float32)
                f.parent.mkdir(parents=True, exist_ok=True)
                tmp = f.with_name(f.name + ".tmp.npz")
                np.savez(tmp, emb=G); os.replace(tmp, f)
            self._gw = (G, grel, gnames, gsrc)
        G, grel, gnames, gsrc = self._gw
        pos = {c: i for i, c in enumerate(names)}
        keep = np.array([i for i, c in enumerate(grel) if c in pos], dtype=np.int64)
        if len(keep) == 0:
            res = None
        else:
            res = (G[keep], np.array([pos[grel[i]] for i in keep], dtype=np.int64), gnames[keep], gsrc[keep])
        self._gw_cs = (charset, res)
        return res

    _REAL_CACHE_MAX = 2
    """基集 + 升级档两档（见 `_real_slots`）。"""

    @property
    def _real_cs(self) -> tuple[tuple, tuple | None] | None:
        """最近用过的一档 `(key, 结果)`；赋值 = 存一档（LRU，满了淘汰最久未用），赋 None = 清空。"""
        return self._real_slots[-1] if self._real_slots else None

    @_real_cs.setter
    def _real_cs(self, v) -> None:
        if v is None:
            self._real_slots = []
            return
        self._real_slots = [kv for kv in self._real_slots if kv[0] != v[0]] + [v]
        del self._real_slots[:-self._REAL_CACHE_MAX]

    def _real_index(self, charset, names: list[str], exclude_ids: frozenset = frozenset(),
                    specs: tuple | None = None):
        """真刻例多原型档（R2 / T11）限定到当前字表：`(R, rows_idx, iids)`，
        `rows_idx[i]` 是第 i 个原型的字在字体索引 `names` 里的行号，与 `_gw_index`
        同一套接线（`emb_topk_batch` 里按 `rows_idx` 做 max 融合）。

        `exclude_ids`：评测时的留一法摘除集合（物理格粒度）——按
        `match._cell_parts` 同册同页同列、格号相差 <=2 一并摘，不只摘字面同一个
        id（教训见 `GlyphMatcher._same_cell_rows`：只摘一个 id 摘不干净，v1/v2/
        机器准入同一格有好几种 id）。产线（非评测）传空集。

        `specs`：按书配置调用时传显式 store 列表（见 `book_real_proto`），覆盖模块级
        `REAL_PROTO_SPECS`；`None`（缺省）时走模块级——评测脚本与此前调用方式逐位
        相同。**进缓存 key**：换书换 specs 不会命中上一本书留下的内存缓存。

        **不落盘**：真刻例池比 GlyphWiki 小两个量级（千级 vs 万级），CPU 全量
        前向本身秒级，落盘缓存反而引入「换书但 key 没变」的新鲜度坑（同
        `load_real_exemplars` 的理由）。按 `(charset, exclude_ids, specs)` 记一次内存缓存。
        """
        sp = REAL_PROTO_SPECS if specs is None else specs
        key = (charset, exclude_ids, sp)
        for i, (k, res) in enumerate(self._real_slots):
            if k == key:
                self._real_slots.append(self._real_slots.pop(i))   # LRU：命中的挪到末尾
                return res
        if not sp or not self._ensure():
            self._real_cs = (key, None)
            return None
        pool = load_real_exemplars(sp, charset)
        if not pool:
            self._real_cs = (key, None)
            return None
        from .match import _cell_parts

        def _excluded(iid: str) -> bool:
            if not exclude_ids:
                return False
            if iid in exclude_ids:
                return True
            q = _cell_parts(iid)
            if q is None:
                return False
            for e in exclude_ids:
                ek = _cell_parts(e)
                if ek is None or ek[:3] != q[:3]:
                    continue
                diff = abs(ek[3] - q[3])
                # 两边都是重键后的精确格号坐标（非 v1:）才要求 =0；
                # 有一边是未确认的 v1: idx 换算格号，保留 ±2（字形库 12 §六）
                if ek[4] and q[4]:
                    if diff == 0:
                        return True
                elif diff <= 2:
                    return True
            return False

        import torch
        pos = {c: i for i, c in enumerate(names)}
        vecs, rows_idx, iids = [], [], []
        with torch.no_grad():
            for ch, items in pool.items():
                if ch not in pos:
                    continue
                items = [(iid, img) for iid, img in items if not _excluded(iid)]
                if not items:
                    continue
                x = torch.tensor(np.stack([im for _, im in items])[:, None].astype(np.float32),
                                 device=self._dev)
                e, _, _ = self._net(x)
                e = (e / (e.norm(dim=1, keepdim=True) + 1e-9)).cpu().numpy()
                protos, proto_ids = _farthest_point_protos(e, [iid for iid, _ in items], REAL_PROTO_K)
                for v, iid in zip(protos, proto_ids):
                    vecs.append(v); rows_idx.append(pos[ch]); iids.append(iid)
        res = None
        if vecs:
            res = (np.stack(vecs).astype(np.float32), np.array(rows_idx, dtype=np.int64), iids)
        self._real_cs = (key, res)
        return res


EMB_EXTRA_SPECS: tuple[str, ...] = ()
"""embedding 模板的外部真刻本图源（`extra_glyphs.py` 的 spec）。

**2026-09-08 起清空**——改用 `fonts/kangxi/` 的康熙字典体（见 `font_candidates.FONT_ORDER`）。
用户裁定：效果差不多就直接用字体。实测依据（`external_glyph_sources_experiment.md` §5.11）：

| 模板 | unseen 严格 top-1 | 体积 | 文件数 |
|---|---|---|---|
| 4 套字体（基线）| 95.9% | — | — |
| **+ 康熙字典体 OTF** | **96.4%** | 54.9 MB | 1 |
| + 自切康熙扫描图 | 96.0% | 180 MB（原始扫描另 1.4 GB）| 44,634 |

字体赢在**覆盖率 100% vs 76%**，不是赢在还原度：逐字比「谁更像我们书里的真刻例」，
扫描图仍赢 36% 的字；形态上扫描图的墨占比 0.1948 贴近真刻例 0.1972（字体 0.1690 偏细 14%），
但它的连通块数 4.60 远高于真刻例 3.36（断笔/噪点），噪声抵消了真实性优势。

**切图资产保留**在 `D:/data/glyph-sources/kangxi/crops`（32,898 张，交叉验证过，
独立源不一致率 0.312%），随时可以填回本元组重新启用；若日后给扫描图做了去噪
（把连通块压到 3.4 左右），值得再比一次。
"""


def template_set_fingerprint(specs: tuple[str, ...] = EMB_EXTRA_SPECS) -> str:
    """外部模板集指纹：每条 spec 的目录/白名单 stamp 拼起来。

    只对**就绪**的 spec 取 stamp（`_spec_ready`），源目录缺失时该 spec 不参与
    ——与 `_emb_index` 静默退回纯字体模板同一条口径，换机器（有/无这批数据）
    不会互相污染对方的指纹。stamp 复用 `extra_glyphs.load_extra_glyphs` 那把
    尺子（zitools 用 manifest.tsv 大小，kangxi 用白名单文件行数/切图张数）。
    """
    from .extra_glyphs import parse_spec

    parts = []
    for spec in specs:
        if not _spec_ready(spec):
            continue
        kind, d, styles = parse_spec(spec)
        if kind == "kangxi" and isinstance(styles, str):
            stamp = len(Path(styles).read_text(encoding="utf-8").split())
        elif kind == "zitools":
            man = d / "manifest.tsv"
            stamp = man.stat().st_size if man.exists() else 0
        else:
            stamp = len(list(d.glob("KX*.png")))
        parts.append(f"{spec}:{stamp}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def full_fingerprint(ckpt: str | Path = DEFAULT_CKPT,
                      specs: tuple[str, ...] = EMB_EXTRA_SPECS,
                      real_proto: tuple[bool, tuple[str, ...]] | None = None,
                      gw_enabled: bool | None = None) -> str:
    """生僻字候选栈的完整指纹：checkpoint + 外部模板集 + **模板字体集**（2026-09-21 补，
    此前换 `fonts/` 里的档产物不过期）。进 Step 参数才能让 `rare_candidates` 产物在
    换模型/换模板/换字体时正确过期（见 `steps/rare_candidates.py`）。

    `real_proto`（5-b 开关转正，2026-09-26）：`(enabled, specs)`，按书配置调用时传
    `book_real_proto(ctx.book.font)` 的结果；`None`（缺省）时走模块级
    `REAL_PROTO_ENABLED`/`REAL_PROTO_SPECS`——不传参的旧调用方式与此前逐位相同，
    关着时（不管是模块级还是书级）这段一律不进指纹（`real_proto_fingerprint`
    短路返回空串）。

    `gw_enabled`（T4 变体形转正，2026-09-27）：按书配置调用时传
    `book_gw_variant(ctx.book.font)`；`None`（缺省）时走模块级 `GW_ENABLED`。

    ⚠️ **这里补了一个此前就该有的短路**：改之前 `gw_catalog_fingerprint()` 不看
    `GW_ENABLED`/`gw_enabled`，只要 `cache/glyphwiki/catalog_64.npz` 存在就把它的
    stamp 并进来——`_gw_index` 用不用是另一回事，关着的书只要这份目录内容一变
    （比如别的道重新生成了目录），`rare_candidates` 也会被判过期，`params_hash`
    与实际用没用 gw 对不上，跟 `real_proto` 那次的坑同源。现在关着（不管模块级
    还是书级）一律不进指纹，与加这个形参之前、目录缺席时逐位相同。"""
    from .font_candidates import font_set_fingerprint
    # GlyphWiki 变体形目录（第六档模板）并进「模板集」那一段，指纹保持三段（测试钉着这个形状）；
    # 目录缺席或关着时该段与从前逐位相同。
    tmpl = template_set_fingerprint(specs)
    gw = gw_catalog_fingerprint(enabled=gw_enabled)
    if gw:
        tmpl = hashlib.sha1(f"{tmpl}|gw={gw}".encode()).hexdigest()[:16]
    if real_proto is not None:
        en, sp = real_proto
        real = real_proto_fingerprint(sp, enabled=en)
    else:
        real = real_proto_fingerprint()
    if real:
        tmpl = hashlib.sha1(f"{tmpl}|real={real}".encode()).hexdigest()[:16]
    return f"{fingerprint(ckpt)}:{tmpl}:{font_set_fingerprint()}"


def _spec_ready(spec: str) -> bool:
    """源目录/白名单在不在。不在就跳过这条 spec。"""
    try:
        from .extra_glyphs import parse_spec
        kind, d, styles = parse_spec(spec)
        if not Path(d).exists():
            return False
        if kind == "kangxi" and isinstance(styles, str):
            return Path(styles).exists()
        return True
    except Exception:
        return False


_EMB_DOWN_SEEN: set[str] = set()


def _warn_emb_down(why: str) -> None:
    """embedding 这一路失效时**出声**（2026-09-17）。

    这一路是候选栈里最强的单源（unseen top-1 97.4%），它一死候选就只剩
    分类头独撑，而分类头对 `classes` 外的字是硬零——北行日錄 54 页
    181,680 条候选全部标 `cnn`、一条 `emb` 都没有，top-10 因此只有 79.1%
    （同字表下修好应为 95.6%）。此前这条路静默 `return []`，产物里也看不出，
    于是藏了一整轮。同一进程里同一个原因只喊一次，不刷屏。
    """
    if why in _EMB_DOWN_SEEN:
        return
    _EMB_DOWN_SEEN.add(why)
    import warnings
    warnings.warn(f"CNN embedding 候选路失效（{why}）——候选将退化为分类头独撑，"
                  f"classes 外的字会整个查不到。", RuntimeWarning, stacklevel=3)


HOG_WEIGHT = 0.0
CNN_WEIGHT = 1.0
EMB_WEIGHT = 4.0
"""三源 RRF 权重（HOG 字体检索 / CNN 分类头 / CNN embedding 检索）。

**2026-09-07 重标为 0 / 1 / 4**（外部真刻本模板上线，`external_glyph_sources_experiment.md` §5.3）。
embedding 模板从「4 套字体渲染」换成「字体 + 康熙字头 + 字统网印楷」后，HOG 那一路
（字体模板检索）被 embedding 完全覆盖，归零反而更好——unseen 1,327 实测三源融合
top-1 **95.0 → 97.2**（严格 93.5 → 95.6），rare-char top-1 81.0 → 90.5。
HOG 保留在代码里（权重 0 即不参与 RRF），换回字体模板时改回 0.5。

以下是 2026-09-05 的旧标定，字体模板时代的依据，留档：


2026-09-05 扫描（run-2 checkpoint；unseen 1,327 / rare 21，异体算对）：

| hog / cls / emb | unseen top1 / 5 / 10 | rare top1 / 5 / 10 |
|---|---|---|
| 1 / 2 / 2 | 91.9 / 98.2 / 98.8 | 66.7 / 90.5 / 100 |
| 1 / 2 / 3 | 92.0 / 98.4 / 98.8 | 66.7 / 95.2 / 100 |
| 0 / 1 / 2 | 91.6 / 98.0 / 98.6 | 76.2 / 100 / 100 |
| 0 / 1 / 1 | 90.9 / 97.7 / 98.5 | 71.4 / 100 / 100 |
| 1 / 1 / 3 | 92.3 / 98.3 / 98.9 | 66.7 / 90.5 / 100 |
| **0.5 / 1 / 3** | **92.8 / 98.3 / 98.9** | 71.4 / **100 / 100** |

两条规律：**embedding 检索权重越高越好**（它是最强单源，91.9%）；**HOG 权重要压
低**——它在最难那撮（rare）只有 47.6% top-1，模拟磨损下再掉 14 个点，权重 1 时
把 rare top-5 拖到 90.5%。取 0.5 / 1 / 3：unseen top-1 最高，rare top-5/10 100%。
"""


def rrf(*orders: list[str], k: int = 10, c: int = RRF_K,
        weights: tuple[float, ...] | None = None) -> list[str]:
    """倒数排名融合。只看名次，不看分数——各源量纲不同，分数相加没有意义。

    `weights` 与 `orders` 一一对应；缺省全 1。生产权重见
    `HOG_WEIGHT`/`CNN_WEIGHT`/`EMB_WEIGHT`（现行 0 / 1 / 4）。
    """
    score: dict[str, float] = {}
    ws = weights or (1.0,) * len(orders)
    for order, w in zip(orders, ws):
        if w <= 0:
            continue
        for r, ch in enumerate(order):
            score[ch] = score.get(ch, 0.0) + w / (c + r)
    return [ch for ch, _ in sorted(score.items(), key=lambda kv: -kv[1])[:k]]


#: 软门控看 embedding 前几名来判「这个字位像不像类外字」。
#: 3 是实测最优（北行 383 条：top1=82.8%；取 1 太硬、类内掉 5.7 点，取 5 太钝）。
CLS_GATE_TOPM = 3


def shared_classes() -> set[str]:
    """现役 checkpoint 的类表（分类头的输出空间）。checkpoint 缺席时返回空集。

    空集会让 `cls_gate_weight` 恒给 `lo`——分类头本来也没输出，不影响结果。
    """
    try:
        c = shared()
        if not c._ensure():
            return set()
        return set(c._classes)
    except Exception:
        return set()


def cls_gate_weight(emb_order: list[str], classes: set[str],
                    hi: float = CNN_WEIGHT, lo: float = 0.0,
                    topm: int = CLS_GATE_TOPM) -> float:
    """分类头在这个字位该占多少权重（2026-09-17 加）。

    ## 为什么需要它

    分类头的输出空间**锁死在训练时的 4,654 类**，类外字它根本给不出——
    `cache/oov_bench` 314 条类外真刻例实测，`cls` 的 top-1 / top-5 / top-10
    **全是 0.0%**。可它在 RRF 里照样占着 `CNN_WEIGHT=1.0`，拿一串错字去压
    embedding 的正确答案：同一个集上 emb 单源 top-1 **67.8%**，
    两路 RRF 反而只有 **26.4%**——分类头白白拖掉 41 个点。

    ## 判据

    没法预先知道一个字位是不是类外字，但 **embedding 的前几名给了很强的暗示**：
    它不受类表限制，如果它的前 `topm` 名大多落在 `classes` 外，
    这个字位多半就是类外字，分类头的意见不该算数。按落在类内的比例插值：

        w = lo + (hi - lo) · |{前 topm 名 ∩ classes}| / topm

    ## 实测（北行 383 条用户裁决，类内 314 / 类外 69）

    | 方案 | 全体 top-1 | 类内 top-1 | 类外 top-1 |
    |---|---|---|---|
    | 现行（恒 w=1.0）| 75.7% | 89.8% | 11.6% |
    | 固定降权 w=0.1 | 82.0% | 87.9% | 55.1% |
    | 硬门控（topm=1）| 82.2% | **84.1%** | 73.9% |
    | **软门控 topm=3** | **82.8%** | **89.5%** | 52.2% |

    topm=3 两头都不牺牲：类内只掉 0.3 点，全体最高。硬门控类外最好看，
    但 emb top-1 一猜错就把分类头整路关掉，类内要赔 5.7 点，不值。
    top-10 在所有方案下都是 94.8%，不受影响——这是**排序**问题，不是召回问题。
    """
    head = list(emb_order or [])[:topm]
    if not head:
        return hi
    frac = sum(1 for ch in head if ch in classes) / len(head)
    return lo + (hi - lo) * frac


@lru_cache(maxsize=1)
def shared(ckpt: str = str(DEFAULT_CKPT)) -> CnnCandidates:
    return CnnCandidates(ckpt)
