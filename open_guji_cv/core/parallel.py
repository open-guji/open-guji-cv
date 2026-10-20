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
    warm_first: bool = False
    """先在主进程跑一页把进程级缓存建好，再 fork（子进程写时复制共享），见 `Engine._run_one_step_parallel`。"""


AUDITED: dict[str, ParallelAudit] = {
    "cell_shrink": ParallelAudit(
        mem_gb=0.5,
        note="run_page 只读本页 cells／column_windows／列图与原图（印章遮挡），写的只有本页键的字块图"
             "（`cache.put`，原子写；清缓存与记戳在主进程）；extractor／crop_quality／frame_bar_strategy／"
             "seam 无模块级可变状态。第四册 46 页串行／4 进程产物与 8436 张字块图逐个相同，"
             "墙钟 27.8 s → 9.1 s，单进程 0.19 GB（2026-10-20）。"),
    "row_segment": ParallelAudit(
        mem_gb=1.0,
        note="run_page 只读本页 gate_manifest／column_windows／列图与册级人裁表（lookup，只读），"
             "U-Net 裁判是进程内单例（get_judge），每个 worker 各载一份；列图惰性再生写的是本页的键，"
             "改戳走 ImageCache 的锁。第四册 46 页串行／4 进程产物 sha 逐页相同，墙钟 65 s → 26 s；worker 里 torch 1 线程（2026-10-20）。"),
    "glyph_match": ParallelAudit(
        mem_gb=1.0, warm_first=True,
        note="字形库匹配器走 seeding.cached_matcher_from_db 的进程级缓存；warm_first（2026-10-20 晚）：主进程先跑一页"
             "把它建好，fork 后各 worker 共享，不再各建一份。库含字体域（约 17.4 万条，特征矩阵 1.2 GB）时这件事要紧："
             "各建一份是每进程约 2 分钟、2 GB；匹配器特征另有盘上缓存（`seeding._matcher_arrays`，mmap 共享页缓存）；"
             "人裁例数、借用名单按库指纹缓存在 step 实例上，只读。格级复用读的是本步旧产物，"
             "本步产物只由主进程写。cell_budget_s 是按墙钟的每格预算（缺省关）：开着时并行"
             "让单格变慢就可能多出 timeout 格——与换台机器跑同一性质，不是并行特有。"
             "第四册 46 页串行／4 进程产物 sha 逐页相同，墙钟 231 s → 80 s，单 worker 峰值 0.53 GB（库 18,474 条；登记 1 GB 留余量）（2026-10-20）。"),
    "rare_candidates": ParallelAudit(
        mem_gb=1.5, warm_first=True,
        note="审查（2026-10-20）：缓存都只按输入记忆（_emb_cache／_fwd_cache／_gw_cs 用 is 比对，_real_slots 按值），"
             "落盘都是带 pid 的临时文件 + os.replace；每页单独组批、eval 模式无随机。前置：emb 索引在 fork 前已在盘上"
             "（`RareCandidatesStep.parallel_warm` 在主进程建，缺盘时只建一次）；跑批期间不改字形库、checkpoint、fonts、册 yaml。"
             "第四册 46 页串行／4 进程产物 sha 逐页相同，墙钟 65 s → 23.5 s，单进程 1.06 GB（2026-10-20）。"),
    "seed_admit": ParallelAudit(
        mem_gb=2.0, warm_first=True,
        note="审查（2026-10-20）：run_page 不写事件／台账／人裁，只读；模块级缓存都按输入键记忆。"
             "修掉的：font_candidates._row_norms 按 id 缓存拿错矩阵（串行也随页序变）；图块缓存、"
             "绑定缓存、字体索引改原子写（并发读到半个文件会整页失败或静默为空）。"
             "前置：本批页的字块缓存已建好（`guji cache warm`），铁证会读别页的人裁刻例图；"
             "跑批期间不交人裁、不 `guji db sync`（串行同理）。warm_first：主进程先跑一页建好证人索引、"
             "人裁匹配器、绑定表，fork 后共享；Windows（spawn）各进程自建，单进程峰值约 2.1 GB。"
             "第四册 46 页串行／4 进程产物 sha 逐页相同，墙钟 82 s → 50 s，单进程峰值 2.1 GB；"
             "worker 里 cv2.setNumThreads 置空（cnn_candidates 模块顶层调它，fork 子进程里卡死过），"
             "fork 前 `SeedAdmitStep.parallel_warm` 预建证人索引与铁证匹配器（先跑一页建不全）（2026-10-20）。"
             "内存登记 3.0 → 2.0 GB（2026-10-20 晚）：每步一个子进程后 vol06 主进程峰值 1.95 GB，主进程加 3 个 worker "
             "合计 PSS 3.3 GB（fork 共享页）；按 3.0 算，15 GB 的机器只开得出 3 个进程，CPU 利用率 51%。"),
}


def warm(step, ctx) -> None:
    """fork 前在主进程预建这一步的进程级缓存：Step 有 `parallel_warm(ctx)` 就调（写在 Step 上，
    因为 core 不许 import steps）。「先跑一页」建不全——懒加载的缓存第一页可能碰不到，worker 又各自
    重建（seed_admit 的证人索引就是）。只管提速，出错就跳过、不影响结果。"""
    f = getattr(step, "parallel_warm", None)
    if f is None:
        return
    try:
        f(ctx)
    except Exception:  # noqa: BLE001 —— 预热只管提速
        pass


def warm_first(step) -> bool:
    a = AUDITED.get(step.spec.id)
    return bool(a and a.warm_first)


def is_parallel_safe(step) -> bool:
    return bool(step.spec.parallel_safe) or step.spec.id in AUDITED


def _cgroup_available_bytes(proc_cgroup: str = "/proc/self/cgroup",
                            root: str = "/sys/fs/cgroup") -> int | None:
    """本进程所在 cgroup 还能用多少内存：上限 − 已用 + 文件页（页缓存，活跃的也算：内存紧时能回收，
    挤不掉的是匿名内存）。没有上限返回 None。只加不活跃那部分会少算——跑过一步之后 mmap 的特征缓存和读过的图
    都是活跃文件页（云端实测 5.7 GB），seed_admit 被压到 2 个进程。

    容器里 `/proc/meminfo` 看到的是整台宿主（2026-10-20 云端：MemAvailable 15 GiB，cgroup 上限 13.4 GiB），
    按它压进程数会高估；超了 cgroup 上限是直接 OOM 杀进程（字体域进库后 dev 上的 glyph_match 4 进程就这样被杀）。"""
    try:
        lines = open(proc_cgroup, encoding="ascii").read().splitlines()
    except OSError:
        return None
    for ln in lines:
        hid, ctrls, path = ln.split(":", 2)
        if hid == "0" and ctrls == "":                          # cgroup v2
            base = root + path
            files = ("memory.max", "memory.current", "memory.stat", ("active_file", "inactive_file"))
        elif "memory" in ctrls.split(","):                      # cgroup v1
            base = root + "/memory" + path
            files = ("memory.limit_in_bytes", "memory.usage_in_bytes", "memory.stat",
                     ("total_active_file", "total_inactive_file"))
        else:
            continue
        try:
            lim = open(os.path.join(base, files[0]), encoding="ascii").read().strip()
            if lim == "max" or int(lim) >= 1 << 60:
                continue                                        # 这一层没设上限
            used = int(open(os.path.join(base, files[1]), encoding="ascii").read())
            file_pages = 0
            for st in open(os.path.join(base, files[2]), encoding="ascii"):
                k, _, v = st.partition(" ")
                if k in files[3]:
                    file_pages += int(v)
            return max(0, int(lim) - used + file_pages)
        except (OSError, ValueError):
            continue
    return None


def available_memory_gb() -> float | None:
    """本机此刻可用内存（GB）：`MemAvailable` 与本进程 cgroup 余量取小；都取不到返回 None（不按内存压进程数）。"""
    try:
        cg = _cgroup_available_bytes()
    except Exception:  # noqa: BLE001 —— 只是限流参考
        cg = None
    sysgb = _system_available_gb()
    if cg is None:
        return sysgb
    cg_gb = cg / (1 << 30)
    return cg_gb if sysgb is None else min(sysgb, cg_gb)


def _system_available_gb() -> float | None:
    """`/proc/meminfo` 的 MemAvailable（Windows 走 GlobalMemoryStatusEx）。"""
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


#: numpy／scipy 轮子自带的 OpenBLAS 的运行期线程数接口（符号名随打包方式变）。
_BLAS_SETTERS = ("scipy_openblas_set_num_threads64_", "scipy_openblas_set_num_threads",
                 "openblas_set_num_threads64_", "openblas_set_num_threads")


def set_blas_threads(n: int) -> int:
    """运行期把已加载的 OpenBLAS 线程池改成 `n`，返回改了几个库。

    环境变量 `OPENBLAS_NUM_THREADS` 只在库加载时读一次；fork 出的 worker 早已带着主进程
    加载好的 numpy，设变量不生效，只能调库自己的接口。不改的代价实测（第四册 8 页
    glyph_match 串行）：OpenBLAS 默认开满核，墙钟 45 s、CPU 147 s；1 线程墙钟 51 s、CPU 53 s，
    产物逐字节相同——多出来的两核多基本是线程空转。4 个 worker 各开满核时每页慢到 4 倍，
    页级并行整个白做。没装 threadpoolctl，自己找轮子里的 so，找不到就算了（只影响快慢）。"""
    import ctypes
    import glob
    import importlib.util
    done = 0
    for pkg in ("numpy", "scipy"):
        spec = importlib.util.find_spec(pkg)
        if spec is None or not spec.origin:
            continue
        pkg_dir = os.path.dirname(spec.origin)
        for lib in glob.glob(os.path.join(pkg_dir + ".libs", "*openblas*")) \
                + glob.glob(os.path.join(pkg_dir, ".libs", "*openblas*")):
            try:
                h = ctypes.CDLL(lib)
            except OSError:
                continue
            for name in _BLAS_SETTERS:
                fn = getattr(h, name, None)
                if fn is not None:
                    fn(ctypes.c_int(n))
                    done += 1
                    break
    return done
