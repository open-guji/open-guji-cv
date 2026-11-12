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
    """一组字（如 土士）在同一模板下的本书类中心。sd 用各类合并的标准差；
    `sds` 是各类自己的标准差（`llr_decide` 用：两类散布差很多时——木 的底横位置几乎不落墨、本 有长有短——
    合并标准差会把 本 的短底横判成 木；全唐文 已放行 15,477 格按册留出，木本 不一致 23→5、人入 29→6）。"""
    means: dict            # {字: np.ndarray}
    sd: np.ndarray
    n: dict                # {字: 例数}
    sds: dict | None = None  # {字: np.ndarray}

    @classmethod
    def from_samples(cls, samples: dict, eps: float = 1e-3, floor: float = 0.02) -> "ClassStats":
        """floor：各类标准差的下限（特征是 0–1 的比例；刻例一律很像时别让方差趋零）。"""
        allx = np.vstack([np.vstack(v) for v in samples.values() if len(v)])
        return cls(means={c: np.mean(v, 0) for c, v in samples.items() if len(v)},
                   sd=allx.std(0) + eps, n={c: len(v) for c, v in samples.items()},
                   sds={c: np.std(v, 0) + floor for c, v in samples.items() if len(v)})

    def loglik(self, x: np.ndarray) -> dict:
        """各类对角高斯的对数似然（用各类自己的标准差）。"""
        sds = self.sds or {c: self.sd for c in self.means}
        return {c: float(-0.5 * (((x - m) / sds[c]) ** 2).sum() - np.log(sds[c]).sum())
                for c, m in self.means.items()}

    def llr_decide(self, x: np.ndarray, t: float = 5.0):
        """似然比判：最像的类比次像的对数似然高出 ≥ t 才判，否则弃权。返回 (字或 None, 对数似然表)。
        t 按书按组定（全唐文 15,477 格：t=5 时 木本／目自／人入 不一致 5／9／1，全为方法错；t 越大越保守）。"""
        ll = self.loglik(x)
        order = sorted(ll, key=ll.get, reverse=True)
        if len(order) < 2:
            return (order[0] if order else None), ll
        return (order[0] if ll[order[0]] - ll[order[1]] >= t else None), ll

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
        d = {"means": {c: np.round(m, 5).tolist() for c, m in self.means.items()},
             "sd": np.round(self.sd, 5).tolist(), "n": self.n}
        if self.sds:
            d["sds"] = {c: np.round(v, 5).tolist() for c, v in self.sds.items()}
        return d

    @classmethod
    def from_json(cls, d: dict) -> "ClassStats":
        return cls(means={c: np.asarray(m, float) for c, m in d["means"].items()},
                   sd=np.asarray(d["sd"], float), n=d["n"],
                   sds={c: np.asarray(v, float) for c, v in d["sds"].items()} if d.get("sds") else None)


def bad_fit(fit: Fit, stroke: int, min_cover: float = 0.85, min_on_ink: float = 0.7,
            max_ink_frac: float = 0.45) -> bool:
    """整体贴坏了：骨架被解释得少、别的笔有一笔不落墨、或墨框里墨太满（切坏的黑块）。"""
    others = [s.on_ink for j, s in enumerate(fit.strokes) if j != stroke]
    return fit.cover < min_cover or bool(others and min(others) < min_on_ink) or fit.ink_frac > max_ink_frac


def extra_feats(fit: Fit, stroke: int) -> np.ndarray:
    """差一笔「学门槛」用的特征：验的那一笔的（独占率, 落墨率）。"""
    s = fit.strokes[stroke]
    return np.array([s.excl, s.on_ink], float)


def verify_learned(fit: Fit, stroke: int, stats: "ClassStats", margin: float = 0.3, **bad):
    """差一笔按本书刻例学门槛：stats 是两字刻例 `extra_feats` 的类统计（`ClassStats.from_samples`）。
    多出那一笔和别的笔交叉时（本 的底横、自 的撇、士 的短横）独占率天然只有 0.3–0.6，固定门槛弃权太多；
    殿本库留一（2026-11-10）：木本 弃权 99→2、目自 80→29、十士 21→2，大太／王玉 不变。
    返回 (字或 None, 距离表)；贴坏照 `bad_fit` 弃权。"""
    if bad_fit(fit, stroke, **bad):
        return None, {}
    return stats.decide(extra_feats(fit, stroke), margin=margin)


def verify_extra(fit: Fit, stroke: int, hi: float = 0.75, lo: float = 0.2, min_cover: float = 0.85,
                 min_on_ink: float = 0.7, max_ink_frac: float = 0.45):
    """差一笔：fit 用笔多的字的模板贴。返回 ("more" | "less" | None, 独占率)。
    独占率 ≥ hi（0.75：真点几乎都 ≥0.9，污点、斑多在 0.5–0.75）→ more；≤ lo → less；中间弃权。
    整体贴坏了也弃权：骨架被解释得少（cover < min_cover），或别的笔有一笔落墨率 < min_on_ink
    （模板被邻字碎墨、坏切拉走；全唐文留出 4,536 格里 7 个异判有 3 个是这种），或墨框里墨太满（切坏的黑条 0.61；全唐文 300 格常规最高 0.24）。"""
    e = fit.strokes[stroke].excl
    if bad_fit(fit, stroke, min_cover, min_on_ink, max_ink_frac):
        return None, e
    if e >= hi:
        return "more", e
    if e <= lo:
        return "less", e
    return None, e


__all__ = ["FEATS", "stroke_feats", "geometry", "ClassStats", "verify_extra", "verify_learned", "extra_feats", "bad_fit"]
