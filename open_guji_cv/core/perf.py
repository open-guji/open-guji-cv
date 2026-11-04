"""跑批耗时统计（2026-11-03，A20；方案见 Claude Doc《CV 管线性能统计方案》）。

回答「跑那么多脚本，哪一步慢、慢在哪、哪里能提速」。三样东西：

- `span("名字")` / `@timed("名字")`：给一段代码计墙钟（perf_counter）和 CPU（process_time），可嵌套；
  `count("名字", n)`：计数（缓存命中、候选数……）。都按「当前这一步这一页」累加，不逐次记流水，
  开销微秒级。**不在跑批里（没有 `page_scope`）时什么也不做**，单测、控制台调同一函数不受影响。
- `page_scope(step, page)`：引擎包住一页，期间所有 span／count 记到这一页名下。
- `RunPerf`：一次 `Engine.run()` 一份，边跑边往 `<产物根>/../perf/<册>/<run_id>.jsonl` 追加：
  开头一行 run（机器、版本、命令行、任务库单号），每页一行 page，每步一行 step（汇总＋最慢 20 页），
  末尾一行 end。断了也有前半。

**本模块不进任何 Step 的 `code_deps`，改它不动指纹**；Step 里打 span 会改那个 Step 模块的源码，
要走 `core/code_equiv` 登记（产物逐字节相同才登记）。文件放在产物根**外面**的 `perf/`：
产物包、冻结登记、部署检查都按产物根下的目录当步／册扫，放进去会被当成一步打包。

关掉：环境变量 `GUJI_PERF=0`。换目录：`GUJI_PERF_DIR`。
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sys
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

#: 每步 step 行里带几张最慢的页
SLOWEST_N = 20

_cur: PageRec | None = None

#: 一次运行写完（`RunPerf.close`）后调的回调，参数是 perf 文件路径。引擎在 L1、不认识任务库，
#: 推到美国机 jobs 库的逻辑由命令行层（`cli_v2.main`）登记进来（`jobs/perf_push.py`）。
_sinks: list = []


def add_sink(fn) -> None:
    if fn not in _sinks:
        _sinks.append(fn)


class PageRec:
    """一页一步的分段累加：spans = {名字: [次数, 墙钟秒, CPU 秒]}，counts = {名字: 数}。"""

    __slots__ = ("_stack", "counts", "spans")

    def __init__(self) -> None:
        self.spans: dict[str, list] = {}
        self.counts: dict[str, int] = {}
        self._stack: list[str] = []

    def add(self, name: str, wall: float, cpu: float) -> None:
        s = self.spans.get(name)
        if s is None:
            self.spans[name] = [1, wall, cpu]
        else:
            s[0] += 1
            s[1] += wall
            s[2] += cpu

    def to_dict(self) -> dict:
        out: dict = {}
        if self.spans:
            out["spans"] = {k: [v[0], round(v[1], 4), round(v[2], 4)] for k, v in self.spans.items()}
        if self.counts:
            out["counts"] = dict(self.counts)
        return out


@contextmanager
def page_scope(rec: PageRec | None = None):
    """把这段时间里的 span／count 记进 `rec`（缺省新建一个）；可嵌套，退出时还原外层。"""
    global _cur
    prev, _cur = _cur, (rec if rec is not None else PageRec())
    try:
        yield _cur
    finally:
        _cur = prev


@contextmanager
def span(name: str):
    """计一段代码的墙钟与 CPU。嵌套的 span 记成 `外层/内层`，同名多次累加。不在跑批里时是空操作。"""
    rec = _cur
    if rec is None:
        yield
        return
    full = "/".join((*rec._stack, name)) if rec._stack else name
    rec._stack.append(name)
    t0, c0 = time.perf_counter(), time.process_time()
    try:
        yield
    finally:
        rec.add(full, time.perf_counter() - t0, time.process_time() - c0)
        rec._stack.pop()


def timed(name: str | None = None):
    """装饰器版 `span`：`@timed()` 用函数名，`@timed("读模板表")` 用给的名字。"""
    def deco(fn):
        label = name or fn.__name__

        @wraps(fn)
        def wrapper(*a, **kw):
            if _cur is None:
                return fn(*a, **kw)
            with span(label):
                return fn(*a, **kw)
        return wrapper
    return deco


def count(name: str, n: int = 1) -> None:
    """计数。不在跑批里时是空操作。"""
    rec = _cur
    if rec is not None:
        rec.counts[name] = rec.counts.get(name, 0) + n


def enabled() -> bool:
    return os.environ.get("GUJI_PERF", "1") not in ("0", "false", "no", "off")


def machine_info() -> dict:
    """机器规格：横比同一步的耗时必须连着它读（4 核云端与 8 核本机不能直接比）。"""
    info = {"host": os.environ.get("GUJI_MACHINE") or socket.gethostname(),
            "platform": platform.platform(terse=True), "python": platform.python_version(),
            "cpus": os.cpu_count()}
    try:
        info["cpus_usable"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    info["mem_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except OSError:
        pass
    # 机器类别：云端会话 / 服务器 / 本机。显式给 GUJI_MACHINE_KIND 为准
    kind = os.environ.get("GUJI_MACHINE_KIND")
    if not kind:
        kind = "cloud" if os.environ.get("CLAUDE_CODE_REMOTE") else ("windows" if os.name == "nt" else "local")
    info["kind"] = kind
    if os.environ.get("CLAUDE_CODE_CONTAINER_ID"):   # 云端容器主机名都是 vm，靠容器号区分
        info["container"] = os.environ["CLAUDE_CODE_CONTAINER_ID"].removeprefix("container_")[:16]
    if "torch" in sys.modules:          # 只看已经 import 的，不为统计去加载 torch
        try:
            t = sys.modules["torch"]
            info["gpu"] = t.cuda.get_device_name(0) if t.cuda.is_available() else None
        except Exception:  # noqa: BLE001
            pass
    return info


def _rusage() -> tuple[float, float, int]:
    """(本进程 CPU 秒, 子进程 CPU 秒, 本进程峰值内存 MB)；没有 resource 模块（Windows）回 0。"""
    try:
        import resource
    except ImportError:
        return time.process_time(), 0.0, 0
    s = resource.getrusage(resource.RUSAGE_SELF)
    c = resource.getrusage(resource.RUSAGE_CHILDREN)
    rss = s.ru_maxrss // (1024 * 1024 if sys.platform == "darwin" else 1024)
    return s.ru_utime + s.ru_stime, c.ru_utime + c.ru_stime, int(rss)


def _pct(xs: list[float], q: float) -> float:
    return xs[min(len(xs) - 1, int(len(xs) * q))]


class StepPerf:
    """一步的累加器：引擎每页 `page(...)` 一次，跑完 `finish()` 出 step 行。"""

    def __init__(self, run: RunPerf, step: str, n_pages: int, jobs: int) -> None:
        self.run, self.step, self.n_pages, self.jobs = run, step, n_pages, jobs
        self.t0 = time.perf_counter()
        self.cpu0, self.ccpu0, _ = _rusage()
        self.status = {"ok": 0, "skipped": 0, "failed": 0}
        self.elapsed: list[tuple[float, int]] = []
        self.spans: dict[str, list] = {}
        self.counts: dict[str, int] = {}
        self.overhead: dict[str, float] = {}

    def add_overhead(self, name: str, secs: float) -> None:
        """引擎在主进程做的、不算进单页计算的事：算指纹、清缓存、落盘、整册准备……"""
        self.overhead[name] = self.overhead.get(name, 0.0) + secs

    def page(self, page: int, status: str, elapsed: float | None = None, detail: dict | None = None,
             overhead: dict | None = None) -> None:
        self.status[status] = self.status.get(status, 0) + 1
        for k, v in (overhead or {}).items():
            self.add_overhead(k, v)
        if status == "skipped":
            return                       # 跳过的页只计数，不写 page 行（每次重跑大多是跳过）
        row = {"t": "page", "step": self.step, "page": page, "status": status}
        if elapsed is not None:
            row["elapsed"] = round(elapsed, 4)
            if status == "ok":
                self.elapsed.append((elapsed, page))
        if overhead:
            row["overhead"] = {k: round(v, 4) for k, v in overhead.items()}
        for k, v in (detail or {}).get("spans", {}).items():
            s = self.spans.setdefault(k, [0, 0.0, 0.0])
            s[0] += v[0]
            s[1] += v[1]
            s[2] += v[2]
        for k, v in (detail or {}).get("counts", {}).items():
            self.counts[k] = self.counts.get(k, 0) + v
        if detail:
            row.update(detail)
        self.run.write(row)

    def finish(self) -> dict:
        cpu1, ccpu1, rss = _rusage()
        wall = time.perf_counter() - self.t0
        el = sorted(e for e, _ in self.elapsed)
        row: dict = {"t": "step", "step": self.step, "pages": self.n_pages, "jobs": self.jobs,
                     **self.status, "wall_s": round(wall, 3),
                     "cpu_s": round(cpu1 - self.cpu0, 2), "child_cpu_s": round(ccpu1 - self.ccpu0, 2),
                     "peak_rss_mb": rss}
        if el:
            total = sum(el)
            row.update({"compute_s": round(total, 3), "p50_s": round(_pct(el, 0.5), 3),
                        "p90_s": round(_pct(el, 0.9), 3), "max_s": round(el[-1], 3)})
            if self.jobs > 1 and wall > 0:
                row["parallel_eff"] = round(total / (wall * self.jobs), 3)
            row["slowest"] = [[p, round(e, 3)] for e, p in sorted(self.elapsed, reverse=True)[:SLOWEST_N]]
        if self.overhead:
            row["overhead"] = {k: round(v, 3) for k, v in self.overhead.items()}
        if self.spans:
            row["spans"] = {k: [v[0], round(v[1], 3), round(v[2], 3)] for k, v in self.spans.items()}
        if self.counts:
            row["counts"] = self.counts
        self.run.write(row)
        return row


class RunPerf:
    """一次运行的耗时记录。写不进文件（只读目录、磁盘满）就安静地不记，绝不拖垮跑批。"""

    def __init__(self, products_root: Path, book: str, meta: dict) -> None:
        self.run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.path = perf_dir(products_root) / book / f"{self.run_id}.jsonl"
        self.t0 = time.perf_counter()
        self.steps: list[dict] = []
        self._ok = True
        self.write({"t": "run", "run_id": self.run_id, "book": book, "started_at": time.time(),
                    "argv": sys.argv[1:], "job_id": os.environ.get("GUJI_JOB_ID"),
                    "group": os.environ.get("GUJI_PERF_GROUP"),
                    "machine": machine_info(), **meta})

    def write(self, row: dict) -> None:
        if not self._ok:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            self._ok = False

    def step(self, step: str, n_pages: int, jobs: int = 1) -> StepPerf:
        return StepPerf(self, step, n_pages, jobs)

    def close(self, stopped: bool = False) -> None:
        self.write({"t": "end", "run_id": self.run_id, "finished_at": time.time(),
                    "wall_s": round(time.perf_counter() - self.t0, 3), "stopped": stopped})
        if self._ok:
            for fn in _sinks:
                try:
                    fn(self.path)
                except Exception as e:  # noqa: BLE001 —— 统计推不上绝不拖垮跑批
                    print(f"  ⚠ 耗时记录没推上（{type(e).__name__}: {str(e)[:120]}），之后 guji perf push 补",
                          file=sys.stderr)


def perf_dir(products_root: Path) -> Path:
    """perf 文件的根：`GUJI_PERF_DIR`，缺省产物根旁边的 `perf/`。"""
    if os.environ.get("GUJI_PERF_DIR"):
        return Path(os.environ["GUJI_PERF_DIR"])
    return Path(products_root).resolve().parent / "perf"


def load(path: Path) -> dict:
    """读一份 perf 文件 → {"run": {...}, "steps": [...], "pages": [...], "end": {...}|None}。坏行跳过。"""
    out: dict = {"run": None, "steps": [], "pages": [], "end": None}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        t = row.get("t")
        if t == "run":
            out["run"] = row
        elif t == "step":
            out["steps"].append(row)
        elif t == "page":
            out["pages"].append(row)
        elif t == "end":
            out["end"] = row
    return out


def runs(root: Path, book: str | None = None, since: float | None = None) -> list[dict]:
    """读 `root`（perf_dir）下的运行记录，按开始时间从新到旧。`since` 是 epoch 秒。"""
    root = Path(root)
    files = sorted((root / book).glob("*.jsonl") if book else root.glob("*/*.jsonl"), reverse=True)
    out = []
    for f in files:
        r = load(f)
        if r["run"] is None or (since and (r["run"].get("started_at") or 0) < since):
            continue
        r["path"] = str(f)
        out.append(r)
    return out


def top(rs: list[dict]) -> list[dict]:
    """把多次运行的 step 行按步合起来：总计算秒、页数、每页中位（各次 p50 按页数加权近似）、墙钟、次数。
    按总墙钟从大到小——先看机器时间花在哪。"""
    agg: dict[str, dict] = {}
    for r in rs:
        for s in r["steps"]:
            a = agg.setdefault(s["step"], {"step": s["step"], "runs": 0, "pages_run": 0, "skipped": 0,
                                           "wall_s": 0.0, "compute_s": 0.0, "_p50w": 0.0, "max_s": 0.0,
                                           "overhead": {}, "spans": {}})
            a["runs"] += 1
            a["pages_run"] += s.get("ok", 0) + s.get("failed", 0)
            a["skipped"] += s.get("skipped", 0)
            a["wall_s"] += s.get("wall_s", 0.0)
            a["compute_s"] += s.get("compute_s", 0.0)
            a["_p50w"] += s.get("p50_s", 0.0) * s.get("ok", 0)
            a["max_s"] = max(a["max_s"], s.get("max_s", 0.0))
            for k, v in (s.get("overhead") or {}).items():
                a["overhead"][k] = a["overhead"].get(k, 0.0) + v
            for k, v in (s.get("spans") or {}).items():
                a["spans"][k] = a["spans"].get(k, 0.0) + v[1]
    rows = []
    for a in agg.values():
        ok = a["pages_run"]
        a["p50_s"] = round(a.pop("_p50w") / ok, 3) if ok else None
        a["wall_s"], a["compute_s"] = round(a["wall_s"], 1), round(a["compute_s"], 1)
        rows.append(a)
    return sorted(rows, key=lambda a: a["wall_s"], reverse=True)
