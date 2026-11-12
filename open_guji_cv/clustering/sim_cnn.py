"""度量学习 CNN 做 5a 逐对相似度（2026-11-10，A23；Sheldon 同意「开关接进 pipeline、在书上测」）。

## 为什么

5a 精验现在用 `verify.verify_pair_elastic` 的覆盖分（cov）：对齐后墨迹互相覆盖多少。它在笔画变细、残笔、
污点下掉得厉害，形近字（干/于、刃/刀、鳥/烏）也常给到 0.98 以上。全唐文相似度基准（cv `scripts/eval_sim_bench.py`）
上用本书库刻例训的小 CNN（CosFace 度量学习，嵌入 128 维）把 AUROC 0.962 → 0.997，腐蚀扰动下首位命中 88% → 94%；
端到端（同一套 kNN 粗排、同一套护栏，只换精验分）全唐文 2812 格：首位命中 99.41 → 99.74%，
精度 99.9% 下 same 放行 74.3 → 78.7%，每格 28 → 14 ms。数字与过程见 ai-team
`domain/CV/字形领域/5a相似度算法-2026-11-09.md`。

## 怎么接

`GlyphMatcher` 的精验是可换的函数 `_verify(a, b, cov_high=, miss_wmax=) -> PairVerdict`。这里给出同签名的
`CnnVerifier`：库里每个刻例的嵌入**整库算一次**缓存起来，查询图的嵌入按查询缓存一份，逐对分数 = 两个单位向量的点积
（余弦）。分数写进 `PairVerdict.f1`（下游 cov 一词照旧指这个分），`diff_blob_ratio` 恒为 0（CNN 没有这个量）。
判决：分数 ≥ `same` → same；≥ `low` → unsure；否则 diff。护栏 1／2、共识升档、font_tier 照旧在匹配器上走。

⚠️ 分数尺度和 cov 不同：开了以后 `consensus_cov`／`consensus_margin`、`font_tier.cov` 这些「cov ≥ X」的门槛
都要按书重标（`scripts/eval_match_bench.py`），沿用旧值不会报错，只会静默放宽或关死。

## 模型

网络结构见 `SimNet`（4 段卷积 + 全连接到 128 维，约 94 万参数，64×64 二值图进）。训练脚本
`scripts/train_glyph_sim_cnn.py`（本书库刻例，排除评测分片的格）。权重不进 git，按 `config/model-registry.json`
从 R2 取（`models/README.md`）。权重文件的 sha256 进 `GlyphMatchParams` 的参数指纹，换权重产物判过期。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .verify import PairVerdict

REPO = Path(__file__).resolve().parents[2]


def resolve_model(path: str) -> Path:
    """相对路径按仓根解析（`models/...`），绝对路径原样。"""
    p = Path(path)
    return p if p.is_absolute() else REPO / p


def model_sha256(path: str) -> str:
    p = resolve_model(path)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sim_fingerprint(path: str) -> str:
    """开着 `sim_model` 时进参数指纹的值：权重 sha256 ＋ 本模块「只认代码」哈希（前 16 位）。

    本模块**不进** glyph_match 的 `code_deps`（不开的书指纹逐字节不变）；改了它，开着的书照样靠这一项判过期。"""
    from ..core.engine import code_only_text
    src = code_only_text(Path(__file__).read_text(encoding="utf-8"))
    return f"{model_sha256(path)}:{hashlib.sha256(src.encode('utf-8')).hexdigest()[:16]}"


def _build_net(d: int = 128):
    import torch.nn as nn
    import torch.nn.functional as F

    def block(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(),
                             nn.Conv2d(o, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU())

    class SimNet(nn.Module):
        def __init__(self, n_cls: int = 0):
            super().__init__()
            self.f = nn.Sequential(block(1, 32), nn.MaxPool2d(2), block(32, 64), nn.MaxPool2d(2),
                                   block(64, 128), nn.MaxPool2d(2), block(128, 192), nn.AdaptiveAvgPool2d(2))
            self.e = nn.Linear(192 * 4, d)
            if n_cls:
                import torch
                self.W = nn.Parameter(torch.randn(n_cls, d) * 0.01)   # 只训练时用（CosFace 类中心）

        def embed(self, x):
            return F.normalize(self.e(self.f(x).flatten(1)), dim=1)

    return SimNet


def SimNet(n_cls: int = 0):  # noqa: N802 —— 对外当类用
    return _build_net()(n_cls)


_NETS: dict[str, object] = {}


def load_net(path: str):
    """按权重文件缓存的推理网络（CPU，eval 模式；训练时的类中心 W 丢掉）。"""
    import torch
    p = str(resolve_model(path))
    net = _NETS.get(p)
    if net is None:
        sd = torch.load(p, map_location="cpu")
        sd = {k: v for k, v in sd.items() if k != "W"}
        net = SimNet()
        net.load_state_dict(sd)
        net.eval()
        _NETS.clear()
        _NETS[p] = net
    return net


def embed(net, patches, batch: int = 512) -> np.ndarray:
    import torch
    if not len(patches):
        return np.zeros((0, 128), dtype=np.float32)
    a = np.stack([np.asarray(x, dtype=np.float32) for x in patches])
    out = []
    with torch.no_grad():
        for i in range(0, len(a), batch):
            out.append(net.embed(torch.from_numpy(a[i:i + batch])[:, None]).numpy())
    return np.concatenate(out).astype(np.float32)


@dataclass(frozen=True)
class SimModelConfig:
    """`GlyphMatchParams.sim_model` 的解析结果。"""
    path: str
    same: float = 0.90
    low: float = 0.50

    @classmethod
    def from_any(cls, v) -> "SimModelConfig | None":
        if not v:
            return None
        if isinstance(v, str):
            return cls(path=v)
        if isinstance(v, dict):
            if not v.get("path"):
                raise ValueError("glyph_match.sim_model 要写 path（权重文件，如 models/glyph_sim_qtw/model.pt）")
            return cls(path=str(v["path"]), same=float(v.get("same", cls.same)), low=float(v.get("low", cls.low)))
        raise TypeError(f"glyph_match.sim_model 不认识的写法：{v!r}")


class CnnVerifier:
    """`GlyphMatcher._verify` 的替身：逐对分数 = CNN 嵌入余弦。

    库刻例按对象身份（`id(归一图)`）找它在库里的行；库表在匹配器建好后不再变（`add` 只在建库时调），
    第一次用到时整库嵌入一次。查询图只缓存最近一张（一格要和 k 个刻例逐对比，同一张图连着来）。"""

    def __init__(self, cfg: SimModelConfig, patches: list):
        self.cfg = cfg
        self.net = load_net(cfg.path)
        self._patches = patches
        self._E: np.ndarray | None = None
        self._row: dict[int, int] = {}
        self._q_key: int | None = None
        self._q_ref = None
        self._q: np.ndarray | None = None

    def _lib(self) -> np.ndarray:
        if self._E is None or len(self._row) != len(self._patches):
            self._E = embed(self.net, self._patches)
            self._row = {id(x): j for j, x in enumerate(self._patches)}
        return self._E

    def score(self, a: np.ndarray, b: np.ndarray) -> float:
        E = self._lib()
        j = self._row.get(id(b))
        eb = E[j] if j is not None else embed(self.net, [b])[0]
        if self._q_key != id(a) or self._q_ref is not a:
            self._q = embed(self.net, [a])[0]
            self._q_key, self._q_ref = id(a), a
        return float(self._q @ eb)

    def __call__(self, a: np.ndarray, b: np.ndarray, **_kw) -> PairVerdict:
        s = self.score(a, b)
        verdict = "same" if s >= self.cfg.same else ("unsure" if s >= self.cfg.low else "diff")
        return PairVerdict(verdict, s, s, (0, 0), 1.0, 0.0)
