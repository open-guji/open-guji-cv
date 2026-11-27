"""rerun_prep.sh 的 safe_checkout：切 cv 遇未跟踪文件冲突时，只处理报出的文件、带时间戳备份到工作区外、日志记路径、不整仓 clean。

从脚本里抽出 `# >>> safe_checkout` 到 `# <<< safe_checkout` 那段，在临时仓上用 bash 跑。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rerun_prep.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("git") is None, reason="要 bash 和 git")


def _func() -> str:
    m = re.search(r"^# >>> safe_checkout.*?^# <<< safe_checkout$", SCRIPT.read_text(encoding="utf-8"), re.S | re.M)
    assert m, "rerun_prep.sh 里找不到 safe_checkout 段"
    return m.group(0)


def _g(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _run(repo: Path, ref: str, bak: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "GUJI_CHECKOUT_BAK": str(bak)}
    return subprocess.run(["bash", "-c", "set -euo pipefail\n" + _func() + '\nsafe_checkout "$1" "$2"', "x",
                           str(repo), ref], capture_output=True, text=True, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A 不跟踪 models/m.pt、fonts/f.ttf；B 开始跟踪。停在 A，本机有这两个未跟踪文件，另有不冲突的未跟踪文件和目录。"""
    r = tmp_path / "seed"
    r.mkdir()
    _g(r, "init", "-q", "-b", "main")
    _g(r, "config", "user.email", "t@t")
    _g(r, "config", "user.name", "t")
    (r / "a.txt").write_text("a\n")
    _g(r, "add", ".")
    _g(r, "commit", "-qm", "A")
    _g(r, "tag", "A")
    (r / "models").mkdir()
    (r / "models" / "m.pt").write_text("tracked\n")
    (r / "fonts").mkdir()
    (r / "fonts" / "f.ttf").write_text("tracked font\n")
    _g(r, "add", ".")
    _g(r, "commit", "-qm", "B")
    _g(r, "tag", "B")
    _g(r, "checkout", "-q", "A")
    (r / "models").mkdir(exist_ok=True)
    (r / "models" / "m.pt").write_text("local copy\n")
    (r / "fonts").mkdir(exist_ok=True)
    (r / "fonts" / "f.ttf").write_text("local font\n")
    (r / "scratch.log").write_text("keep me\n")
    (r / "cache").mkdir()
    (r / "cache" / "x.bin").write_text("keep\n")
    return r


def test_only_reported_files_touched_no_clean(repo: Path, tmp_path: Path):
    """第 1 条：只动 checkout 报出的冲突文件，别的未跟踪文件和目录原样留着。"""
    r = _run(repo, "B", tmp_path / "bak")
    assert r.returncode == 0, r.stderr
    assert _g(repo, "rev-parse", "HEAD") == _g(repo, "rev-parse", "B")
    assert (repo / "scratch.log").read_text() == "keep me\n"
    assert (repo / "cache" / "x.bin").read_text() == "keep\n"
    assert (repo / "models" / "m.pt").read_text() == "tracked\n"


def test_backup_outside_repo_with_timestamp(repo: Path, tmp_path: Path):
    """第 2 条：先带时间戳备份到工作区外，内容原样。"""
    bak = tmp_path / "bak"
    assert _run(repo, "B", bak).returncode == 0
    stamps = list(bak.iterdir())
    assert len(stamps) == 1 and re.match(r"^\d{8}T\d{6}Z-\d+$", stamps[0].name)
    assert (stamps[0] / "seed" / "models" / "m.pt").read_text() == "local copy\n"
    assert (stamps[0] / "seed" / "fonts" / "f.ttf").read_text() == "local font\n"
    assert not stamps[0].resolve().is_relative_to(repo.resolve())


def test_backup_path_logged(repo: Path, tmp_path: Path):
    """第 3 条：日志（stdout，进执行方 run.log）里记下备份路径和动了哪些文件。"""
    bak = tmp_path / "bak"
    r = _run(repo, "B", bak)
    stamp = next(bak.iterdir())
    assert str(stamp / "seed") in r.stdout
    assert "models/m.pt" in r.stdout and "fonts/f.ttf" in r.stdout


def test_no_conflict_no_backup(repo: Path, tmp_path: Path):
    (repo / "models" / "m.pt").unlink()
    (repo / "fonts" / "f.ttf").unlink()
    r = _run(repo, "B", tmp_path / "bak")
    assert r.returncode == 0 and r.stdout == ""
    assert not (tmp_path / "bak").exists()


def test_other_errors_untouched(repo: Path, tmp_path: Path):
    """不是未跟踪冲突的错照原样失败，什么都不动。"""
    r = _run(repo, "no-such-ref", tmp_path / "bak")
    assert r.returncode != 0
    assert (repo / "models" / "m.pt").read_text() == "local copy\n"
    assert not (tmp_path / "bak").exists()


def test_backup_inside_repo_refused(repo: Path):
    r = _run(repo, "B", repo / "bak")
    assert r.returncode != 0 and "在仓" in r.stderr
    assert (repo / "models" / "m.pt").read_text() == "local copy\n"
