"""`guji perf`：看跑批耗时（`core/perf.py` 写的本机记录）。不跑 Step，不进任何 Step 的 `code_deps`。

    guji perf top  [--days 7] [--book 册] -w <工作区>     # 各步合计：哪一步花的机器时间最多
    guji perf show <册> [--run ID] -w <工作区>            # 一次运行（缺省最新一次）各步明细与最慢的页
    guji perf pages <册> <步> [--slowest 20] [--run ID]    # 这一步最慢的页及其分段

    guji perf top --remote [--by host|cv_version|book]   # 全队（美国机任务库），在库里聚合好再回
    guji perf push [--book 册]                           # 补推没推上的本机记录
    guji perf job <单号>                                 # 一条任务单的各步耗时

记录在产物根旁边的 `perf/<册>/<run_id>.jsonl`（`GUJI_PERF_DIR` 可改）。设了 JOBSDB_TOKEN 时每次运行写完
自动推一份汇总到美国机任务库 `jobs.perf_run`／`jobs.perf_step`（约 15 KB），**不推 Neon**。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _root(args) -> Path:
    if getattr(args, "workspace", None):
        os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())
    from .core.perf import perf_dir
    from .products.store import default_products_root
    return perf_dir(default_products_root())


def _fmt_s(x) -> str:
    if x is None:
        return "-"
    if x >= 3600:
        return f"{x / 3600:.1f}h"
    if x >= 120:
        return f"{x / 60:.1f}m"
    return f"{x:.1f}s" if x >= 10 else f"{x:.2f}s"


def _pick(rs: list[dict], run: str | None) -> dict:
    if not rs:
        print("✗ 没有耗时记录（跑过 guji pipeline／step 才有）", file=sys.stderr)
        sys.exit(1)
    if run:
        hit = [r for r in rs if r["run"]["run_id"].startswith(run)]
        if not hit:
            print(f"✗ 没有运行 {run}", file=sys.stderr)
            sys.exit(1)
        return hit[0]
    return rs[0]


def cmd_top(args) -> None:
    from .core import perf
    if args.remote:
        _remote_top(args)
        return
    rs = perf.runs(_root(args), args.book, since=time.time() - args.days * 86400)
    rows = perf.top(rs)
    if args.json:
        print(json.dumps({"runs": len(rs), "steps": rows}, ensure_ascii=False, indent=1))
        return
    total = sum(r["wall_s"] for r in rows) or 1.0
    print(f"近 {args.days} 天 {len(rs)} 次运行" + (f"（{args.book}）" if args.book else "") + "，按墙钟合计排：")
    print(f"{'步':<22}{'墙钟':>8}{'占比':>6}{'跑页':>7}{'跳过':>7}{'每页中位':>9}{'最慢页':>8}  主进程开销")
    for r in rows:
        ov = "，".join(f"{k} {_fmt_s(v)}" for k, v in sorted(r["overhead"].items(), key=lambda kv: -kv[1])[:3])
        print(f"{r['step']:<22}{_fmt_s(r['wall_s']):>8}{r['wall_s'] / total:>6.0%}{r['pages_run']:>7}"
              f"{r['skipped']:>7}{_fmt_s(r['p50_s']):>9}{_fmt_s(r['max_s']):>8}  {ov}")


def _remote_top(args) -> None:
    from .jobs import perf_push
    if not perf_push.enabled():
        print("✗ --remote 要设 JOBSDB_TOKEN／JOBSDB_PASSWORD（美国机任务库）", file=sys.stderr)
        sys.exit(2)
    rows = perf_push.remote_top(args.days, args.book, args.by)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        return
    total = float(sum(r["wall_s"] or 0 for r in rows)) or 1.0
    print(f"美国机任务库近 {args.days} 天" + (f"（{args.book}）" if args.book else "") + "，按墙钟合计排：")
    head = f"{'步':<22}" + (f"{args.by:<24}" if args.by else "")
    print(head + f"{'墙钟':>8}{'占比':>6}{'次数':>6}{'跑页':>8}{'每页中位':>9}{'最慢页':>8}")
    for r in rows:
        w = float(r["wall_s"] or 0)
        print(f"{r['step']:<22}" + (f"{r['grp_key']!s:<24}" if args.by else "")
              + f"{_fmt_s(w):>8}{w / total:>6.0%}{r['runs']:>6}{r['pages_run']:>8}"
              f"{_fmt_s(float(r['p50_s']) if r['p50_s'] is not None else None):>9}"
              f"{_fmt_s(float(r['max_s']) if r['max_s'] is not None else None):>8}")


def cmd_push(args) -> None:
    from .jobs import perf_push
    ok, bad = perf_push.push_pending(_root(args), args.book)
    print(f"推了 {ok} 份" + (f"，{bad} 份坏文件跳过" if bad else "") + "（美国机任务库 jobs.perf_run／perf_step）")


def cmd_job(args) -> None:
    from .jobs import perf_push
    if not perf_push.enabled():
        print("✗ 要设 JOBSDB_TOKEN／JOBSDB_PASSWORD（美国机任务库）", file=sys.stderr)
        sys.exit(2)
    rows = perf_push.remote_job(args.job_id)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        return
    if not rows:
        print(f"任务 #{args.job_id} 没有耗时记录（执行方要用带 perf 的 cv）")
        return
    last = None
    for r in rows:
        if r["run_id"] != last:
            last = r["run_id"]
            print(f"\n{r['run_id']}  {r['book']}  {r['host']}  cv {r['cv_version']}  墙钟 {_fmt_s(r['run_wall_s'])}")
        if r["step"]:
            print(f"   {r['step']:<22} 跑 {r['ok']} 跳 {r['skipped']} 失败 {r['failed']}  墙钟 {_fmt_s(r['wall_s'])}"
                  f"  每页中位 {_fmt_s(r['p50_s'])}  最慢 {_fmt_s(r['max_s'])}")


def cmd_show(args) -> None:
    from .core import perf
    r = _pick(perf.runs(_root(args), args.book), args.run)
    if args.json:
        print(json.dumps({k: r[k] for k in ("run", "steps", "end")}, ensure_ascii=False, indent=1))
        return
    run, m = r["run"], r["run"].get("machine") or {}
    wall = (r["end"] or {}).get("wall_s")
    print(f"{run['run_id']}  {run['book']}  {run.get('pipeline')}  cv {run.get('cv_version')}  "
          f"墙钟 {_fmt_s(wall)}{'（中断）' if r['end'] is None or r['end'].get('stopped') else ''}")
    print(f"机器 {m.get('host')}（{m.get('kind')}，{m.get('cpus')} 核，{m.get('mem_gb')} GB）  --jobs {run.get('jobs')}"
          + (f"  任务库 #{run['job_id']}" if run.get("job_id") else ""))
    for s in r["steps"]:
        print(f"\n== {s['step']}：跑 {s.get('ok', 0)} 页、跳过 {s.get('skipped', 0)}、失败 {s.get('failed', 0)}；"
              f"墙钟 {_fmt_s(s['wall_s'])}，每页中位 {_fmt_s(s.get('p50_s'))} p90 {_fmt_s(s.get('p90_s'))} "
              f"最慢 {_fmt_s(s.get('max_s'))}" + (f"，并行效率 {s['parallel_eff']:.0%}" if s.get("parallel_eff") else ""))
        if s.get("overhead"):
            print("   主进程：" + "，".join(f"{k} {_fmt_s(v)}" for k, v in s["overhead"].items()))
        for k, v in sorted((s.get("spans") or {}).items(), key=lambda kv: -kv[1][1])[:8]:
            print(f"   {k:<30} {v[0]:>6} 次 {_fmt_s(v[1]):>8}")
        if s.get("counts"):
            print("   计数：" + "，".join(f"{k} {v}" for k, v in s["counts"].items()))
        if s.get("slowest"):
            print("   最慢：" + "  ".join(f"p{p} {_fmt_s(e)}" for p, e in s["slowest"][:5]))


def cmd_pages(args) -> None:
    from .core import perf
    r = _pick(perf.runs(_root(args), args.book), args.run)
    rows = sorted((p for p in r["pages"] if p["step"] == args.step and p.get("elapsed") is not None),
                  key=lambda p: -p["elapsed"])[:args.slowest]
    if not rows:
        print(f"✗ 运行 {r['run']['run_id']} 里 {args.step} 没有跑过的页", file=sys.stderr)
        sys.exit(1)
    for p in rows:
        sp = "，".join(f"{k} {_fmt_s(v[1])}" for k, v in sorted((p.get("spans") or {}).items(),
                                                                 key=lambda kv: -kv[1][1])[:4])
        print(f"p{p['page']:<5} {_fmt_s(p['elapsed']):>8}  {p['status']}  {sp}")


def add_parser(sub) -> None:
    p = sub.add_parser("perf", help="看跑批耗时：哪一步慢、慢在哪（本机 perf/ 记录）")
    ps = p.add_subparsers(dest="perf_cmd", required=True)
    t = ps.add_parser("top", help="各步合计，按墙钟排")
    t.add_argument("--days", type=float, default=7)
    t.add_argument("--book", default=None)
    t.add_argument("--remote", action="store_true", help="查美国机任务库（全队各机器），在库里聚合好再回")
    t.add_argument("--by", choices=["host", "cv_version", "book"], default=None, help="--remote 时再按它拆")
    s = ps.add_parser("show", help="一次运行的各步明细")
    s.add_argument("book")
    s.add_argument("--run", default=None, help="run_id 前缀，缺省最新一次")
    g = ps.add_parser("pages", help="某一步最慢的页")
    g.add_argument("book")
    g.add_argument("step")
    g.add_argument("--slowest", type=int, default=20)
    g.add_argument("--run", default=None)
    u = ps.add_parser("push", help="把还没推过的本机记录推到美国机任务库（只推美国机，不推 Neon）")
    u.add_argument("--book", default=None)
    j = ps.add_parser("job", help="一条任务单的各步耗时（美国机任务库）")
    j.add_argument("job_id", type=int)
    for q in (t, s, g, u, j):
        q.add_argument("-w", "--workspace", default=None)
        q.add_argument("--json", action="store_true")
    p.set_defaults(_perf=True)


def cmd_perf(args) -> None:
    {"top": cmd_top, "show": cmd_show, "pages": cmd_pages, "push": cmd_push, "job": cmd_job}[args.perf_cmd](args)


# ── 步内分段计时（第三期，2026-11-04）──────────────────────────────
# 不改 Step 源码（改了要动指纹、登记代码等价），在跑批进程里把下面这些函数／方法换成计时的薄壳：
# 壳只调原函数、原样返回，产物逐字节不变（`tests/test_perf_hooks.py` 核开关两种跑法产物相同）。
# 只换「按名字在模块全局或类上查」的调用点：Step 里 `foo()` 查的是模块全局，换模块属性就生效；
# 别的模块 `from x import foo` 早拿走的引用不受影响（那些调用不计，不出错）。
# 不换拿函数身份做判断的东西（如 `GlyphMatcher._verify is verify_pair_elastic`），所以 verify 不单独计。
PERF_HOOKS: dict[str, dict] = {
    "open_guji_cv.steps.glyph_match": {
        "funcs": ("_patch", "_page_queries", "_keben_subset", "human_confirmed_counts", "borrowed_ids",
                  "demote_borrowed", "consensus_same"),
        "methods": {"GlyphMatchStep": ("_matcher",)},
    },
    "open_guji_cv.clustering.match": {
        "methods": {"GlyphMatcher": ("_match", "extract", "_same_cell_rows", "_apply_near_shape",
                                     "_apply_shape_rerank")},
    },
    # 匹配器里面（11-04 第二轮）：verify_pair_elastic 本身不换（`_match` 拿它做身份判断），换它按全局名调的几段；
    # 矩阵乘与排序＝`_match` 减去这些
    "open_guji_cv.clustering.verify": {"funcs": ("_elastic_align", "_prepare", "_elastic_miss", "verify_pair_cov")},
    "open_guji_cv.clustering.features": {"methods": {"HogFeature": ("extract",)}},
    "open_guji_cv.clustering.normalize": {"funcs": ("normalize_patch",)},
    "open_guji_cv.core.reuse": {"funcs": ("cell_reuse",)},
    "open_guji_cv.steps.seed_admit": {
        # `_run_page` 里直接调的各道关（静态扫出来的，按调用次数挑掉了逐格的小工具）
        "funcs": ("_opt", "_align", "_human_shapes", "_iron_context", "_iron_page_scale", "_occluded",
                  "_approx_index", "_approx_hit", "_book_knn_pass", "_context_guard", "_context_lib_dissent",
                  "_context_variant_tie", "_coord_refs", "_edge_pair_pass", "_follow_ref_pass", "_garble_guard",
                  "_group_flow_pass", "_header_formula_pass", "_human_unbound_pass", "_iron_confusable_witness",
                  "_iron_coord_dissent", "_iron_ctx_dissent", "_lane_witnesses", "_lib_near_tie", "_near_knn_pass",
                  "_pair_shape_pass", "_pick_char", "_pua_rule_pass", "_rare_ref_pass", "_rare_run_ids",
                  "_ref_lib_coord_pass", "_ref_topk_pass", "_review_lanes_pass", "_rr_shape_pass",
                  "_seal_blank_flip", "_shadow_veto_pass", "_solo_ctx_vetoed", "_symbol_ref_blank_pass",
                  "_symbol_review_pass", "_vis_ruling_pass", "_keben_counts", "_doubts",
                  # 第二轮：铁证闸逐格再匹配、字组流程与影子闸里面
                  "_iron_decide", "_page_patch", "_clf_ctx", "_hard_blocked", "_shadow_gate"),
    },
    "open_guji_cv.groups.flow": {"funcs": ("entry", "decide", "decide_joint", "_solve", "_pick_form",
                                           "_provisional", "_vis_try")},
    "open_guji_cv.shadow.gate": {"methods": {"ShadowGate": ("judge",)}},
    # seed_admit 在函数里现 import 的（调用时才按模块属性取，换模块属性就生效）
    "open_guji_cv.clustering.exclusions": {"funcs": ("excluded_ids",)},
    "open_guji_cv.clustering.note_lexicon": {"funcs": ("load_lexicon", "match_segment")},
    "open_guji_cv.feedback.bindings": {"funcs": ("rebind_library_shapes",)},
    "open_guji_cv.feedback.lookup": {"funcs": ("human_chars",)},
    "open_guji_cv.steps.align_ref": {"funcs": ("rare_topk_map",)},
}
_HOOKED = False


def _wrap(label: str, fn):
    from .core import perf
    w = perf.timed(label)(fn)
    for attr in ("cache_clear", "cache_info", "cache_parameters"):   # lru_cache 的接口照旧能用
        if hasattr(fn, attr):
            setattr(w, attr, getattr(fn, attr))
    w.__perf_hook__ = fn
    return w


def install_hooks(hooks: dict | None = None) -> list[str]:
    """把 `PERF_HOOKS` 里的函数换成计时薄壳；关了统计（`GUJI_PERF=0`）不换。返回换上的名字。
    同一进程只换一次；找不到的名字跳过（代码改名后不报错，只是少一段）。"""
    global _HOOKED
    import importlib
    from .core import perf
    if (_HOOKED and hooks is None) or not perf.enabled():
        return []
    done: list[str] = []
    for modname, spec in (hooks or PERF_HOOKS).items():
        try:
            mod = importlib.import_module(modname)
        except Exception:  # noqa: BLE001 —— 统计是附带的
            continue
        short = modname.rsplit(".", 1)[-1]
        for name in spec.get("funcs", ()):
            fn = getattr(mod, name, None)
            if callable(fn) and not hasattr(fn, "__perf_hook__") and not isinstance(fn, type):
                setattr(mod, name, _wrap(f"{short}.{name}", fn))
                done.append(f"{short}.{name}")
        for cname, meths in spec.get("methods", {}).items():
            cls = getattr(mod, cname, None)
            if cls is None:
                continue
            for name in meths:
                fn = cls.__dict__.get(name)
                if callable(fn) and not hasattr(fn, "__perf_hook__"):
                    setattr(cls, name, _wrap(f"{cname}.{name}", fn))
                    done.append(f"{cname}.{name}")
    if hooks is None:
        _HOOKED = True
    return done


def uninstall_hooks(hooks: dict | None = None) -> None:
    """换回原函数（测试用）。"""
    global _HOOKED
    import importlib
    for modname, spec in (hooks or PERF_HOOKS).items():
        try:
            mod = importlib.import_module(modname)
        except Exception:  # noqa: BLE001
            continue
        for name in spec.get("funcs", ()):
            fn = getattr(mod, name, None)
            if hasattr(fn, "__perf_hook__"):
                setattr(mod, name, fn.__perf_hook__)
        for cname, meths in spec.get("methods", {}).items():
            cls = getattr(mod, cname, None)
            for name in meths if cls is not None else ():
                fn = cls.__dict__.get(name)
                if hasattr(fn, "__perf_hook__"):
                    setattr(cls, name, fn.__perf_hook__)
    if hooks is None:
        _HOOKED = False


COMMANDS = {"perf": (add_parser, cmd_perf)}
