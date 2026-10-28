"""任务库的读写（Neon 中心库 `jobs` schema）。连库走 `datastore.connect`（443 桥），不经 Worker。

连哪个库：缺省正式库 main（`NEON_DATABASE_URL`）；`GUJI_JOBS_BRANCH=ci` 之类改连 Neon 的别的分支（试表用）。
领单：`FOR UPDATE SKIP LOCKED` 挑一条 queued，同册有在跑的就跳过（另有唯一索引兜底）；
领到就开一条 attempt，租约 `LEASE` 分钟，执行方每分钟心跳续租。会话死了租约过期，下一个执行方 `reap` 收回重排，
领满 `max_attempts` 次还没成就记 failed。
"""
from __future__ import annotations

import json
import os
import socket
from importlib import resources

LEASE_MIN = int(os.environ.get("GUJI_JOBS_LEASE_MIN", "10"))
RETRY_BACKOFF_MIN = int(os.environ.get("GUJI_JOBS_BACKOFF_MIN", "5"))   # 环境类失败重排后隔几分钟（×次数）


def connect():
    """开一条 autocommit 连接（写操作各自包在 `conn.transaction()` 里，读不留悬着的事务）。"""
    from ..datastore.connect import connect as _connect
    br = os.environ.get("GUJI_JOBS_BRANCH")
    if br and br != "main":
        from ..datastore.neonapi import branch_endpoint
        c = _connect(endpoint=branch_endpoint(br))
    else:
        c = _connect()
    c.autocommit = True
    return c


class DB:
    """断线自动重连的连接：`db(fn, *a)` 调 `fn(conn, *a)`，连接断了（443 桥、Neon 休眠）重连再试。

    执行方一跑几个小时，主线程那条连接中间可能长时间不用、被掐掉；进展、结果、收尾都经这里写，不因断线丢。
    """

    def __init__(self, factory=None):
        self.factory = factory or connect
        self.c = None

    def __call__(self, fn, *a, **kw):
        import time

        import psycopg
        for i in range(6):
            try:
                if self.c is None or self.c.closed:
                    self.c = self.factory()
                return fn(self.c, *a, **kw)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                self.close()
                if i == 5:
                    raise
                time.sleep(min(60, 3 * 2 ** i))

    def close(self) -> None:
        try:
            if self.c is not None:
                self.c.close()
        except Exception:       # noqa: BLE001
            pass
        self.c = None


def init(conn) -> None:
    sql = resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
    with conn.transaction():
        conn.execute(sql)


def _rows(cur) -> list[dict]:
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(cur) -> dict | None:
    r = _rows(cur)
    return r[0] if r else None


def who() -> str:
    """提交人／执行方的名字：GUJI_JOBS_WHO（如 A30），没有就主机名。"""
    return os.environ.get("GUJI_JOBS_WHO") or socket.gethostname()


# ── 提交与查看 ────────────────────────────────────────────────────────────

def submit(conn, spec: dict, h: str, *, by: str, why: str | None, priority: int = 100,
           depends_on: list[int] | None = None, again: bool = False) -> dict:
    """存一条任务。同指纹已有排队／在跑／成功的（且没给 again）就记成 duplicate 指向它。"""
    with conn.transaction():
        dup = None
        if not again:
            dup = _one(conn.execute(
                "SELECT id, status FROM jobs.job WHERE spec_hash=%s AND status IN ('queued','running','succeeded')"
                " ORDER BY (status='succeeded') DESC, id DESC LIMIT 1", (h,)))
        row = _one(conn.execute(
            "INSERT INTO jobs.job (kind, book, spec, spec_hash, status, priority, depends_on, duplicate_of,"
            " submitted_by, why, finished_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (spec["kind"], spec["book"], json.dumps(spec, ensure_ascii=False), h,
             "duplicate" if dup else "queued", priority, depends_on or [], dup and dup["id"], by, why,
             None if not dup else _now(conn))))
        _event(conn, row["id"], None, "submit", f"{by} 提交" + (f"；与 #{dup['id']}（{dup['status']}）同一配置，不另跑"
                                                             if dup else ""))
    row["dup_status"] = dup and dup["status"]
    return row


def _now(conn):
    return conn.execute("SELECT now()").fetchone()[0]


def list_jobs(conn, *, status: list[str] | None = None, book: str | None = None, limit: int = 30,
              mine: str | None = None) -> list[dict]:
    q = ["SELECT j.*, (SELECT a.worker FROM jobs.attempt a WHERE a.job_id=j.id ORDER BY a.n DESC LIMIT 1) worker"
         " FROM jobs.job j WHERE true"]
    a: list = []
    if status:
        q.append("AND j.status = ANY(%s)")
        a.append(status)
    if book:
        q.append("AND j.book = %s")
        a.append(book)
    if mine:
        q.append("AND j.submitted_by = %s")
        a.append(mine)
    q.append("ORDER BY (j.status='running') DESC, (j.status='queued') DESC,"
             " CASE WHEN j.status='queued' THEN j.priority END, CASE WHEN j.status='queued' THEN j.id END, j.id DESC LIMIT %s")
    a.append(limit)
    return _rows(conn.execute(" ".join(q), a))


def get(conn, job_id: int) -> dict | None:
    return _one(conn.execute("SELECT * FROM jobs.job WHERE id=%s", (job_id,)))


def detail(conn, job_id: int) -> dict | None:
    j = get(conn, job_id)
    if j is None:
        return None
    j["attempts_rows"] = _rows(conn.execute("SELECT * FROM jobs.attempt WHERE job_id=%s ORDER BY n", (job_id,)))
    j["events"] = _rows(conn.execute("SELECT * FROM jobs.event WHERE job_id=%s ORDER BY id", (job_id,)))
    j["results"] = _rows(conn.execute("SELECT * FROM jobs.result WHERE job_id=%s ORDER BY id", (job_id,)))
    return j


def results(conn, job_id: int, kind: str | None = None) -> list[dict]:
    q, a = "SELECT * FROM jobs.result WHERE job_id=%s", [job_id]
    if kind:
        q += " AND kind=%s"
        a.append(kind)
    return _rows(conn.execute(q + " ORDER BY id", a))


def cancel(conn, job_id: int, by: str) -> str:
    """排队的直接取消；在跑的置 cancel_requested，执行方下次心跳时停掉子进程。"""
    with conn.transaction():
        j = _one(conn.execute("SELECT status FROM jobs.job WHERE id=%s FOR UPDATE", (job_id,)))
        if j is None:
            return "没有这条"
        if j["status"] == "queued":
            conn.execute("UPDATE jobs.job SET status='cancelled', finished_at=now(), updated_at=now() WHERE id=%s",
                         (job_id,))
            _event(conn, job_id, None, "cancel", f"{by} 取消（还没开跑）")
            return "已取消"
        if j["status"] == "running":
            conn.execute("UPDATE jobs.job SET cancel_requested=true, updated_at=now() WHERE id=%s", (job_id,))
            _event(conn, job_id, None, "cancel", f"{by} 要求停下")
            return "已要求停下（执行方一分钟内停）"
        return f"已是 {j['status']}，不用取消"


def bump(conn, job_id: int, priority: int, by: str) -> bool:
    with conn.transaction():
        r = conn.execute("UPDATE jobs.job SET priority=%s, updated_at=now() WHERE id=%s AND status='queued'",
                         (priority, job_id))
        if r.rowcount:
            _event(conn, job_id, None, "bump", f"{by} 把优先级改成 {priority}（越小越先）")
        return bool(r.rowcount)


def retry(conn, job_id: int, by: str) -> bool:
    """失败／blocked／取消的单重新排队（同一条，attempts 清零）。"""
    with conn.transaction():
        r = conn.execute(
            "UPDATE jobs.job SET status='queued', attempts=0, error=NULL, stage=NULL, progress=NULL,"
            " cancel_requested=false, finished_at=NULL, run_after=NULL, updated_at=now()"
            " WHERE id=%s AND status IN ('failed','blocked','cancelled')", (job_id,))
        if r.rowcount:
            _event(conn, job_id, None, "retry", f"{by} 重新排队")
        return bool(r.rowcount)


# ── 执行方 ────────────────────────────────────────────────────────────────

def reap(conn) -> list[tuple[int, str]]:
    """租约过期的 attempt 记 lost，任务退回排队（次数用完记 failed）；依赖失败的排队单记 blocked。"""
    out: list[tuple[int, str]] = []
    with conn.transaction():
        lost = _rows(conn.execute(
            "UPDATE jobs.attempt SET finished_at=now(), outcome='lost' WHERE finished_at IS NULL"
            " AND lease_until < now() RETURNING id, job_id, worker"))
        for a in lost:
            j = _one(conn.execute("SELECT attempts, max_attempts, status FROM jobs.job WHERE id=%s FOR UPDATE",
                                  (a["job_id"],)))
            if j is None or j["status"] != "running":
                continue
            if j["attempts"] >= j["max_attempts"]:
                conn.execute("UPDATE jobs.job SET status='failed', finished_at=now(), updated_at=now(),"
                             " error=%s WHERE id=%s",
                             (f"执行会话失联 {j['attempts']} 次（租约过期）", a["job_id"]))
                out.append((a["job_id"], "failed"))
            else:
                conn.execute("UPDATE jobs.job SET status='queued', stage=NULL, updated_at=now() WHERE id=%s",
                             (a["job_id"],))
                out.append((a["job_id"], "queued"))
            _event(conn, a["job_id"], a["id"], "reap", f"{a['worker']} 失联，租约过期，退回排队"
                   if out[-1][1] == "queued" else f"{a['worker']} 失联，次数用完", level="warn")
        dead = _rows(conn.execute(
            "UPDATE jobs.job j SET status='blocked', finished_at=now(), updated_at=now(),"
            " error=(SELECT '依赖 ' || string_agg('#' || d.id || '（' || d.status || '）', '、') || ' 没成功，不跑'"
            " FROM jobs.job d WHERE d.id = ANY(j.depends_on) AND d.status IN ('failed','blocked','cancelled'))"
            " WHERE j.status='queued' AND EXISTS (SELECT 1 FROM jobs.job d"
            " WHERE d.id = ANY(j.depends_on) AND d.status IN ('failed','blocked','cancelled')) RETURNING id"))
        for d in dead:
            _event(conn, d["id"], None, "reap", "依赖的任务没成功，不跑", level="warn")
            out.append((d["id"], "blocked"))
    return out


_CLAIM = """
WITH c AS (
  SELECT j.id FROM jobs.job j
  WHERE j.status = 'queued'
    AND NOT EXISTS (SELECT 1 FROM jobs.job d WHERE d.id = ANY(j.depends_on) AND d.status <> 'succeeded')
    AND (j.book IS NULL OR NOT EXISTS (SELECT 1 FROM jobs.job r WHERE r.book = j.book AND r.status = 'running'))
    AND (%(kinds)s::text[] IS NULL OR j.kind = ANY(%(kinds)s))
    AND (%(only)s::bigint IS NULL OR j.id = %(only)s)
    AND (j.run_after IS NULL OR j.run_after <= now() OR %(only)s::bigint IS NOT NULL)
  ORDER BY j.priority,
    EXISTS (SELECT 1 FROM jobs.attempt f WHERE f.job_id = j.id AND f.worker = %(who)s AND f.outcome = 'failed'),
    (j.book IS NOT DISTINCT FROM %(aff)s) DESC, j.created_at, j.id
  FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE jobs.job j SET status = 'running', attempts = j.attempts + 1, started_at = coalesce(j.started_at, now()),
  stage = 'claimed', progress = NULL, error = NULL, run_after = NULL, updated_at = now()
FROM c WHERE j.id = c.id RETURNING j.*
"""


def claim(conn, worker: str, *, session: str | None = None, affinity: str | None = None,
          kinds: list[str] | None = None, only: int | None = None) -> tuple[dict, dict] | None:
    """领一条可跑的单，返回 (job, attempt)；没有就 None。"""
    import psycopg
    for _ in range(5):
        try:
            with conn.transaction():
                j = _one(conn.execute(_CLAIM, {"kinds": kinds, "aff": affinity, "only": only, "who": worker}))
                if j is None:
                    return None
                # 领单序号接着这条单历来的最大序号往下排：retry 把 attempts（重试额度）清零，但旧 attempt 还在
                a = _one(conn.execute(
                    "INSERT INTO jobs.attempt (job_id, n, worker, session, host, cv_commit, lease_until)"
                    " SELECT %s, coalesce(max(n), 0) + 1, %s, %s, %s, %s, now() + make_interval(mins => %s)"
                    " FROM jobs.attempt WHERE job_id = %s RETURNING *",
                    (j["id"], worker, session, socket.gethostname(), j["spec"].get("cv"), LEASE_MIN, j["id"])))
                _event(conn, j["id"], a["id"], "claim", f"{worker} 领单（第 {a['n']} 次）")
                return j, a
        except psycopg.errors.UniqueViolation as e:
            if e.diag.constraint_name != "job_one_running_per_book":
                raise
            continue      # 同册被别的执行方同时领走，换一条
    return None


def heartbeat(conn, attempt_id: int, *, stage: str | None = None, progress: str | None = None) -> bool:
    """续租，顺手更新阶段与进展；返回是否有人要求停下。租约已被收回（会话卡太久）也当作要停。"""
    with conn.transaction():
        r = _one(conn.execute(
            "UPDATE jobs.attempt SET heartbeat_at=now(), lease_until=now() + make_interval(mins => %s)"
            " WHERE id=%s AND finished_at IS NULL RETURNING job_id", (LEASE_MIN, attempt_id)))
        if r is None:
            return True
        j = _one(conn.execute(
            "UPDATE jobs.job SET stage=coalesce(%s, stage), progress=coalesce(%s, progress), updated_at=now()"
            " WHERE id=%s RETURNING cancel_requested", (stage, progress, r["job_id"])))
        return bool(j and j["cancel_requested"])


def event(conn, job_id: int, attempt_id: int | None, stage: str | None, msg: str, *, level: str = "info",
          secs: float | None = None, data: dict | None = None) -> None:
    with conn.transaction():
        _event(conn, job_id, attempt_id, stage, msg, level=level, secs=secs, data=data)


def _event(conn, job_id, attempt_id, stage, msg, *, level="info", secs=None, data=None) -> None:
    conn.execute("INSERT INTO jobs.event (job_id, attempt_id, stage, level, msg, secs, data)"
                 " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (job_id, attempt_id, stage, level, msg[:4000], secs,
                  json.dumps(data, ensure_ascii=False) if data is not None else None))


def add_result(conn, job_id: int, attempt_id: int | None, kind: str, name: str, *,
               location: str | None = None, data: dict | None = None) -> None:
    with conn.transaction():
        conn.execute("INSERT INTO jobs.result (job_id, attempt_id, kind, name, location, data)"
                     " VALUES (%s,%s,%s,%s,%s,%s)",
                     (job_id, attempt_id, kind, name, location,
                      json.dumps(data, ensure_ascii=False) if data is not None else None))


def finish(conn, job_id: int, attempt_id: int, outcome: str, *, error: str | None = None,
           exit_code: int | None = None, log_tail: str | None = None) -> None:
    """收尾。failed 而次数没用完的，退回排队重试；blocked／cancelled／succeeded 都是终态。"""
    with conn.transaction():
        conn.execute("UPDATE jobs.attempt SET finished_at=now(), outcome=%s, exit_code=%s, log_tail=%s"
                     " WHERE id=%s", (outcome, exit_code, (log_tail or "")[-8000:] or None, attempt_id))
        j = _one(conn.execute("SELECT attempts, max_attempts FROM jobs.job WHERE id=%s FOR UPDATE", (job_id,)))
        status = outcome
        if outcome == "failed" and j and j["attempts"] < j["max_attempts"] and (error or "").startswith("环境："):
            status = "queued"      # 环境类故障（断网、库连不上）换个会话再试；配置或代码错不重试
        # 退回排队的隔 5×已领次数 分钟再领，且优先让别的执行方领（见 _CLAIM 排序）
        conn.execute(
            "UPDATE jobs.job SET status=%s, error=%s, updated_at=now(), finished_at=CASE WHEN %s='queued'"
            " THEN NULL ELSE now() END, stage=CASE WHEN %s='queued' THEN NULL ELSE stage END,"
            " run_after=CASE WHEN %s='queued' THEN now() + make_interval(mins => %s * attempts) END WHERE id=%s",
            (status, error, status, status, status, RETRY_BACKOFF_MIN, job_id))
        _event(conn, job_id, attempt_id, "finish", {"succeeded": "完成", "failed": "失败", "blocked": "拦下（检查没过）",
                                                     "cancelled": "已停", "queued": "失败，退回排队重试"}[status]
               + (f"：{error}" if error else ""), level="info" if status == "succeeded" else "warn")


def worker_seen(conn, name: str, *, state: str, session: str | None = None, job_id: int | None = None,
                runner: str | None = None, done: int | None = None, started: bool = False,
                note: str | None = None) -> None:
    """执行方报到／心跳：started=True 是刚起（重置开始时间）；state 为 idle／busy／stopped。"""
    with conn.transaction():
        conn.execute(
            "INSERT INTO jobs.worker (name, session, host, runner, state, job_id, done, note) VALUES"
            " (%s,%s,%s,%s,%s,%s,coalesce(%s,0),%s) ON CONFLICT (name) DO UPDATE SET"
            " session=coalesce(EXCLUDED.session, jobs.worker.session), host=EXCLUDED.host,"
            " runner=coalesce(EXCLUDED.runner, jobs.worker.runner), state=EXCLUDED.state, job_id=EXCLUDED.job_id,"
            " done=coalesce(%s, jobs.worker.done), note=coalesce(EXCLUDED.note, jobs.worker.note), seen_at=now(),"
            " started_at=CASE WHEN %s THEN now() ELSE jobs.worker.started_at END",
            (name, session, socket.gethostname(), runner, state, job_id, done, note, done, started))


def workers(conn, minutes: int = 5) -> list[dict]:
    """登记过的执行方，带是否在线（近 minutes 分钟内报到过，且没说已停）。库还没升到有 worker 表时返回空。"""
    import psycopg
    try:
        with conn.transaction():
            return _rows(conn.execute(
                "SELECT w.*, (w.state <> 'stopped' AND w.seen_at > now() - make_interval(mins => %s)) AS online"
                " FROM jobs.worker w ORDER BY online DESC, w.seen_at DESC", (minutes,)))
    except psycopg.errors.UndefinedTable:
        return []


def live_workers(conn, minutes: int = 3) -> list[dict]:
    """近几分钟有心跳的执行方（在跑单的）。"""
    return _rows(conn.execute(
        "SELECT a.worker, a.session, a.job_id, a.heartbeat_at FROM jobs.attempt a WHERE a.finished_at IS NULL"
        " AND a.heartbeat_at > now() - make_interval(mins => %s) ORDER BY a.heartbeat_at DESC", (minutes,)))


def queue_depth(conn) -> int:
    return conn.execute("SELECT count(*) FROM jobs.job WHERE status='queued'").fetchone()[0]
