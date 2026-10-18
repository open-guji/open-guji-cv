"""guji-workspace（某个 git 提交）→ 中心库 Postgres，幂等（GUJI-603）。

做法：扫出该提交里每个工作区「应有的行」（scope.py），和库里现有的行按主键比
raw 的 sha256，只写有差别的；每写一行在 ``changes`` 记一条、分配全局递增的 rev。
同一提交重跑：0 写入，rev 不动。全部在一个事务里，失败就整体回滚。

删除：某行在提交里没了 → 库里也删（镜像）。但 ``append_only`` 的台账（events、consumed、
anchors）发现要删行就中止，除非显式 ``allow_delete``——防止拿旧提交把新人裁冲掉。
行号变了但内容没变（字形库导出重排）只更新 src_line，不算变更、不记 rev。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

import psycopg

from . import gitsource
from .scope import TABLES, Row, ScanResult, fingerprint, scan_files

SCHEMA_FILE = "schema.sql"


class DeleteRefused(RuntimeError):
    pass


def apply_schema(conn) -> None:
    from importlib.resources import files
    sql = files(__package__).joinpath(SCHEMA_FILE).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def scan_commit(repo, commit: str, only_ws: set[str] | None = None) -> list[ScanResult]:
    tree = gitsource.list_tree(repo, commit)
    reader = gitsource.BlobReader(repo)
    try:
        out = []
        for d, files in gitsource.workspaces_in_tree(tree).items():
            items = [(rel, (lambda oid=oid: reader.read(oid))) for rel, oid in files]
            res = scan_files(items, d)
            if only_ws and res.ws not in only_ws and d not in only_ws:
                continue
            out.append(res)
        return out
    finally:
        reader.close()


# ─── 差分（纯函数，可单测） ─────────────────────────────────────────────

@dataclass
class Plan:
    inserts: list[Row] = field(default_factory=list)
    updates: list[Row] = field(default_factory=list)       # 内容变了
    moves: list[Row] = field(default_factory=list)         # 只是行号变了
    deletes: list[tuple] = field(default_factory=list)     # 主键（不含 ws）
    old_sha: dict[tuple, str] = field(default_factory=dict)

    @property
    def n_changes(self) -> int:
        return len(self.inserts) + len(self.updates) + len(self.deletes)


def diff(rows: list[Row], existing: dict[tuple, tuple[str, int]]) -> Plan:
    """``existing``：{主键: (fingerprint, src_line)}。"""
    plan = Plan()
    want: dict[tuple, Row] = {}
    for r in rows:
        want[r.key] = r                   # 主键重复：后者覆盖（scope 已记入问题）
    for k, r in want.items():
        old = existing.get(k)
        if old is None:
            plan.inserts.append(r)
        elif old[0] != fingerprint(r):
            plan.updates.append(r)
            plan.old_sha[k] = old[0]
        elif old[1] != r.src_line:
            plan.moves.append(r)
    for k, (sha, _) in existing.items():
        if k not in want:
            plan.deletes.append(k)
            plan.old_sha[k] = sha
    return plan


# ─── 读写库 ─────────────────────────────────────────────────────────────

def _columns(cur, tbl: str) -> list[tuple[str, str]]:
    """[(列名, 类型)]，按建表顺序。"""
    cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s "
                "ORDER BY ordinal_position", (tbl,))
    return [(r[0], r[1]) for r in cur.fetchall()]


def _pk_cols(tbl: str) -> list[str]:
    return ["ws", *TABLES[tbl].key]


def load_existing(cur, tbl: str, ws: str) -> dict[tuple, tuple[str, int]]:
    keys = TABLES[tbl].key
    sel = ", ".join(keys) + ", " if keys else ""
    text = "raw || E'\\n' || COALESCE(patch_sha, '')" if tbl == "glyph_instances" else "raw"
    cur.execute(f"SELECT {sel}encode(sha256(convert_to({text}, 'UTF8')), 'hex'), src_line "
                f"FROM {tbl} WHERE ws = %s", (ws,))
    n = len(keys)
    return {tuple(r[:n]): (r[n], r[n + 1]) for r in cur.fetchall()}


def _record(row: Row, ws: str, rev: int, cols: list[tuple[str, str]]) -> tuple:
    base = {"ws": ws, "src_path": row.src_path, "src_line": row.src_line,
            "raw": row.raw, "rev": rev}
    if TABLES[row.tbl].has_doc:
        base["doc"] = row.doc
    for k, v in zip(TABLES[row.tbl].key, row.key):
        base[k] = v
    base.update(row.cols)
    out = []
    for c, typ in cols:
        v = base.get(c)
        if v is not None and typ == "jsonb":
            v = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, sort_keys=True)
        out.append(v)
    return tuple(out)


def _write_rows(cur, tbl: str, ws: str, rows: list[Row], revs: list[int] | None,
                keep_rev: bool = False) -> None:
    """upsert ``rows``；``keep_rev`` 时只改 src_line（行号变动）。"""
    if not rows:
        return
    typed = [c for c in _columns(cur, tbl) if c[0] != "ingested_at"]
    cols = [c for c, _ in typed]
    pk = _pk_cols(tbl)
    cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS _stage_{tbl} "
                f"(LIKE {tbl} INCLUDING DEFAULTS) ON COMMIT DROP")
    cur.execute(f"TRUNCATE _stage_{tbl}")
    with cur.copy(f"COPY _stage_{tbl} ({', '.join(cols)}) FROM STDIN") as cp:
        for i, r in enumerate(rows):
            cp.write_row(_record(r, ws, revs[i] if revs else 0, typed))
    if keep_rev:
        cur.execute(f"UPDATE {tbl} t SET src_line = s.src_line FROM _stage_{tbl} s WHERE "
                    + " AND ".join(f"t.{c} = s.{c}" for c in pk))
        return
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in pk)
    cur.execute(f"INSERT INTO {tbl} ({', '.join(cols)}) "
                f"SELECT {', '.join(cols)} FROM _stage_{tbl} "
                f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {upd}, ingested_at = now()")


def _delete_rows(cur, tbl: str, ws: str, keys: list[tuple]) -> None:
    if not keys:
        return
    pk = TABLES[tbl].key
    if not pk:
        cur.execute(f"DELETE FROM {tbl} WHERE ws = %s", (ws,))
        return
    cond = " AND ".join(f"{c} = %s" for c in pk)
    cur.executemany(f"DELETE FROM {tbl} WHERE ws = %s AND {cond}",
                    [(ws, *k) for k in keys])


def _alloc_revs(cur, n: int) -> list[int]:
    if n == 0:
        return []
    cur.execute("SELECT nextval('changes_rev_seq') FROM generate_series(1, %s)", (n,))
    return [r[0] for r in cur.fetchall()]


def current_rev(cur) -> int:
    cur.execute("SELECT COALESCE(max(rev), 0) FROM changes")
    return cur.fetchone()[0]


@dataclass
class ImportReport:
    commit: str
    import_id: int | None = None
    rev_from: int = 0
    rev_to: int = 0
    per_table: dict = field(default_factory=dict)
    per_ws: dict = field(default_factory=dict)
    problems: dict = field(default_factory=dict)
    skipped: dict = field(default_factory=dict)
    dry_run: bool = False

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def import_commit(conn, repo, commit: str = "HEAD", *, only_ws: set[str] | None = None,
                  allow_delete: bool = False, actor: str | None = None,
                  dry_run: bool = False, source: str = "git:open-guji/guji-workspace"
                  ) -> ImportReport:
    commit = gitsource.resolve(repo, commit)
    scans = scan_commit(repo, commit, only_ws)
    rep = ImportReport(commit=commit, dry_run=dry_run)
    with conn.transaction():
        cur = conn.cursor()
        apply_schema(conn)
        cur.execute("LOCK TABLE changes IN EXCLUSIVE MODE")   # 同时只许一个导入
        rep.rev_from = current_rev(cur)
        cur.execute("INSERT INTO imports (source, git_commit, actor, rev_from) "
                    "VALUES (%s, %s, %s, %s) RETURNING import_id",
                    (source, commit, actor, rep.rev_from))
        rep.import_id = cur.fetchone()[0]
        refused = []
        plans: list[tuple[str, str, Plan, list[Row]]] = []
        for sc in scans:
            by_tbl: dict[str, list[Row]] = {t: [] for t in TABLES}
            for r in sc.rows:
                by_tbl[r.tbl].append(r)
            rep.problems[sc.ws] = sc.problems
            rep.skipped[sc.ws] = dict(Counter(_top(p) for p in sc.skipped))
            for tbl in TABLES:
                plan = diff(by_tbl[tbl], load_existing(cur, tbl, sc.ws))
                if plan.deletes and TABLES[tbl].append_only and not allow_delete:
                    refused.append(f"{sc.ws}/{tbl}: 要删 {len(plan.deletes)} 行"
                                   f"（如 {plan.deletes[0]}）")
                plans.append((sc.ws, tbl, plan, by_tbl[tbl]))
        if refused:
            raise DeleteRefused("只追加的台账在这个提交里少了行，拒绝导入（确认无误再加 "
                                "--allow-delete）：\n" + "\n".join(refused))
        # 写入顺序：先 workspaces（外键），删除倒序
        for ws, tbl, plan, rows in plans:
            st = rep.per_table.setdefault(tbl, Counter())
            st["rows"] += len(rows)
            st["insert"] += len(plan.inserts)
            st["update"] += len(plan.updates)
            st["delete"] += len(plan.deletes)
            st["moved"] += len(plan.moves)
            w = rep.per_ws.setdefault(ws, Counter())
            w["changes"] += plan.n_changes
            if dry_run:
                continue
            ups = plan.inserts + plan.updates
            revs = _alloc_revs(cur, len(ups))
            _write_rows(cur, tbl, ws, ups, revs)
            _write_rows(cur, tbl, ws, plan.moves, None, keep_rev=True)
            drevs = _alloc_revs(cur, len(plan.deletes))
            _log_changes(cur, rep.import_id, tbl, ws, plan, revs, drevs)
        if not dry_run:
            for ws, tbl, plan, _ in reversed(plans):
                _delete_rows(cur, tbl, ws, plan.deletes)
        rep.rev_to = current_rev(cur) if not dry_run else rep.rev_from
        rep.per_table = {k: dict(v) for k, v in rep.per_table.items()}
        rep.per_ws = {k: dict(v) for k, v in rep.per_ws.items()}
        cur.execute("UPDATE imports SET finished_at = now(), rev_to = %s, stats = %s "
                    "WHERE import_id = %s",
                    (rep.rev_to, json.dumps({"per_table": rep.per_table, "per_ws": rep.per_ws,
                                             "problems": rep.problems}, ensure_ascii=False),
                     rep.import_id))
        if dry_run:
            raise psycopg.Rollback()
    return rep


def _log_changes(cur, import_id, tbl, ws, plan: Plan, revs, drevs) -> None:
    rows = []
    for rev, r in zip(revs, plan.inserts + plan.updates):
        new = fingerprint(r)
        rows.append((rev, import_id, tbl, "update" if r.key in plan.old_sha else "insert", ws,
                     json.dumps(list(r.key), ensure_ascii=False), plan.old_sha.get(r.key), new))
    for rev, k in zip(drevs, plan.deletes):
        rows.append((rev, import_id, tbl, "delete", ws, json.dumps(list(k), ensure_ascii=False),
                     plan.old_sha.get(k), None))
    if not rows:
        return
    with cur.copy("COPY changes (rev, import_id, tbl, op, ws, pk, old_sha, new_sha) "
                  "FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


def _top(rel: str) -> str:
    parts = rel.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else rel
