"""执行方磁盘：job 目录结束即删，领单前清旧的 job 目录、空间不够就不领单（writes 不碰缓存）。"""
from open_guji_cv.jobs import runner as R


def test_clean_job_dirs_removes_only_job_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", tmp_path)
    (tmp_path / "job1589-a1").mkdir()
    (tmp_path / "job1589-a1" / "x.bin").write_bytes(b"x" * 1000)
    (tmp_path / "job1590-a2").mkdir()
    (tmp_path / "worker.log").write_text("keep")
    (tmp_path / "cache").mkdir()
    R._clean_job_dirs()
    assert not (tmp_path / "job1589-a1").exists()
    assert not (tmp_path / "job1590-a2").exists()
    assert (tmp_path / "worker.log").exists()
    assert (tmp_path / "cache").is_dir()


def test_disk_gate_passes_when_enough_space(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(R, "MIN_FREE_GB", 0)
    assert R._disk_gate() is None


def test_disk_gate_refuses_when_short(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(R, "MIN_FREE_GB", 10 ** 9)
    msg = R._disk_gate()
    assert msg and "不领单" in msg


def test_failed_job_keeps_only_run_log_and_prunes(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(R, "FAILED_LOGS", tmp_path / "failed-logs")
    monkeypatch.setattr(R, "FAILED_LOGS_KEEP", 2)
    for i in range(3):
        d = tmp_path / f"job{i}-a1"
        d.mkdir()
        (d / "run.log").write_text("log")
        (d / "big.bin").write_bytes(b"x" * 100)
        R._retire_dir(d, "failed", i, 1)
        assert not d.exists()
    names = sorted(p.name for p in (tmp_path / "failed-logs").iterdir())
    assert len(names) == 2


def test_succeeded_job_dir_is_removed_entirely(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(R, "FAILED_LOGS", tmp_path / "failed-logs")
    d = tmp_path / "job9-a1"
    d.mkdir()
    (d / "run.log").write_text("log")
    R._retire_dir(d, "succeeded", 9, 1)
    assert not d.exists()
    assert not (tmp_path / "failed-logs").exists()


def test_disk_gate_clears_caches_before_refusing(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "HOME", tmp_path)
    uv = tmp_path / "uv"; uv.mkdir(); (uv / "x").write_text("x")
    monkeypatch.setattr(R, "_CACHES", (uv,))
    monkeypatch.setattr(R, "MIN_FREE_GB", 10 ** 9)
    msg = R._disk_gate(say=lambda *_: None)
    assert msg and "不领单" in msg
    assert not uv.exists()
