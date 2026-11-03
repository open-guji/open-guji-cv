"""把本机跑批耗时记录（`core/perf.py` 写的 `perf/<册>/<run_id>.jsonl`）推到美国机任务库。

**只推美国机**（`jobsdb.enabled()`，设了 JOBSDB_TOKEN）：没设就什么也不做，绝不往 Neon 写——
Neon 存储和出流量都按量计费（Sheldon 11-03 定）。每次运行只推 run 一行＋每步一行（含最慢 20 页），
约 15 KB；每页明细留在本机文件里。

表 `jobs.perf_run`／`jobs.perf_step`（与任务库同库同 schema，`jobs_rw` 是属主，`CREATE … IF NOT EXISTS` 幂等）。
推过的文件旁边写 `<run_id>.pushed`，`guji perf push` 补推时跳过；重复推是幂等的（主键 run_id／(run_id, step)）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS jobs.perf_run (
  run_id      text PRIMARY KEY,
  grp         text,
  book        text NOT NULL,
  book_id     text,
  pipeline    text,
  steps       text[],
  n_pages     integer,
  jobs        integer,
  force       boolean,
  job_id      bigint,
  cv_version  text,
  cv_commit   text,
  host        text,
  machine     jsonb,
  argv        jsonb,
  started_at  timestamptz,
  finished_at timestamptz,
  wall_s      real,
  stopped     boolean,
  pushed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS perf_run_started ON jobs.perf_run (started_at DESC);
CREATE INDEX IF NOT EXISTS perf_run_book ON jobs.perf_run (book, started_at DESC);
CREATE INDEX IF NOT EXISTS perf_run_job ON jobs.perf_run (job_id) WHERE job_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS jobs.perf_step (
  run_id       text NOT NULL REFERENCES jobs.perf_run (run_id) ON DELETE CASCADE,
  step         text NOT NULL,
  pages        integer, ok integer, skipped integer, failed integer, jobs integer,
  wall_s       real, compute_s real, p50_s real, p90_s real, max_s real, parallel_eff real,
  cpu_s        real, child_cpu_s real, peak_rss_mb integer,
  overhead     jsonb, spans jsonb, counts jsonb, slowest jsonb,
  PRIMARY KEY (run_id, step)
);
CREATE INDEX IF NOT EXISTS perf_step_step ON jobs.perf_step (step);
"""

_STEP_COLS = ("pages", "ok", "skipped", "failed", "jobs", "wall_s", "compute_s", "p50_s", "p90_s", "max_s",
              "parallel_eff", "cpu_s", "child_cpu_s", "peak_rss_mb")
_STEP_JSON = ("overhead", "spans", "counts", "slowest")
_ready = False


def enabled() -> bool:
    from . import jobsdb
    return jobsdb.enabled()


def _ts(x):
    return datetime.fromtimestamp(x, tz=timezone.utc) if x else None


def _book_id(run: dict) -> str | None:
    """书 ID：工作区目录名 `<书ID>-…` 的前段（同 jobs.job.book_id 的口径），取不到回 None。"""
    import os
    ws = os.environ.get("GUJI_WORKSPACE") or ""
    head = Path(ws).name.split("-", 1)[0] if ws else ""
    return head if len(head) == 10 else None


def rows(path: Path) -> tuple[dict, list[dict]]:
    """perf 文件 → (perf_run 行, perf_step 行列表)。"""
    from ..core import perf
    r = perf.load(path)
    run, end = r["run"], r["end"] or {}
    if run is None:
        raise ValueError(f"{path} 没有 run 行")
    m = run.get("machine") or {}
    host = m.get("host")
    if m.get("container"):
        host = f"{host}:{m['container'][:8]}"
    job = run.get("job_id")
    head = {"run_id": run["run_id"], "grp": run.get("group"), "book": run["book"], "book_id": _book_id(run),
            "pipeline": run.get("pipeline"), "steps": run.get("steps"), "n_pages": run.get("n_pages"),
            "jobs": run.get("jobs"), "force": run.get("force"),
            "job_id": int(job) if job and str(job).isdigit() else None,
            "cv_version": run.get("cv_version"), "cv_commit": run.get("cv_commit"), "host": host,
            "machine": json.dumps(m, ensure_ascii=False), "argv": json.dumps(run.get("argv"), ensure_ascii=False),
            "started_at": _ts(run.get("started_at")), "finished_at": _ts(end.get("finished_at")),
            "wall_s": end.get("wall_s"), "stopped": end.get("stopped") if end else None}
    steps = []
    for s in r["steps"]:
        row = {"run_id": run["run_id"], "step": s["step"]}
        row.update({k: s.get(k) for k in _STEP_COLS})
        row.update({k: json.dumps(s[k], ensure_ascii=False) if s.get(k) is not None else None for k in _STEP_JSON})
        steps.append(row)
    return head, steps


def push_file(path: Path, conn=None) -> bool:
    """推一份；没开美国机任务库回 False。推完在旁边写 .pushed。"""
    global _ready
    if not enabled():
        return False
    path = Path(path)
    head, steps = rows(path)
    own = conn is None
    if own:
        from .store import connect
        conn = connect()
    try:
        with conn.transaction():
            if not _ready:
                conn.execute(DDL)
                _ready = True
            cols = list(head)
            conn.execute(
                f"INSERT INTO jobs.perf_run ({', '.join(cols)}) VALUES ({', '.join('%(' + c + ')s' for c in cols)}) "
                "ON CONFLICT (run_id) DO UPDATE SET finished_at = EXCLUDED.finished_at, wall_s = EXCLUDED.wall_s, "
                "stopped = EXCLUDED.stopped, pushed_at = now()", head)
            for s in steps:
                cols = list(s)
                upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("run_id", "step"))
                conn.execute(
                    f"INSERT INTO jobs.perf_step ({', '.join(cols)}) VALUES ({', '.join('%(' + c + ')s' for c in cols)}) "
                    f"ON CONFLICT (run_id, step) DO UPDATE SET {upd}", s)
    finally:
        if own:
            conn.close()
    path.with_suffix(".pushed").write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return True


def sink(path: Path) -> None:
    """`core.perf.add_sink` 用：一次运行写完就推（推不上由 perf 打一行警告）。"""
    push_file(path)


def pending(root: Path, book: str | None = None) -> list[Path]:
    """还没推过的 perf 文件，从旧到新（中断的运行没有 end 行，也照推，墙钟记空）。"""
    root = Path(root)
    files = sorted((root / book).glob("*.jsonl") if book else root.glob("*/*.jsonl"))
    return [f for f in files if not f.with_suffix(".pushed").exists()]


def push_pending(root: Path, book: str | None = None) -> tuple[int, int]:
    """补推；返回 (推了几份, 失败几份)。一条连接推完。"""
    if not enabled():
        raise SystemExit("没设 JOBSDB_TOKEN（美国机任务库）：耗时记录只推美国机，不推 Neon")
    from .store import connect
    files = pending(root, book)
    if not files:
        return 0, 0
    conn = connect()
    ok = bad = 0
    try:
        for f in files:
            try:
                push_file(f, conn)
                ok += 1
            except ValueError:
                bad += 1
    finally:
        conn.close()
    return ok, bad


def remote_top(days: float = 7, book: str | None = None, by: str | None = None) -> list[dict]:
    """在库里按步聚合好再回（几 KB）：近 `days` 天各步墙钟合计、跑页、每页中位（按页数加权）、最慢页。
    `by`＝host／cv_version／book 时再按它拆（行里多一列 `grp_key`）。"""
    from .store import connect
    if by not in (None, "host", "cv_version", "book"):
        raise ValueError(f"by 只能是 host／cv_version／book：{by}")
    extra_sel = f", r.{by} AS grp_key" if by else ""
    extra_grp = f", r.{by}" if by else ""
    where = "AND r.book = %(book)s" if book else ""
    sql = f"""
      SELECT s.step{extra_sel}, count(*) AS runs,
             sum(coalesce(s.ok, 0) + coalesce(s.failed, 0)) AS pages_run, sum(coalesce(s.skipped, 0)) AS skipped,
             round(sum(s.wall_s)::numeric, 1) AS wall_s, round(sum(s.compute_s)::numeric, 1) AS compute_s,
             round((sum(s.p50_s * s.ok) / nullif(sum(s.ok), 0))::numeric, 3) AS p50_s,
             round(max(s.max_s)::numeric, 2) AS max_s
        FROM jobs.perf_step s JOIN jobs.perf_run r USING (run_id)
       WHERE r.started_at >= now() - make_interval(secs => %(secs)s) {where}
       GROUP BY s.step{extra_grp} ORDER BY sum(s.wall_s) DESC NULLS LAST"""
    c = connect()
    try:
        cur = c.execute(sql, {"secs": days * 86400, "book": book})
        names = [d.name for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]
    finally:
        c.close()


def remote_job(job_id: int) -> list[dict]:
    """一条任务单的各次运行与各步（单号由执行方经 GUJI_JOB_ID 带上）。"""
    from .store import connect
    c = connect()
    try:
        cur = c.execute("""
          SELECT r.run_id, r.book, r.host, r.cv_version, r.started_at, r.wall_s AS run_wall_s,
                 s.step, s.ok, s.skipped, s.failed, s.wall_s, s.p50_s, s.max_s, s.overhead, s.slowest
            FROM jobs.perf_run r LEFT JOIN jobs.perf_step s USING (run_id)
           WHERE r.job_id = %s ORDER BY r.started_at, s.wall_s DESC""", (job_id,))
        names = [d.name for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]
    finally:
        c.close()
