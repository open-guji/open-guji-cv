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
