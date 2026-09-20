"""code_hash 不认行尾（2026-09-20）。

仓里 LF/CRLF 混存、git 视为同一内容；另一会话把 `row_boundaries.py` 存回 LF 后
bxgb 从 `column_gate` 起 11 步 54 页全线过期，产物一字未变。
"""
from __future__ import annotations

import sys

from open_guji_cv.core import engine as E

SRC = "X = 1\n\n\ndef f():\n    return X\n"


def _write(tmp_path, name, text):
    (tmp_path / f"{name}.py").write_bytes(text.encode())


def test_crlf_and_lf_copies_hash_the_same(tmp_path, monkeypatch):
    _write(tmp_path, "eol_lf_mod", SRC)
    _write(tmp_path, "eol_crlf_mod", SRC.replace("\n", "\r\n"))
    _write(tmp_path, "eol_other_mod", SRC.replace("X = 1", "X = 2"))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(E, "_code_hash_cache", {})
    for m in ("eol_lf_mod", "eol_crlf_mod", "eol_other_mod"):
        sys.modules.pop(m, None)
    assert E._module_source_hash("eol_lf_mod") == E._module_source_hash("eol_crlf_mod"), \
        "同一份源码只是行尾不同，code_hash 不该变"
    assert E._module_source_hash("eol_lf_mod") != E._module_source_hash("eol_other_mod"), \
        "内容真变了必须变"
