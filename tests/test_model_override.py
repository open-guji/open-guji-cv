# -*- coding: utf-8 -*-
"""两本书钉同一模型的不同版本：`core/model_override` 按册换读模型模块的缺省路径（模块源码不动）。"""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from open_guji_cv.core import model_override as mo
from open_guji_cv.core import model_pack as mp


def mb_place():
    from open_guji_cv.ops import model_blobs as mb
    return mb._place


def _item(rel, sha):
    return {"root": "repo", "path": rel, "sha256": sha}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.ops import model_blobs as mb
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "dh"))
    monkeypatch.setattr("open_guji_cv.core.workspace.workspace_root", lambda: tmp_path)
    cnn_rel = Path(cc.DEFAULT_CKPT).resolve().relative_to(mp.REPO_ROOT).as_posix()
    rr_rel = "models/rr_clf/forest.npz"
    pt_rel = "models/pagetype/pagetype_v1.joblib"
    new = b"pagetype-B"
    man = {"digest": "abcdef0123456789ff",
           "items": [_item(cnn_rel, mp._sha256(mp.REPO_ROOT / cnn_rel)),
                     _item(rr_rel, mp._sha256(mp.REPO_ROOT / rr_rel)),
                     _item(pt_rel, hashlib.sha256(new).hexdigest()),
                     {"root": "data", "path": "config/x.npz", "sha256": "0" * 64}]}
    monkeypatch.setattr(mp, "load_manifest", lambda ws, v: man)
    placed = []

    def fake_place(todo):
        for _sha, p in todo:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(new)
            placed.append(p)
        return len(todo), []
    monkeypatch.setattr(mb, "_place", fake_place)
    yield SimpleNamespace(man=man, cnn_rel=cnn_rel, rr_rel=rr_rel, pt_rel=pt_rel, placed=placed, cc=cc)
    mo.apply(None)


def test_switch_and_restore(setup):
    from open_guji_cv.groups import ids_online
    from open_guji_cv.pagetype_model import model as ptm
    from open_guji_cv.shadow import model as shm
    from open_guji_cv.utils import rr_clf
    cc = setup.cc
    orig = (ptm.DEFAULT_MODEL, cc.DEFAULT_CKPT, cc.fingerprint.__defaults__, rr_clf.MODEL_DIR,
            shm.DEFAULT_MODEL, ids_online.unet_path, ids_online.bank_path, ids_online.whole_bank_path)
    root = mo.activate(SimpleNamespace(model=2), mb_place())
    assert root == mo.cache_root(setup.man) and mo.active_root() == root
    assert Path(ptm.DEFAULT_MODEL) == root / setup.pt_rel
    assert Path(ptm.DEFAULT_MODEL).read_bytes() == b"pagetype-B"        # 不同的那个从 R2 取
    assert Path(cc.DEFAULT_CKPT) == root / setup.cnn_rel                # 一致的从仓里拷
    assert Path(cc.fingerprint.__defaults__[0]) == root / setup.cnn_rel  # 函数缺省参数一起换
    assert Path(rr_clf.MODEL_DIR) == root / "models/rr_clf"
    assert shm.DEFAULT_MODEL == orig[4]                                  # 清单里没有的不换
    assert ids_online.bank_path is not orig[6] and ids_online.whole_bank_path is not orig[7]   # 模板库路径也走缓存根（ids_bank／ids_whole_bank）
    assert [p.name for p in setup.placed] == ["pagetype_v1.joblib"]
    assert mp._base("repo", Path(".")) == root and mp._base("repo", Path("."), real=True) == mp.REPO_ROOT
    # 起跑前校验按缓存根核对：清单里 repo 项都对得上
    r = mp.check_files(Path("."), {"items": [i for i in setup.man["items"] if i["root"] == "repo"]})
    assert not r["changed"] and not r["missing"]
    # 换回没钉的册：全部还原
    assert mo.activate(SimpleNamespace(model=None)) is None
    assert (ptm.DEFAULT_MODEL, cc.DEFAULT_CKPT, cc.fingerprint.__defaults__, rr_clf.MODEL_DIR,
            shm.DEFAULT_MODEL, ids_online.unet_path, ids_online.bank_path, ids_online.whole_bank_path) == orig
    assert mp.REPO_OVERRIDE[0] is None


def test_no_drift_no_switch(setup, monkeypatch):
    from open_guji_cv.pagetype_model import model as ptm
    before = ptm.DEFAULT_MODEL
    man = {"digest": "x", "items": [i for i in setup.man["items"] if i["path"] != setup.pt_rel]}
    monkeypatch.setattr(mp, "load_manifest", lambda ws, v: man)
    assert mo.activate(SimpleNamespace(model=1), mb_place()) is None
    assert ptm.DEFAULT_MODEL == before and not setup.placed


def test_worker_init_no_fetch(setup):
    """worker 里不联网：缓存没摆齐时照样指过去（缺的起跑前校验拒跑）。"""
    root = mo.activate(SimpleNamespace(model=2))
    assert root is not None and not setup.placed
    from open_guji_cv.pagetype_model import model as ptm
    assert Path(ptm.DEFAULT_MODEL) != root / setup.pt_rel                # 缓存里没有就不换这一项
    # 起跑前准备（联网）摆齐后再切一次，同一根下这项也换上
    assert mo.activate(SimpleNamespace(model=2), mb_place()) == root
    assert Path(ptm.DEFAULT_MODEL) == root / setup.pt_rel
