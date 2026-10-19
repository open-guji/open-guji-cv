"""``guji db pull --full`` / ``guji db push`` 验收（GUJI-608 写入切换）。

还原进工作区本身与库逐字节相同；改了再 push 写回、另一份工作副本拉到同样内容；
基于旧版本的 push 整次拒绝（不互相冲掉）；文件没了、只追加台账少了行都拒绝；
有没 push 的改动时 pull --full 拒绝。要 ``GUJI_TEST_PG_DSN``，不给就跳过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test_datastore_pg import DSN, _commit, _line, conn, repo  # noqa: F401  (fixtures)
from test_datastore_pull import _Cache, _workspace

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not DSN, reason="没有 GUJI_TEST_PG_DSN（测试用 Postgres）")


def _setup(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    files = _workspace(tmp_path)
    import_commit(conn, repo, _commit(repo, files, "c1"))
    cache = _Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()})
    return PgSource(conn), files, cache


def _clone(src, tmp_path, name, files, cache):
    from open_guji_cv.datastore.push import pull_full
    ws = tmp_path / name
    ws.mkdir()
    (ws / "workspace.yaml").write_bytes(files["W/workspace.yaml"])
    res = pull_full(src, ws, cache=cache)
    return ws, res


def _local(ws: Path) -> dict[str, bytes]:
    return {p.relative_to(ws).as_posix(): p.read_bytes() for p in ws.rglob("*")
            if p.is_file() and p.name != ".central.json"}


def test_pull_full_push_roundtrip(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.push import push_dir, read_meta
    src, files, cache = _setup(repo, conn, tmp_path)
    ws, res = _clone(src, tmp_path, "a", files, cache)
    assert _local(ws) == {k[2:]: v for k, v in files.items()}      # 逐字节同提交
    assert read_meta(ws)["rev"] == res["rev"] == src.status()

    # 没改：push 不产生变更
    rep = push_dir(conn, ws, actor="t", uploader=lambda imgs: {"n": len(imgs)})
    assert rep["rev_to"] == rep["rev_from"]

    # 加一条人裁、加一个配置文件 → push → 另一份副本拉到同样内容
    ev = ws / "feedback" / "events" / "b.jsonl"
    ev.write_bytes(ev.read_bytes() + (_line(id="evt_b_2", batch="b", seq=2) + "\n").encode())
    (ws / "books" / "vol04.yaml").write_bytes(b"id: vol04\n")
    seen = {}
    rep = push_dir(conn, ws, actor="t", uploader=lambda imgs: seen.update(imgs) or {"n": len(imgs)})
    assert rep["rev_to"] > rep["rev_from"] and read_meta(ws)["rev"] == rep["rev_to"]
    assert seen and all(p.exists() for p in seen.values())          # 刻例图交给传图的函数
    ws2, _ = _clone(src, tmp_path, "b", files, cache)
    assert _local(ws2) == _local(ws)


def test_push_refuses_stale_base(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.push import StaleBase, push_dir
    src, files, cache = _setup(repo, conn, tmp_path)
    a, _ = _clone(src, tmp_path, "a", files, cache)
    b, _ = _clone(src, tmp_path, "b", files, cache)
    (a / "books" / "vol04.yaml").write_bytes(b"id: vol04\n")
    push_dir(conn, a, actor="a")
    rev = src.status()
    (b / "books" / "vol05.yaml").write_bytes(b"id: vol05\n")
    with pytest.raises(StaleBase):
        push_dir(conn, b, actor="b")
    assert src.status() == rev                                       # 整次回滚
    # 重新 pull 会被本地改动挡住；--force 丢掉后再改再 push 就行
    from open_guji_cv.datastore.push import pull_full
    with pytest.raises(SystemExit, match="还没 push"):
        pull_full(src, b, cache=cache)
    pull_full(src, b, cache=cache, force=True)
    assert (b / "books" / "vol04.yaml").exists() and not (b / "books" / "vol05.yaml").exists()
    (b / "books" / "vol05.yaml").write_bytes(b"id: vol05\n")
    assert push_dir(conn, b, actor="b")["rev_to"] > rev


def test_push_refuses_lost_files_and_ledger_rows(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.importer import DeleteRefused
    from open_guji_cv.datastore.push import FileDeleteRefused, push_dir
    src, files, cache = _setup(repo, conn, tmp_path)
    ws, _ = _clone(src, tmp_path, "a", files, cache)
    (ws / "books" / "vol03.yaml").unlink()
    with pytest.raises(FileDeleteRefused):
        push_dir(conn, ws, actor="t")
    assert push_dir(conn, ws, actor="t", allow_delete=True)["rev_to"] > 0

    ws2, _ = _clone(src, tmp_path, "b", files, cache)
    assert not (ws2 / "books" / "vol03.yaml").exists()               # 镜像：库里删了本地也删
    (ws2 / "feedback" / "events" / "b.jsonl").write_bytes(b"")       # 只追加的台账少了行
    with pytest.raises(DeleteRefused):
        push_dir(conn, ws2, actor="t")


def test_push_needs_pull_full_first(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.push import push_dir
    _setup(repo, conn, tmp_path)
    ws = tmp_path / "x"
    ws.mkdir()
    (ws / "workspace.yaml").write_bytes(b"id: tws\n")
    with pytest.raises(SystemExit, match="先 guji db pull"):
        push_dir(conn, ws, actor="t")
