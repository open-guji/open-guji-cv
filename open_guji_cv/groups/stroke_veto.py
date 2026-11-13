"""书级笔画反向护栏（`stroke_veto/1`）：已放行格的笔画判和放行字相反 → 交 seed_admit 降回待审。

用的是 A23 的笔画识别（`strokes`：通用模板配准、`ink_gap` 一类的「接不接」量法、`ClassStats.llr_decide(max_z=)`，
cv #1474；研究稿 ai-team `domain/CV/字形领域/笔画识别-研究-2026-11-07/扩组2-2026-11-13.md`）。

只做两组（全唐文 001–030 已放行 6,450 格按册留出验证过的）：

- `jys` 己 对 已巳：己 左上留缺口，已／巳 左竖直通顶横。用 巳 的通用模板贴，量「横折起点→横起点」落墨比例、
  「横起点直上到顶横」最长断口（两处）。已／巳 本书刻法相同，并成一类「已巳」，只判 己 和 已巳。
- `qg` 千 对 干：千 首笔短斜撇，干 首横平长。用 干 的模板贴，量首笔方向、首笔与第二笔长度比、顶部 12%／20% 墨宽。

模型 JSON（一本书一份，随中心库走，如 `config/groups/stroke_veto.json`）::

    {"schema": "stroke_veto/1",
     "groups": {"jys": {"feat": "jys", "template": <StrokeTemplate JSON>,
                        "classes": {"己": "己", "已": "已巳", "巳": "已巳"},
                        "stats": <ClassStats JSON>, "t": 3.0, "max_z": 6.0}, ...}}

`channels`（可缺）：只看这些通道放行的格（全唐文按册留出：match_ref／split_ref 放行格被笔画判反的 15 格文意全对，
放行错几乎都在 group_flow）；缺省看全部通道。`classes` 是放行字 → 类名；类统计由本书已放行格学（`build`）。判：似然比 ≥ t 且离最近一类不超过 max_z 才给类，
否则弃权；贴坏（`bad_fit`）也弃权。护栏只在「给了类、且放行字的类≠给的类」时降审，弃权一律不动。
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

SCHEMA = "stroke_veto/1"


# ---------------------------------------------------------------- 特征

def _seg_on(dt: np.ndarray, a, b, w: float, tol: float = 0.6) -> float:
    """a→b 直线上落墨比例（离墨 ≤ tol×笔宽 算在墨上）。"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = max(2, int(np.linalg.norm(b - a)))
    q = a + (b - a) * np.linspace(0, 1, n)[:, None]
    H, W = dt.shape
    iy = np.clip(np.round(q[:, 0]).astype(int), 0, H - 1)
    ix = np.clip(np.round(q[:, 1]).astype(int), 0, W - 1)
    return float((dt[iy, ix] <= tol * w).mean())


def _max_gap(dt: np.ndarray, a, b, w: float, size: float, tol: float = 0.35) -> float:
    """a→b 直线上最长断口，按字身（`Fit.size`）归一。"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = max(2, int(np.linalg.norm(b - a)))
    q = a + (b - a) * np.linspace(0, 1, n)[:, None]
    H, W = dt.shape
    iy = np.clip(np.round(q[:, 0]).astype(int), 0, H - 1)
    ix = np.clip(np.round(q[:, 1]).astype(int), 0, W - 1)
    run = best = 0
    for o in dt[iy, ix] <= tol * w:
        run = 0 if o else run + 1
        best = max(best, run)
    return best * float(np.linalg.norm(b - a)) / max(n - 1, 1) / size


def _feat_jys(gray: np.ndarray, ink: np.ndarray, dt: np.ndarray, fit) -> list[float]:
    s0, s1, _ = fit.strokes[:3]
    top, mid = np.array(s0.start, float), np.array(s1.start, float)
    c1 = _seg_on(dt, top, mid, fit.w)                                   # 横折起点 → 横起点（左竖该在的位置）
    ytop = min(s0.start[0], s0.pts[:, 0].min())
    g1 = _max_gap(dt, mid, (ytop, mid[1]), fit.w, fit.size)             # 横起点直上到顶横的最长断口
    xs = np.nonzero(ink)[1]
    xl = xs.min() + fit.w * 0.7                                         # 左墨边往右 0.7 笔宽再量一次（左竖可能比横起点偏左）
    g2 = _max_gap(dt, (mid[0], xl), (ytop, xl), fit.w, fit.size)
    return [c1, g1, g2]


def _feat_qg(gray: np.ndarray, ink: np.ndarray, dt: np.ndarray, fit) -> list[float]:
    from ..strokes import geometry
    ys, xs = np.nonzero(ink)
    y0, y1 = ys.min(), ys.max()
    H, wd = y1 - y0 + 1, np.ptp(xs) + 1

    def band(a: float, b: float) -> float:
        r = ink[y0 + int(a * H): y0 + max(int(b * H), int(a * H) + 1)]
        cx = np.nonzero(r.any(0))[0]
        return (np.ptp(cx) + 1) / wd if len(cx) else 0.0
    g0, g1 = geometry(fit, strokes=(0,)), geometry(fit, strokes=(1,))
    return [float(g0[1]), float(g0[0] / max(g1[0], 1e-3)), band(0, 0.12), band(0, 0.2)]


FEATS = {"jys": _feat_jys, "qg": _feat_qg}


def features(gray: np.ndarray, gm: dict):
    """字块 → (特征向量 或 None, 贴坏与否)。`gm` 是模型里的一组（已 `load` 过，带 `_tpl`）。"""
    from ..strokes import bad_fit, register
    from ..strokes._ink import binarize, clean_cell
    try:
        ink = clean_cell(binarize(gray))
        if not ink.any():
            return None, True
        dt = cv2.distanceTransform((1 - (ink > 0)).astype(np.uint8), cv2.DIST_L2, 5)
        fit = register(gray, gm["_tpl"])
        x = np.array(FEATS[gm["feat"]](gray, ink, dt, fit), float)
        return x, bool(bad_fit(fit, -1))
    except Exception:  # noqa: BLE001 —— 贴不上、字块怪：一律算贴坏、弃权，不拦管线
        return None, True


# ---------------------------------------------------------------- 模型

@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> dict:
    from ..strokes import ClassStats
    from ..strokes.template import StrokeTemplate
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if m.get("schema") != SCHEMA:
        raise ValueError(f"{path}：schema 应为 {SCHEMA}，读到 {m.get('schema')!r}")
    for g in m["groups"].values():
        g["_tpl"] = StrokeTemplate.from_json(g["template"])
        g["_stats"] = ClassStats.from_json(g["stats"])
    return m


def load(path: str) -> dict:
    p = Path(path)
    return _load(str(p), p.stat().st_mtime)


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else "missing"


def group_of(model: dict, char: str):
    """放行字落在哪一组 → (组名, 组) 或 (None, None)。"""
    for gid, g in model["groups"].items():
        if char in g["classes"]:
            return gid, g
    return None, None


def judge(gray: np.ndarray, gm: dict) -> dict:
    """→ {"cls": 类名|None, "why": "llr"|"abstain"|"out"|"bad_fit", "llr": 领先量, "x": 特征}。"""
    x, bad = features(gray, gm)
    if x is None or bad:
        return {"cls": None, "why": "bad_fit"}
    st = gm["_stats"]
    out = {"x": np.round(x, 3).tolist()}
    if gm.get("max_z") is not None and st.max_z(x) > float(gm["max_z"]):
        return {**out, "cls": None, "why": "out"}
    got, ll = st.llr_decide(x, float(gm.get("t", 3.0)))
    order = sorted(ll, key=ll.get, reverse=True)
    lead = round(ll[order[0]] - ll[order[1]], 2) if len(order) >= 2 else None
    return {**out, "cls": got, "why": "llr" if got else "abstain", "llr": lead}


def build(samples: dict, templates: dict, t: float = 3.0, max_z: float | None = 6.0,
          channels: list[str] | None = None) -> dict:
    """由本书已放行格学模型。`samples`：{组名: [(字块, 放行字), …]}；`templates`：{组名: StrokeTemplate}。
    组名须是 `FEATS` 的键；类映射见模块头（jys 并 已巳）。贴坏的格不进统计。"""
    from ..strokes import ClassStats
    classes = {"jys": {"己": "己", "已": "已巳", "巳": "已巳"}, "qg": {"千": "千", "干": "干"}}
    groups = {}
    for gid, items in samples.items():
        gm = {"feat": gid, "_tpl": templates[gid]}
        S: dict = {}
        for gray, ch in items:
            x, bad = features(gray, gm)
            if x is None or bad or ch not in classes[gid]:
                continue
            S.setdefault(classes[gid][ch], []).append(x)
        st = ClassStats.from_samples(S)
        groups[gid] = {"feat": gid, "template": templates[gid].to_json(), "classes": classes[gid],
                       "stats": st.to_json(), "t": t, "max_z": max_z}
        if channels:
            groups[gid]["channels"] = list(channels)
    return {"schema": SCHEMA, "groups": groups}


__all__ = ["SCHEMA", "FEATS", "features", "load", "fingerprint", "group_of", "judge", "build"]
