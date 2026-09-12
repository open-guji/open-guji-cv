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
from functools import lru_cache
from pathlib import Path

import numpy as np

def _resolve_default_ckpt() -> Path:
    """checkpoint 不可重建（重训要 GPU + 数小时），2026-09-09 起进 Git，
    落在 `models/glyph_cnn_r4/`（`/cache/` 整体 gitignore，云端 clone 拿不到）。
    本机若还有旧路径 `cache/glyph_cnn_r4/best.pt`，优先用它——不强迫已有工作区搬文件，
    也不改变本机现役 checkpoint 的 mtime（会让 fingerprint 变、下游产物被判 stale）。
    """
    legacy = Path("cache/glyph_cnn_r4/best.pt")
    if legacy.exists():
        return legacy
    return Path("models/glyph_cnn_r4/best.pt")


DEFAULT_CKPT = _resolve_default_ckpt()
"""现役 checkpoint。2026-09-07 从 `cache/glyph_cnn/best.pt`（run-5，纯字体补类）切到
`glyph_cnn_r4`（训练时每类另加康熙字头 + 字统网真刻本图，`external_glyph_sources_experiment.md` §5.4）：
分类头 unseen top-1 94.3 → 96.5，seen_test 99.5 → 99.8 无回退，异体组内定形差距拉开 12.6 倍。
**换 checkpoint 会让下游产物过期**（路径 + mtime 进 `fingerprint()`），相关页要重跑。
旧 checkpoint 保留在原路径可随时切回；切回时 `HOG_WEIGHT`/`EMB_WEIGHT`/`FORM_EMB_GAP` 都要还原。"""
RRF_K = 60


def fingerprint(path: str | Path = DEFAULT_CKPT) -> str:
    p = Path(path)
    if not p.exists():
        return "nockpt"
    st = p.stat()
    return hashlib.sha1(f"{p}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]


def _build_net(n_cls: int, n_comp: int, d: int = 256):
    """与 train_glyph_cnn.Net 同构；结构改了这里要同步（用 checkpoint 里的维度校验）。"""
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

        def forward(self, x):
            x = self.l4(self.l3(self.l2(self.l1(self.stem(x)))))
            e = F.normalize(self.emb(x.flatten(1)), dim=1) * 16.0
            return e, self.cls(e), self.comp(e)

    return Net()


class CnnCandidates:
    """懒加载；没有 checkpoint 或没装 torch 时 `available` 为 False，调用方跳过。"""

    def __init__(self, ckpt: str | Path = DEFAULT_CKPT, device: str | None = None):
        self.ckpt = Path(ckpt)
        self.device = device
        self._net = None
        self._classes: list[str] = []
        self._cidx: dict[str, int] = {}
        self._emb_cache: tuple[tuple, np.ndarray, list[str]] | None = None
        """`_emb_index` 的内存缓存：(charset, mat, names)。见该方法模块头
        「2026-09-10 修」——没有它，逐字调用会把 `load_many` 的目录扫描/npz
        解压重复付一遍，而不是只算一次 key 就命中磁盘缓存。"""

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
        ck = torch.load(self.ckpt, map_location="cpu", weights_only=False)
        self._classes = list(ck["classes"])
        self._cidx = {c: i for i, c in enumerate(self._classes)}
        net = _build_net(len(self._classes), len(ck["comps"]))
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
        with torch.no_grad():
            x = torch.tensor(np.stack(norm_patches)[:, None].astype(np.float32),
                             device=self._dev)
            _, lg, _ = self._net(x)                     # (N, n_cls)
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
        """
        if self._emb_cache is not None and self._emb_cache[0] is charset:
            return self._emb_cache[1], self._emb_cache[2]

        import hashlib
        import torch
        from .font_candidates import _font_files
        from .synth import render_char

        cs = tuple(charset)
        # 外部真刻本模板（康熙字头 / 字统网）：每字的模板 = mean(字体渲染 ∪ 真刻本图)。
        # 2026-09-07 上线，实测 unseen emb top-1 95.9 → 97.4（严格 94.5 → 95.6），
        # 异体子集 83.2 → 91.6。源目录缺失时静默退回纯字体（实验数据不在仓里）。
        extra: dict = {}
        try:
            from .extra_glyphs import load_many
            specs = [sp for sp in EMB_EXTRA_SPECS if _spec_ready(sp)]
            if specs:
                extra = load_many(specs, cs)
        except Exception:
            extra = {}
        key = hashlib.sha1((fingerprint(self.ckpt) + "".join(cs)
                            + "|".join(sorted(extra)) ).encode("utf-8")).hexdigest()[:16]
        f = self.ckpt.parent / f"emb_{key}.npz"
        if f.exists():
            z = np.load(f, allow_pickle=False)
            mat, names = z["mat"], z["chars"].tolist()
            self._emb_cache = (charset, mat, names)
            return mat, names
        fonts = _font_files()
        vecs, names = [], []
        with torch.no_grad():
            for ch in cs:
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
                    continue
                x = torch.tensor(np.stack(ims)[:, None].astype(np.float32), device=self._dev)
                e, _, _ = self._net(x)
                v = e.mean(0)
                vecs.append((v / (v.norm() + 1e-9)).cpu().numpy())
                names.append(ch)
        mat = np.stack(vecs).astype(np.float32) if vecs else np.zeros((0, 256), np.float32)
        f.parent.mkdir(parents=True, exist_ok=True)
        np.savez(f, mat=mat, chars=np.array(names))
        self._emb_cache = (charset, mat, names)
        return mat, names

    def emb_topk(self, norm_patch: np.ndarray, charset, k: int = 10) -> list[tuple[str, float]]:
        """归一化 64² 二值图 → 与字体模板 embedding 的余弦 top-k。"""
        if not self._ensure():
            return []
        import torch
        mat, names = self._emb_index(charset)
        if mat.shape[0] == 0:
            return []
        with torch.no_grad():
            x = torch.tensor(norm_patch[None, None].astype(np.float32), device=self._dev)
            e, _, _ = self._net(x)
            q = e[0]
            q = (q / (q.norm() + 1e-9)).cpu().numpy()
        sims = mat @ q
        order = np.argsort(-sims)[:k]
        return [(names[int(i)], float(sims[int(i)])) for i in order]

    def emb_topk_batch(self, norm_patches: list[np.ndarray], charset, k: int = 10
                       ) -> list[list[tuple[str, float]]]:
        """`emb_topk()` 的批量版：网络前向与模板矩阵检索都改一次一批。

        ## 2026-09-10 生僻字候选提速第二轮：批处理网络前向 + 矩阵-矩阵乘法

        与 `font_candidates.candidates_batch` 同一个道理：`rare_for` 原先
        对页里每个字都单独调一次 `emb_topk`——CNN 前向单独跑一次、跟模板矩阵
        的余弦检索也单独做一次矩阵-向量乘法（GEMV）。这一页所有字块一起
        过网络（一次前向吃满 batch，torch 本身就支持）、检索也改成矩阵-矩阵
        乘法（GEMM）——两处都是"同一份模板/同一张网络，换一批输入"，批处理
        没有精度代价，只是把 IO/调度开销摊到一批里。
        """
        if not self._ensure():
            return [[] for _ in norm_patches]
        import torch
        mat, names = self._emb_index(charset)
        if mat.shape[0] == 0 or not norm_patches:
            return [[] for _ in norm_patches]
        with torch.no_grad():
            x = torch.tensor(np.stack(norm_patches)[:, None].astype(np.float32),
                             device=self._dev)
            e, _, _ = self._net(x)                        # (N, 256)
            Q = e / (e.norm(dim=1, keepdim=True) + 1e-9)
            Q = Q.cpu().numpy()
        sims = mat @ Q.T                                   # (rows, N)
        out = []
        for j in range(sims.shape[1]):
            order = np.argsort(-sims[:, j])[:k]
            out.append([(names[int(i)], float(sims[i, j])) for i in order])
        return out


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
                      specs: tuple[str, ...] = EMB_EXTRA_SPECS) -> str:
    """生僻字候选栈的完整指纹：checkpoint + 外部模板集。进 Step 参数才能让
    `rare_candidates` 产物在换模型/换模板时正确过期（见 `steps/rare_candidates.py`）。"""
    return f"{fingerprint(ckpt)}:{template_set_fingerprint(specs)}"


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

    `weights` 与 `orders` 一一对应；缺省全 1。生产里 HOG=1、CNN=CNN_WEIGHT。
    """
    score: dict[str, float] = {}
    ws = weights or (1.0,) * len(orders)
    for order, w in zip(orders, ws):
        for r, ch in enumerate(order):
            score[ch] = score.get(ch, 0.0) + w / (c + r)
    return [ch for ch, _ in sorted(score.items(), key=lambda kv: -kv[1])[:k]]


@lru_cache(maxsize=1)
def shared(ckpt: str = str(DEFAULT_CKPT)) -> CnnCandidates:
    return CnnCandidates(ckpt)
