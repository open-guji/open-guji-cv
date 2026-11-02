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


def _mk_ws(root, name, pins, *, manifests=()):
    """造一个工作区：books/*.yaml 钉 pins，config/glyph-pack/g<N>/manifest.json 给 manifests。"""
    ws = root / name
    (ws / "books").mkdir(parents=True)
    (ws / "output").mkdir()
    for i, p in enumerate(pins):
        (ws / "books" / f"v{i}.yaml").write_text(f"id: v{i}\nglyph_pin: {p}\n")
    for n in manifests:
        d = ws / "config" / "glyph-pack" / f"g{n}"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text('{"digest": "x"}')
    return ws


def _patch_pins(monkeypatch, tmp_path, pins_by_ws):
    """pins_in_use 不开 cv 引擎：按工作区查表；manifest 按文件在不在。"""
    from open_guji_cv.ops import glyph_snapshot as GS
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(GS, "pins_in_use", lambda ws: {n: ["b"] for n in pins_by_ws[Path(ws)]})


from pathlib import Path  # noqa: E402


def test_prune_keeps_pinned_deletes_rebuildable_old(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path, "wsrepo", [3], manifests=(1, 2, 3))
    for n in (1, 2, 3):
        (ws / "output" / f"glyph-g{n}.db").write_bytes(b"x" * 1000)
    (ws / "output" / "glyph.db").write_bytes(b"live")
    _patch_pins(monkeypatch, tmp_path, {ws: [3]})
    freed = R._prune_glyph_dbs(say=lambda *_: None)
    assert freed == 2000
    assert not (ws / "output" / "glyph-g1.db").exists()
    assert not (ws / "output" / "glyph-g2.db").exists()
    assert (ws / "output" / "glyph-g3.db").exists()
    assert (ws / "output" / "glyph.db").exists()


def test_prune_keeps_old_db_without_manifest(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path, "wsrepo", [3], manifests=(3,))
    (ws / "output" / "glyph-g1.db").write_bytes(b"x")
    _patch_pins(monkeypatch, tmp_path, {ws: [3]})
    assert R._prune_glyph_dbs(say=lambda *_: None) == 0
    assert (ws / "output" / "glyph-g1.db").exists()


def test_prune_keeps_everything_when_pins_unreadable(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path, "wsrepo", [], manifests=(1,))
    (ws / "output" / "glyph-g1.db").write_bytes(b"x")
    from open_guji_cv.ops import glyph_snapshot as GS
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    def boom(_):
        raise RuntimeError("bad yaml")
    monkeypatch.setattr(GS, "pins_in_use", boom)
    assert R._prune_glyph_dbs(say=lambda *_: None) == 0
    assert (ws / "output" / "glyph-g1.db").exists()


def test_prune_finds_nested_book_workspaces(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path / "guji-workspace", "96mid-book", [18], manifests=(1, 18))
    (ws / "output" / "glyph-g1.db").write_bytes(b"x" * 10)
    (ws / "output" / "glyph-g18.db").write_bytes(b"y" * 10)
    _patch_pins(monkeypatch, tmp_path, {ws: [18]})
    assert R._prune_glyph_dbs(say=lambda *_: None) == 10
    assert not (ws / "output" / "glyph-g1.db").exists()
    assert (ws / "output" / "glyph-g18.db").exists()


def test_disk_gate_prunes_old_glyph_dbs(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path, "wsrepo", [2], manifests=(1, 2))
    (ws / "output" / "glyph-g1.db").write_bytes(b"x")
    _patch_pins(monkeypatch, tmp_path, {ws: [2]})
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(R, "MIN_FREE_GB", 0)
    assert R._disk_gate(say=lambda *_: None) is None
    assert not (ws / "output" / "glyph-g1.db").exists()


def test_prune_keep_recent_ignores_yaml_and_manifest(tmp_path, monkeypatch):
    import os
    ws = _mk_ws(tmp_path, "wsrepo", [1, 2, 3, 4, 5])      # 都被钉，且没有任何清单
    for n in range(1, 6):
        f = ws / "output" / f"glyph-g{n}.db"
        f.write_bytes(b"x" * 10)
        os.utime(f, (1000 + n, 1000 + n))
    _patch_pins(monkeypatch, tmp_path, {ws: [1, 2, 3, 4, 5]})
    assert R._prune_glyph_dbs(say=lambda *_: None) == 0             # 缺省档：全在用，不动
    assert R._prune_glyph_dbs(say=lambda *_: None, keep_recent=2) == 30
    left = sorted(p.name for p in (ws / "output").glob("glyph-g*.db"))
    assert left == ["glyph-g4.db", "glyph-g5.db"]


def test_disk_gate_escalates_to_keep_recent_only_when_short(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path, "wsrepo", [1, 2, 3, 4])
    for n in range(1, 5):
        (ws / "output" / f"glyph-g{n}.db").write_bytes(b"x")
    _patch_pins(monkeypatch, tmp_path, {ws: [1, 2, 3, 4]})
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(R, "MIN_FREE_GB", 0)
    monkeypatch.setattr(R, "GLYPH_DB_KEEP_RECENT", 1)
    R._disk_gate(say=lambda *_: None)
    assert len(list((ws / "output").glob("glyph-g*.db"))) == 4      # 空间够，不动
    monkeypatch.setattr(R, "MIN_FREE_GB", 10 ** 9)
    R._disk_gate(say=lambda *_: None)
    assert len(list((ws / "output").glob("glyph-g*.db"))) == 1
