"""中心库数据副本（GUJI-608）：数据迁出工作区、pull／push、版本号比对、glyph.db 导出与重建。

要 ``GUJI_TEST_PG_DSN``（可建删 schema 的 Postgres），不给就跳过。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from test_datastore_pg import DSN, _commit, _git, _line, conn, repo  # noqa: F401  (fixtures)
from test_datastore_pull import _Cache, _tables, _workspace

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not DSN, reason="没有 GUJI_TEST_PG_DSN（测试用 Postgres）")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    for k in ("GUJI_WORKSPACE", "GUJI_GLYPH_DB", "GUJI_GLYPH_STORE", "GUJI_FEEDBACK_DIR"):
        monkeypatch.delenv(k, raising=False)


def _setup(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    files = _workspace(tmp_path)
    c1 = _commit(repo, files, "c1")
    import_commit(conn, repo, c1)
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()})
    return PgSource(conn), files, cache, c1


def _checkout(files, d: Path) -> Path:
    """模拟 guji-workspace 的 git 检出：数据都在工作区里。"""
    for rel, b in files.items():
        p = d / rel[2:]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return d


def _fresh(files, d: Path, src, cache, hooks=None) -> Path:
    """新机器：只有 workspace.yaml 和标记，pull 下来。"""
    from open_guji_cv.datastore.workcopy import pull
    d.mkdir(parents=True)
    (d / "workspace.yaml").write_bytes(files["W/workspace.yaml"])
    (d / ".central.json").write_text('{"ws": "tws", "branch": "main"}')
    pull(src, d, cache=cache, glyph=hooks(d) if hooks else None)
    return d


def _data_files(data: Path) -> dict[str, bytes]:
    return {p.relative_to(data).as_posix(): p.read_bytes() for p in data.rglob("*")
            if p.is_file() and p.name != ".central-state.json"}


def test_migrate_moves_data_out_of_workspace(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.core import workspace as W
    from open_guji_cv.datastore.workcopy import local_changes, migrate
    from open_guji_cv.ops.central_glyph import glyph_hooks, rebuild_db
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    ws = _checkout(files, tmp_path / "ws")
    (ws / "products").mkdir()
    (ws / "products" / "x.json").write_text("{}")
    db = ws / "output" / "glyph.db"
    rebuild_db(ws, ws / "output" / "glyph_store", db)
    db_sha = hashlib.sha256(db.read_bytes()).hexdigest()

    rep = migrate(src, ws, cache=cache, glyph=glyph_hooks(ws))
    assert rep["n_differ"] == 0 and rep["removed_from_workspace"] > 0
    left = sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file())
    assert left == [".central.json", "output/glyph.db", "products/x.json", "workspace.yaml"]
    assert hashlib.sha256(db.read_bytes()).hexdigest() == db_sha        # glyph.db 不动（指纹不跳）

    data = W.central_data_dir("tws")
    assert _data_files(data) == {k[2:]: v for k, v in files.items() if k != "W/workspace.yaml"}
    tok = W.set_workspace_override(str(ws))
    try:
        assert W.feedback_root() == data / "feedback" and W.glyph_store_path() == data / "output" / "glyph_store"
        assert W.books_dir() == data / "books" and W.glyph_db_path() == db
    finally:
        W.reset_workspace_override(tok)
    assert local_changes(ws, glyph_hooks(ws)) == []
    with pytest.raises(SystemExit, match="已经迁过"):
        migrate(src, ws, cache=cache)


def test_migrate_refuses_differences_unless_keep_local(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.cli_db import _pg_conn  # noqa: F401  （入口能导入）
    from open_guji_cv.datastore.workcopy import local_changes, migrate, push
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    ws = _checkout(files, tmp_path / "ws")
    ev = ws / "feedback" / "events" / "b.jsonl"
    ev.write_bytes(ev.read_bytes() + (_line(id="evt_b_2", batch="b", seq=2) + "\n").encode())
    with pytest.raises(SystemExit, match="不一致"):
        migrate(src, ws, cache=cache)
    assert ev.exists() and not (ws / ".central.json").exists()          # 拒绝时什么都没动
    rep = migrate(src, ws, cache=cache, keep_local=True)
    assert rep["pending"] == 1 and not ev.exists()
    assert local_changes(ws) == ["feedback/events/b.jsonl"]
    out = push(conn, ws, actor="t")
    assert out["rev_to"] > out["rev_from"] and local_changes(ws) == []
    assert any(r["id"] == "evt_b_2" for r in src.rows("events", "tws"))


def test_pull_push_between_two_machines(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    from open_guji_cv.datastore.importer import DeleteRefused
    from open_guji_cv.datastore.workcopy import FileDeleteRefused, StaleBase, data_dir, pull, push
    from open_guji_cv.ops.central_glyph import glyph_hooks
    src, files, cache, c1 = _setup(repo, conn, tmp_path)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    a = _fresh(files, tmp_path / "a", src, cache, glyph_hooks)
    da = data_dir(a)
    # 重建的 glyph.db 与直接从 git 的字形库 rebuild 的全部表逐行相同
    from open_guji_cv.clustering.glyph_db import rebuild_from_store
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), c1)
    rebuild_from_store(wt / "W" / "output" / "glyph_store", tmp_path / "ref.sqlite")
    assert _tables(a / "output" / "glyph.db") == _tables(tmp_path / "ref.sqlite")

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    b = _fresh(files, tmp_path / "b", src, cache)
    db_ = data_dir(b)
    assert _data_files(da) == _data_files(db_)

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    (da / "books" / "vol04.yaml").write_bytes(b"id: vol04\n")
    push(conn, a, actor="a")
    rev = src.status()
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    (db_ / "books" / "vol05.yaml").write_bytes(b"id: vol05\n")
    with pytest.raises(StaleBase):
        push(conn, b, actor="b")
    assert src.status() == rev
    with pytest.raises(SystemExit, match="还没推"):
        pull(src, b, cache=cache)
    pull(src, b, cache=cache, force=True)
    assert (db_ / "books" / "vol04.yaml").exists() and not (db_ / "books" / "vol05.yaml").exists()

    (db_ / "books" / "vol03.yaml").unlink()
    with pytest.raises(FileDeleteRefused):
        push(conn, b, actor="b")
    push(conn, b, actor="b", allow_delete=True)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    pull(src, a, cache=cache)
    assert not (da / "books" / "vol03.yaml").exists()                   # 镜像：库里删了本地也删
    (da / "feedback" / "events" / "b.jsonl").write_bytes(b"")
    with pytest.raises(DeleteRefused):
        push(conn, a, actor="a")


def test_glyph_db_changes_are_exported_before_push(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.workcopy import GlyphHooks, data_dir, local_changes, push
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    db = tmp_path / "fake.db"
    db.write_text("v1")
    calls = []

    def export(p, store):
        calls.append(p)
        (Path(store) / "meta.jsonl").write_text('{"key": "k", "value": "' + Path(p).read_text() + '"}\n')
        return {}
    hooks = GlyphHooks(fingerprint=lambda p: Path(p).read_text(), export=export,
                       rebuild=lambda w, s, p: {}, db_path=db)
    ws = _fresh(files, tmp_path / "ws", src, cache, lambda d: hooks)
    assert local_changes(ws, hooks) == [] and not calls                 # 指纹没变不导出
    db.write_text("v2")
    assert local_changes(ws, hooks) == ["output/glyph_store/meta.jsonl"] and calls
    out = push(conn, ws, actor="t", glyph=hooks)
    assert out["rev_to"] > out["rev_from"]
    assert (data_dir(ws) / "output" / "glyph_store" / "meta.jsonl").read_text().count("v2")


def test_not_migrated_workspace_is_refused(tmp_path):
    from open_guji_cv.datastore.workcopy import data_dir
    (tmp_path / "workspace.yaml").write_text("id: x\n")
    with pytest.raises(SystemExit, match="db migrate"):
        data_dir(tmp_path)


def test_sync_merges_appends_from_two_machines(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    from open_guji_cv.datastore.workcopy import SyncConflict, data_dir, local_changes, sync
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    a = _fresh(files, tmp_path / "a", src, cache)
    da = data_dir(a)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    b = _fresh(files, tmp_path / "b", src, cache)
    db_ = data_dir(b)
    rel = "feedback/events/b.jsonl"
    la = _line(id="evt_b_a", batch="b", seq=2)
    lb = _line(id="evt_b_b", batch="b", seq=3)

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    assert sync(src, conn, a, actor="a", cache=cache)["action"] == "nothing"
    (da / rel).write_bytes((da / rel).read_bytes() + (la + "\n").encode())
    (da / "books" / "vol04.yaml").write_bytes(b"id: vol04\n")
    assert sync(src, conn, a, actor="a", cache=cache)["action"] == "push"

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    (db_ / rel).write_bytes((db_ / rel).read_bytes() + (lb + "\n").encode())
    out = sync(src, conn, b, actor="b", cache=cache)
    assert out["action"] == "merged+push" and out["merged"] == [rel]
    assert (db_ / "books" / "vol04.yaml").exists()                      # 库里新的文件拉下来
    assert local_changes(b) == []
    ids = {r["id"] for r in src.rows("events", "tws")}
    assert {"evt_b_1", "evt_b_a", "evt_b_b"} <= ids                     # 两边追加的行都在

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    assert sync(src, conn, a, actor="a", cache=cache)["action"] == "pulled"
    assert (da / rel).read_bytes() == (db_ / rel).read_bytes()

    # 非追加文件两边都改 → 整次停下，本地不动
    (da / "books" / "vol03.yaml").write_bytes(b"id: vol03\nnote: a\n")
    sync(src, conn, a, actor="a", cache=cache)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    (db_ / "books" / "vol03.yaml").write_bytes(b"id: vol03\nnote: b\n")
    with pytest.raises(SyncConflict):
        sync(src, conn, b, actor="b", cache=cache)
    assert (db_ / "books" / "vol03.yaml").read_bytes() == b"id: vol03\nnote: b\n"
    assert not any(p.name.endswith(".sync.tmp") for p in db_.parent.iterdir())


def test_merge_append_keeps_both_tails():
    from open_guji_cv.datastore.workcopy import _merge_append
    assert _merge_append(b"x\na\n", b"x\nb\n") == b"x\nb\na\n"
    assert _merge_append(b"x\na\n", b"x\na\nb\n") == b"x\na\nb\n"
    assert _merge_append(b"", b"") == b""


def test_anchor_patches_round_trip(repo, conn, tmp_path):  # noqa: F811
    """锚图只记在 anchor_patches_meta（不进 source_files）：迁移不该把它们当差异，新机器 pull 要还原出来。"""
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.workcopy import data_dir, local_changes, migrate
    files = _workspace(tmp_path)
    files["W/feedback/anchor_patches/vol03/ab/ab12.png"] = b"\x89PNG anchor"
    import_commit(conn, repo, _commit(repo, files, "c1"))
    src = PgSource(conn)
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()})

    ws = _checkout(files, tmp_path / "ws")
    rep = migrate(src, ws, cache=cache)
    assert rep["n_differ"] == 0
    assert (data_dir(ws) / "feedback/anchor_patches/vol03/ab/ab12.png").read_bytes() == b"\x89PNG anchor"
    assert local_changes(ws) == []

    fresh = _fresh(files, tmp_path / "m2", src, cache)
    assert (data_dir(fresh) / "feedback/anchor_patches/vol03/ab/ab12.png").read_bytes() == b"\x89PNG anchor"
    assert local_changes(fresh) == []
