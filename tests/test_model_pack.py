# -*- coding: utf-8 -*-
"""模型系统第一期（`core/model_pack.py`）：模型卡、总号清单、册钉 model: N、补「钉语料的册换模型不过期」缺口。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_guji_cv.core import model_pack as mp


@pytest.fixture
def ws(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "models" / "partition_unet_v2").mkdir(parents=True)
    (repo / "models" / "partition_unet_v2" / "model.pt").write_bytes(b"unet")
    (repo / "models" / "README.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mp, "REPO_ROOT", repo)
    w = tmp_path / "book1"
    (w / "config" / "groups" / "l2model").mkdir(parents=True)
    (w / "config" / "groups" / "l2model" / "jys.json").write_text('{"w": 1}', encoding="utf-8")
    monkeypatch.delenv(mp.DRIFT_ENV, raising=False)
    mp._TOKEN.clear()
    mp._CLEAN.clear()
    return w


def test_collect_cards(ws):
    items = mp.collect(ws)
    by = {i["kind"]: i for i in items}
    assert set(by) == {"partition_unet", "l2_head"}
    assert by["partition_unet"]["level"] == "global" and by["partition_unet"]["owner"] == "global"
    assert by["l2_head"]["level"] == "book" and by["l2_head"]["owner"] == "book1"   # "*" = 所在的书
    assert by["l2_head"]["schema"] == mp.CARD_SCHEMA and len(by["l2_head"]["sha256"]) == 64


def test_build_once_and_bump(ws):
    r = mp.build(ws, note="first")
    assert r["version"] == 1 and mp.versions(ws) == [1]
    assert mp.build(ws)["unchanged"] == 1                       # 内容没变不出新号
    (ws / "config" / "groups" / "l2model" / "jys.json").write_text('{"w": 2}', encoding="utf-8")
    r2 = mp.build(ws)
    assert r2["version"] == 2 and r2["digest"] != mp.load_manifest(ws, 1)["digest"]
    with pytest.raises(ValueError):
        mp.build(ws, version=1)                                 # 清单只写一次


def test_require_clean(ws, monkeypatch):
    mp.build(ws)
    mp.require_model_clean(ws, 1)
    (ws / "config" / "groups" / "l2model" / "jys.json").write_text('{"w": 9}', encoding="utf-8")
    with pytest.raises(mp.ModelDrift):
        mp.require_model_clean(ws, 1)
    monkeypatch.setenv(mp.DRIFT_ENV, "warn")
    mp.require_model_clean(ws, 1)                               # 临时放行
    with pytest.raises(mp.ModelDrift):
        mp.require_model_clean(ws, 7)                           # 没有这号的清单


def test_pinned_group_flow_opt_in(ws, monkeypatch):
    mp.build(ws)
    monkeypatch.setattr("open_guji_cv.core.workspace.workspace_root", lambda: ws)
    assert mp.pinned_group_flow("corpus-v25", SimpleNamespace(model=None)) == "corpus-v25"   # 没钉：逐位不变
    tok = mp.pinned_group_flow("corpus-v25", SimpleNamespace(model=1))
    assert tok == "corpus-v25+" + mp.load_manifest(ws, 1)["digest"]


def test_parse_pin():
    assert mp.parse_pin(None) is None and mp.parse_pin("") is None
    assert mp.parse_pin(3) == 3 and mp.parse_pin("m4") == 4
    with pytest.raises(ValueError):
        mp.parse_pin("x")


def test_fetch_places_missing_files(ws, monkeypatch, tmp_path):
    """二期：清单里缺的文件按 sha 从 R2（这里是假的 BlobCache）取回、放回登记位置；内容不同的不覆盖。"""
    from open_guji_cv.ops import model_blobs as mb
    mp.build(ws)
    unet = mp.REPO_ROOT / "models" / "partition_unet_v2" / "model.pt"
    head = ws / "config" / "groups" / "l2model" / "jys.json"
    blobs = {mp._sha256(unet): unet.read_bytes()}
    unet.unlink()
    head.write_text('{"w": 3}', encoding="utf-8")            # 本机改过：不覆盖

    class FakeCache:
        def __init__(self):
            self.root = tmp_path / "cache"

        def path(self, sha):
            return self.root / sha

        def has(self, sha):
            return self.path(sha).exists()

        def ensure(self, src, shas, ext="png"):
            assert ext == mb.EXT
            self.root.mkdir(exist_ok=True)
            for s in shas:
                if s in blobs:
                    self.path(s).write_bytes(blobs[s])
            return {"missing": [s for s in shas if s not in blobs]}

    import open_guji_cv.datastore.client as dc
    monkeypatch.setattr(dc, "BlobCache", FakeCache)
    monkeypatch.setattr(dc, "WorkerSource", lambda: None)
    r = mb.fetch(ws, 1)
    assert r["placed"] == 1 and unet.read_bytes() == b"unet"
    assert r["differ_not_overwritten"] == ["data:config/groups/l2model/jys.json"]
    assert head.read_text(encoding="utf-8") == '{"w": 3}'


def test_upload_refuses_stale(ws):
    from open_guji_cv.ops import model_blobs as mb
    mp.build(ws)
    plan = mb.upload(ws, 1)
    assert plan["local"] == 2 and not plan["executed"]
    (ws / "config" / "groups" / "l2model" / "jys.json").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        mb.upload(ws, 1)


def test_repo_registry_matches_models_dir():
    """cv 自带的模型表与 models/ 一致：在的文件 sha 要对得上，models/ 里登记了种类的文件都要在表里。
    （models/ 搬出 git 后文件不在，只核在的那些。）改了模型文件忘了 guji model registry 就红。"""
    reg = {i["path"]: i["sha256"] for i in mp.load_registry()}
    assert reg, "config/model-registry.json 缺失或为空"
    for it in mp.repo_items():
        assert reg.get(it["path"]) == it["sha256"], f"{it['path']} 与模型表不符：跑 guji model registry"


def test_fetch_registry_places_missing(monkeypatch, tmp_path):
    from open_guji_cv.ops import model_blobs as mb
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "models" / "rr_clf").mkdir(parents=True)
    f = repo / "models" / "rr_clf" / "meta.json"
    f.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mp, "REPO_ROOT", repo)
    mp.build_registry()
    sha = mp._sha256(f)
    f.unlink()
    assert [i["path"] for i in mp.missing_repo_models()] == ["models/rr_clf/meta.json"]
    monkeypatch.setattr(mb, "_place", lambda todo: (len([p.write_text("{}", encoding="utf-8") for s, p in todo
                                                          if s == sha]), []))
    r = mb.fetch_registry()
    assert r["placed"] == 1 and f.exists() and not mp.missing_repo_models()


def test_provenance_on_cards_not_in_digest(ws):
    (mp.REPO_ROOT / "config").mkdir(exist_ok=True)
    before = mp.items_digest(mp.collect(ws))
    (mp.REPO_ROOT / mp.PROVENANCE).write_text(
        '{"kinds": {"partition_unet": {"script": "train.py", "trained_on": "合成"}}}', encoding="utf-8")
    mp._PROV.clear()
    items = mp.collect(ws)
    unet = next(i for i in items if i["kind"] == "partition_unet")
    assert unet["source"] == {"script": "train.py", "trained_on": "合成"}
    assert mp.items_digest(items) == before                    # 出处不进清单哈希


def test_repo_provenance_covers_every_kind():
    import json
    kinds = json.loads((mp.REPO_ROOT / mp.PROVENANCE).read_text(encoding="utf-8"))["kinds"]
    assert {k.kind for k in mp.KINDS} <= set(kinds), "新模型种类要在 config/model-provenance.json 记出处"


def test_ids_unet_moved_out_of_corpus():
    from open_guji_cv.core.corpus_pin import _not_corpus
    assert _not_corpus("repo", "config/groups/jue/unet.npz")
    assert not _not_corpus("repo", "config/groups/jue/ids_bank.json")
