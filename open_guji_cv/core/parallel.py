"""页级并行的审查登记（2026-10-20）：哪些 Step 审过、可以 `--jobs N` 按页并行跑。

## 为什么不直接在 Step 上标 `StepSpec.parallel_safe=True`

`parallel_safe` 写在 Step 模块里，而 Step 模块的源码进 `code_hash`（`core/engine.py::code_hash`）：
给 `glyph_match` 加这一个关键字参数，四庫各册 Step5 以下全线判过期、整册重算——可并行与否
根本不改产物（计算在子进程、落盘在主进程，产物逐字节相同，见 `Engine._run_one_step_parallel`）。
所以审查结论登记在这里：本模块不在任何 Step 的 `code_deps` 里，改它不动指纹。
`StepSpec.parallel_safe` 照旧认（`border_detect`／`line_detect` 早就标在 Step 上），两处任一为真即可。

## 登记纪律（同 `StepSpec.parallel_safe` 的文档）

标错的代价是**静默数据错误**，不是报错。每一条都要写清审过什么：没有跨页累积状态；
一次性初始化（字形库、模型）在每个 worker 里各建一份不出错；只写按页隔离的东西；
读的外部状态（字形库、人裁）在一次跑批里不变。最后一道是实测：同一批页串行与并行跑，
产物 sha256 逐页相同（`scripts/parallel_equivalence.py`）。

## 内存

每个 worker 各自加载一份重资源。`mem_gb` 是**单个 worker 的峰值常驻内存**（实测），
引擎按本机可用内存把进程数压下来，免得并行把机器拖进换页——慢过串行，或被 OOM 杀掉。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ParallelAudit:
    mem_gb: float
    """单个 worker 的峰值常驻内存（GB，实测，留了余量）。"""
    note: str
    """审了什么、怎么验的。"""


AUDITED: dict[str, ParallelAudit] = {
    "row_segment": ParallelAudit(
        mem_gb=1.5,
        note="run_page 只读本页 gate_manifest／column_windows／列图与册级人裁表（lookup，只读），"
             "U-Net 裁判是进程内单例（get_judge），每个 worker 各载一份；列图惰性再生写的是本页的键，"
             "改戳走 ImageCache 的锁。第四册串行／4 进程产物逐页比对：待验（scripts/parallel_equivalence.py）。"),
    "glyph_match": ParallelAudit(
        mem_gb=2.0,
        note="字形库匹配器走 seeding.cached_matcher_from_db 的进程级缓存，worker 各建一份（约 17 s）；"
             "人裁例数、借用名单按库指纹缓存在 step 实例上，只读。格级复用读的是本步旧产物，"
             "本步产物只由主进程写。cell_budget_s 是按墙钟的每格预算（缺省关）：开着时并行"
             "让单格变慢就可能多出 timeout 格——与换台机器跑同一性质，不是并行特有。"
             "第四册串行／4 进程产物逐页比对：待验（scripts/parallel_equivalence.py）。"),
}


def is_parallel_safe(step) -> bool:
    return bool(step.spec.parallel_safe) or step.spec.id in AUDITED


def available_memory_gb() -> float | None:
    """本机此刻可用内存（GB）；取不到返回 None（不按内存压进程数）。"""
    try:
        if os.name == "nt":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return None
            return ms.ullAvailPhys / (1 << 30)
        with open("/proc/meminfo", encoding="ascii") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) / (1 << 20)
    except Exception:  # noqa: BLE001 —— 只是限流参考，取不到就不限
        return None
    return None


def effective_jobs(step, jobs: int) -> tuple[int, str | None]:
    """(这一步实际用几个进程, 被压下来的原因或 None)。

    上限三条取最小：调用方给的 `jobs`、页数之外的 CPU 数、可用内存 ÷ 单 worker 峰值。
    主进程自己也占着内存（产物落盘、manifest），留一个 worker 的量给它。"""
    if jobs <= 1:
        return 1, None
    n = min(jobs, os.cpu_count() or jobs)
    why = None
    if n < jobs:
        why = f"CPU 只有 {n} 核"
    audit = AUDITED.get(step.spec.id)
    avail = available_memory_gb() if audit else None
    if audit and avail is not None:
        by_mem = max(1, int(avail // audit.mem_gb) - 1)
        if by_mem < n:
            n, why = by_mem, f"可用内存 {avail:.1f} GB，单进程约 {audit.mem_gb:g} GB"
    return n, why


def worker_threads(jobs: int) -> int:
    """每个 worker 给 torch／BLAS 几个线程：核数平分，至少 1。
    不压的话 4 个 worker 各开 4 个线程，16 个线程抢 4 个核，比串行还慢。"""
    return max(1, (os.cpu_count() or 1) // max(1, jobs))
