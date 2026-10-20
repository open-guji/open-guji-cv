# -*- coding: utf-8 -*-
"""全字表字形向量包（hanzi 库 B2）：版本只认同规格、按字表逐位复现、以字找字取行。不装 torch 也跑。"""
from __future__ import annotations

import hashlib
import io
import json

import numpy as np
import pytest

from open_guji_cv.clustering import emb_pack as E

SPEC = {"ckpt": "glyph_cnn_r5", "ckpt_fp": "aaaaaaaaaaaa", "font_fp": "bbbbbbbbbbbb",
        "code_fp": "cccccccccccc", "extra": []}


def _publish(tmp_path, spec=SPEC, chars="一丁七", failed="丂", dim=4):
    """造一版包：三个文件放进假 blob 缓存，清单写进假 emb 目录。"""
    rng = np.random.default_rng(0)
    mat = rng.standard_normal((len(chars), dim)).astype(np.float32)
    buf = io.BytesIO()
    np.save(buf, mat, allow_pickle=False)
    files = {"vectors.npy": buf.getvalue(), "chars.txt": "".join(c + "\n" for c in chars).encode(),
             "failed.txt": "".join(c + "\n" for c in failed).encode()}
    blobs = tmp_path / "blobs"
    meta = {}
    for name, data in files.items():
        sha = hashlib.sha256(data).hexdigest()
        p = blobs / sha[:2] / f"{sha}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        meta[name] = {"sha256": sha, "bytes": len(data)}
    m = {"version": E.version_of(spec), **spec, "dim": dim, "dtype": "float32", "files": meta}
    emb_dir = tmp_path / "emb"
    emb_dir.mkdir(exist_ok=True)
    (emb_dir / f"{m['version']}.json").write_text(json.dumps(m), encoding="utf-8")
    return m, mat, blobs, emb_dir


def test_version_changes_with_any_spec_field():
    v = E.version_of(SPEC)
    assert v.startswith("emb-")
    for k in ("ckpt_fp", "font_fp", "code_fp"):
        assert E.version_of({**SPEC, k: "000000000000"}) != v          # 重新训练、换字体、改渲染代码都换版本
    assert E.version_of({**SPEC, "extra": ["kangxi:x"]}) != v
    assert E.version_of({**SPEC, "ckpt": "改名不算"}) == v                # 目录名不进版本，按内容认


def test_find_only_returns_same_spec(tmp_path):
    m, _, _, emb_dir = _publish(tmp_path)
    assert E.find(SPEC, emb_dir)["version"] == m["version"]
    assert E.find({**SPEC, "ckpt_fp": "retrained000"}, emb_dir) is None    # 新模型没出包 → 不拿旧向量冒充
    m2, *_ = _publish(tmp_path, spec={**SPEC, "ckpt_fp": "retrained000"})
    assert E.find({**SPEC, "ckpt_fp": "retrained000"}, emb_dir)["version"] == m2["version"]
    assert E.find(SPEC, emb_dir)["version"] == m["version"]                  # 旧版照留


def test_load_and_materialize_reproduces_build_order(tmp_path):
    m, mat, blobs, _ = _publish(tmp_path)
    pk = E.EmbPack.load(m, blob_dir=blobs, fetch=lambda url: pytest.fail("本机有缓存不该下载"))
    assert pk.chars == list("一丁七") and pk.failed == {"丂"}
    calls = []

    def compute(cs):
        calls.append(cs)
        return np.ones((len(cs), 4), np.float32), list(cs)

    got, names = pk.materialize("七丂万一", compute)                     # 丂 渲染失败，产线也跳过
    assert names == ["七", "万", "一"] and calls == [("万",)]
    assert np.array_equal(got[0], mat[2]) and np.array_equal(got[2], mat[0]) and got.dtype == np.float32
    with pytest.raises(KeyError):
        pk.materialize("万")                                                # 包外的字又不给现算 → 不出缺行的索引


def test_load_checks_sha_and_download_flag(tmp_path):
    m, *_ = _publish(tmp_path)
    assert E.EmbPack.load(m, blob_dir=tmp_path / "empty", download=False) is None
    with pytest.raises(ValueError, match="sha256"):
        E.EmbPack.load(m, blob_dir=tmp_path / "empty", fetch=lambda url: b"tampered")


def test_template_bank_takes_rows_from_pack(tmp_path, monkeypatch):
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.review.alt_cands import TemplateBank
    m, mat, blobs, _ = _publish(tmp_path)
    pk = E.EmbPack.load(m, blob_dir=blobs)

    class FakeCnn:
        ckpt = tmp_path / "other.pt"                                        # 不是现役模型：不挂包
        _net = _dev = None

    bank = TemplateBank(FakeCnn())
    assert bank._pack is None
    bank._pack = pk
    built = []
    monkeypatch.setattr(cc, "build_emb_matrix",
                        lambda net, dev, cs, extra, render: (built.append(cs) or
                                                             (np.zeros((len(cs), 4), np.float32), list(cs))))
    got = bank.vectors(["一", "丂", "万"])
    assert np.array_equal(got["一"], mat[0]) and "丂" not in got           # 失败的字不现算
    assert built == [("万",)]                                              # 只有包外的字现场渲染
