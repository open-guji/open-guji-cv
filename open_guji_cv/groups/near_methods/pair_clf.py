"""## pair_clf（按书字对分类器，3a `glyph_match.stages.pair` 的 5a.3 搬来，结构拆分 A4，2026-11-28）

包的是 `groups.pair_clf.judge`（3a `stage_pair`／`_pair_unsure` 用的同一个函数）：本书刻例上按对训的逻辑回归，吃**相似度 CNN 的嵌入**。
3b 照 3a 的做法自己算嵌入：`char_patch` → `clustering.normalize.normalize_patch(图, stroke_width=norm_stroke, isotropic=标点格)`
→ `sim_cnn.embed(load_net(sim))`。`norm_stroke` 取 `glyph_match.norm_stroke`，没给取册配置的（同 3a）；标点格看 `cells[].punct`
（char_index `step3_kind == "punct"`）。分类器文件一份挂多对，一个组取一对：

    dt: {ref: dt, trigger: cands, methods: {pair_clf: {path: config/groups/pair_clf.json, pair: [大, 太],
                                                        sim: models/glyph_sim_qtw/model.pt}}}

`sim` 必须写，且要与 `glyph_match.sim_model` 的 path 是同一个模型（载入时 `pair_clf.check_sim_model` 核分类器文件记的嵌入模型，
跑的时候再核 3a 的 sim_model，对不上报错：嵌入对不上分类器就是乱分）。

- `sims`：有分类器、算出了 p（判成 `b` 的概率）→ `{b: p, a: 1−p}`；档 0（本书一形没刻例）、归文意（`tier: context`）→ `{}`。
- `evidence`：`{method: "pair_clf", **judge()}`＝`{pair, tier, p?, lean?, char?}`，与 3a `MatchRec.stage.pair[]` 一行同键同值
  （3a `_pair_unsure` 多一个 `cand` 键记是哪个候选的对，3b 按组触发，不带）。`char` 只在档 2／3 且把握 ≥ `p_min` 时有，
  3b 不定字；3a 的 `pair.final`（档 3 直接定字）不搬，放不放归第四步。
- 指纹：`spec_fingerprint`＝分类器文件（`pair_clf.fingerprint`）＋字对（码位序）＋`sim_cnn.sim_fingerprint(sim)`（权重＋代码）；
  `model_sha`＝`pair_clf.fingerprint(文件)`，与 3a `stages_sha` 的 pair 段同算法。代码 `pair_clf`、`sim_cnn`、`normalize` 在 glyph_near `code_deps` 里。
- 校准：没有（`p` 本身是留出验过门槛的概率，但还没做 near-calib，`calibrate` 一律 None）。
- 登记表：各组 `handling.methods` 都许 pair_clf（挂哪对由书的分类器文件定；日曰、己已巳人定 [] 除外）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np


class PairClf:
    """5a.3 形近字对的按书分类器（`groups.pair_clf`，吃相似度 CNN 的嵌入）包成 3b 方法（结构拆分 A4，2026-11-28），
    见模块头「pair_clf」。"""

    patch = "char_patch"

    def __init__(self, path: Path, pair=None, sim=None):
        from .. import pair_clf
        if pair is None or sim is None or len(pair) != 2:
            raise ValueError("pair_clf：要写 {path: 分类器文件, pair: [字, 字], sim: 相似度模型（＝glyph_match.sim_model 的 path）}")
        p = Path(path)
        self.src = p
        self.path = p / "pair_clf.json" if p.is_dir() else p
        self.model = pair_clf.load(self.path)
        self.key = pair_clf.pair_key(str(pair[0]), str(pair[1]))
        if self.key not in self.model["pairs"] and self.key not in self.model["context"]:
            raise ValueError(f"pair_clf：{self.path} 里没有字对 {self.key}")
        self.sim = str(sim)
        pair_clf.check_sim_model(self.model, self.sim)

    def _norm(self, ctx) -> int | None:
        """与 3a 同一把尺子：`glyph_match.norm_stroke`，没给取册配置 `norm_stroke`；还核 3a 的 sim_model 就是本方法的 `sim`。"""
        if ctx is None:
            return None
        from ...clustering.sim_cnn import SimModelConfig, resolve_model
        from ...core.step import STEPS
        gm = ctx.params_for(STEPS["glyph_match"])
        if gm.sim_model and resolve_model(SimModelConfig.from_any(gm.sim_model).path) != resolve_model(self.sim):
            raise ValueError(f"pair_clf：方法的 sim {self.sim} 与 glyph_match.sim_model 不是同一个模型，嵌入对不上")
        ns = gm.norm_stroke if gm.norm_stroke is not None else getattr(ctx.book, "norm_stroke", None)
        return int(ns) if ns else None

    def sims_of(self, ev: dict) -> dict[str, float]:
        if "p" not in ev:
            return {}
        pr = self.model["pairs"][self.key]
        return {pr["b"]: ev["p"], pr["a"]: round(1.0 - ev["p"], 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from ...clustering.normalize import normalize_patch
        from ...clustering.sim_cnn import embed, load_net
        from .. import pair_clf
        cells = cells or [{} for _ in patches]
        ns = self._norm(ctx)
        norm = [normalize_patch(g, stroke_width=ns, isotropic=bool(c.get("punct"))) for g, c in zip(patches, cells)]
        E = embed(load_net(self.sim), norm)
        out = []
        for e in E:
            ev = pair_clf.judge(self.model, self.key, e)
            out.append({"sims": self.sims_of(ev), "evidence": {"method": "pair_clf", **ev}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        return None

    @staticmethod
    def spec_fingerprint(d: Path, kw: dict) -> str:
        """分类器文件（`pair_clf.fingerprint`）＋字对（码位序）＋相似度模型（`sim_cnn.sim_fingerprint`：权重＋代码）的短哈希。"""
        from ...clustering.sim_cnn import sim_fingerprint
        from .. import pair_clf
        f = d / "pair_clf.json" if d.is_dir() else d
        pr = kw.get("pair") or ()
        h = hashlib.sha256()
        h.update(pair_clf.fingerprint(f).encode())
        h.update(("|pair:" + (pair_clf.pair_key(str(pr[0]), str(pr[1])) if len(pr) == 2 else "")).encode())
        h.update(("|sim:" + (sim_fingerprint(str(kw["sim"])) if kw.get("sim") else "")).encode())
        return h.hexdigest()[:16]

    def fingerprint(self) -> str:
        return self.spec_fingerprint(self.src, {"pair": list(self.key), "sim": self.sim})

    @property
    def model_sha(self) -> str:
        """分类器文件版本，与 3a `stages_sha` 的 pair 段同算法（`pair_clf.fingerprint`）。"""
        from .. import pair_clf
        return pair_clf.fingerprint(self.path)
