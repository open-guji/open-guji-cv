"""（2026-11-04：本文件的测试随 datastore.verify 搬去 guji-manager tests/from_cv/；这里只留 test_datastore_workcopy 用的夹具。）

中心库导入 → 核对 → 重跑幂等 → 增量 → 删除护栏，在真 Postgres 上走一遍。

需要一个可随便建删 schema 的 Postgres：环境变量 ``GUJI_TEST_PG_DSN``（不给就跳过）。
每条测试在自己的临时 schema 里跑，跑完删掉；工作区是测试当场 ``git init`` 造的小仓。
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
DSN = os.environ.get("GUJI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="没有 GUJI_TEST_PG_DSN（测试用 Postgres）")


def _line(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False, sort_keys=True)


def _git(repo, *args) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo, files: dict[str, bytes | None], msg: str) -> str:
    for rel, data in files.items():
        p = repo / rel
        if data is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "ws-repo"
    r.mkdir()
    _git(r, "init", "-q")
    return r


@pytest.fixture
def conn():
    schema = "t_" + uuid.uuid4().hex[:10]
    c = psycopg.connect(DSN, autocommit=True)
    c.execute(f"CREATE SCHEMA {schema}")
    c.execute(f"SET search_path TO {schema}")
    try:
        yield c
    finally:
        c.execute(f"DROP SCHEMA {schema} CASCADE")
        c.close()


def _base() -> dict[str, bytes]:
    ev = lambda i, v: _line(id=f"evt_b_{i}", batch="b", seq=i, kind="confirm", actor="user",
                            payload={"v": v}, target={"book": "vol03"}, ts="t")
    inst = _line(instance_id="v2:vol03:1:1:1", source_id="v2", page="1", col=1, idx=1,
                 label="曰", semantic="曰", updated_at="t")
    return {
        "W/workspace.yaml": b"id: tws\n",
        "W/books/vol03.yaml": "id: vol03\ntitle: 卷三\n".encode(),
        "W/feedback/events/b.jsonl": (ev(1, "師") + "\n" + ev(2, "所") + "\n").encode(),
        "W/feedback/consumed/glyphdb_admit.jsonl": (
            (_line(event="evt_b_1", ts="t", note="b") + "\n") * 2).encode(),
        "W/feedback/lists/x.txt": b"vol03:1:1:1\n",
        "W/output/glyph_store/glyphs.jsonl": (_line(
            edition_tag="e", char="曰", status="sparse", n_confirmed=1, updated_at="t") + "\n"
        ).encode(),
        "W/output/glyph_store/approx_clears.jsonl": b"",
        "W/output/glyph_store/instances/v2.jsonl": (inst + "\n").encode(),
        "W/output/glyph_store/patches/v2_vol03_1_1_1.png": b"\x89PNG one",
        "W/other/page.png": b"out of scope, never read",
    }
