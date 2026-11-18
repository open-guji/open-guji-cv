# -*- coding: utf-8 -*-
"""5-b 的第二路证据：不认字的笔画检测 → 和候选字的 KAGE 标准骨架做集合匹配（2026-11-18，OCR 研究方向 4）。

**只给已有候选打分，不找字**：笔画单路找字远不如向量检索（首位约 50% 对 85%），但两者错的不是同一批。
两种接法（册配置 `font.stroke_evidence.mode`）：

- `emb`：融合之前把 embedding 那一路的前 k 名按「余弦 + weight × 笔画分」重排，这一路的成员和各自的余弦分不动。
- `rrf`：对各路候选的并集按笔画分排名次，当多出来的一路进 `rare_panel._fuse` 的名次融合。不带字表外的新候选，
  但融合后的前 k 名成员会变。缺省是它：全唐文产线路径回放首位 76.2→81.1（权重 4）。

数字、读法、没做的事见 `doc/design/5b-笔画证据.md`；研究过程见 ai-team
`domain/CV/字形领域/笔画集合检索候选字-2026-11-15/`。

**按书开**（册配置 `font.stroke_evidence: {enabled: true}`，要改再写 `mode`、`weight`，缺省关）：哪种接法好、
值不值得开因书而异（全唐文 rrf 成立，殿本收益小，史記 emb 0.1 比 rrf 干净），打开前先用
`scripts/eval_stroke_evidence.py` 在本书人裁格上量。关着时这个模块不被调用。

流程（参数都在调参集上定过，别单改一个）：

1. 检测：字块缩到 128 像素，全卷积小网络出六类笔段（横、竖、撇、捺／点、提、折）的中点热图，
   中点处回归起点、终点。分数 > `DET_THR`，同类近重复只留高分。
2. 归一：检出笔段和标准骨架各按自己全部点的外框缩到 0–1（不用墨迹外框：字块边上的脏会把框撑大）。
3. 逐候选对齐：按软对应给检出笔段每轴拟一个缩放（限 1±`ALIGN_LIM`）和平移。
4. 打分：同类笔段三点（中、起、终）平均距 d，相似度 exp(−d²/2σ²)，一对一（匈牙利）匹配的 F1。
   一个字有多个地区形（GlyphWiki 无后缀和 -k -t -g -j），取最高分。

资源在 `models/stroke_evidence_v1/`（模型表登记，`guji model fetch` 取）：`net.pt` 检测权重（合成数据训，
不含任何书的刻例）、`skel.npz`＋`skel_forms.json` 97,681 字 149,881 形的骨架索引（GlyphWiki dump 展开）。
缺任何一个就告警一次并原样返回。目录名带版本：换权重或索引出 `_v2`，不动 `_v1`。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "stroke_evidence_v1"
NC = 6                 # 横 竖 撇 捺/点 提 折
DET_THR = 0.3          # 检测分数门槛
DEDUP_PX = 4.0         # 同类笔段三点平均距小于它（128 图像素）算重复检出
SIGMA_ALIGN = 0.15     # 对齐时找软对应的容差（归一坐标）
SIGMA = 0.12           # 打分容差
ALIGN_LIM = 0.25       # 每轴缩放限 1±0.25
MIN_STROKES = 3        # 检出不足 3 段不出分：一两笔的字外框退化，笔画分没有区分力
DEFAULT_WEIGHT = 0.1   # mode=emb：余弦量纲。三书冻结集上 0.05–0.15 都可用，再大类内字开始掉
RRF_WEIGHT = 4.0       # mode=rrf：名次融合里笔画这一路的权重（embedding 是 4，分类头不超过 1）。产线路径回放：
                       # 1–2 基本不动，4 最好，6 以上类内字（unseen 层）首位开始掉


MODES = ("rrf", "emb")


def book_stroke_evidence(font: dict | None) -> tuple[bool, float, str]:
    """册配置 `font.stroke_evidence` → `(enabled, weight, mode)`。缺省关。

    `mode: rrf`（缺省）：笔画分给各路候选的并集排一个名次，当名次融合里多出来的一路，weight 是融合权重
    （与 `CNN_WEIGHT`／`EMB_WEIGHT` 同量纲，没写取 `RRF_WEIGHT`）。
    `mode: emb`：embedding 那一路的前 k 名按「余弦 + weight × 笔画分」重排，weight 是余弦量纲（没写取 `DEFAULT_WEIGHT`）。"""
    cfg = (font or {}).get("stroke_evidence") or {}
    mode = str(cfg.get("mode", "rrf"))
    if mode not in MODES:
        raise ValueError(f"font.stroke_evidence.mode 只能是 {MODES}，收到 {mode!r}")
    w = cfg.get("weight", DEFAULT_WEIGHT if mode == "emb" else RRF_WEIGHT)
    return bool(cfg.get("enabled", False)), float(w), mode


def _build_net():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class Res(nn.Module):
        def __init__(s, c, d=1):
            super().__init__()
            s.a = nn.Conv2d(c, c, 3, padding=d, dilation=d, bias=False)
            s.b = nn.Conv2d(c, c, 3, padding=1, bias=False)
            s.n1 = nn.BatchNorm2d(c)
            s.n2 = nn.BatchNorm2d(c)

        def forward(s, x):
            return F.relu(x + s.n2(s.b(F.relu(s.n1(s.a(x))))))

    def down(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, 2, 1, bias=False), nn.BatchNorm2d(o), nn.ReLU())

    class Net(nn.Module):
        """128px 字图 → 64×64 网格：每类笔段中点热图 + （亚格偏移, 起点偏移, 终点偏移）"""

        def __init__(s, c=(32, 64, 128, 192)):
            super().__init__()
            s.s1 = nn.Sequential(down(1, c[0]), Res(c[0]))
            s.s2 = nn.Sequential(down(c[0], c[1]), Res(c[1]), Res(c[1]))
            s.s3 = nn.Sequential(down(c[1], c[2]), Res(c[2]), Res(c[2], 2))
            s.s4 = nn.Sequential(down(c[2], c[3]), Res(c[3]), Res(c[3], 2), Res(c[3]))
            s.u3 = nn.Sequential(nn.Conv2d(c[3] + c[2], c[2], 3, padding=1, bias=False),
                                 nn.BatchNorm2d(c[2]), nn.ReLU(), Res(c[2]))
            s.u2 = nn.Sequential(nn.Conv2d(c[2] + c[1], c[1], 3, padding=1, bias=False),
                                 nn.BatchNorm2d(c[1]), nn.ReLU(), Res(c[1]))
            s.u1 = nn.Sequential(nn.Conv2d(c[1] + c[0], 64, 3, padding=1, bias=False),
                                 nn.BatchNorm2d(64), nn.ReLU(), Res(64))
            s.heat = nn.Sequential(nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(), nn.Conv2d(64, NC, 1))
            s.reg = nn.Sequential(nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(), nn.Conv2d(64, 6, 1))

        def forward(s, x):
            a = s.s1(x)
            b = s.s2(a)
            c = s.s3(b)
            d = s.s4(c)
            up = lambda t, r: F.interpolate(t, size=r.shape[-2:], mode="bilinear", align_corners=False)  # noqa: E731
            c = s.u3(torch.cat([up(d, c), c], 1))
            b = s.u2(torch.cat([up(c, b), b], 1))
            a = s.u1(torch.cat([up(b, a), a], 1))
            return s.heat(a), s.reg(a)

    return Net()


def _decode(heat, reg, thr: float, st: int = 2) -> list[np.ndarray]:
    """→ 每张图一个 [n, 8]：分数, 类, 中x, 中y, 起x, 起y, 终x, 终y（128 图像素）"""
    import torch
    import torch.nn.functional as F
    p = torch.sigmoid(heat)
    m = (F.max_pool2d(p, 3, 1, 1) == p) & (p > thr)
    out = []
    for b in range(p.shape[0]):
        c, iy, ix = torch.nonzero(m[b], as_tuple=True)
        r = reg[b][:, iy, ix].T
        sc = p[b][c, iy, ix]
        kx = (ix + 0.5 + r[:, 0]) * st
        ky = (iy + 0.5 + r[:, 1]) * st
        o = torch.stack([sc, c.float(), kx, ky, kx + r[:, 2] * 16, ky + r[:, 3] * 16,
                         kx + r[:, 4] * 16, ky + r[:, 5] * 16], 1)
        out.append(o.cpu().numpy())
    return out


def normalize_strokes(det: np.ndarray, thr: float = DET_THR) -> tuple[np.ndarray, np.ndarray] | None:
    """检测输出 [n, 8] → `(类 [m], 点 [m, 6])`，点按全部点的外框归一到 0–1。不足 `MIN_STROKES` 段返回 None。"""
    det = det[det[:, 0] > thr]
    det = det[np.argsort(-det[:, 0], kind="stable")]
    keep: list[np.ndarray] = []
    for q in det:
        dup = any(int(q[1]) == int(k[1])
                  and np.linalg.norm((q[2:] - k[2:]).reshape(3, 2), axis=1).mean() < DEDUP_PX for k in keep)
        if not dup:
            keep.append(q)
    if len(keep) < MIN_STROKES:
        return None
    a = np.array(keep)
    pts = a[:, 2:].reshape(-1, 2)
    lo, hi = pts.min(0), pts.max(0)
    pts = (pts - lo) / np.maximum(hi - lo, 1.0)
    return a[:, 1].astype(np.int64), pts.reshape(-1, 6).astype(np.float32)


def match_score(qc: np.ndarray, qp: np.ndarray, cc: np.ndarray, cp: np.ndarray) -> float:
    """检出笔段 `(qc [n], qp [n,6])` 对一个标准形 `(cc [m], cp [m,6])` 的笔画分（0–1）。"""
    from scipy.optimize import linear_sum_assignment
    n, m = len(qc), len(cc)
    if not n or not m:
        return 0.0
    same = qc[:, None] == cc[None, :]

    def sim(q, sig):
        d = np.linalg.norm(q.reshape(n, 1, 3, 2) - cp.reshape(1, m, 3, 2), axis=-1).mean(-1)
        return np.exp(-d * d / (2 * sig * sig)) * same

    s = sim(qp, SIGMA_ALIGN)
    j = s.argmax(1)
    w = np.repeat(s[np.arange(n), j] + 1e-4, 3)[:, None]                 # [3n, 1]
    src = qp.reshape(-1, 2)
    tgt = cp[j].reshape(-1, 2)
    sw = w.sum()
    mx, my = (w * src).sum(0) / sw, (w * tgt).sum(0) / sw
    dx, dy = src - mx, tgt - my
    a = np.clip((w * dx * dy).sum(0) / ((w * dx * dx).sum(0) + 1e-6), 1 - ALIGN_LIM, 1 + ALIGN_LIM)
    s2 = sim((dx * a + my).reshape(n, 6).astype(np.float32), SIGMA)
    r, c = linear_sum_assignment(-s2)
    return float(2 * s2[r, c].sum() / (n + m))


class StrokeEvidence:
    """检测网络 + 骨架索引。懒加载；资源缺了 `available` 为 False。

    测试可注入：`forms`（{字: [(类 [m], 点 [m,6]), …]}）和 `detect`（灰度图列表 → 每图 [n,8]）。
    """

    def __init__(self, model_dir: Path | None = None, forms: dict | None = None, detect=None):
        self.dir = Path(model_dir) if model_dir else MODEL_DIR
        self._forms = forms
        self._detect = detect
        self._net = None
        self._warned = False

    @property
    def available(self) -> bool:
        if self._forms is not None and self._detect is not None:
            return True
        return all((self.dir / f).is_file() for f in ("net.pt", "skel.npz", "skel_forms.json"))

    def _load(self) -> None:
        if self._forms is None:
            z = np.load(self.dir / "skel.npz")
            chars = json.loads((self.dir / "skel_forms.json").read_text(encoding="utf-8"))["chars"]
            S, nseg = z["S"], z["nseg"]
            forms: dict[str, list] = {}
            for i, ch in enumerate(chars):
                a = S[i, : int(nseg[i])]
                forms.setdefault(ch, []).append((a[:, 0].astype(np.int64), a[:, 1:].astype(np.float32)))
            self._forms = forms
        if self._detect is None:
            import torch
            net = _build_net()
            net.load_state_dict(torch.load(self.dir / "net.pt", map_location="cpu"))
            net.eval()
            self._net = net

            def detect(imgs: list) -> list[np.ndarray]:
                import cv2
                xs = []
                for im in imgs:
                    g = im if im.ndim == 2 else cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
                    xs.append(cv2.resize(255 - g, (128, 128), interpolation=cv2.INTER_AREA))
                out: list[np.ndarray] = []
                with torch.no_grad():
                    for i in range(0, len(xs), 64):
                        x = torch.from_numpy(np.stack(xs[i:i + 64]).astype(np.float32) / 255)[:, None]
                        h, r = net(x)
                        out += _decode(h, r, DET_THR * 0.5)
                return out
            self._detect = detect

    def scores(self, det: np.ndarray, chars: list[str]) -> dict[str, float] | None:
        """一个字块的检测输出对一批候选字的笔画分。检出太少返回 None；索引里没有的字不在返回里。"""
        q = normalize_strokes(det)
        if q is None:
            return None
        qc, qp = q
        out = {}
        for ch in chars:
            fs = self._forms.get(ch)
            if fs:
                out[ch] = max(match_score(qc, qp, cc, cp) for cc, cp in fs)
        return out

    def _ready(self) -> bool:
        if not self.available:
            if not self._warned:
                print(f"  ⚠️  笔画证据开着但资源不全（{self.dir}，先跑 guji model fetch），本次不生效",
                      file=sys.stderr)
                self._warned = True
            return False
        self._load()
        return True

    def orders(self, imgs: list, cand_rows: list[list[str]]) -> list[list[str]]:
        """`mode: rrf` 用：`cand_rows[i]` 是第 i 个字块各路候选的并集，返回按笔画分降序的名次表
        （只含索引里有骨架的字）。检出太少、只有一个候选、资源缺失的格返回空表（这一路不投票）。"""
        if not cand_rows or not self._ready():
            return [[] for _ in cand_rows]
        idx = [i for i, r in enumerate(cand_rows) if len(r) > 1]
        dets = dict(zip(idx, self._detect([imgs[i] for i in idx]))) if idx else {}
        out = []
        for i, row in enumerate(cand_rows):
            sc = self.scores(dets[i], list(row)) if i in dets else None
            out.append(sorted(sc, key=lambda ch: -sc[ch]) if sc else [])
        return out

    def rerank_rows(self, imgs: list, rows: list[list[tuple[str, float]]], weight: float = DEFAULT_WEIGHT
                    ) -> list[list[tuple[str, float]]]:
        """`rows[i]` 是第 i 个字块 embedding 路的 `[(字, 余弦), …]`（已按余弦降序）。
        返回同样的元组、按「余弦 + weight × 笔画分」重排；索引里没有骨架的候选（符号、私用码）取本格
        其余候选笔画分的中位，不因为没有骨架吃亏。检出太少、资源缺失的格原样返回。"""
        if not rows or weight <= 0:
            return rows
        if not self._ready():
            return rows
        idx = [i for i, r in enumerate(rows) if len(r) > 1]
        dets = dict(zip(idx, self._detect([imgs[i] for i in idx]))) if idx else {}
        out = []
        for i, row in enumerate(rows):
            sc = self.scores(dets[i], [c for c, _ in row]) if i in dets else None
            if not sc:
                out.append(row)
                continue
            mid = float(np.median(list(sc.values())))
            key = [-(cos + weight * sc.get(ch, mid)) for ch, cos in row]
            out.append([row[j] for j in np.argsort(key, kind="stable")])
        return out


_SHARED: StrokeEvidence | None = None


def shared() -> StrokeEvidence:
    global _SHARED
    if _SHARED is None:
        _SHARED = StrokeEvidence()
    return _SHARED
