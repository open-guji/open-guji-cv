"""IDS 路 U-Net 线上推理（纯 numpy）：与 torch eval 前向一致；仓里的 yi_560 权重能加载并出折线。"""
import numpy as np
import pytest

from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups import ids_unet as U


def test_numpy_forward_matches_torch(tmp_path):
    pytest.importorskip("torch")
    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    net = U.make_net(12).eval()
    U.save_weights(net, tmp_path / "w.npz")
    g = (np.random.default_rng(0).random((80, 60)) * 255).astype(np.uint8)
    assert np.abs(U.predict_prob(net, g) - U.predict_prob_np(U.NpNet(tmp_path / "w.npz"), g)).max() < 1e-4


def test_yi_560_shipped_weights_give_two_ordered_polylines():
    net = O._load_unet("yi_560")
    assert net is not None
    g = np.full((90, 70), 255, np.uint8)
    g[10:80, 15:55] = 0
    pl, _vc = O._unet_three(net, g)
    assert len(pl) == 2 and all(len(l) >= 2 for l in pl)
    assert all(a[1] <= b[1] + 1e-6 for a, b in zip(*pl))


def test_judge_three_without_weights_abstains(monkeypatch):
    monkeypatch.setattr(O, "_load_unet", lambda g: None)
    bank = {"0|彐": [np.zeros((32, 32), np.float32)]}
    assert O._judge_three("yi_560", np.zeros((10, 10), np.uint8), bank, O.SPECS["yi_560"]).why == "abstain:no_model"
