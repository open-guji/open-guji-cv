# -*- coding: utf-8 -*-
"""书级代码（core/book_code.py，2026-11-09）：书仓 code/ 挂载、覆盖、指纹、钉版本、版本简写。"""
import json
import shutil
from pathlib import Path

import pytest

from open_guji_cv.core import book_code as BC
from open_guji_cv.core import engine as E
from open_guji_cv.core import seg_set as S
from open_guji_cv.core.engine import code_hash
from open_guji_cv.core.step import STEPS
from open_guji_cv.core.workspace import reset_workspace_override, set_workspace_override
from tests.helpers import make_book

REPO = Path(__file__).resolve().parents[1]
SIKU = "open_guji_cv.impl.keben"


def _abs_src(rel: str) -> str:
    """cv 里的套书模块改成书仓写法：相对 import 换成绝对的（书级代码只许 import open_guji_cv.seg 等公开面）。"""
    src = (REPO / rel).read_text(encoding="utf-8")
    return (src.replace("from ...seg", "from open_guji_cv.seg").replace("from ...core", "from open_guji_cv.core")
            .replace("from . import jiazhu_split", "from open_guji_cv.impl.keben import jiazhu_split"))


@pytest.fixture
def ws(tmp_path):
    """一个空工作区；用完清掉指纹缓存（书级模块名进了缓存）。"""
    tok = set_workspace_override(str(tmp_path))
    yield tmp_path
    reset_workspace_override(tok)
    BC._CACHE.clear()
    E._code_hash_cache.clear()
    E._raw_hash_cache.clear()


def _code(ws: Path, yaml_text: str, files: dict[str, str] | None = None) -> Path:
    d = ws / "code"
    d.mkdir(exist_ok=True)
    (d / "code.yaml").write_text(yaml_text, encoding="utf-8")
    for k, v in (files or {}).items():
        (d / k).parent.mkdir(parents=True, exist_ok=True)
        (d / k).write_text(v, encoding="utf-8")
    return d


def _steps():
    import open_guji_cv.steps  # noqa: F401
    return STEPS


def test_no_code_dir_is_noop(ws):
    assert BC.load() is None
    assert S.resolve(make_book(), f"{SIKU}.row_boundaries") == f"{SIKU}.row_boundaries"


def test_empty_code_runs_like_default(ws):
    """code/ 只有 code.yaml、没写 overrides：全走缺省实现，各步代码指纹与没有 code/ 时逐位相同。"""
    st = _steps()
    before = {sid: code_hash(st[sid], book=make_book()) for sid in ("border_detect", "row_segment", "cell_shrink")}
    _code(ws, "name: dianben\nbase: keben\n")
    b = make_book()
    assert S.seg_set_of(b) == "dianben"
    for sid, h in before.items():
        assert code_hash(st[sid], book=b) == h
    assert S.seg_set_params("dianben") == {}


def test_override_from_code_dir(ws):
    """书仓覆盖 row_boundaries：模块按 guji_book.<name>.<模块> 挂上、row_segment 指纹变成书自己的；别的步不变。"""
    src = _abs_src("open_guji_cv/impl/keben/row_boundaries.py")
    _code(ws, "name: testbook\nbase: keben\noverrides:\n  keben.row_boundaries: row_boundaries\n",
          {"row_boundaries.py": src + "\nX_TEST = 1\n"})
    st = _steps()
    b = make_book()
    assert S.resolve(b, f"{SIKU}.row_boundaries") == "guji_book.testbook.row_boundaries"
    import importlib
    m = importlib.import_module("guji_book.testbook.row_boundaries")
    assert m.X_TEST == 1
    assert code_hash(st["row_segment"], book=b) != code_hash(st["row_segment"])
    assert code_hash(st["border_detect"], book=b) == code_hash(st["border_detect"])


def test_equiv_yaml_forked_keeps_fingerprint(ws):
    """书仓 equiv.yaml 登记分叉：复制没改过就按原模块名、原哈希进指纹（L0）。"""
    import hashlib
    src = _abs_src("open_guji_cv/impl/keben/row_boundaries.py")
    h = E._module_source_hash(f"{SIKU}.row_boundaries")
    new = hashlib.sha256(E.code_only_text(src).encode()).hexdigest()     # 只改了 import 路径：登 entries 换回原哈希
    _code(ws, "name: forkbook\nbase: keben\noverrides:\n  keben.row_boundaries: row_boundaries\n",
          {"row_boundaries.py": src,
           "equiv.yaml": (f"forked:\n  row_boundaries: {{from: {SIKU}.row_boundaries, hash: {h}}}\n"
                          f"entries:\n  - {{module: row_boundaries, new: {new}, old: {h}}}\n")})
    st = _steps()
    assert code_hash(st["row_segment"], book=make_book()) == code_hash(st["row_segment"])


def test_explicit_other_seg_set_ignores_code_dir(ws):
    _code(ws, "name: other\nbase: keben\n")
    assert S.seg_set_of(make_book(seg_set="siku_zongmu")) == "siku_zongmu"
    assert S.validate_seg_set("other") == "other"
    with pytest.raises(ValueError):
        S.validate_seg_set("nope")


def test_bad_code_yaml_rejected(ws):
    _code(ws, "name: Bad-Name\n")
    with pytest.raises(BC.BookCodeError):
        BC.load()


def test_override_missing_file_rejected(ws):
    _code(ws, "name: x\noverrides:\n  keben.border: border\n")
    with pytest.raises(BC.BookCodeError, match="不存在"):
        BC.load()


def test_release_and_drift(ws):
    root = _code(ws, "name: rel\nbase: keben\n", {"a.py": "A = 1\n"})
    n, p = BC.make_release(root, cv_version="0.7.0")
    assert n == 1 and json.loads(p.read_text())["files"]["a.py"]
    with pytest.raises(BC.BookCodeError, match="完全相同"):
        BC.make_release(root, cv_version="0.7.0")
    assert BC.drift(root, 1) == []
    (root / "a.py").write_text("A = 2\n")
    assert BC.drift(root, 1) == ["改了 a.py"]
    b = make_book()
    b.code = 1
    with pytest.raises(BC.BookCodeError, match="与 k1 不符"):
        BC.require_clean(b)
    n2, _ = BC.make_release(root, cv_version="0.7.0")
    assert n2 == 2
    b.code = 2
    BC.require_clean(b)
    assert BC.label(b) == "k2"


def test_pin_without_code_dir_rejected(ws):
    b = make_book()
    b.code = 3
    with pytest.raises(BC.BookCodeError, match="没有 code/"):
        BC.require_clean(b)


def test_parse_pin():
    assert BC.parse_pin(None) is None
    assert BC.parse_pin(3) == 3 and BC.parse_pin("k3") == 3
    with pytest.raises(ValueError):
        BC.parse_pin("x3")


def test_lib_pins_shorthand():
    from open_guji_cv.core.lib_pins import expand_layer, format_pins, parse
    assert parse("cv0.7.0-c31-g19-m2-k3") == {"cv_version": "0.7.0", "corpus": 31, "glyph_pin": 19,
                                               "model": 2, "code": 3}
    assert expand_layer({"pin": "c31-k3", "x": 1}) == {"x": 1, "corpus": 31, "code": 3}
    assert expand_layer({"pin": "g19", "glyph_pin": "g19"}) == {"glyph_pin": 19}
    with pytest.raises(ValueError, match="不一致"):
        expand_layer({"pin": "g19", "glyph_pin": 18})
    with pytest.raises(ValueError):
        parse("c31-x2")
    assert format_pins(cv="v0.7.0", corpus=31, glyph="g-82293e", model=2, code=3) == "cv0.7.0-c31-g-82293e-m2-k3"


def test_pin_shorthand_in_book_yaml(tmp_path, monkeypatch):
    """册 yaml 写 pin: 简写，load_book 展开成各键；基础配置写的被册层压掉。"""
    from open_guji_cv.core.book import load_book
    books = tmp_path / "books"
    books.mkdir()
    (books / "v1.yaml").write_text("id: v1\nraw_dir: /tmp\npin: c31-g19-m2-k3\n", encoding="utf-8")
    b = load_book("v1", books)
    assert (b.corpus, b.glyph_pin, b.model, b.code) == (31, 19, 2, 3)


def test_check_cv_range():
    bc = BC.BookCode(root=Path("."), name="x", base="keben", cv=">=0.6.31")
    assert BC.check_cv(bc, "0.6.31") is None and BC.check_cv(bc, "0.7.0") is None
    assert "要求" in BC.check_cv(bc, "0.6.30")
    assert BC.check_cv(bc, "0.6.31.dev3+g931422e.dirty") is None      # 开发检出不拦
