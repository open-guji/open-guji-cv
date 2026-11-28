"""## book_knn（字组书级刻形近邻：门族 閒間 等，第四步 group_flow 的 `_book_knn_pass` 搬来，2026-11-28）

包的是 `groups.book_knn`（本书已放行格当刻例、整字 HOG 投 PCA 做 k 近邻），吃 `char_patch` 字块图。库是第四步那份书级文件
（数据目录 `config/groups/book_knn/<组>.json`，`schema: book_knn/1`），一组一个，书配置直接指它：

    men: {ref: men, trigger: cands, methods: {book_knn: config/groups/book_knn/men.json}}

**拆成两段**（CV3／CV4 11-28 定）：现役 `book_knn.judge(图, 模型, ref)` 只在 B 档用整理本对位字 ref，3b 看不到整理本，所以

- 前段 `book_knn_measure(特征, 模型)`（3b 出）：＝`judge_feat(特征, 模型, None)`——票数 `votes`、距离比 `ratio`、`nn`、多数字 `pick`、
  A 档结论（`agree`／`tier: A`）或弃权（`no_ink`／`nan`／`out_of_group`／`background`／`low_margin`）；`low_margin` 时另给
  `b_ok`＝「整理本字若是 pick，B 档门槛过不过」（拿 `ref=pick` 再调一次 `judge_feat` 得，比的是未取整的距离比）。
- 后段 `book_knn_settle(前段, ref)`（4d 调）：`low_margin`＋`b_ok`＋`ref == pick` → `{char: pick, why: agree_ref, tier: B}`，其余原样；
  出来的 dict 与现役 `judge(图, 模型, ref)` 逐键同值、同舍入、键次序同第四步 `evidence.book_knn`（测试按 A／B／各弃权档逐键比，
  并跑 `_book_knn_pass` 比 `evidence.book_knn`）。**现役第四步判法一行没动**，仍走 `judge`。
- 本格自己若是库里的刻例（训练时它已放行），现役运行时不屏蔽（库里没有格 id，`judge_feat` 的 `exclude` 只给训练留出用），3b 照现役，也不屏蔽。

- `sims`：`{pick: 票数/k}`（4 位）；没有 pick 或 pick 是背景刻例 `~` → `{}`。没有校准表（`calibrate` 返回 None）。
- `evidence`：`{method: "book_knn", char, why, tier, pick, votes, ratio, nn[, b_ok]}`；4d 用 `book_knn_settle(evidence, 整理本字)` 得
  第四步要存的 `evidence.book_knn`（`method`／`b_ok` 自动去掉）。
- 指纹（库钉版）：`lib_fingerprint(库文件)`＝文件 sha256 前 16 位，与第四步参数指纹 `bk` 段（`book_knn.fingerprint`）同值；
  `method_fingerprint("book_knn", 路径)`＝`book_knn=<lib_fingerprint>`，`methods_sha` 里是 `<组>:book_knn=<指纹>`，`model_sha` 也是它。
  4d 拿 `group_flow_book_knn[组]` 调 `lib_fingerprint` 比，不一致本地现算并计数、不报错。
- 触发：现役第四步只判**字组流程归进这一组（`evidence.group.id`）且仍待审**的格；3b 用 `trigger: cands` 罩（3a 首位或前 topk 名里有
  组内任一字就跑）。罩不住的格（字组靠整理本字归组、3a 前 topk 名里没有组字），4d 本地现算并计数。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ._base import lib_fingerprint


BOOK_KNN_KEYS = ("char", "why", "tier", "pick", "votes", "ratio", "nn")


def book_knn_measure(f, model: dict) -> dict:
    """book_knn 前段「出原始量」：HOG 特征 → 不看整理本时 `book_knn.judge_feat` 的结果（票数、距离比、nn、pick、A 档结论或弃权），
    再加 `b_ok`（只在 `abstain:low_margin` 时有）：整理本对位字若恰是 pick，B 档（`ref_votes_min`／`ref_ratio_max`）过不过。

    `judge_feat` 只在 B 档那一句用到 `ref`，且只看 `ref == pick`，所以 `b_ok` 直接拿 `ref=pick` 再调一次 `judge_feat` 算
    （比的是未取整的距离比，与现役同一个判断），不另写一份门槛。"""
    from .. import book_knn
    v = book_knn.judge_feat(f, model, None)
    if v["why"] == "abstain:low_margin":
        v["b_ok"] = book_knn.judge_feat(f, model, v["pick"])["why"] == "agree_ref"
    return v


def book_knn_settle(ev: dict, ref: str | None) -> dict:
    """book_knn 后段「定档」：前段的量（`book_knn_measure` 的结果，或 3b 证据 `NearMethodOut.evidence`，多的 `method` 键不管）
    ＋整理本对位字 → 与现役 `book_knn.judge(图, 模型, ref)` 逐键相同的 dict（键次序同 `BOOK_KNN_KEYS`，即第四步 `evidence.book_knn`）。
    只有前段弃权在 `low_margin`、`b_ok` 为真、整理本字＝pick 时升 B 档（`agree_ref`），其余原样。不读模型。"""
    v = {k: ev[k] for k in BOOK_KNN_KEYS if k in ev}
    if ev.get("why") == "abstain:low_margin" and ev.get("b_ok") and ref is not None and ref == ev.get("pick"):
        v.update(char=ev["pick"], why="agree_ref", tier="B")
    return v


class BookKnn:
    """字组书级刻形近邻（`groups.book_knn`）包成 3b 方法，只出前段（A 档）；B 档由 4d 用 `book_knn_settle` 定，见模块头「book_knn」。"""

    patch = "char_patch"
    lib = True                       # 方法指纹＝刻例库文件指纹（`lib_fingerprint`），不是模型目录指纹

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from .. import book_knn
        self.model = book_knn.load(str(self.path))

    def sims_of(self, v: dict) -> dict[str, float]:
        """前段结果 → `{pick: 票数/k}`（4 位）：只给近邻多数字的票份额；没有 pick、pick 是背景刻例 `~` → `{}`。"""
        from .. import book_knn
        pick = v.get("pick")
        if pick is None or pick == book_knn.BACKGROUND:
            return {}
        return {str(pick): round(int(v["votes"]) / int(self.model["k"]), 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from ..rr_shape import features
        out = []
        for g in patches:
            v = book_knn_measure(features(g)[0], self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "book_knn", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        return None                  # 没有校准表：票份额只当证据

    def fingerprint(self) -> str:
        return lib_fingerprint(self.path)

    @property
    def model_sha(self) -> str:
        """库文件的版本，与第四步参数指纹 `bk` 段同算法（`book_knn.fingerprint`）。"""
        return self.fingerprint()
