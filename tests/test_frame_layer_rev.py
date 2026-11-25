# -*- coding: utf-8 -*-
"""双线版框下端剥层修订号（`engine.FRAME_LAYER_REV`，cv #1891）：只给 column_end、且册配置下端两层的册加键。"""
from __future__ import annotations

from helpers import make_book


def _payload(book, step_cls):
    from open_guji_cv.core import engine as E
    step = step_cls()
    ph = E.params_hash(step.spec.params(), step.spec.soft_params, step.spec.path_params)
    return E._self_payload(step, book, ph)


def test_frame_layer_rev_only_for_bottom_two_layers():
    from open_guji_cv.core import engine as E
    from open_guji_cv.steps.column_end import ColumnEndStep
    plain = _payload(make_book(), ColumnEndStep)
    assert "frame_layer_rev" not in plain
    assert "frame_layer_rev" not in _payload(make_book(frame_layers={"top": 2, "bottom": 1}), ColumnEndStep)
    two = _payload(make_book(frame_layers={"top": 2, "bottom": 2}), ColumnEndStep)
    assert two["frame_layer_rev"] == E.FRAME_LAYER_REV


def test_frame_layer_rev_not_on_other_steps():
    from open_guji_cv.steps.border_detect import BorderDetectStep
    assert "frame_layer_rev" not in _payload(make_book(frame_layers={"top": 2, "bottom": 2}), BorderDetectStep)
