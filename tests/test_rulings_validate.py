# -*- coding: utf-8 -*-
"""写裁定前校验（`rulings.validate`，`RulingLog.append`；GM4／CV4 2026-11-24 裁定键长期方案①）。"""
from __future__ import annotations

import pytest

from open_guji_cv.errors import BadRequest
from open_guji_cv.feedback import rulings as R


def _ev(payload, seq=1):
    return R.make_event("t-val", seq, R.KIND, R.EventTarget(step="seed_admit", unit="cell", key="tb:1:1:1", book="tb"),
                        payload, actor="model")


@pytest.mark.parametrize("g,ver", [("O", "vis-o1"), ("O", "src-1"), ("O", "ctx-m1"), ("O", "src-2"),
                                   ("O", "ctx-m1#claude-x:high"), ("ry", "ry-l2-2"), ("ry", "ry-l2-2#m:high"),
                                   ("zy", "vis1:abcdef012345"), ("O", "vis1:abc")])
def test_accepts_known_versions(g, ver):
    assert R.validate({"group": g, "prompt_ver": ver}) == ([], [])


@pytest.mark.parametrize("g,ver", [("O", "ctx-wenyi-1"), ("ry", "rm-l2-1"), ("ry", "ry-l2-1"), ("rm", "ry-l2-2"),
                                   ("ry", "src-1"), ("O", "")])
def test_rejects_unknown_versions(g, ver):
    errs, _ = R.validate({"group": g, "prompt_ver": ver})
    assert errs


def test_equiv_table_versions_accepted():
    eq = {"pairs": {("ry", "ry-l2-2"): ["ry-l2-1"], ("*", "ctx-m1"): ["ctx-wenyi-1"]}, "model_suffix": False}
    assert R.validate({"group": "ry", "prompt_ver": "ry-l2-1"}, eq)[0] == []
    assert R.validate({"group": "O", "prompt_ver": "ctx-wenyi-1"}, eq)[0] == []
    assert R.validate({"group": "rm", "prompt_ver": "ry-l2-1"}, eq)[0]          # 只登记给 ry


def test_subclass_warns_not_rejects():
    errs, warns = R.validate({"group": "O", "prompt_ver": "vis-o1", "admit_ok": True, "subclass": "C240"})
    assert not errs and warns
    assert R.validate({"group": "O", "prompt_ver": "vis-o1", "admit_ok": False, "subclass": "C240"}) == ([], [])
    assert R.validate({"group": "O", "prompt_ver": "ctx-m1", "admit_ok": True, "subclass": "W"}) == ([], [])  # 子类各书可加
    assert R.validate({"group": "O", "prompt_ver": "src-1", "admit_ok": True, "subclass": "PUA"}) == ([], [])


def test_log_append_rejects_whole_batch(tmp_path):
    log = R.RulingLog(tmp_path)
    with pytest.raises(BadRequest):
        log.append([_ev({"group": "O", "prompt_ver": "vis-o1"}, 1), _ev({"group": "O", "prompt_ver": "ctx-wenyi-1"}, 2)])
    assert list(log.iter_all(raw=True)) == []
    assert log.append([_ev({"group": "O", "prompt_ver": "vis-o1"}, 1)]) == 1
    (tmp_path / "rulings" / R.EQUIV_FILE).write_text("equiv:\n  - {from: ctx-wenyi-1, to: ctx-m1}\n", encoding="utf-8")
    assert log.append([_ev({"group": "O", "prompt_ver": "ctx-wenyi-1"}, 2)]) == 1                  # 登记了就收


def test_pipeline_put_not_validated(tmp_path):
    st = R.RulingStore(tmp_path)
    st.put("日曰", "試驗版", "子", "學而", char="曰", conf="high", why="", model="m")              # 管线缓存写不校验
    assert st.get("日曰", "試驗版", "子", "學而")["char"] == "曰"


def test_vis_ruling_specs_shared_with_seed_admit():
    from open_guji_cv.steps import seed_admit as sa
    assert sa._VIS_RULING_SPECS is R.VIS_RULING_SPECS and sa._VIS_RULING_GROUP == R.VIS_RULING_GROUP
    assert sa._VIS_RULING_SUBCLASSES == frozenset({"A68", "B99", "D130", "L04"})
