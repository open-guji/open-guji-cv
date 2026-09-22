# -*- coding: utf-8 -*-
"""Step A′ 外挂结构头（`CnnCandidates.attach_probe`）的契约：装了 torch 才跑。

用仓内 checkpoint（`models/glyph_cnn_r5`）+ 一个临时造的线性探针，钉住：
挂上后 `has_struct_heads` 为真、两路概率的键空间就是探针文件里的标签、
主干指纹对不上时拒挂、没挂时 r5 照旧没有结构头。**不测准确率**——那是评测（T1）。
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")


def _make_probe(tmp_path, backbone: str, n_s=3, n_l=4):
    import torch.nn as nn
    head = nn.ModuleDict({"struct": nn.Linear(256, n_s), "slot": nn.Linear(256, n_l)})
    f = tmp_path / "probe_linear.pt"
    torch.save({"state": head.state_dict(), "arch": "linear", "scale": 16.0,
                "struct_classes": ["⿰", "⿱", "SINGLE"][:n_s], "slot_labels": ["言@L", "俞@R", "口@L", "木@R"][:n_l],
                "vocab_fingerprint": "test", "backbone": backbone}, f)
    return f


def test_probe_attach_and_probs(tmp_path):
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates, fingerprint
    if not DEFAULT_CKPT.exists():
        pytest.skip("仓里没有 checkpoint")
    cnn = CnnCandidates(DEFAULT_CKPT)
    assert cnn.has_struct_heads is False and cnn.struct_source == ""
    assert cnn.attach_probe(_make_probe(tmp_path, fingerprint(DEFAULT_CKPT)))
    assert cnn.has_struct_heads and cnn.struct_source.startswith("probe:")
    img = np.zeros((64, 64), np.uint8); img[20:44, 20:44] = 1
    sp = cnn.struct_probs_batch([img, img])
    lp = cnn.slot_probs_batch([img])
    assert len(sp) == 2 and set(sp[0]) == {"⿰", "⿱", "SINGLE"} and abs(sum(sp[0].values()) - 1) < 1e-4
    assert set(lp[0]) == set(cnn.slot_labels) == {"言@L", "俞@R", "口@L", "木@R"}
    # 摘掉 → 回到没有
    assert cnn.attach_probe(None) is False and cnn.has_struct_heads is False


def test_probe_refuses_wrong_backbone(tmp_path):
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    if not DEFAULT_CKPT.exists():
        pytest.skip("仓里没有 checkpoint")
    cnn = CnnCandidates(DEFAULT_CKPT, probe=_make_probe(tmp_path, "deadbeef0000"))
    assert cnn.has_struct_heads is False
    assert cnn.struct_probs_batch([np.zeros((64, 64), np.uint8)]) == [{}]
