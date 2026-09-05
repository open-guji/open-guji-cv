"""「义定形未定」：语义两路一致之后，刻本到底刻的是哪个形。

背景（variant_strategy.md §4.1）：准入的文本两路（整理本 × OCR，或整理本 × 库
top1 语义一致）只能定**语义**。整理本对 1,489 个组只用一种形（髪/髮 一律印 髮），
所以它定不了形；库 ``unsure`` 时 ``_pick_char`` 曾把整理本形直接写进 ``char``——
刻 髪、存 髮，字形库错标一例，之后 髪 实例继承错。语义表一扩，这个洞就从"人审"
变成"静默错标"，所以扩表必须连着这一步一起上。

这一步只做一件事：语义已定、组里 ≥2 个可能的形时，**用形状证据定形**，定不了就
落人审（组视图一次），而不是默认整理本形。

三档（``FormDecision.state``）：

- ``fixed_lib``：库候选里组内 top1 cov ≥ FORM_LIB_COV，且组内没有对手贴到
  FORM_LIB_MARGIN 之内，且这个形本书**人确认过**——本书原型是最硬的形证据；
- ``fixed_form``：库定不了，用字体模板 + CNN 三源在组内做 closed-set 检索，三源
  top1 一致、embedding 余弦差 ≥ FORM_EMB_GAP，且该形人确认过；
- ``open``：其余——首例、分歧、差距不够。落人审，卡片只列组内的形。

阈值都是**起点**，要用组视图抽审 200 例后重定（§4.5）；产物里把三源分数全记下，
标定时不必重跑。用字账是先验不是规则：人确认过的形才允许自动定，本书 髪 ×17
不禁止第 18 次刻 髮，只是让它进组视图。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..variant_ledger import BookLedger

FORM_LIB_COV = 0.95        # 库候选组内 top1 至少这么像（same 闸 0.99 之下一档）
FORM_LIB_MARGIN = 0.01     # 组内第二名不能贴得比这更近（髪/髮 差一笔，库分得开就采）
FORM_EMB_GAP = 0.03        # 三源一致时 embedding 余弦差还得过这条线


@dataclass
class FormDecision:
    state: str                          # single | fixed_lib | fixed_form | open
    char: str | None                    # 定下的形；open 时 None
    forms: list[str]                    # 组内候选形（按本书偏好排）
    evidence: dict = field(default_factory=dict)

    def to_evidence(self) -> dict:
        return {"state": self.state, "char": self.char, "forms": self.forms, **self.evidence}


def group_forms(ledger: BookLedger, semantic_char: str) -> list[str]:
    """整理本字所在组里、本书或整理本出现过的形，按本书偏好排（preferred 最前，
    其次刻本次数多的）。不在账本里 → 只有它自己。"""
    grp = ledger.group_of(semantic_char)
    if not grp:
        return [semantic_char]
    forms = grp.get("forms", {})

    def carved(m: str) -> int:
        b = forms.get(m, {}).get("book", {})
        return int(b.get("products", 0)) + int(b.get("db", 0)) - int(b.get("align", 0))

    live = [m for m in grp.get("members", [])
            if carved(m) > 0 or forms.get(m, {}).get("ref", 0) > 0 or m == semantic_char]
    pref = grp.get("preferred")
    live.sort(key=lambda m: (m != pref, -carved(m), m != semantic_char, ord(m)))
    return live or [semantic_char]


def decide_form(semantic_char: str, forms: list[str],
                lib_candidates: list[tuple[str, float]],
                ledger: BookLedger,
                image_ranks: dict[str, list[tuple[str, float]]] | None = None,
                ) -> FormDecision:
    """见模块头。``lib_candidates`` 是库匹配的 (char, cov)；``image_ranks`` 是
    组内 closed-set 检索各源的 (char, score) 排序（键 hog / cls / emb），没图时 None。"""
    human = {f: ledger.human_confirmed(f) for f in forms}
    ev: dict = {"semantic": semantic_char, "human": human}
    if len(forms) < 2:
        return FormDecision("single", forms[0] if forms else semantic_char, forms, ev)

    lib_in = sorted(((c, float(v)) for c, v in lib_candidates if c in forms),
                    key=lambda t: -t[1])
    ev["lib"] = lib_in[:4]
    if lib_in:
        c1, v1 = lib_in[0]
        v2 = lib_in[1][1] if len(lib_in) > 1 else 0.0
        if v1 >= FORM_LIB_COV and v1 - v2 >= FORM_LIB_MARGIN and human.get(c1, 0) > 0:
            return FormDecision("fixed_lib", c1, forms, ev)

    if image_ranks:
        from .cnn_candidates import CNN_WEIGHT, EMB_WEIGHT, HOG_WEIGHT, rrf
        orders, weights = [], []
        for key, w in (("hog", HOG_WEIGHT), ("cls", CNN_WEIGHT), ("emb", EMB_WEIGHT)):
            r = image_ranks.get(key) or []
            if r:
                orders.append([c for c, _ in r])
                weights.append(w)
        ev["image"] = {k: [(c, round(float(s), 4)) for c, s in (image_ranks.get(k) or [])]
                       for k in ("hog", "cls", "emb")}
        if orders:
            fused = rrf(*orders, k=len(forms), weights=tuple(weights))
            top = fused[0]
            agree = all(o[0] == top for o in orders)
            emb = image_ranks.get("emb") or []
            gap = (float(emb[0][1]) - float(emb[1][1])) if len(emb) > 1 else 0.0
            ev["fused"] = fused
            ev["agree"] = agree
            ev["emb_gap"] = round(gap, 4)
            if agree and gap >= FORM_EMB_GAP and human.get(top, 0) > 0:
                return FormDecision("fixed_form", top, forms, ev)

    return FormDecision("open", None, forms, ev)


def image_ranks_for(norm_patch: np.ndarray, forms: list[str]
                    ) -> dict[str, list[tuple[str, float]]]:
    """组内 closed-set 检索：字体 HOG + CNN 分类头 + CNN embedding，各给 (char, score)。
    没 checkpoint 时只剩 HOG。字表只有 2–4 个字，索引现建、极快。"""
    out: dict[str, list[tuple[str, float]]] = {"hog": [], "cls": [], "emb": []}
    try:
        from .font_candidates import candidates
        out["hog"] = [h.as_tuple() for h in candidates(norm_patch, tuple(forms), k=len(forms))]
    except Exception:
        pass
    try:
        from .cnn_candidates import shared
        cnn = shared()
        if cnn.available:
            out["cls"] = cnn.topk(norm_patch, forms, k=len(forms))
            out["emb"] = cnn.emb_topk(norm_patch, forms, k=len(forms))
    except Exception:
        pass
    return out
