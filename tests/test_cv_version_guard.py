# -*- coding: utf-8 -*-
"""GUJI-577：manifest 记 cv_version／cv_commit；册配置固定版本与装的不符时 step／pipeline 拒跑。"""

from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv import cli_v2
from open_guji_cv.core import cv_version as cvv
from open_guji_cv.core.book import BookSpec, load_book
from open_guji_cv.core.engine import Engine, code_hash
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.manifest import Manifest
from open_guji_cv.products.store import ProductStore


# ── 版本号口径 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("s,want", [
    ("v0.3.0-0-g" + "a" * 40, "0.3.0"),
    ("v0.3.0-2-g" + "b" * 40, "0.3.1.dev2+g" + "b" * 12),       # 下一个 PATCH 的 dev 号＋12 位 hash
    ("v10.20.30-15-gabc1234", "10.20.31.dev15+gabc1234"),
    ("cv-v0.1.0-3-gabc", None),
    ("garbage", None),
])
def test_parse_describe(s, want):
    assert cvv.parse_describe(s) == want


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


def test_describe_on_real_git(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "a")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v0.3.0", "-m", "x")
    ver, commit = cvv.describe.__wrapped__(tmp_path)
    assert ver == "0.3.0" and len(commit) == 40
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "b")
    # rc tag 不算正式版本
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v0.4.0-rc.1", "-m", "x")
    ver, commit = cvv.describe.__wrapped__(tmp_path)
    assert ver == f"0.3.1.dev1+g{commit[:12]}"
    assert not cvv.is_formal(ver) and cvv.is_formal("0.3.0")


def test_describe_without_tags_records_hash(tmp_path):
    """浅克隆／没拉 tag：describe 失败也要记得是哪个提交，不再记空。"""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "a")
    ver, commit = cvv.describe.__wrapped__(tmp_path)
    assert ver == f"dev+g{commit[:12]}" and not cvv.is_formal(ver)


def test_describe_dirty_and_foreign_repo(tmp_path):
    repo = tmp_path / "cv"
    (repo / "open_guji_cv").mkdir(parents=True)
    (repo / "open_guji_cv" / "a.py").write_text("x = 1\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v0.3.0", "-m", "x")
    assert cvv.describe.__wrapped__(repo)[0] == "0.3.0"
    (repo / "notes.md").write_text("未跟踪、也不在 open_guji_cv/ 下，不算改动")
    assert cvv.describe.__wrapped__(repo)[0] == "0.3.0"
    (repo / "open_guji_cv" / "a.py").write_text("x = 2\n")
    assert cvv.describe.__wrapped__(repo)[0] == "0.3.0+dirty"
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "b")
    (repo / "open_guji_cv" / "a.py").write_text("x = 3\n")
    ver, commit = cvv.describe.__wrapped__(repo)
    assert ver == f"0.3.1.dev1+g{commit[:12]}.dirty"
    # 包目录在外层 git 仓的子目录里（不是仓根）：不读外层仓的 HEAD
    sub = repo / "open_guji_cv"
    ver, commit = cvv.describe.__wrapped__(sub)
    assert commit is None


def test_mismatch_explains_dirty_and_shallow(monkeypatch):
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("0.3.0+dirty", "d" * 40))
    assert "没提交的改动" in cvv.mismatch("0.3.0")
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("dev+g" + "d" * 12, "d" * 40))
    assert "浅克隆" in cvv.mismatch("0.3.0")
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("0.3.1.dev2+g" + "d" * 12 + ".dirty", "d" * 40))
    assert "没提交的改动" in cvv.mismatch("0.3.0")


def test_mismatch(monkeypatch):
    # installed=None 表示「自己去探装的版本」；固定成探不到，免得结果随检出的 tag 变
    monkeypatch.setattr(cvv, "describe", lambda repo=None: (None, None))
    assert cvv.mismatch(None, "0.3.0") is None
    assert cvv.mismatch("0.3.0", "0.3.0") is None
    assert cvv.mismatch("v0.3.0", "0.3.0") is None
    assert "0.3.1.dev2+gabc" in cvv.mismatch("0.3.0", "0.3.1.dev2+gabc")
    assert "GUJI_DATA_BRANCH=exp/" in cvv.mismatch("0.3.0", "0.3.1.dev2+gabc")
    assert "未知版本" in cvv.mismatch("0.3.0", None)


# ── 册配置字段 ────────────────────────────────────────────────────────
def test_book_yaml_cv_version(tmp_path):
    (tmp_path / "b1.yaml").write_text('id: b1\ntitle: t\nraw_dir: raw\ncv_version: "0.3.0"\n',
                                      encoding="utf-8")
    (tmp_path / "b2.yaml").write_text("id: b2\ntitle: t\nraw_dir: raw\n", encoding="utf-8")
    assert load_book("b1", books_dir=tmp_path).cv_version == "0.3.0"
    assert load_book("b2", books_dir=tmp_path).cv_version is None


def test_cv_version_not_in_any_fingerprint():
    """新字段与新模块都不进 19 步的 code_hash／book_deps。"""
    for sid, st in STEPS.items():
        assert "cv_version" not in (st.spec.book_deps or ())
        assert "open_guji_cv.core.cv_version" not in st.spec.code_deps, sid
    assert all(code_hash(s) for s in STEPS.values())


# ── manifest 记版本 ───────────────────────────────────────────────────
def test_manifest_records_cv_version(tmp_path, monkeypatch):
    import open_guji_cv.core.engine as eng_mod
    monkeypatch.setattr(cvv, "manifest_fields",
                        lambda: {"cv_version": "0.3.0+1", "cv_commit": "c" * 40})
    raw = tmp_path / "raw"
    raw.mkdir()
    cv2.imwrite(str(raw / "1.png"), np.zeros((20, 20), np.uint8))
    book = BookSpec(id="tcv", title="t", raw_dir=raw)
    sid = "border_detect"
    pl = Pipeline(id="tcvp", title="t", steps=[sid])
    eng = Engine(book, pl, store=ProductStore(tmp_path / "p"), cache=ImageCache(tmp_path / "c"),
                 log=lambda s: None)
    assert eng._cv == {"cv_version": "0.3.0+1", "cv_commit": "c" * 40, "db_rev": None}   # 没工作区：无中心库 rev
    eng._cv["cv_override"] = "exp-branch:exp/GUJI-1-t"                                     # 护栏放行时补
    eng.run(steps=[sid], pages=[1])
    line = (tmp_path / "p" / "tcv" / sid / "_manifest.jsonl")
    rows = [json.loads(x) for x in line.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows and all(r["cv_version"] == "0.3.0+1" and r["cv_commit"] == "c" * 40 for r in rows)
    assert all(r["cv_override"] == "exp-branch:exp/GUJI-1-t" for r in rows)
    # 读回不丢字段；老条目（没有这两个键）读成 None
    m = Manifest(line)
    assert m.get("p0001").cv_version == "0.3.0+1"
    old = tmp_path / "old.jsonl"
    old.write_text(json.dumps({"key": "p0001", "fingerprint": "x"}) + "\n", encoding="utf-8")
    assert Manifest(old).get("p0001").cv_version is None
    assert eng_mod  # 引用一下，免 lint


def test_manifest_records_config_overrides(tmp_path, monkeypatch):
    """`--override`（环境变量 GUJI_BOOK_OVERRIDE）的原文记进每条 manifest；没覆盖时没有这个键（manifest 不变）。"""
    monkeypatch.setattr(cvv, "manifest_fields", lambda: {"cv_version": "0.3.0+1", "cv_commit": "c" * 40})
    monkeypatch.setenv("GUJI_BOOK_OVERRIDE", '{"corpus": 23}')
    raw = tmp_path / "raw"
    raw.mkdir()
    cv2.imwrite(str(raw / "1.png"), np.zeros((20, 20), np.uint8))
    book = BookSpec(id="tcv2", title="t", raw_dir=raw)
    sid = "border_detect"
    eng = Engine(book, Pipeline(id="tcvp2", title="t", steps=[sid]), store=ProductStore(tmp_path / "p"),
                 cache=ImageCache(tmp_path / "c"), log=lambda s: None)
    assert eng._cv["config_overrides"] == '{"corpus": 23}'
    eng.run(steps=[sid], pages=[1])
    line = tmp_path / "p" / "tcv2" / sid / "_manifest.jsonl"
    assert Manifest(line).get("p0001").config_overrides == '{"corpus": 23}'


# ── CLI 护栏 ──────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_override_env(monkeypatch):
    monkeypatch.delenv(cvv.OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(cvv, "isolated_branch", lambda: None)


def test_guard_refuses_and_allows(monkeypatch, capsys):
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("0.3.1.dev2+g" + "d" * 12, "d" * 40))
    book = SimpleNamespace(cv_version="0.3.0")
    with pytest.raises(SystemExit) as e:
        cli_v2._guard_cv_version(book)
    assert e.value.code == 2
    assert "cv_version=0.3.0" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:                  # --allow-cv-mismatch 不写理由不放行
        cli_v2._guard_cv_version(book, allow=True)
    assert e.value.code == 2 and "--why" in capsys.readouterr().err
    eng = SimpleNamespace(_cv={"cv_version": "x", "cv_override": None})
    cli_v2._guard_cv_version(book, allow=True, why="核对 vol05", eng=eng)   # 放行但提醒，理由记进 manifest
    assert "⚠️" in capsys.readouterr().err
    assert eng._cv["cv_override"] == "核对 vol05" and os.environ[cvv.OVERRIDE_ENV] == "核对 vol05"
    eng2 = SimpleNamespace(_cv={})
    cli_v2._guard_cv_version(book, allow=True, eng=eng2)  # 逐步子进程：理由从环境变量继承
    assert eng2._cv["cv_override"] == "核对 vol05"
    capsys.readouterr()
    cli_v2._guard_cv_version(book, warn_only=True)
    assert "⚠️" in capsys.readouterr().err
    cli_v2._guard_cv_version(SimpleNamespace(cv_version=None))   # 没固定：不出声
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("0.3.0", "d" * 40))
    cli_v2._guard_cv_version(book)                        # 一致：不出声
    assert capsys.readouterr().err == ""


def test_guard_auto_allows_on_exp_branch(monkeypatch, capsys):
    """中心库实验分支上（产物落分支自己的目录）：钉版册用 dev 代码跑只提醒，manifest 记分支。"""
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("0.3.1.dev2+g" + "d" * 12, "d" * 40))
    monkeypatch.setattr(cvv, "isolated_branch", lambda: "exp/GUJI-1-try")
    eng = SimpleNamespace(_cv={})
    cli_v2._guard_cv_version(SimpleNamespace(cv_version="0.3.0"), eng=eng)
    assert "⚠️" in capsys.readouterr().err
    assert eng._cv["cv_override"] == "exp-branch:exp/GUJI-1-try"
    cli_v2._guard_cv_version(SimpleNamespace(cv_version=None, freeze=FZ), eng=eng)   # 冻结册同样放行
    assert "⚠️" in capsys.readouterr().err


def test_isolated_branch_needs_isolated_products(tmp_path, monkeypatch):
    """只有产物真随分支换了目录才算隔离：GUJI_PRODUCTS_DIR 显式指定、没迁中心库的工作区都不算。"""
    monkeypatch.undo()                                     # 去掉 autouse 的替身，测真函数
    from open_guji_cv.core import workspace as W
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setattr(W, "_branch_local", lambda rel: tmp_path / "exp" / rel)
    monkeypatch.setattr(W, "active_branch", lambda ws=None: "exp/GUJI-1-try")
    assert cvv.isolated_branch() == "exp/GUJI-1-try"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "p"))
    assert cvv.isolated_branch() is None
    monkeypatch.delenv("GUJI_PRODUCTS_DIR")
    monkeypatch.setattr(W, "_branch_local", lambda rel: None)
    assert cvv.isolated_branch() is None


def test_isolated_argv_passes_allow_flag():
    args = SimpleNamespace(book="b", pipeline="p", pages="all", force=False, stop_on_error=False,
                           params=None, jobs=None, allow_sample_db=False, allow_cv_mismatch=True,
                           why="核对")
    argv = cli_v2.isolated_step_argv(args, "s", "/ws")
    assert "--allow-cv-mismatch" in argv and argv[argv.index("--why") + 1] == "核对"


# ── 冻结册护栏（M10·D7，GUJI-694）────────────────────────────────────
FZ = {"at": "1.0.0", "snapshot": "snap/x/vol01/T1", "cv_commit": "a" * 40, "cv_version": "0.4.5"}


def test_frozen_mismatch_by_commit():
    assert cvv.frozen_mismatch(FZ, installed_commit="a" * 40, installed_version="0.4.5+3") is None   # 冻结提交在分支上
    msg = cvv.frozen_mismatch(FZ, installed_commit="b" * 40, installed_version="0.4.7")
    assert msg and "已冻结" in msg and "aaaaaaaaaaaa" in msg
    assert "没提交的改动" in cvv.frozen_mismatch(FZ, installed_commit="a" * 40, installed_version="0.4.5+3+dirty")


def test_frozen_mismatch_by_version_and_not_frozen():
    fz = {"snapshot": "snap/x", "cv_version": "v0.4.5"}
    assert cvv.frozen_mismatch(fz, installed_commit="c" * 40, installed_version="0.4.5") is None
    assert cvv.frozen_mismatch(fz, installed_commit="c" * 40, installed_version="0.4.7")
    assert cvv.frozen_mismatch({}, installed_commit="c" * 40, installed_version="0.4.7") is None
    assert cvv.frozen_mismatch({"cv_commit": "a" * 40}) is None          # 没有快照不算冻结


def test_guard_refuses_frozen_book_without_top_level_version(monkeypatch, capsys):
    """vol01 现状：顶层没写 cv_version、只有 freeze 段——以前在 main 上照样能跑。"""
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("0.4.7", "b" * 40))
    book = SimpleNamespace(cv_version=None, freeze=FZ)
    with pytest.raises(SystemExit) as e:
        cli_v2._guard_cv_version(book)
    assert e.value.code == 2 and "已冻结" in capsys.readouterr().err
    cli_v2._guard_cv_version(book, allow=True, why="试")
    assert "⚠️" in capsys.readouterr().err
    monkeypatch.setattr(cvv, "describe", lambda repo=None: ("0.4.5+3", "a" * 40))
    cli_v2._guard_cv_version(book)
    assert capsys.readouterr().err == ""


def test_textsrc_keeps_dev_version_whole():
    """book-text CHANGES 里写的 dev 版本整段读出，不截成三段冒充正式版。"""
    from open_guji_cv.opinions.textsrc import _CV_VER
    assert _CV_VER.search("cv v0.5.9 重跑").group(1) == "v0.5.9"
    assert _CV_VER.search("cv 0.5.10.dev12+g1a2b3c4d5e6f 重跑").group(1) == "0.5.10.dev12+g1a2b3c4d5e6f"
    assert _CV_VER.search("cv dev+g1a2b3c4d5e6f").group(1) == "dev+g1a2b3c4d5e6f"
