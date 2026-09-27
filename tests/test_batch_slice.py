"""`utils.batch_slice.batch_active()` 回归（任务书-K-控制台常驻内存，2026-09-28）。

只测这一个新函数：`enter_batch_slice()` 已有的行为不动。
"""
from __future__ import annotations

from open_guji_cv.utils.batch_slice import batch_active


def _write_cgroup(proc_dir, pid: str, line: str) -> None:
    d = proc_dir / pid
    d.mkdir()
    (d / "cgroup").write_text(line, encoding="utf-8")


def test_batch_active_true_when_some_pid_is_in_the_slice(tmp_path):
    _write_cgroup(tmp_path, "123",
                  "0::/user.slice/user-0.slice/user@0.service/guji-batch.slice/guji-pipeline-123.scope\n")
    assert batch_active(tmp_path) is True


def test_batch_active_false_when_no_pid_is_in_the_slice(tmp_path):
    _write_cgroup(tmp_path, "42", "0::/user.slice/user-0.slice/user@0.service/app.slice/foo.service\n")
    assert batch_active(tmp_path) is False


def test_batch_active_false_when_proc_dir_missing(tmp_path):
    assert batch_active(tmp_path / "does-not-exist") is False


def test_batch_active_ignores_unreadable_cgroup_file(tmp_path):
    """一个进程在检查瞬间退出（`cgroup` 文件读不到）不该让整个判断报错——
    继续看下一个 pid，读不到就当它跟自己无关。"""
    d = tmp_path / "99"
    d.mkdir()
    # 不写 cgroup 文件：模拟 read_text() 抛 FileNotFoundError/OSError
    _write_cgroup(tmp_path, "100",
                  "0::/user.slice/guji-batch.slice/guji-step-100.scope\n")
    assert batch_active(tmp_path) is True


def test_batch_active_ignores_non_pid_entries(tmp_path):
    # "self" 不是纯数字目录名，必须被跳过——否则会把 /proc/self 误判成进程
    d = tmp_path / "self"
    d.mkdir()
    (d / "cgroup").write_text("0::/user.slice/guji-batch.slice/x.scope\n", encoding="utf-8")
    assert batch_active(tmp_path) is False
