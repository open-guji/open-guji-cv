"""任务队列：一个 worker 串行跑子进程，日志落 runs/<id>.log，记录落 runs/<id>.json。

沿用 web/runner.py 的子进程模型（隔离崩溃与 GPU 显存），加了：落盘（控制台重启不丢）、
队列（同一时刻只跑一个，避免同一 book+step 互相写）、取消排队中的任务。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

PENDING, RUNNING, COMPLETED, FAILED, CANCELLED = "pending", "running", "completed", "failed", "cancelled"
TERMINAL = {COMPLETED, FAILED, CANCELLED}


def default_runs_root() -> Path:
    env = os.environ.get("GUJI_RUNS_DIR")
    return Path(env) if env else Path(__file__).resolve().parent.parent.parent / "runs"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@dataclass
class JobSpec:
    book: str
    pipeline: str
    from_step: str | None = None
    to_step: str | None = None
    pages: str = "dev_set"
    force: bool = False
    params: dict = field(default_factory=dict)

    def argv(self) -> list[str]:
        cmd = [sys.executable, "-m", "open_guji_cv", "pipeline", self.pipeline, self.book,
               "--pages", self.pages]
        if self.from_step:
            cmd += ["--from", self.from_step]
        if self.to_step:
            cmd += ["--to", self.to_step]
        if self.force:
            cmd.append("--force")
        if self.params:
            cmd += ["--params", json.dumps(self.params, ensure_ascii=False)]
        return cmd


@dataclass
class Job:
    id: str
    spec: JobSpec
    status: str = PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    pid: int | None = None
    argv: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["spec"] = asdict(self.spec)
        d["duration"] = (round((self.finished_at or time.time()) - self.started_at, 1)
                         if self.started_at else None)
        return d


class JobRunner:
    def __init__(self, runs_root: Path | None = None):
        self.root = runs_root or default_runs_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._q: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._load_existing()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="guji-jobs")
        self._worker.start()

    # ── 持久化 ───────────────────────────────────────────────────────
    def _rec_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def log_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.log"

    def _save(self, job: Job) -> None:
        self._rec_path(job.id).write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=1),
                                          encoding="utf-8")

    def _load_existing(self) -> None:
        for p in sorted(self.root.glob("job_*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                spec = JobSpec(**{k: v for k, v in d["spec"].items() if k in JobSpec.__dataclass_fields__})
                job = Job(id=d["id"], spec=spec, status=d.get("status", FAILED),
                          created_at=d.get("created_at", 0), started_at=d.get("started_at"),
                          finished_at=d.get("finished_at"), exit_code=d.get("exit_code"),
                          pid=d.get("pid"), argv=d.get("argv", []))
                if job.status in (PENDING, RUNNING):      # 上次控制台死了，这些任务不会再跑
                    job.status = FAILED
                    job.finished_at = job.finished_at or time.time()
                    self._save(job)
                self.jobs[job.id] = job
            except Exception:
                continue

    # ── 对外 ─────────────────────────────────────────────────────────
    def submit(self, spec: JobSpec) -> Job:
        job = Job(id=f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}", spec=spec, argv=spec.argv())
        with self._lock:
            self.jobs[job.id] = job
        self._save(job)
        self._q.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self, limit: int = 50) -> list[dict]:
        jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs[:limit]]

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in TERMINAL:
            return False
        with self._lock:
            proc = self._procs.get(job_id)
            if proc is not None:
                proc.terminate()
            job.status = CANCELLED
            job.finished_at = time.time()
        self._save(job)
        return True

    def running(self) -> Job | None:
        return next((j for j in self.jobs.values() if j.status == RUNNING), None)

    # ── worker ───────────────────────────────────────────────────────
    def _loop(self) -> None:
        while True:
            job_id = self._q.get()
            job = self.jobs.get(job_id)
            if job is None or job.status != PENDING:
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        log = self.log_path(job.id)
        with open(log, "w", encoding="utf-8") as f:
            f.write("$ " + " ".join(job.argv) + "\n")
            f.flush()
            try:
                proc = subprocess.Popen(job.argv, stdout=f, stderr=subprocess.STDOUT,
                                        cwd=repo_root(), env=env)
            except Exception as e:   # noqa: BLE001
                f.write(f"启动失败: {e}\n")
                job.status, job.finished_at = FAILED, time.time()
                self._save(job)
                return
            with self._lock:
                self._procs[job.id] = proc
                job.status, job.started_at, job.pid = RUNNING, time.time(), proc.pid
            self._save(job)
            code = proc.wait()
        with self._lock:
            self._procs.pop(job.id, None)
            if job.status != CANCELLED:
                job.status = COMPLETED if code == 0 else FAILED
            job.exit_code, job.finished_at = code, time.time()
        self._save(job)
