"""中心库备份与恢复演练（GUJI-611）：导出 → 恢复到另一个库 → 逐表行数与哈希一致；改一行就对不上。
要 ``GUJI_TEST_PG_DSN``，不给就跳过；经 Worker 存取那段用假的存储。"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from test_datastore_pg import DSN, _commit, conn, repo  # noqa: F401  (fixtures)
from test_datastore_pull import _workspace

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not DSN, reason="没有 GUJI_TEST_PG_DSN（测试用 Postgres）")


class _Store:
    """假的 /v1/backups。"""

    def __init__(self):
        self.objs: dict[tuple[str, str], bytes] = {}

    def put_backup(self, day, name, data, ct):
        self.objs[(day, name)] = data

    def list_backups(self):
        days = sorted({d for d, _ in self.objs})
        return [{"date": d, "files": sum(1 for k in self.objs if k[0] == d)} for d in days]

    def get_backup(self, day, name):
        if (day, name) not in self.objs:
            raise KeyError(name)
        return self.objs[(day, name)]

    def delete_backup(self, day):
        for k in [k for k in self.objs if k[0] == day]:
            del self.objs[k]


@pytest.fixture
def other():
    schema = "r_" + uuid.uuid4().hex[:10]
    c = psycopg.connect(DSN, autocommit=True)
    c.execute(f"CREATE SCHEMA {schema}")
    c.execute(f"SET search_path TO {schema}")
    try:
        yield c
    finally:
        c.execute(f"DROP SCHEMA {schema} CASCADE")
        c.close()


def test_backup_restore_roundtrip(repo, conn, other, tmp_path):  # noqa: F811
    from open_guji_cv.datastore import backup as B
    from open_guji_cv.datastore.importer import import_commit
    import_commit(conn, repo, _commit(repo, _workspace(tmp_path), "c1"))
    files, man = B.dump(conn)
    assert man["rev"] > 0 and man["tables"]["events"]["rows"] == 1
    assert man["tables"]["glyph_instances"]["rows"] > 0

    st = _Store()
    B.upload(st, "2026-10-19", files, man)
    st.put_backup("2026-10-01", "x.copy.gz", b"", "")                # 没有清单＝不完整
    assert B.complete_dates(st) == ["2026-10-19"]
    files2, man2 = B.fetch(st, "2026-10-19")

    other.execute("CREATE TABLE junk (x int)")                      # 目标库原有的东西不碍事
    B.restore(other, files2, man2)
    res = B.check(other, man2)
    assert res["ok"], res
    cur = other.cursor()
    cur.execute("SELECT coalesce(max(rev), 0) FROM changes")
    assert cur.fetchone()[0] == man["rev"]
    cur.execute("SELECT nextval('changes_rev_seq')")                # 序列接着往下走，不撞号
    assert cur.fetchone()[0] > man["rev"]

    other.execute("UPDATE events SET raw = raw || ' '")
    assert not B.check(other, man2)["ok"]

    assert B.prune(st, 10, today=date(2026, 10, 20)) == ["2026-10-01"]
    assert [d["date"] for d in st.list_backups()] == ["2026-10-19"]
