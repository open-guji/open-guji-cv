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
    from open_guji_cv.datastore.workcopy import (
        FileDeleteRefused,
        StaleBase,
        data_dir,
        pull,
        push,
    )
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
    from open_guji_cv.datastore.workcopy import (
        GlyphHooks,
        data_dir,
        local_changes,
        push,
    )
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    db = tmp_path / "fake.db"
    db.write_text("v1")
    calls = []

    def export(p, store):
        calls.append(p)
        (Path(store) / "meta.jsonl").write_text('{"key": "k", "value": "' + Path(p).read_text() + '"}\n')
        return {}
    hooks = GlyphHooks(fingerprint=lambda p: Path(p).read_text(), export=export,
                       rebuild=lambda w, s, p, e=None: {}, db_path=db)
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
    from open_guji_cv.datastore.workcopy import (
        SyncConflict,
        data_dir,
        local_changes,
        sync,
    )
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


def test_merge_events_renumbers_local_seq_clash():
    """规范 §9 F-6：两台机器往同一批次各追加一条、都编成 seq 2 → 库里的不动，本地的顺延成 seq 3。"""
    import json

    from open_guji_cv.datastore.workcopy import _merge_events
    base = _line(id="evt_b_000001", batch="b", seq=1, ts="t1")
    r = _line(id="evt_b_000002", batch="b", seq=2, ts="t2", payload={"v": "r"})
    lo = _line(id="evt_b_000002", batch="b", seq=2, ts="t3", payload={"v": "l"})
    same = _line(id="evt_b_000002", batch="b", seq=2, ts="t2", payload={"v": "r"})
    m, ren = _merge_events(f"{base}\n{lo}\n".encode(), f"{base}\n{r}\n".encode())
    rows = [json.loads(x) for x in m.decode().splitlines()]
    assert ren == {"evt_b_000002": "evt_b_000003"}
    assert [(x["id"], x["seq"], x["payload"]["v"]) for x in rows[1:]] == [
        ("evt_b_000002", 2, "r"), ("evt_b_000003", 3, "l")]
    assert _merge_events(f"{base}\n{same}\n".encode(), f"{base}\n{r}\n".encode()) == (
        f"{base}\n{r}\n".encode(), {})                                   # 同一条两边都有：不重编


def test_sync_renumbers_clashing_events_and_their_ledger(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    """撞号重编后，本地记账里引用旧 id 的行跟着改；库里两条都在、各自的记账不互相遮挡。"""
    import json

    from open_guji_cv.datastore.workcopy import data_dir, local_changes, sync
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    a = _fresh(files, tmp_path / "a", src, cache)
    da = data_dir(a)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    b = _fresh(files, tmp_path / "b", src, cache)
    db_ = data_dir(b)
    rel, led = "feedback/events/b.jsonl", "feedback/consumed/gold_add.jsonl"

    def write(d, v):
        (d / rel).write_bytes((d / rel).read_bytes() + (_line(id="evt_b_000009", batch="b", seq=9, payload={"v": v})
                                                        + "\n").encode())
        p = d / led
        old = p.read_bytes() if p.exists() else b""
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(old + (_line(event="evt_b_000009", note=v) + "\n").encode())

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    write(da, "a")
    assert sync(src, conn, a, actor="a", cache=cache)["action"] == "push"
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    write(db_, "b")
    out = sync(src, conn, b, actor="b", cache=cache)
    assert out["renumbered"] == {"evt_b_000009": "evt_b_000010"}
    assert local_changes(b) == []
    ev = {r["id"]: json.loads(r["raw"]).get("payload", {}).get("v") for r in src.rows("events", "tws")}
    assert ev["evt_b_000009"] == "a" and ev["evt_b_000010"] == "b"
    notes = {json.loads(x)["note"]: json.loads(x)["event"] for x in (db_ / led).read_text().splitlines()}
    assert notes == {"a": "evt_b_000009", "b": "evt_b_000010"}


def test_sync_takes_remote_glyph_store_and_replays_local_events(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    """两台机器各有新人裁、各自消费改了字形库 → 不停：取库里的字形库，本地新事件的字形库记账删掉，
    交给 replay 在库里的字形库上重新消费，再推（册 005 10-23 三次手工 pull --force 的那一步）。"""
    import json

    from open_guji_cv.datastore.workcopy import (
        SyncConflict,
        data_dir,
        local_changes,
        sync,
    )
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    calls: list = []
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    a = _fresh(files, tmp_path / "a", src, cache)
    da = data_dir(a)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    b = _fresh(files, tmp_path / "b", src, cache)
    db_ = data_dir(b)
    ev, adm, glyphs = "feedback/events/b.jsonl", "output/glyph_store/admissions.jsonl", "output/glyph_store/glyphs.jsonl"
    led, gold = "feedback/consumed/glyphdb_admit.jsonl", "feedback/consumed/gold_add.jsonl"

    def row(rel, eid):
        if rel == adm:
            return _line(admitted_at="t", char="乙", evidence=None, instance_id=f"tbook:乙:{eid}", provenance=eid)
        return _line(char=eid, edition_tag="ed1", ids=None, n_confirmed=1, semantic=eid, status="stable",
                     unicode_cp=None, updated_at="t")

    def admit(d, rel, eid):
        (d / rel).write_bytes((d / rel).read_bytes() + (row(rel, eid) + "\n").encode())

    def judge(d, eid, seq, *, store=(adm,)):            # 一条新人裁，消费者改了字形库、记了账
        (d / ev).write_bytes((d / ev).read_bytes() + (_line(id=eid, batch="b", seq=seq) + "\n").encode())
        for rel in store:
            admit(d, rel, eid)
        for rel in (led, gold):
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((p.read_bytes() if p.exists() else b"") + (_line(event=eid) + "\n").encode())

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    judge(da, "evt_b_2", 2)
    assert sync(src, conn, a, actor="a", cache=cache)["action"] == "push"
    remote_adm = (da / adm).read_bytes()

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    judge(db_, "evt_b_3", 3, store=(adm, glyphs))       # glyphs.jsonl 只有本地改了：也回到库里那份
    hooks = _fake_hooks(tmp_path / "b.db", calls)
    with pytest.raises(SyncConflict):                    # 不给 replay：照旧停下
        sync(src, conn, b, actor="b", cache=cache, glyph=hooks)

    seen = {}

    def replay(ids):
        seen["ids"] = set(ids)
        seen["adm"] = (db_ / adm).read_bytes()
        seen["glyphs"] = (db_ / glyphs).read_bytes()
        seen["led"] = (db_ / led).read_text()
        for i in sorted(ids):                            # 模拟消费者在库里的字形库上重新进库、记账
            admit(db_, adm, i)
            (db_ / led).write_bytes((db_ / led).read_bytes() + (_line(event=i) + "\n").encode())
        return {"events": len(ids)}

    out = sync(src, conn, b, actor="b", cache=cache, glyph=hooks, replay=replay)
    assert seen["ids"] == {"evt_b_3"}
    assert seen["adm"] == remote_adm                     # 重新消费前：字形库是库里的
    assert seen["glyphs"] == files["W/" + glyphs]
    assert "evt_b_3" not in seen["led"] and "evt_b_2" in seen["led"]   # 只删本地新事件的字形库记账
    assert "evt_b_3" in (db_ / gold).read_text()        # 别的消费者的记账不动
    assert sorted(out["glyph_taken_remote"]) == [adm, glyphs] and out["replay_unconsumed"] == 1
    assert out["action"] == "merged+push" and local_changes(b) == []
    admits = [json.loads(x)["provenance"] for x in (db_ / adm).read_text().splitlines()]
    assert admits[-2:] == ["evt_b_2", "evt_b_3"] and "evt_b_3" not in admits[:-2]
    ids = {r["id"] for r in src.rows("events", "tws")}
    assert {"evt_b_2", "evt_b_3"} <= ids


def test_sync_glyph_store_clash_without_new_events_still_stops(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    """本地字形库改了却没有新人裁（不是消费者算出来的）：有 replay 也照旧停下，不丢本地的。"""
    from open_guji_cv.datastore.workcopy import SyncConflict, data_dir, sync
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    a = _fresh(files, tmp_path / "a", src, cache)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    b = _fresh(files, tmp_path / "b", src, cache)
    adm = "output/glyph_store/admissions.jsonl"
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    (data_dir(a) / adm).write_bytes((data_dir(a) / adm).read_bytes() + (_line(admitted_at="t", char="乙", evidence=None, instance_id="tbook:乙:a", provenance="a") + "\n").encode())
    sync(src, conn, a, actor="a", cache=cache)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    mine = (data_dir(b) / adm).read_bytes() + (_line(admitted_at="t", char="乙", evidence=None, instance_id="tbook:乙:b",
                                                                provenance="b") + "\n").encode()
    (data_dir(b) / adm).write_bytes(mine)
    with pytest.raises(SyncConflict):
        sync(src, conn, b, actor="b", cache=cache, glyph=_fake_hooks(tmp_path / "b.db", []), replay=lambda ids: {})
    assert (data_dir(b) / adm).read_bytes() == mine


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


def test_push_refuses_dropping_anchor_patches(repo, conn, tmp_path):  # noqa: F811
    """数据目录里缺了锚图（v0.4.0 及更早的 pull 不还原锚图）时，push 不能把库里的锚图删掉。"""
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.workcopy import (
        FileDeleteRefused,
        data_dir,
        migrate,
        push,
    )
    files = _workspace(tmp_path)
    files["W/feedback/anchor_patches/vol03/ab/ab12.png"] = b"\\x89PNG anchor"
    import_commit(conn, repo, _commit(repo, files, "c1"))
    src = PgSource(conn)
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()})
    ws = _checkout(files, tmp_path / "ws")
    migrate(src, ws, cache=cache)
    (data_dir(ws) / "feedback/anchor_patches/vol03/ab/ab12.png").unlink()
    with pytest.raises(FileDeleteRefused, match="ab12.png"):
        push(conn, ws, actor="t")
    assert [r["src_path"] for r in src.rows("anchor_patches_meta", "tws")] == ["feedback/anchor_patches/vol03/ab/ab12.png"]


def test_push_uploads_only_images_new_to_db(repo, conn, tmp_path):  # noqa: F811
    """库里已有的图不再交给 uploader（每次推都核两万张会拖到连接被断）；只传新图。"""
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.workcopy import data_dir, migrate, push
    files = _workspace(tmp_path)
    files["W/feedback/anchor_patches/vol03/ab/ab12.png"] = b"\\x89PNG anchor"
    import_commit(conn, repo, _commit(repo, files, "c1"))
    src = PgSource(conn)
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()})
    ws = _checkout(files, tmp_path / "ws")
    migrate(src, ws, cache=cache)
    new = data_dir(ws) / "feedback/anchor_patches/vol03/cd/cd34.png"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"\\x89PNG new anchor")
    calls = []
    push(conn, ws, actor="t", uploader=lambda imgs: calls.append(dict(imgs)) or {})
    assert calls == [{hashlib.sha256(b"\\x89PNG new anchor").hexdigest(): new}]


# ---- 整理本进中心库（共享方案 2.2 节，S1）----

def _migrated(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.workcopy import migrate
    files = _workspace(tmp_path)
    import_commit(conn, repo, _commit(repo, files, "c1"))
    src = PgSource(conn)
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()})
    ws = _checkout(files, tmp_path / "ws")
    migrate(src, ws, cache=cache)
    return src, cache, files, ws


def test_corpus_adopt_push_and_pull(repo, conn, tmp_path):  # noqa: F811
    """已迁过的工作区根上的 corpus/、corpus-pack/：migrate 补迁进数据目录 → push 进库（文本按 txt 进 R2）
    → 新机器 pull 还原；库里有的整理本本地删了，push 拒绝。"""
    from open_guji_cv.datastore.workcopy import (
        FileDeleteRefused,
        data_dir,
        local_changes,
        migrate,
        push,
    )
    src, cache, files, ws = _migrated(repo, conn, tmp_path)
    text = "欽定四庫全書總目\n卷一\n".encode("utf-8")
    man = b'{"corpus_version": 1}\n'
    (ws / "corpus" / "sub").mkdir(parents=True)
    (ws / "corpus" / "zongmu.txt").write_bytes(text)
    (ws / "corpus" / "sub" / "0001.jsonl").write_bytes(b'{"a": 1}\n')
    (ws / "corpus-pack" / "v1").mkdir(parents=True)
    (ws / "corpus-pack" / "v1" / "manifest.json").write_bytes(man)
    (ws / "corpus" / "README.md.bak-1").write_bytes(b"x")         # 备份不进库，也不挪

    dry = migrate(src, ws, dry_run=True)
    assert dry["adopt"] == 3 and (ws / "corpus" / "zongmu.txt").exists()
    rep = migrate(src, ws)
    data = data_dir(ws)
    assert rep["adopt"] == 3
    assert (data / "corpus/zongmu.txt").read_bytes() == text
    assert (data / "config/corpus-pack/v1/manifest.json").read_bytes() == man
    assert not (ws / "corpus-pack").exists() and not (ws / "corpus" / "zongmu.txt").exists()
    assert (ws / "corpus" / "README.md.bak-1").exists()
    assert local_changes(ws) == ["config/corpus-pack/v1/manifest.json", "corpus/sub/0001.jsonl",
                                 "corpus/zongmu.txt"]

    calls = []
    push(conn, ws, actor="t", uploader=lambda imgs, ext="png": calls.append((ext, dict(imgs))) or {})
    sha = hashlib.sha256(text).hexdigest()
    assert [(e, sorted(g)) for e, g in calls] == [
        ("txt", sorted([sha, hashlib.sha256(b'{"a": 1}\n').hexdigest()]))]
    rows = {r["src_path"]: r["sha256"] for r in src.rows("corpus_files", "tws")}
    assert rows["corpus/zongmu.txt"] == sha and len(rows) == 2
    assert "config/corpus-pack/v1/manifest.json" in {r["src_path"] for r in src.rows("files", "tws")}
    assert local_changes(ws) == []

    for b in (text, b'{"a": 1}\n'):
        cache.put(hashlib.sha256(b).hexdigest(), b)
    fresh = _fresh(files, tmp_path / "m2", src, cache)
    assert (data_dir(fresh) / "corpus/zongmu.txt").read_bytes() == text
    assert (data_dir(fresh) / "config/corpus-pack/v1/manifest.json").read_bytes() == man
    assert local_changes(fresh) == []

    (data / "corpus/zongmu.txt").unlink()
    with pytest.raises(FileDeleteRefused, match="zongmu.txt"):
        push(conn, ws, actor="t")


def test_corpus_adopt_refuses_clash(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.workcopy import data_dir, migrate
    src, _, _, ws = _migrated(repo, conn, tmp_path)
    (ws / "corpus").mkdir()
    (ws / "corpus" / "a.txt").write_bytes(b"old")
    (data_dir(ws) / "corpus").mkdir()
    (data_dir(ws) / "corpus" / "a.txt").write_bytes(b"new")
    with pytest.raises(SystemExit, match="内容不同"):
        migrate(src, ws)
    assert (ws / "corpus" / "a.txt").read_bytes() == b"old"


def test_corpus_paths_follow_data_dir(tmp_path, monkeypatch):
    """corpus_path／清单目录：迁过的工作区在数据目录；还没补迁时退回工作区根；没迁的照旧。"""
    from open_guji_cv.core.corpus_pin import _base, pack_root
    from open_guji_cv.core.workspace import central_data_dir, corpus_dir, corpus_path
    plain = tmp_path / "plain"
    plain.mkdir()
    assert corpus_dir(plain) == plain / "corpus" and pack_root(plain) == plain / "corpus-pack"

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".central.json").write_text('{"ws": "tws", "branch": "main"}')
    data = central_data_dir("tws")
    (ws / "corpus").mkdir()
    (ws / "corpus-pack").mkdir()
    assert corpus_dir(ws) == ws / "corpus" and pack_root(ws) == ws / "corpus-pack"   # 还没补迁
    (data / "corpus").mkdir(parents=True)
    (data / "config" / "corpus-pack").mkdir(parents=True)
    assert corpus_dir(ws) == data / "corpus"
    assert pack_root(ws) == data / "config" / "corpus-pack"
    assert _base("ws", "corpus/**/*.txt", ws) == data
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert corpus_path("x.txt") == data / "corpus" / "x.txt"


def test_blob_rows_tolerates_old_worker():
    """Worker 还没开放 corpus_files（旧版回 404 no_table）时当空表，pull 照常。"""
    from open_guji_cv.datastore.client import CentralError
    from open_guji_cv.datastore.materialize import blob_rows

    class Old:
        def rows(self, tbl, ws):
            if tbl == "corpus_files":
                raise CentralError(404, "no_table", "不开放的表：corpus_files")
            yield {"src_path": "x", "sha256": "y"}

    assert blob_rows(Old(), "corpus_files", "tws") == []
    assert blob_rows(Old(), "anchor_patches_meta", "tws") == [{"src_path": "x", "sha256": "y"}]


# ---- 借库与共享层只读（共享方案 S4）----

def _lib_store(tmp_path) -> dict[str, bytes]:
    """另一本书的字形库（字、实例号都和 ``_workspace`` 的不重）。"""
    from test_datastore_pull import _cc

    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    db = GlyphDB(tmp_path / "lib-seed.sqlite")
    try:
        _cc.seed_glyphs(db, chars=("丙",), n_each=3, edition="lib", seed=7)
        store = tmp_path / "lib_store"
        export_store(db, store)
    finally:
        db.close()
    return {f"output/glyph_store/{p.relative_to(store).as_posix()}": p.read_bytes()
            for p in sorted(store.rglob("*")) if p.is_file()}


def _borrowing(repo, conn, tmp_path):  # noqa: F811
    """库里两个工作区：tws 借 lib 的字形库（workspace.yaml 写工作区名）。"""
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    files = _workspace(tmp_path)
    files["W/workspace.yaml"] = b"id: tws\nglyph_lib:\n  borrow: [lib]\n"
    lib = {"L/workspace.yaml": b"id: lib\n", **{f"L/{k}": v for k, v in _lib_store(tmp_path).items()}}
    import_commit(conn, repo, _commit(repo, {**files, **lib}, "c1"))
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in {**files, **lib}.items()})
    return PgSource(conn), files, lib, cache


def _fake_hooks(db: Path, calls: list):
    from open_guji_cv.datastore.workcopy import GlyphHooks
    db.write_text("v1")
    return GlyphHooks(fingerprint=lambda p: Path(p).read_text(), export=lambda p, s: {},
                      rebuild=lambda w, s, p, e=None: calls.append(list(e or [])) or {}, db_path=db)


def test_pull_materializes_borrowed_store_and_follows_its_updates(repo, conn, tmp_path):  # noqa: F811
    """pull 把被借工作区的字形库拉成只读副本、带上它重建 glyph.db；被借库没变不重拉不重建，
    有新写入（pull 或 sync）就重拉并重建。"""
    from open_guji_cv.core.workspace import borrowed_root
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.workcopy import BORROW_STATE, local_changes, pull, sync
    src, files, lib, cache = _borrowing(repo, conn, tmp_path)
    calls: list = []
    hooks = _fake_hooks(tmp_path / "fake.db", calls)
    ws = _fresh(files, tmp_path / "ws", src, cache, lambda d: hooks)
    lib_dir = borrowed_root("lib") / "output" / "glyph_store"
    assert calls == [[lib_dir]]
    assert _data_files(lib_dir) == {k[len("L/output/glyph_store/"):]: v for k, v in lib.items()
                                    if k.startswith("L/output/glyph_store/")}
    assert not (borrowed_root("lib") / "workspace.yaml").exists()      # 只拉字形库
    stamp = (borrowed_root("lib") / BORROW_STATE).read_text()
    assert local_changes(ws, hooks) == []                               # 借来的库不算本地改动

    out = pull(src, ws, cache=cache, glyph=hooks)
    assert out["borrow"][0].startswith("lib@") and calls == [[lib_dir]]   # 没变：不重建
    assert (borrowed_root("lib") / BORROW_STATE).read_text() == stamp     # 也不重拉

    meta = b'{"key": "note", "value": "lib v2"}\n'
    import_commit(conn, repo, _commit(repo, {"L/output/glyph_store/meta.jsonl": meta}, "c2"))
    out = pull(src, ws, cache=cache, glyph=hooks)
    assert len(calls) == 2 and (lib_dir / "meta.jsonl").read_bytes() == meta
    assert out["borrow"] != [stamp]

    meta3 = b'{"key": "note", "value": "lib v3"}\n'
    import_commit(conn, repo, _commit(repo, {"L/output/glyph_store/meta.jsonl": meta3}, "c3"))
    assert sync(src, conn, ws, actor="t", cache=cache, glyph=hooks)["action"] == "nothing"
    assert len(calls) == 3 and (lib_dir / "meta.jsonl").read_bytes() == meta3
    assert sync(src, conn, ws, actor="t", cache=cache, glyph=hooks)["action"] == "nothing"
    assert len(calls) == 3


def test_pull_rebuilds_glyph_db_with_borrowed_instances(repo, conn, tmp_path):  # noqa: F811
    """真聚类层：重建出的 glyph.db 里有借来的字（丙），自己的字（甲乙）也在。"""
    import sqlite3

    from open_guji_cv.ops.central_glyph import glyph_hooks
    src, files, _, cache = _borrowing(repo, conn, tmp_path)
    ws = _fresh(files, tmp_path / "ws", src, cache, glyph_hooks)
    c = sqlite3.connect(glyph_hooks(ws).db_path)
    try:
        chars = {r[0] for r in c.execute("SELECT DISTINCT label FROM instances")}
    finally:
        c.close()
    assert {"甲", "乙", "丙"} <= chars


def test_borrow_of_missing_or_self_workspace_is_refused(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    files = _workspace(tmp_path)
    files["W/workspace.yaml"] = b"id: tws\nglyph_lib:\n  borrow: [tws]\n"
    import_commit(conn, repo, _commit(repo, files, "c1"))
    src = PgSource(conn)
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()})
    calls: list = []
    with pytest.raises(SystemExit, match="写了自己"):
        _fresh(files, tmp_path / "ws", src, cache, lambda d: _fake_hooks(tmp_path / "f.db", calls))


def test_shared_workspaces_are_read_only(repo, conn, tmp_path):  # noqa: F811
    """corpus-base、glyphlib-*：普通 push 拒绝；升级脚本（shared_writer）能写 corpus-base，
    glyphlib-* 发布过就不能再写。"""
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.workcopy import data_dir, pull, push
    files = {"C/workspace.yaml": b"id: corpus-base\n", "C/books/a.yaml": b"id: a\n",
             "G/workspace.yaml": b"id: glyphlib-t1\n", "G/books/a.yaml": b"id: a\n"}
    import_commit(conn, repo, _commit(repo, files, "c1"))
    src = PgSource(conn)
    for name, top in (("corpus-base", "C"), ("glyphlib-t1", "G")):
        d = tmp_path / name
        d.mkdir()
        (d / "workspace.yaml").write_bytes(files[f"{top}/workspace.yaml"])
        (d / ".central.json").write_text(f'{{"ws": "{name}", "branch": "main"}}')
        pull(src, d)
        (data_dir(d) / "books" / "b.yaml").write_bytes(b"id: b\n")
        with pytest.raises(SystemExit, match="只读"):
            push(conn, d, actor="t")
    out = push(conn, tmp_path / "corpus-base", actor="t", shared_writer=True)
    assert out["rev_to"] > out["rev_from"]
    with pytest.raises(SystemExit, match="已经发布过"):
        push(conn, tmp_path / "glyphlib-t1", actor="t", shared_writer=True)


# ---- 两级语料库清单（共享方案 S2）----

def test_corpus_base_published_and_pulled_with_book(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    """build-base 第一次新开 corpus-base、之后加新版不动旧版；书库清单写了 base 的工作区，
    pull 顺带把底库清单拉成只读副本，verify 两级一起对。"""
    from open_guji_cv.core.corpus_pin import BASE_DIR, BASE_WS
    from open_guji_cv.core.workspace import borrowed_root
    from open_guji_cv.datastore.workcopy import data_dir, pull, push, uses_corpus_base
    from open_guji_cv.ops import corpus_pack as cp
    monkeypatch.setattr(cp, "_repo_dirty", lambda paths, repo=None: [])
    monkeypatch.setattr(cp, "_repo_commit", lambda repo=None: "c0ffee")
    src, cache, files, ws = _migrated(repo, conn, tmp_path)

    r1 = cp.publish_base(src, conn, note="b1", actor="t")
    assert r1["base_version"] == 1 and r1["push"]["rev_to"] > r1["push"]["rev_from"]
    rows = {r["src_path"] for r in src.rows("files", BASE_WS)}
    assert f"{BASE_DIR}/b1/manifest.json" in rows
    with pytest.raises(SystemExit, match="只读"):                    # 普通 push 照旧拒绝
        push(conn, cp.base_workdir("main"), actor="t")

    assert not uses_corpus_base(ws)
    pull(src, ws, cache=cache)
    assert not (borrowed_root(BASE_WS) / BASE_DIR).exists()             # 用不到底库就不拉
    # 本机拉一份底库（同 guji corpus init），出两级书库清单，推上去
    from open_guji_cv.datastore.workcopy import refresh_corpus_base
    refresh_corpus_base(src, ws, cache=cache, always=True)
    cp.build(ws, base="latest")
    push(conn, ws, actor="t")
    assert uses_corpus_base(ws) and cp.verify(ws, 1)["base"] == 1

    r2 = cp.publish_base(src, conn, note="b2", actor="t")
    assert r2["base_version"] == 2
    assert {f"{BASE_DIR}/b1/manifest.json", f"{BASE_DIR}/b2/manifest.json"} <= \
        {r["src_path"] for r in src.rows("files", BASE_WS)}

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-m2"))       # 新机器
    fresh = _fresh(files, tmp_path / "m2", src, cache)
    assert (data_dir(fresh) / "config/corpus-pack/v1/manifest.json").exists()
    assert sorted(p.name for p in (borrowed_root(BASE_WS) / BASE_DIR).iterdir()) == ["b1", "b2"]
    assert cp.verify(fresh, 1)["base"] == 1


def test_glyphlib_publish_creates_once(repo, conn, tmp_path):  # noqa: F811
    """共享刻例库：升级脚本第一次推新开工作区、图按 png 进 R2；同一版再推拒绝（版本不可改）。"""
    from open_guji_cv.core.workspace import central_data_dir
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import apply_schema
    from open_guji_cv.ops.glyphlib import publish
    apply_schema(conn)                                                  # 空库（真库早有表）
    data = central_data_dir("glyphlib-t-v1")
    for rel, b in _lib_store(tmp_path).items():
        p = data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    calls = []
    out = publish(conn, "glyphlib-t-v1", actor="t", uploader=lambda imgs, ext="png": calls.append(ext) or {})
    assert out["rev_to"] > out["rev_from"] and calls == ["png"]
    assert PgSource(conn).rows("glyph_instances", "glyphlib-t-v1")
    with pytest.raises(SystemExit, match="已经发布过"):
        publish(conn, "glyphlib-t-v1", actor="t")


# ---- 省流量：只向库要变了的文件、只取要用的列（Neon 免费档每月 5 GiB 公网流量）----

class _Counting:
    """包一层数据源，记下每次 rows 的表、列、过滤，和回了几行。"""

    def __init__(self, src):
        self.src, self.calls = src, []

    def __getattr__(self, k):
        return getattr(self.src, k)

    def rows(self, table, ws=None, cols=None, **filters):
        out = list(self.src.rows(table, ws, cols=cols, **filters))
        self.calls.append((table, cols, filters, len(out)))
        return iter(out)


def test_pull_fetches_only_changed_files(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.materialize import LINE_COLS
    from open_guji_cv.datastore.workcopy import data_dir, pull
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    a = _fresh(files, tmp_path / "a", src, cache)
    da = data_dir(a)

    # 库里改一个事件文件；本机另把一个没变的文件改坏
    rel = "feedback/events/b.jsonl"
    files2 = dict(files)
    files2["W/" + rel] = files["W/" + rel] + (_line(id="evt_b_9", batch="b", seq=9) + "\n").encode()
    import_commit(conn, repo, _commit(repo, files2, "c2"))
    other = next(p for p in _data_files(da) if p.endswith(".jsonl") and p != rel)
    good = (da / other).read_bytes()
    (da / other).write_bytes(b"tampered\n")

    cs = _Counting(src)
    out = pull(cs, a, cache=cache, force=True)
    assert out["fetched"] == 2 and out["reused"] >= 1
    assert (da / rel).read_bytes() == files2["W/" + rel]
    assert (da / other).read_bytes() == good                               # 改坏的照样从库里取回
    line_calls = [c for c in cs.calls if c[1] == LINE_COLS]
    assert line_calls and all(set(c[2].get("src_path", [])) <= {rel, other} and c[2] for c in line_calls)

    # 再拉一次：什么都没变，一个文本文件都不向库要
    cs.calls.clear()
    out = pull(cs, a, cache=cache)
    assert out["fetched"] == 0
    assert not [c for c in cs.calls if c[1] == LINE_COLS]


def test_worker_rows_multi_value_and_old_worker(monkeypatch):
    from open_guji_cv.datastore.client import CentralError, WorkerSource
    w = WorkerSource(url="https://x", token="t")
    seen = []

    def call(method, path, *, query=None, tries=5, **kw):
        seen.append((path, dict(query or {})))
        if "cols" in (query or {}) and old:
            raise CentralError(400, "bad_filter", "表 workspaces 没有列 cols")
        return {"rows": [{"q": dict(query)}], "next": None}

    monkeypatch.setattr(w, "_call", call)
    old = False
    rows = list(w.rows("events", "tws", cols=("src_path", "raw"), src_path=["b", "a"]))
    assert len(rows) == 1 and rows[0]["q"]["src_path"] == ["a", "b"] and rows[0]["q"]["cols"] == "src_path,raw"

    w2 = WorkerSource(url="https://x", token="t")
    monkeypatch.setattr(w2, "_call", call)
    old = True
    rows = list(w2.rows("events", "tws", cols=("raw",), src_path=["b", "a"]))
    assert [r["q"]["src_path"] for r in rows] == ["a", "b"]               # 旧 Worker：逐值查、整行取
    assert all("cols" not in r["q"] for r in rows)


class _WithSnapshots(_Counting):
    """带快照接口的数据源（快照存内存，同 Worker 的 /v1/snapshots：只留 rev 最大的）。"""

    def __init__(self, src, store):
        super().__init__(src)
        self.store = store

    def get_snapshot(self, ws):
        return self.store.get(ws)

    def put_snapshot(self, ws, rev, data):
        if ws not in self.store or self.store[ws][0] < rev:
            self.store[ws] = (rev, data)
        return {}


def test_fresh_pull_seeds_from_snapshot(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.materialize import LINE_COLS
    from open_guji_cv.datastore.workcopy import data_dir
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    store: dict = {}
    sa = _WithSnapshots(src, store)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-a"))
    a = _fresh(files, tmp_path / "a", sa, cache)
    assert "tws" in store                                                  # 第一台整拉后存了快照

    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-b"))
    sb = _WithSnapshots(src, store)
    b = _fresh(files, tmp_path / "b", sb, cache)
    assert not [c for c in sb.calls if c[1] == LINE_COLS]                  # 文本全从快照来
    assert _data_files(data_dir(b)) == _data_files(data_dir(a))

    # 快照之后库里又改了一个文件：新机器只向库要这一个
    rel = "feedback/events/b.jsonl"
    files2 = dict(files)
    files2["W/" + rel] = files["W/" + rel] + (_line(id="evt_b_9", batch="b", seq=9) + "\n").encode()
    import_commit(conn, repo, _commit(repo, files2, "c2"))
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-c"))
    sc = _WithSnapshots(src, store)
    c = _fresh(files, tmp_path / "c", sc, cache)
    got = [c_ for c_ in sc.calls if c_[1] == LINE_COLS]
    assert got and all(c_[2].get("src_path") == [rel] for c_ in got)
    assert (data_dir(c) / rel).read_bytes() == files2["W/" + rel]

    # 坏快照：整拉照样对
    store["tws"] = (store["tws"][0], b"not a tarball")
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home-d"))
    d = _fresh(files, tmp_path / "d", _WithSnapshots(src, {"tws": store["tws"]}), cache)
    assert (data_dir(d) / rel).read_bytes() == files2["W/" + rel]
