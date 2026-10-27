"""`guji pipeline` 开跑前备 Step5-b 模板索引（`prep.ensure_rare_index`，A30 10-24）。"""
import json

import numpy as np

from open_guji_cv import cli_v2
from open_guji_cv.ops import prep


class _FakePack:
    version = "emb-test"

    def __init__(self):
        self.precisions = []

    def materialize(self, cs, compute=None):
        return np.ones((len(cs), 4), np.float32), list(cs)


def _setup(monkeypatch, tmp_path, pack):
    f = tmp_path / "emb_k.npz"
    monkeypatch.setattr(prep, "rare_index_missing",
                        lambda book: (object(), [("base", ("甲", "乙"), "k", f)]))
    from open_guji_cv.clustering import emb_pack
    seen = {}

    def load(m, precision="int8", **kw):
        seen["precision"] = precision
        return pack
    monkeypatch.setattr(emb_pack, "find", lambda spec, *a, **k: {"version": "emb-test"} if pack else None)
    monkeypatch.setattr(emb_pack, "current_spec", lambda *a, **k: {})
    monkeypatch.setattr(emb_pack.EmbPack, "load", staticmethod(load))
    return f, seen


def test_pulls_fp32_from_pack(monkeypatch, tmp_path):
    monkeypatch.delenv("GUJI_NO_RARE_INDEX_PREP", raising=False)
    f, seen = _setup(monkeypatch, tmp_path, _FakePack())
    logs = []
    prep.ensure_rare_index("b", jobs=4, log=lambda s, **k: logs.append(s))
    assert seen["precision"] == "fp32"                     # 跑批绝不用 int8
    z = np.load(f)
    assert z["mat"].shape == (2, 4) and z["chars"].tolist() == ["甲", "乙"]
    side = json.loads((tmp_path / "emb_k.npz.source.json").read_text(encoding="utf-8"))
    assert side == {"emb": "emb-test", "precision": "fp32"}
    assert any("备好" in s for s in logs)


def test_opt_out_only_warns(monkeypatch, tmp_path):
    monkeypatch.setenv("GUJI_NO_RARE_INDEX_PREP", "1")
    f, _ = _setup(monkeypatch, tmp_path, _FakePack())
    logs = []
    prep.ensure_rare_index("b", jobs=4, log=lambda s, **k: logs.append(s))
    assert not f.exists()
    assert any("--precision fp32" in s for s in logs)


def test_nothing_missing_is_silent(monkeypatch):
    monkeypatch.setattr(prep, "rare_index_missing", lambda book: (None, []))
    logs = []
    prep.ensure_rare_index("b", log=lambda s, **k: logs.append(s))
    assert logs == []


def test_force_disables_cell_reuse(monkeypatch):
    """--force 必须每格重算（10-24 vol07：修好空 g2 后 --force 重跑，glyph_match 仍从旧产物搬回空库判决）。"""
    import argparse
    import os

    import pytest

    monkeypatch.delenv("GUJI_NO_REUSE", raising=False)

    class _Stop(Exception):
        pass

    def stop():
        raise _Stop
    import open_guji_cv.core.workspace as w
    monkeypatch.setattr(w, "assert_workspace_declared", stop)
    with pytest.raises(_Stop):
        cli_v2.cmd_pipeline(argparse.Namespace(force=True))
    assert os.environ.get("GUJI_NO_REUSE") == "1"
    monkeypatch.delenv("GUJI_NO_REUSE", raising=False)
    with pytest.raises(_Stop):
        cli_v2.cmd_pipeline(argparse.Namespace(force=False))
    assert os.environ.get("GUJI_NO_REUSE") is None
