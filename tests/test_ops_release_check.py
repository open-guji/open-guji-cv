# -*- coding: utf-8 -*-
"""`guji release check` 的机械层：假 git 仓里指纹变化/影响清单列得对，测试差集算得对。

**不 import 真的 `open_guji_cv.core.step`**——`affected_steps` 故意跟 `step_file_map`
分开（见 `ops/release_check.py` 模块头），这里只测前者，用手造的 `step_files` 字典，
不依赖真实 Step 注册表，也就不用啃一整个 STEPS 的 import 链。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from open_guji_cv.ops import release_check as rc


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture
def fake_repo(tmp_path) -> Path:
    repo = tmp_path / "fake-cv"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "a@example.com")
    _git(repo, "config", "user.name", "a")
    (repo / "steps").mkdir()
    (repo / "steps" / "border_detect.py").write_text("VERSION = 1\n", encoding="utf-8")
    (repo / "steps" / "row_segment.py").write_text("VERSION = 1\n", encoding="utf-8")
    (repo / "core_spec.py").write_text("SPEC = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first commit")
    return repo


def test_last_release_tag_none_when_no_tags(fake_repo):
    assert rc.last_release_tag(fake_repo) is None


def test_last_release_tag_picks_newest(fake_repo):
    _git(fake_repo, "tag", "cv-2026.09.01")
    (fake_repo / "steps" / "border_detect.py").write_text("VERSION = 2\n", encoding="utf-8")
    _git(fake_repo, "add", ".")
    _git(fake_repo, "commit", "-q", "-m", "bump border_detect")
    _git(fake_repo, "tag", "cv-2026.09.20")
    assert rc.last_release_tag(fake_repo) == "cv-2026.09.20"


def test_changed_files_between_two_commits(fake_repo):
    old = rc.resolve_rev(fake_repo, "HEAD")
    (fake_repo / "steps" / "row_segment.py").write_text("VERSION = 2\n", encoding="utf-8")
    _git(fake_repo, "add", ".")
    _git(fake_repo, "commit", "-q", "-m", "改 row_segment 的裂列判据")
    new = rc.resolve_rev(fake_repo, "HEAD")
    changed = rc.changed_files(fake_repo, old, new)
    assert changed == ["steps/row_segment.py"]


def test_commit_titles_between_two_commits(fake_repo):
    old = rc.resolve_rev(fake_repo, "HEAD")
    (fake_repo / "steps" / "row_segment.py").write_text("VERSION = 2\n", encoding="utf-8")
    _git(fake_repo, "add", ".")
    _git(fake_repo, "commit", "-q", "-m", "改 row_segment 的裂列判据")
    (fake_repo / "steps" / "border_detect.py").write_text("VERSION = 9\n", encoding="utf-8")
    _git(fake_repo, "add", ".")
    _git(fake_repo, "commit", "-q", "-m", "border_detect 加反色带探测")
    new = rc.resolve_rev(fake_repo, "HEAD")
    titles = rc.commit_titles(fake_repo, old, new)
    assert titles == ["改 row_segment 的裂列判据", "border_detect 加反色带探测"]


def test_affected_steps_hits_only_changed_files():
    step_files = {
        "border_detect": {"steps/border_detect.py", "core_spec.py"},
        "row_segment": {"steps/row_segment.py", "core_spec.py"},
        "column_warp": {"steps/column_warp.py", "core_spec.py"},
    }
    changed = {"steps/row_segment.py"}
    impact = rc.affected_steps(step_files, changed)
    assert impact == {"row_segment": ["steps/row_segment.py"]}


def test_affected_steps_core_spec_change_hits_every_step():
    step_files = {
        "border_detect": {"steps/border_detect.py", "core_spec.py"},
        "row_segment": {"steps/row_segment.py", "core_spec.py"},
    }
    changed = {"core_spec.py"}
    impact = rc.affected_steps(step_files, changed)
    assert set(impact) == {"border_detect", "row_segment"}
    assert impact["border_detect"] == ["core_spec.py"]


def test_affected_steps_empty_when_nothing_hit():
    step_files = {"border_detect": {"steps/border_detect.py"}}
    assert rc.affected_steps(step_files, {"unrelated/file.py"}) == {}


def test_next_version_first_of_day(fake_repo):
    assert rc.next_version(fake_repo, today="2026.09.26") == "cv-2026.09.26"


def test_next_version_bumps_when_same_day_tag_exists(fake_repo):
    _git(fake_repo, "tag", "cv-2026.09.26")
    assert rc.next_version(fake_repo, today="2026.09.26") == "cv-2026.09.26-2"
    _git(fake_repo, "tag", "cv-2026.09.26-2")
    assert rc.next_version(fake_repo, today="2026.09.26") == "cv-2026.09.26-3"


# ── 测试差集（发布唯一的硬门槛）─────────────────────────────────────
def test_diff_test_sets_no_baseline_everything_is_new():
    current = {"failed": ["tests/test_a.py::x"], "skipped": ["tests/test_b.py::y"]}
    d = rc.diff_test_sets(None, current)
    assert d["new_failed"] == ["tests/test_a.py::x"]
    assert d["new_skipped"] == ["tests/test_b.py::y"]
    assert d["regressed"] is True


def test_diff_test_sets_same_as_baseline_not_regressed():
    baseline = {"failed": ["tests/test_a.py::x"], "skipped": []}
    current = {"failed": ["tests/test_a.py::x"], "skipped": []}
    d = rc.diff_test_sets(baseline, current)
    assert d["new_failed"] == []
    assert d["regressed"] is False


def test_diff_test_sets_new_failure_regresses():
    baseline = {"failed": ["tests/test_a.py::x"], "skipped": []}
    current = {"failed": ["tests/test_a.py::x", "tests/test_c.py::z"], "skipped": []}
    d = rc.diff_test_sets(baseline, current)
    assert d["new_failed"] == ["tests/test_c.py::z"]
    assert d["regressed"] is True


def test_diff_test_sets_resolved_failure_is_reported_not_regression():
    baseline = {"failed": ["tests/test_a.py::x", "tests/test_c.py::z"], "skipped": []}
    current = {"failed": ["tests/test_a.py::x"], "skipped": []}
    d = rc.diff_test_sets(baseline, current)
    assert d["resolved_failed"] == ["tests/test_c.py::z"]
    assert d["regressed"] is False


def test_run_test_suite_parses_failed_and_skipped(tmp_path):
    """真跑一次 pytest（子进程），在一个只有假测试的临时目录上——不碰这个仓自己的 tests/。"""
    import sys as _sys

    fake_tests = tmp_path / "fake_tests"
    fake_tests.mkdir()
    (fake_tests / "test_fake.py").write_text(
        "import pytest\n"
        "def test_ok(): assert True\n"
        "def test_boom(): assert False\n"
        "@pytest.mark.skip(reason='占位')\n"
        "def test_skip_me(): pass\n",
        encoding="utf-8",
    )
    result = rc.run_test_suite(tmp_path, python=_sys.executable, tests_dir="fake_tests/")
    assert result["failed"] == ["fake_tests.test_fake::test_boom"]
    assert result["skipped"] == ["fake_tests.test_fake::test_skip_me"]
    assert result["returncode"] != 0


def test_release_check_first_release_does_not_gate_on_test_result(fake_repo):
    """没有 `cv-*` tag、没有 `ops/baseline_tests.json`——首次发布，`regressed` 必须是
    `False`，否则第一版永远发不出去（见 `release_check` 里 `first_release` 那段）。"""
    res = rc.release_check(fake_repo, "HEAD", run_tests=False)
    assert res.old_tag is None
    assert res.test_diff["regressed"] is False
    assert res.test_diff["first_release"] is True
    assert "首次发布" in res.draft


def test_render_release_draft_contains_key_sections():
    draft = rc.render_release_draft(
        version="cv-2026.09.26", old_tag="cv-2026.09.20", new_rev="abc1234",
        titles=["修 row_segment 裂列"], impact={"row_segment": ["steps/row_segment.py"]},
        test_diff={"new_failed": [], "new_skipped": [], "resolved_failed": ["tests/test_old.py::z"]},
        rollback_target="cv-2026.09.20")
    assert "## cv-2026.09.26" in draft
    assert "row_segment" in draft
    assert "cv-2026.09.20" in draft
    assert "本轮修复：tests/test_old.py::z" in draft
