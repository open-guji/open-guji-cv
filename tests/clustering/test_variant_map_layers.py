"""VariantMap 两张表叠加：自动表在下，手工表覆盖；显式路径只读那一份。"""

from __future__ import annotations

from open_guji_cv.clustering import variants as vmod


def test_hand_overrides_auto(monkeypatch, tmp_path):
    auto = tmp_path / "variants.auto.tsv"
    hand = tmp_path / "variants.tsv"
    auto.write_text("# auto\n髪\t髮\tledger\n卽\t即\tledger\n畧\t略\tgraph\n", encoding="utf-8")
    hand.write_text("# hand\n卽\t卽\n㫖\t旨\n", encoding="utf-8")       # 手工把 卽 改回自身
    monkeypatch.setattr(vmod, "DEFAULT_AUTO_PATH", auto)
    monkeypatch.setattr(vmod, "DEFAULT_VARIANTS_PATH", hand)
    vm = vmod.VariantMap.load()
    assert vm.semantic("髪") == "髮"          # 来自自动表
    assert vm.semantic("卽") == "卽"          # 手工覆盖
    assert vm.semantic("㫖") == "旨"          # 只在手工表
    assert vm.semantic("畧") == "略"
    assert len(vm) == 4


def test_explicit_path_reads_only_that_file(monkeypatch, tmp_path):
    auto = tmp_path / "variants.auto.tsv"
    auto.write_text("髪\t髮\tledger\n", encoding="utf-8")
    only = tmp_path / "only.tsv"
    only.write_text("逰\t遊\n", encoding="utf-8")
    monkeypatch.setattr(vmod, "DEFAULT_AUTO_PATH", auto)
    vm = vmod.VariantMap.load(only)
    assert vm.semantic("逰") == "遊" and vm.semantic("髪") == "髪"


def test_missing_auto_table_is_fine(monkeypatch, tmp_path):
    monkeypatch.setattr(vmod, "DEFAULT_AUTO_PATH", tmp_path / "nope.tsv")
    hand = tmp_path / "variants.tsv"
    hand.write_text("彚\t彙\n", encoding="utf-8")
    monkeypatch.setattr(vmod, "DEFAULT_VARIANTS_PATH", hand)
    assert vmod.VariantMap.load().semantic("彚") == "彙"
