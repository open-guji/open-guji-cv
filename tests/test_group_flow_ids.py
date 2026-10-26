# -*- coding: utf-8 -*-
"""字组统一流程的 `ids` 解法（`groups/ids_online`，方案 S7）：在线判别、门槛、模板库文件、指纹、接进流程。

全部自造数据：字块图是画出来的替身（上块＝厽，下半三横＝彡、一竖＝小），模板库在 tmp 里现建，
用 monkeypatch 把 `bank_path` 指过去，不读仓里冻结的殿本模板库。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups import ids_two as T
from open_guji_cv.groups.flow import FlowConfig, decide

CUT = [[0, 0.45], [1, 0.45]]


@dataclass
class Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _glyph(bottom: str, dx: int = 0) -> np.ndarray:
    g = np.full((100, 100), 255, np.uint8)
    g[8:36, 25:75] = 0
    if bottom == "bar":
        for y in (56, 70, 84):
            g[y:y + 6, 25 + dx:75 + dx] = 0
    elif bottom == "col":
        g[52:92, 45 + dx:55 + dx] = 0
    return g


def _bank(n_bar: int = 9, n_col: int = 9) -> dict:
    bank: dict = {}
    for k in range(n_bar):
        T.add_real(bank, _glyph("bar", k % 3 - 1), "彡", CUT, "h")
    for k in range(n_col):
        T.add_real(bank, _glyph("col", k % 3 - 1), "小", CUT, "h")
    return {k: [O.quantize(t).astype(np.float32) / 255 for t in v] for k, v in bank.items()}


SPEC = O.IdsSpec(frame="⿱厽{}", orient="h", prior=0.45, min_margin=0.02, min_class=8)


def test_judge_gives_char_with_evidence():
    bank = _bank()
    v = O.judge_with("can", _glyph("bar"), bank, SPEC)
    assert v.char == "參" and v.why == "agree" and v.via == "ids"
    assert v.extra["ids"] == "⿱厽彡" and v.extra["slot"] == "彡" and v.extra["margin"] >= 0.02
    assert set(v.extra["scores"]) == {"彡", "小"}
    assert O.judge_with("can", _glyph("col"), bank, SPEC).char == "㕘"


def test_judge_abstains_low_margin_few_templates_blank():
    bank = _bank()
    hi = O.IdsSpec(**{**O.asdict(SPEC), "min_margin": 0.99})
    v = O.judge_with("can", _glyph("bar"), bank, hi)
    assert v.char is None and v.why == "abstain:low_margin" and v.extra["margin"] > 0
    v = O.judge_with("can", _glyph("col"), _bank(n_col=2), SPEC)          # 小 只有 2 个刻例，不许给
    assert v.char is None and v.why == "abstain:few_templates" and v.extra["n_templates"] == 2
    assert O.judge_with("can", _glyph("none"), bank, SPEC).why == "abstain:slot"        # 下半没墨迹
    blank = np.full((100, 100), 255, np.uint8)
    assert O.judge_with("can", blank, bank, SPEC).why == "abstain:blank"


BY_FORM = O.IdsSpec(frame="", orient="h", prior=0.45, which=1, min_margin=0.02, min_class=8, by_form=True)


def test_judge_by_form_classifies_by_member_char():
    """按字分类（叙敘 等）：模板按成员字建，切下的一段直接比，不经 IDS 拼字。"""
    cells = [("敘", _glyph("bar", k % 3 - 1)) for k in range(9)] + [("叙", _glyph("col", k % 3 - 1)) for k in range(9)]
    bank = O.form_templates(cells, BY_FORM)
    assert sorted(bank) == ["叙", "敘"] and len(bank["敘"]) == 9
    v = O.judge_with("xu", _glyph("bar"), bank, BY_FORM)
    assert v.char == "敘" and v.why == "agree" and v.extra["form"] == "敘" and v.extra["margin"] >= 0.02
    assert O.judge_with("xu", _glyph("col"), bank, BY_FORM).char == "叙"
    few = O.form_templates(cells[:9] + cells[9:11], BY_FORM)                    # 叙 只有 2 例，不许给
    v = O.judge_with("xu", _glyph("col"), few, BY_FORM)
    assert v.char is None and v.why == "abstain:few_templates"
    assert O.judge_with("xu", np.full((100, 100), 255, np.uint8), bank, BY_FORM).why == "abstain:blank"


def test_repo_by_form_banks_load():
    for g in ("xu", "jiao", "qik", "lih", "jue", "zhi"):
        sp = O.SPECS[g]
        assert (sp.by_form or sp.whole or sp.generic) and O.has_bank(g), g   # 絕絶/厯歴/啓啟 改整字（#345）；叙敘/教敎/絕絶 改通用判法（10-22）
        from open_guji_cv.groups.registry import GROUPS
        assert set(O.load_bank(O.bank_path(g))) <= GROUPS[g].members, g
        if sp.generic:
            assert len(O.generic_meta(g)["shape"]) == 64, g


def test_bank_file_roundtrip_deterministic(tmp_path):
    bank = _bank()
    d = O.dump_bank("can", bank, {"cells": 18})
    O.write_bank(d, tmp_path / "a.json")
    O.write_bank(O.dump_bank("can", bank, {"cells": 18}), tmp_path / "b.json")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    back = O.load_bank(tmp_path / "a.json")
    assert {k: len(v) for k, v in back.items()} == {"小": 9, "彡": 9}
    assert all(np.array_equal(x, y) for k in bank for x, y in zip(bank[k], back[k]))   # 量化后逐像素一致
    # 内容换了自动重读（缓存按内容哈希）
    O.write_bank(O.dump_bank("can", _bank(n_col=3), {}), tmp_path / "a.json")
    assert len(O.load_bank(tmp_path / "a.json")["小"]) == 3


def test_bank_path_prefers_workspace_and_fingerprint(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    p = ws / "config" / "groups" / "ids" / "can.json"
    O.write_bank(O.dump_bank("can", _bank(), {}), p)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert O.bank_path("can") == p and O.has_bank("can")
    assert O.bank_path("dian") is None and not O.has_bank("dian")          # 没登记判法、也没库（點㸃）
    f1 = O.fingerprint(("can", "mn"))
    assert f1.startswith("ids:can=") and "mn" not in f1 and "lv1=" in f1
    O.write_bank(O.dump_bank("can", _bank(n_bar=10), {}), p)
    assert O.fingerprint(("can",)) != f1                                 # 模板库变 → 指纹变
    assert O.fingerprint(("mn", "dian", "jys")) == ""                     # 没有在线 IDS 的组：空，不改旧指纹


def test_judge_entry_without_bank_or_patch(monkeypatch):
    monkeypatch.setattr(O, "bank_path", lambda g: None)
    assert O.judge("can", _glyph("bar")).why == "abstain:no_bank"
    assert O.judge("dian", _glyph("bar")).why == "abstain:no_spec"


@pytest.fixture
def can_bank(tmp_path, monkeypatch):
    p = tmp_path / "can.json"
    O.write_bank(O.dump_bank("can", _bank(), {}), p)
    monkeypatch.setattr(O, "bank_path", lambda g: p if g == "can" else None)
    monkeypatch.setitem(O.SPECS, "can", SPEC)
    return p


def test_flow_ids_decides_before_top1(can_bank):
    cfg = FlowConfig(groups=("can",))
    cands = [("㕘", 0.99), ("參", 0.985)]
    ch, why, trail = decide("can", Rec("a"), cands, None, cfg, patch_fn=lambda cid: _glyph("bar"))
    assert (ch, why) == ("參", "agree")
    assert [t["solver"] for t in trail] == ["freq", "ids"]               # IDS 给字就不再看库形最近
    assert trail[1]["ids"] == "⿱厽彡" and trail[1]["margin"] >= 0.02
    # 没图 → IDS 弃权；can 不再退回库形最近（2026-10-26：字形库偏 㕘，刻 叅 的格会被它放错），待定
    ch, why, trail = decide("can", Rec("a"), cands, None, cfg, patch_fn=lambda cid: None)
    assert ch is None and trail[1]["why"] == "abstain:no_patch" and [t["solver"] for t in trail] == ["freq", "ids"]


def test_flow_ids_no_bank_never_fetches_patch(can_bank):
    def boom(cid):
        raise AssertionError("没有模板库的组不该取图")
    ch, _, trail = decide("zhi", Rec("a"), [("㫖", 0.99), ("旨", 0.98)], None, FlowConfig(groups=("zhi",)),
                          patch_fn=boom)
    assert ch == "㫖" and trail[1] == {"solver": "ids", "char": None, "why": "abstain:no_bank"}


def test_seed_admit_fingerprint_includes_ids(can_bank):
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    p = SeedAdmitParams(db_path="x", group_flow=("can",))
    assert ":ids:can=" in p.group_flow_fingerprint
    q = SeedAdmitParams(db_path="x", group_flow=("mn",))
    assert "ids:" not in q.group_flow_fingerprint


def test_seed_admit_can_fetches_patch_for_ids(tmp_path, monkeypatch, can_bank):
    """接进 seed_admit：can 组有模板库 → 去取字块；缺图（patch_missing=skip）记 `patch_missing`，IDS 弃权（can 不退回 top1，留人审）。"""
    from helpers import make_book, make_ctx, page_decision, page_match, write_product
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    ctx = make_ctx(tmp_path, make_book("tbook"), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(1, "tbook", col=1, recs=[
        dict(slot=1, verdict="unsure", cov=0.98, wmax=10.0, candidates=[("㕘", 0.98), ("參", 0.975)])]))
    write_product(ctx, "context_decide", 1, context_decision=page_decision(
        1, "tbook", col=1, recs=[dict(slot=1, char=None, margin=0.1, source="prior")]))
    ctx.params["seed_admit"] = SeedAdmitParams(patch_missing="skip", group_flow=("can",), shadow_veto=False)   # 影子闸要真字形库与 sklearn，这里没摆
    r = STEPS["seed_admit"].run_page(ctx, 1)["seed_admit"].columns[0].chars[0]
    trail = r.evidence["group"]["solvers"]
    assert [t["solver"] for t in trail] == ["freq", "ids"] and trail[1]["why"] == "abstain:no_patch"
    assert "group_flow" in r.evidence.get("patch_missing", []) and not r.admit


def test_yi_560_three_slot_bank_loads_and_abstains_on_blank():
    """彝组三段版（2026-10-20）：仓里的模板库键是 `位置|部件名`，空白格弃权，指纹带上这一组。"""
    assert O.SPECS["yi_560"].three and O.has_bank("yi_560")
    b = O._slot_bank(O.load_bank(O.bank_path("yi_560")))
    assert set(b) == {0, 1, 2, 3} and set(b[0]) == {"彐", "彑"} and set(b[2]) == {"廾", "大"}
    assert O.judge("yi_560", np.full((100, 100), 255, np.uint8)).why == "abstain:blank"
    assert "yi_560=" in O.fingerprint(["yi_560"])
    assert O.SPECS["yi_560"].unet and O.unet_path("yi_560") is not None and ".u" in O.fingerprint(["yi_560"])


def test_yi_560_nearest_variant_is_released_when_spec_allows(monkeypatch):
    """彑米糸大 无 Unicode 码位，解析器归 𢑴 并打 nearest 旗；sheldon 10-20 定它就是 𢑴，yi_560 放行（其他组仍弃权）。"""
    from dataclasses import replace
    from open_guji_cv.groups import ids_solver
    from open_guji_cv.groups.ids_solver import IdsVerdict
    fake = IdsVerdict("𢑴", "⿳彑⿰米糸大", "nearest", "nearest_variant", ("彑", "米糸", "大"), (0.5, 0.5, 0.5))
    monkeypatch.setattr(ids_solver, "solve", lambda *a, **k: fake)
    monkeypatch.setattr(O, "_unet_three", lambda net, g: (None, None))
    bank = {f"{k}|{n}": [np.zeros((32, 32), np.float32)] * 3
            for k, ns in ((0, "彐彑"), (1, ("米糸", "米分")), (2, "廾大")) for n in ns}
    bank["3|糸"] = bank["3|分"] = [np.zeros((32, 32), np.float32)] * 3
    gray = np.zeros((10, 10), np.uint8)
    spec = O.SPECS["yi_560"]
    assert spec.nearest_ok and O._judge_three("yi_560", gray, bank, spec, net=object()).char == "𢑴"
    assert O._judge_three("yi_560", gray, bank, replace(spec, nearest_ok=False), net=object()).why == "abstain:nearest"
