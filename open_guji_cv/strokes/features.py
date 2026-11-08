"""逐笔几何特征与两种形近字判据的纯算法部分（判法外壳在 groups/methods.py，归 A24）。

- 差一笔（`verify_extra`）：用笔多的字的模板贴，看多出来那一笔的独占率。
- 量几何（`geometry` ＋ `ClassStats.decide`）：用同一个模板贴，逐笔量长度、方向、中点，看离本书哪个字的类中心近。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .register import Fit

#: 每笔特征：长度、方向 (dy, dx)、中点 (y, x)；都按墨框归一。
FEATS = ("len", "dir", "mid")
_FEAT_DIM = {"len": 1, "dir": 2, "mid": 2}


def stroke_feats(fit: Fit, idx: int, feats=FEATS) -> np.ndarray:
    s = fit.strokes[idx]
    lo = np.array(fit.bbox[:2], float)
    span = np.maximum(np.array(fit.bbox[2:], float) - lo, 1e-6)
    a = (np.array(s.start) - lo) / span
    b = (np.array(s.end) - lo) / span
    d = b - a
    L = float(np.linalg.norm(d))
    parts = {"len": [L], "dir": [d[0] / (L or 1), d[1] / (L or 1)], "mid": list((a + b) / 2)}
    return np.array([v for f in feats for v in parts[f]], float)


def geometry(fit: Fit, strokes=(), feats=FEATS) -> np.ndarray:
    """整字特征向量：strokes 为空取全部笔。"""
    idx = strokes or range(len(fit.strokes))
    return np.concatenate([stroke_feats(fit, k, feats) for k in idx])


@dataclass
class ClassStats:
    """一组字（如 土士）在同一模板下的本书类中心。sd 用各类合并的标准差。"""
    means: dict            # {字: np.ndarray}
    sd: np.ndarray
    n: dict                # {字: 例数}

    @classmethod
    def from_samples(cls, samples: dict, eps: float = 1e-3) -> "ClassStats":
        allx = np.vstack([np.vstack(v) for v in samples.values() if len(v)])
        return cls(means={c: np.mean(v, 0) for c, v in samples.items() if len(v)},
                   sd=allx.std(0) + eps, n={c: len(v) for c, v in samples.items()})

    def distances(self, x: np.ndarray) -> dict:
        return {c: float(np.linalg.norm((x - m) / self.sd)) for c, m in self.means.items()}

    def decide(self, x: np.ndarray, margin: float = 0.0):
        """返回 (字或 None, 距离表)。最近与次近的距离差 < margin（按最近距离归一）弃权。"""
        d = self.distances(x)
        order = sorted(d, key=d.get)
        if len(order) < 2:
            return (order[0] if order else None), d
        best, second = d[order[0]], d[order[1]]
        rel = (second - best) / max(second, 1e-9)
        return (order[0] if rel >= margin else None), d

    def to_json(self) -> dict:
        return {"means": {c: np.round(m, 5).tolist() for c, m in self.means.items()},
                "sd": np.round(self.sd, 5).tolist(), "n": self.n}

    @classmethod
    def from_json(cls, d: dict) -> "ClassStats":
        return cls(means={c: np.asarray(m, float) for c, m in d["means"].items()},
                   sd=np.asarray(d["sd"], float), n=d["n"])


def verify_extra(fit: Fit, stroke: int, hi: float = 0.75, lo: float = 0.2, min_cover: float = 0.85,
                 min_on_ink: float = 0.7, max_ink_frac: float = 0.45):
    """差一笔：fit 用笔多的字的模板贴。返回 ("more" | "less" | None, 独占率)。
    独占率 ≥ hi（0.75：真点几乎都 ≥0.9，污点、斑多在 0.5–0.75）→ more；≤ lo → less；中间弃权。
    整体贴坏了也弃权：骨架被解释得少（cover < min_cover），或别的笔有一笔落墨率 < min_on_ink
    （模板被邻字碎墨、坏切拉走；全唐文留出 4,536 格里 7 个异判有 3 个是这种），或墨框里墨太满（切坏的黑条 0.61；全唐文 300 格常规最高 0.24）。"""
    e = fit.strokes[stroke].excl
    others = [s.on_ink for j, s in enumerate(fit.strokes) if j != stroke]
    if fit.cover < min_cover or (others and min(others) < min_on_ink) or fit.ink_frac > max_ink_frac:
        return None, e
    if e >= hi:
        return "more", e
    if e <= lo:
        return "less", e
    return None, e


__all__ = ["FEATS", "stroke_feats", "geometry", "ClassStats", "verify_extra"]
