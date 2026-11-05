"""本书重训 IDS 模板（`groups/ids_retrain`）：模板库文件里的 `spec` 覆盖 `SPECS`；清标签只去被别的类高把握推翻的非人裁格。"""
import json

import numpy as np

from open_guji_cv.groups import ids_online as O, ids_retrain as R


def _bank(tmp_path, spec=None):
    d = O.dump_bank("men", {"門": [np.zeros((48, 48), np.float32)], "問": [np.ones((48, 48), np.float32)]}, {}, size=48)
    if spec is not None:
        d["spec"] = spec
    p = tmp_path / "men.json"
    O.write_bank(d, p)
    return p


def test_bank_spec_overrides_specs(tmp_path):
    assert O._spec_for("men", _bank(tmp_path)) is None
    sp = O._spec_for("men", _bank(tmp_path, {"min_margin": 1.23}))
    assert sp.min_margin == 1.23 and sp.whole == O.SPECS["men"].whole


def test_bank_spec_changes_bank_hash(tmp_path):
    a = _bank(tmp_path).read_bytes()
    assert a != _bank(tmp_path, {"min_margin": 1.23}).read_bytes()      # 门槛进文件 → 进指纹


def test_clean_drops_confident_overturn_but_keeps_human(monkeypatch):
    cells = [dict(id="a", form="門", ch="match_ref"), dict(id="b", form="門", ch="human"), dict(id="c", form="門", ch="match_ref")]
    calls = []

    def fake(g, cs, sp, bank=None):
        calls.append(len(cs))
        allr = [dict(form="門", pick="問", m=0.9, id="a", ch="match_ref"), dict(form="門", pick="問", m=0.9, id="b", ch="human"),
                dict(form="門", pick="門", m=0.9, id="c", ch="match_ref")]
        return [r for r in allr if r["id"] in {c["id"] for c in cs}]
    monkeypatch.setattr(R, "lovo", fake)
    kept, dropped, human = R.clean("men", cells, O.SPECS["men"], {"門", "問"})
    assert [c["id"] for c in kept] == ["b", "c"] and [d["id"] for d in dropped] == ["a"] and [d["id"] for d in human] == ["b"]
