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
