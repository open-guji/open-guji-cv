"""跨机器指纹：内容相同、mtime 不同 → 指纹必须相同（2026-09-27，云端算产物运服务器）。"""
import os

import pytest

from open_guji_cv.steps.context_decide import corpus_fingerprint


def test_corpus_fingerprint_ignores_mtime(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("天地玄黃", encoding="utf-8")
    a = corpus_fingerprint([str(p)])
    os.utime(p, ns=(1_000_000_000, 1_000_000_000))
    assert corpus_fingerprint([str(p)]) == a
    p.write_text("天地玄黄", encoding="utf-8")
    assert corpus_fingerprint([str(p)]) != a


def test_ckpt_fingerprint_ignores_mtime(tmp_path):
    pytest.importorskip("torch")
    from open_guji_cv.utils.cut_select import ckpt_fingerprint
    p = tmp_path / "m.pt"
    p.write_bytes(b"\x00" * 1024)
    a = ckpt_fingerprint(p)
    assert len(a) == 12
    os.utime(p, ns=(1_000_000_000, 1_000_000_000))
    assert ckpt_fingerprint(p) == a
    p.write_bytes(b"\x01" * 1024)
    assert ckpt_fingerprint(p) != a


def test_real_proto_fingerprint_ignores_mtime(tmp_path):
    """真刻例多原型档的 `instances/*.jsonl` 指纹（5-b 转正二，2026-09-27，同一坑）：
    云端跑批算好的 `glyph_store` 运到服务器，文件内容一字不差、mtime 对不上，
    `rare_candidates` 不该被判过期。"""
    from open_guji_cv.clustering.cnn_candidates import real_proto_fingerprint

    store = tmp_path / "glyph_store"
    (store / "instances").mkdir(parents=True)
    jf = store / "instances" / "vol01.jsonl"
    jf.write_text('{"label": "一", "instance_id": "vol01:1:1:1", "label_status": "human"}\n',
                 encoding="utf-8")
    specs = (f"store:{store}",)

    a = real_proto_fingerprint(specs, enabled=True)
    assert a
    os.utime(jf, ns=(1_000_000_000, 1_000_000_000))
    assert real_proto_fingerprint(specs, enabled=True) == a, "只改 mtime 不改内容，指纹不该变"
    jf.write_text('{"label": "二", "instance_id": "vol01:1:1:1", "label_status": "human"}\n',
                 encoding="utf-8")
    assert real_proto_fingerprint(specs, enabled=True) != a, "内容变了指纹该变"


def test_gw_catalog_fingerprint_ignores_mtime(tmp_path):
    """GlyphWiki 变体形目录指纹（T4 变体形转正，2026-09-27，同一坑）：`enabled=True`
    时按内容 sha256，不按 `(大小, mtime)`；`enabled=False`（缺省关，不管文件在不在）
    一律短路回空串——这不是新行为，是补上此前 `full_fingerprint()` 不看 `GW_ENABLED`
    就把这段并进去的那个缺口（见 `cnn_candidates.gw_catalog_fingerprint` 模块头）。"""
    from open_guji_cv.clustering.cnn_candidates import gw_catalog_fingerprint

    p = tmp_path / "catalog_64.npz"
    p.write_bytes(b"\x00" * 1024)

    assert gw_catalog_fingerprint(p, enabled=False) == "", "关着一律空串，不管文件在不在"

    a = gw_catalog_fingerprint(p, enabled=True)
    assert a
    os.utime(p, ns=(1_000_000_000, 1_000_000_000))
    assert gw_catalog_fingerprint(p, enabled=True) == a, "只改 mtime 不改内容，指纹不该变"
    p.write_bytes(b"\x01" * 1024)
    assert gw_catalog_fingerprint(p, enabled=True) != a, "内容变了指纹该变"
