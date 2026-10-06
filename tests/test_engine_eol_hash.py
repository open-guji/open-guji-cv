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


def test_comments_and_docstrings_do_not_count(tmp_path, monkeypatch):
    """2026-10-06（overview#413）：改注释、改 docstring 不让产物过期；改代码照样过期。"""
    base = 'def f(x):\n    return x + 1\n\nclass C:\n    y = "#不是注释"\n'
    variants = {
        "cm_base": base,
        "cm_comment": "# 加一行注释\n" + base.replace("return x + 1", "return x + 1  # 行尾注释"),
        "cm_doc": '"""模块说明。"""\n' + base.replace("def f(x):\n", 'def f(x):\n    """函数说明，\n    两行。"""\n'),
        "cm_blank": base.replace("\n\n", "\n\n\n\n"),
        "cm_code": base.replace("x + 1", "x + 2"),
        "cm_str": base.replace('"#不是注释"', '"#改了"'),        # 字符串里的 # 不是注释，改了要算
    }
    for n, t in variants.items():
        _write(tmp_path, n, t)
        sys.modules.pop(n, None)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(E, "_code_hash_cache", {})
    h = {n: E._module_source_hash(n) for n in variants}
    assert h["cm_base"] == h["cm_comment"] == h["cm_doc"] == h["cm_blank"]
    assert h["cm_code"] != h["cm_base"] and h["cm_str"] != h["cm_base"]


def test_code_only_text_whole_package_parses():
    """包里每个模块都能算（不因非法转义、中文、多行字符串出错）。"""
    from pathlib import Path
    root = Path(E.__file__).resolve().parents[1]
    for p in root.rglob("*.py"):
        E.code_only_text(p.read_text(encoding="utf-8"))
