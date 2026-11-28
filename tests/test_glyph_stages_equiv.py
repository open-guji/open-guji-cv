"""glyph_stages 合算代码哈希查等价登记（结构拆分 A4）：搬家后登记过的开 stages 的书 stages_sha 不变。"""
from __future__ import annotations

from open_guji_cv.core import code_equiv
from open_guji_cv.steps import glyph_stages as gs


def test_code_sha_follows_composite_equiv(monkeypatch):
    mods = gs.STAGES_CODE_MODS
    raw = gs.composite_hash(mods, gs._read_module)
    key = gs.composite_key(mods)
    monkeypatch.setattr(code_equiv, "_TABLE", {**code_equiv._TABLE, key: {raw: "f" * 64}})
    assert gs._code_sha(*mods) == "f" * 16


def test_code_sha_without_entry_is_raw(monkeypatch):
    mods = gs.PAIR_CODE_MODS
    monkeypatch.setattr(code_equiv, "_TABLE", {k: v for k, v in code_equiv._TABLE.items() if k != gs.composite_key(mods)})
    assert gs._code_sha(*mods) == gs.composite_hash(mods, gs._read_module)[:16]


def test_current_stages_code_maps_to_registered_old():
    """本次改 glyph_stages 自身登记过：现版本的合算哈希换算后等于改前（1afa3a39）的值。"""
    assert gs._code_sha(*gs.STAGES_CODE_MODS) == "fbced2adde554dc7"
