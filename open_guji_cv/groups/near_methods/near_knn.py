"""## near_knn（形近护栏格书级刻形近邻，第四步 `_near_knn_pass` 搬来，2026-11-28）

包的是 `groups.near_knn`（本书已放行格当刻例、整字 HOG 投 PCA；候选内近邻＋全库近邻两证），吃 `char_patch` 字块图。库是第四步那份
书级文件（数据目录 `config/groups/near_knn.json`，`schema: near_knn/1`），一本书一个；挂在保留伪组 `_guard` 上（`trigger: guard`，
触发见 `steps/glyph_near.py` 模块头「护栏触发」）：

    _guard: {trigger: guard, gap: true, methods: {near_knn: config/groups/near_knn.json}}

现役 `near_knn.judge(图, 库, 候选)` 的候选是 4d 才知道的「本格字、整理本字、库首位（gap 时库前三）」，所以 3b 不判，只出量：

- `near_knn_measure(特征, 库, 3a 的字)`（3b 出）：与候选无关的 `full`／`full_votes`（全库 k 近邻多数字与票数）、`nn`（3 位）、
  `out_of_book`（`nn > guard`，比未取整的 nn）；`chars`＝看过的 3a 字（首位＋全部候选，去重保序）；`dists`＝其中库里够 `min_n` 格的字
  → 它的库格到本格的距离升序前 k 个（float32 原值）。无墨 → `{char: None, why: abstain:no_ink}`；距离有非有限值 → `nan: True`。
- `near_knn_settle(量, 库, 候选)`（4d 调）：照 `judge_feat` 的次序判（无墨 → 候选不足 → nan → 护栏 → 票／比 → 全库同意），候选内近邻
  ＝各候选字前 k 个距离合起来按（距离, 候选次序, 字内次序）排的前 k 个（＝现役 `argsort(kind="stable")` 的次序），距离比按 float32 除；
  出来的 dict 与现役 `judge` 逐键同值、同舍入。候选里有库里够格的字、3b 却没给它距离（整理本字不在 3a 前几名等）→ None，4d 本地现算并计数。
  只读库的门槛与各字格数，不读图。
- 候选比票之外的 `ref_gate`（gap 出口闸）、`skip_chars`／`skip_groups`、异体边挡法、`via: near_gap` 全留在 4d。
- `sims`：3a 各字（够格的）合起来的前 k 个近邻里各字的票份额（4 位），够格的字不到两个 → `{}`；没有校准表。
- `evidence`：`{method: "near_knn", full, full_votes, nn, out_of_book, chars, dists}`（或无墨／nan 那两种）。
- 指纹：同 book_knn，`lib_fingerprint(库文件)`＝第四步参数指纹 `nk` 段（`near_knn.fingerprint`），`methods_sha` 里是 `_guard:near_knn=<指纹>`。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np

from ._base import lib_fingerprint


NEAR_KNN_KEYS = ("char", "why", "pick", "votes", "ratio", "full", "full_votes", "nn")


def near_knn_measure(f, model: dict, chars) -> dict:
    """near_knn 3b 出的量：HOG 特征＋3a 的字（首位与候选）→ 与候选无关的全库量＋每个字各自的近邻距离。

    - `full`／`full_votes`：全库 k 近邻的多数字与票数；`nn`：离全库最近 5 格的平均距离（3 位，同现役）；`out_of_book`：`nn > guard`
      （比的是未取整的 nn，同现役）；
    - `chars`：看过的 3a 字（去重保序）；`dists`：其中库里够 `min_n` 格的字 → 它的库格到本格的距离**升序前 k 个**（float32 原值，
      次序同 `argsort(kind="stable")`）。现役候选内近邻取「候选字的库格合起来的前 k 个」，每个字至多贡献 k 个，所以前 k 个够用；
    - 无墨 → `{char: None, why: abstain:no_ink}`；距离有非有限值 → `nan: True`（现役先判候选够不够、再判 nan，留给定档按次序判）。"""
    if f is None:
        return {"char": None, "why": "abstain:no_ink"}
    cs = [c for c in dict.fromkeys(chars or ()) if c]
    z = (np.asarray(f, np.float32) - model["pca_mean"]) @ model["pca"].T
    d = np.sqrt(((model["bank"] - z) ** 2).sum(1))
    if not np.all(np.isfinite(d)):
        return {"nan": True, "chars": cs}
    lab, k, by = model["labels"], int(model["k"]), model["_by"]
    of = np.argsort(d, kind="stable")[:k]
    full, fvotes = Counter(lab[of].tolist()).most_common(1)[0]
    nn = float(d[of[:5]].mean())
    dists = {}
    for c in cs:
        if c in by and len(by[c]) >= model.get("min_n", 5):
            dc = d[by[c]]
            dists[c] = [float(x) for x in dc[np.argsort(dc, kind="stable")[:k]]]
    return {"full": full, "full_votes": int(fvotes), "nn": round(nn, 3), "out_of_book": bool(nn > model["guard"]),
            "chars": cs, "dists": dists}


def near_knn_settle(ev: dict, model: dict, cands) -> dict | None:
    """near_knn 定档：3b 的量（`near_knn_measure` 的结果或 3b 证据）＋4d 的候选（本格字、整理本字、库首位／库前三）→ 与现役
    `near_knn.judge(图, 模型, cands)` 逐键同值的 dict（同舍入；距离比按 float32 除，同现役）。候选里有库里够格数的字、
    3b 却没给它的距离（不在 3a 前几名）→ None：4d 本地现算。只用模型的门槛与各字格数，不读图、不算距离。"""
    if ev.get("why") == "abstain:no_ink":
        return {"char": None, "why": "abstain:no_ink"}
    by = model["_by"]
    cs = [c for c in dict.fromkeys(cands) if c and c in by and len(by[c]) >= model.get("min_n", 5)]
    if len(cs) < 2:
        return {"char": None, "why": "abstain:few_cands"}
    if ev.get("nan"):
        return {"char": None, "why": "abstain:nan"}
    dists = ev.get("dists")
    if not isinstance(dists, dict) or any(c not in dists for c in cs):
        return None
    k = int(model["k"])
    pool = sorted((np.float32(x), i, j, c) for i, c in enumerate(cs) for j, x in enumerate(dists[c]))
    top, votes = Counter(c for _, _, _, c in pool[:k]).most_common(1)[0]
    lo_top = np.float32(dists[top][0])
    lo_oth = min(np.float32(dists[c][0]) for c in cs if c != top)
    ratio = float(lo_top / lo_oth) if lo_oth > 0 else 0.0
    out = {"pick": top, "votes": int(votes), "ratio": round(ratio, 3), "full": ev["full"],
           "full_votes": int(ev["full_votes"]), "nn": ev["nn"], "cands": cs}
    if ev["out_of_book"]:
        return {**out, "char": None, "why": "abstain:out_of_book"}
    if votes < model["votes_min"] or ratio >= model["ratio_max"]:
        return {**out, "char": None, "why": "abstain:low_margin"}
    if ev["full"] != top or int(ev["full_votes"]) < model["full_votes_min"]:
        return {**out, "char": None, "why": "abstain:full_dissent"}
    return {**out, "char": top, "why": "agree"}


class NearKnn:
    """形近护栏格书级刻形近邻（`groups.near_knn`）包成 3b 方法，挂在保留伪组 `_guard` 上，见模块头「near_knn」。"""

    patch = "char_patch"
    lib = True                       # 方法指纹＝刻例库文件指纹（`lib_fingerprint`）

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from .. import near_knn
        self.model = near_knn.load(str(self.path))

    def sims_of(self, v: dict) -> dict[str, float]:
        """3a 各字（够格数的）合起来的前 k 个近邻里各字的票份额（4 位）；够格的字不到两个 → `{}`。"""
        dists = v.get("dists") or {}
        if len(dists) < 2:
            return {}
        k = int(self.model["k"])
        pool = sorted((np.float32(x), i, j, c) for i, (c, xs) in enumerate(dists.items()) for j, x in enumerate(xs))
        cnt = Counter(c for _, _, _, c in pool[:k])
        return {c: round(n / k, 4) for c, n in cnt.items()}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from ..rr_shape import features
        out = []
        for i, g in enumerate(patches):
            cell = (cells or [{}] * len(patches))[i] or {}
            chars = [cell.get("char"), *(c for c, _ in (cell.get("candidates") or []))]
            v = near_knn_measure(features(g)[0], self.model, chars)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "near_knn", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        return None                  # 没有校准表：票份额只当证据

    def fingerprint(self) -> str:
        return lib_fingerprint(self.path)

    @property
    def model_sha(self) -> str:
        """库文件的版本，与第四步参数指纹 `nk` 段同算法（`near_knn.fingerprint`）。"""
        return self.fingerprint()
