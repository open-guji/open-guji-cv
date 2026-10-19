"""中心库备份与恢复演练（GUJI-611，设计第八节）。

    python -m open_guji_cv.datastore backup  [--keep-days 30]           # 每日：导全部表 → R2 backup/<日期>/
    python -m open_guji_cv.datastore restore-check --endpoint <ci 端点> [--date YYYY-MM-DD]
                                                                         # 每周：最新备份恢复到 ci 分支并逐表核对

**导出**：一个 REPEATABLE READ 只读事务里（同一快照）对当前 schema（Neon 上是 public）下每张表 ``COPY … TO STDOUT``（文本格式，
恢复时 ``COPY … FROM STDIN`` 原样回去），gzip 后各存一个文件；``manifest.json`` 记每张表的列、行数、
哈希（COPY 输出逐行排序后的 sha256，与行的物理顺序无关）、各序列的当前值、库版本 rev。

**恢复**：只许恢复到 main 以外的端点（``--endpoint`` 必给，等于 main 的端点就拒绝）。删掉清单里的表，
按本仓 ``schema.sql`` 重建，逐表 COPY 回去、设序列，再按同样口径重算行数与哈希，与清单逐表对。

存取经 guji-data Worker 的 ``/v1/backups``（正式令牌 ``GUJI_DATA_TOKEN``）；连库同 ``guji db push``
（``GUJI_DATA_PG_DSN``，没有就从 ``NEON_DATABASE_URL`` 自动起 443 桥）。
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone

MANIFEST = "manifest.json"
FORMAT = "guji-data-backup/1"


def _tables(cur) -> list[str]:
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' ORDER BY table_name")
    return [r[0] for r in cur.fetchall()]


def _columns(cur, t: str) -> list[str]:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = %s ORDER BY ordinal_position", (t,))
    return [r[0] for r in cur.fetchall()]


def _copy_out(cur, t: str, cols: list[str]) -> bytes:
    from psycopg import sql
    q = sql.SQL("COPY (SELECT {} FROM {}) TO STDOUT").format(
        sql.SQL(", ").join(map(sql.Identifier, cols)), sql.Identifier(t))
    buf = io.BytesIO()
    with cur.copy(q) as cp:
        for chunk in cp:
            buf.write(chunk)
    return buf.getvalue()


def _digest(data: bytes) -> tuple[int, str]:
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    lines.sort()
    return len(lines), hashlib.sha256(b"\n".join(lines)).hexdigest()


def _sequences(cur) -> dict[str, int | None]:
    cur.execute("SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = current_schema() ORDER BY 1")
    return {n: (int(v) if v is not None else None) for n, v in cur.fetchall()}


def dump(conn) -> tuple[dict[str, bytes], dict]:
    """{文件名: gz 字节}, 清单。"""
    files: dict[str, bytes] = {}
    tables = {}
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        for t in _tables(cur):
            cols = _columns(cur, t)
            data = _copy_out(cur, t, cols)
            n, h = _digest(data)
            name = f"{t}.copy.gz"
            files[name] = gzip.compress(data, compresslevel=6, mtime=0)
            tables[t] = {"file": name, "columns": cols, "rows": n, "sha256": h, "bytes": len(data)}
        seqs = _sequences(cur)
        cur.execute("SELECT to_regclass('changes')::text")
        rev = 0
        if cur.fetchone()[0]:
            cur.execute("SELECT coalesce(max(rev), 0) FROM changes")
            rev = int(cur.fetchone()[0])
    man = {"format": FORMAT, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "rev": rev, "tables": tables, "sequences": seqs}
    return files, man


def restore(conn, files: dict[str, bytes], man: dict) -> None:
    """清掉目标库里清单上的表，按 schema.sql 重建，逐表灌回、设序列（一个事务）。清单外的表不碰。"""
    from psycopg import sql

    from .importer import apply_schema
    if man.get("format") != FORMAT:
        raise SystemExit(f"不认识的备份格式 {man.get('format')}")
    with conn.transaction():
        cur = conn.cursor()
        for t in man["tables"]:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(t)))
        apply_schema(conn)
        for t in _tables(cur):                         # schema.sql 会种几行（如 db_meta），清掉再灌
            if t in man["tables"]:
                cur.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(t)))
        # 先关外键检查不可移植；按「被引用的先灌」排：workspaces、imports 在前，其余按名字
        order = sorted(man["tables"], key=lambda t: (t not in ("db_meta", "workspaces", "imports"), t))
        for t in order:
            spec = man["tables"][t]
            q = sql.SQL("COPY {} ({}) FROM STDIN").format(
                sql.Identifier(t), sql.SQL(", ").join(map(sql.Identifier, spec["columns"])))
            with cur.copy(q) as cp:
                cp.write(gzip.decompress(files[spec["file"]]))
        for name, v in (man.get("sequences") or {}).items():
            if v is not None:
                cur.execute("SELECT setval(format('%%I.%%I', current_schema(), %s::text), %s, true)", (name, v))


def check(conn, man: dict) -> dict:
    """按清单口径重算目标库各表的行数与哈希，逐表对。"""
    out = {"ok": True, "tables": {}}
    with conn.transaction():
        cur = conn.cursor()
        for t, spec in sorted(man["tables"].items()):
            n, h = _digest(_copy_out(cur, t, spec["columns"]))
            same = n == spec["rows"] and h == spec["sha256"]
            out["tables"][t] = {"rows": n, "ok": same}
            out["ok"] &= same
    return out


# ---- 经 Worker 存取 ----

def upload(src, day: str, files: dict[str, bytes], man: dict) -> dict:
    for name, data in sorted(files.items()):
        src.put_backup(day, name, data, "application/gzip")
    body = json.dumps(man, ensure_ascii=False, indent=1).encode("utf-8")
    src.put_backup(day, MANIFEST, body, "application/json")   # 清单最后传：有清单才算完整
    return {"date": day, "files": len(files) + 1, "bytes": sum(map(len, files.values())) + len(body)}


def complete_dates(src) -> list[str]:
    """有清单的日期（升序）。"""
    out = []
    for d in src.list_backups():
        try:
            src.get_backup(d["date"], MANIFEST)
        except Exception:  # noqa: BLE001  没有清单＝不完整
            continue
        out.append(d["date"])
    return out


def fetch(src, day: str) -> tuple[dict[str, bytes], dict]:
    man = json.loads(src.get_backup(day, MANIFEST))
    files = {spec["file"]: src.get_backup(day, spec["file"]) for spec in man["tables"].values()}
    return files, man


def prune(src, keep_days: int, today: date | None = None) -> list[str]:
    today = today or datetime.now(timezone.utc).date()
    cut = (today - timedelta(days=keep_days)).isoformat()
    gone = [d["date"] for d in src.list_backups() if d["date"] < cut]
    for d in gone:
        src.delete_backup(d)
    return gone
