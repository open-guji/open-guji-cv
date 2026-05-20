"""命令执行管理：subprocess 启动、进度解析、任务跟踪。"""

import os
import re
import sys
import time
import uuid
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Job:
    id: str
    command: str
    input_path: str
    output_path: str
    options: dict
    status: str = "running"  # running / completed / failed / cancelled
    process: subprocess.Popen | None = None
    lines: list = field(default_factory=list)  # [{type, line, timestamp}]
    progress: dict = field(default_factory=dict)  # {phase, done, total, pct}
    started_at: float = 0.0
    finished_at: float | None = None
    exit_code: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "status": self.status,
            "progress": self.progress,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "line_count": len(self.lines),
        }


# 进度解析正则
PHASE_RE = re.compile(r"(Phase \d+.*?|s\d+ \w+|分析|预处理|版面检测|字符网格).*?(\d+)\s*张")
PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]\s+(\d+)%")
STEP_RE = re.compile(r"(s\d+)\s+(\w+):")
COMPLETE_RE = re.compile(r"(完成|全部完成|Done)")


class CommandRunner:
    """管理 guji-cv 命令的执行。"""

    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def start(self, command: str, input_path: str, output_path: str,
              options: dict | None = None) -> str:
        """启动一个命令，返回 job_id。"""
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        options = options or {}

        job = Job(
            id=job_id,
            command=command,
            input_path=input_path,
            output_path=output_path,
            options=options,
            started_at=time.time(),
        )

        cmd = self._build_command(command, input_path, output_path, options)
        job.lines.append({
            "type": "info",
            "line": f"$ {' '.join(cmd)}",
            "timestamp": time.time(),
        })

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # 找到 open_guji_cv 包所在的目录作为 CWD
        project_root = str(Path(__file__).parent.parent.parent)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=project_root,
            )
            job.process = process
        except Exception as e:
            job.status = "failed"
            job.finished_at = time.time()
            job.lines.append({"type": "error", "line": str(e), "timestamp": time.time()})
            self.jobs[job_id] = job
            return job_id

        self.jobs[job_id] = job

        # 启动读取线程
        reader = threading.Thread(target=self._read_output, args=(job,), daemon=True)
        reader.start()

        return job_id

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status != "running":
            return False
        if job.process:
            job.process.terminate()
        job.status = "cancelled"
        job.finished_at = time.time()
        job.lines.append({"type": "info", "line": "任务已取消", "timestamp": time.time()})
        return True

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in sorted(
            self.jobs.values(), key=lambda j: j.started_at, reverse=True
        )]

    def _build_command(self, command: str, input_path: str,
                       output_path: str, options: dict) -> list[str]:
        cmd = [sys.executable, "-m", "open_guji_cv"]

        # recognize-profile 和 cut 不使用 -o
        if output_path and command not in ("recognize-profile", "cut", "show-profile"):
            cmd += ["-o", output_path]

        cmd.append(command)
        cmd.append(input_path)

        # 命令特有选项
        if options.get("profile"):
            cmd += ["--profile", options["profile"]]
        if options.get("range"):
            cmd += ["--range", options["range"]]
        if command == "extract":
            steps = options.get("steps", "all")
            cmd += ["--steps", steps]
            if options.get("input_dir"):
                cmd += ["--input-dir", options["input_dir"]]
        if command == "run":
            fmt = options.get("format", "char_grid")
            cmd += ["--format", fmt]
            if options.get("clean"):
                cmd.append("--clean")

        return cmd

    def _read_output(self, job: Job):
        """在后台线程中逐行读取 stdout，解析进度。"""
        try:
            for line in job.process.stdout:
                line = line.rstrip("\n\r")
                if not line:
                    continue

                entry = {
                    "type": "stdout",
                    "line": line,
                    "timestamp": time.time(),
                }
                job.lines.append(entry)

                # 解析进度
                self._parse_progress(job, line)

        except Exception:
            pass
        finally:
            if job.process:
                job.process.wait()
                job.exit_code = job.process.returncode

            if job.status == "running":
                job.status = "completed" if job.exit_code == 0 else "failed"
            job.finished_at = time.time()

    def _parse_progress(self, job: Job, line: str):
        """从 stdout 行中提取进度信息。"""
        # 阶段检测
        m = PHASE_RE.search(line)
        if m:
            job.progress["phase"] = m.group(1).strip()
            try:
                job.progress["total"] = int(m.group(2))
            except ValueError:
                pass

        # 步骤名检测
        m = STEP_RE.search(line)
        if m:
            job.progress["phase"] = f"{m.group(1)} {m.group(2)}"

        # 进度数值
        m = PROGRESS_RE.search(line)
        if m:
            job.progress["done"] = int(m.group(1))
            job.progress["total"] = int(m.group(2))
            job.progress["pct"] = int(m.group(3))

        # 完成标记
        if COMPLETE_RE.search(line):
            job.progress["pct"] = 100
