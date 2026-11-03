"""`guji perf`：看跑批耗时（`core/perf.py` 写的本机记录）。不跑 Step，不进任何 Step 的 `code_deps`。

    guji perf top  [--days 7] [--book 册] -w <工作区>     # 各步合计：哪一步花的机器时间最多
    guji perf show <册> [--run ID] -w <工作区>            # 一次运行（缺省最新一次）各步明细与最慢的页
    guji perf pages <册> <步> [--slowest 20] [--run ID]    # 这一步最慢的页及其分段

记录在产物根旁边的 `perf/<册>/<run_id>.jsonl`（`GUJI_PERF_DIR` 可改）。第一期只读本机；
推到美国服务器 jobs 库的 `perf` 表、跨机器汇总等 jobs 客户端切到美国机后再加。
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
    s = ps.add_parser("show", help="一次运行的各步明细")
    s.add_argument("book")
    s.add_argument("--run", default=None, help="run_id 前缀，缺省最新一次")
    g = ps.add_parser("pages", help="某一步最慢的页")
    g.add_argument("book")
    g.add_argument("step")
    g.add_argument("--slowest", type=int, default=20)
    g.add_argument("--run", default=None)
    for q in (t, s, g):
        q.add_argument("-w", "--workspace", default=None)
        q.add_argument("--json", action="store_true")
    p.set_defaults(_perf=True)


def cmd_perf(args) -> None:
    {"top": cmd_top, "show": cmd_show, "pages": cmd_pages}[args.perf_cmd](args)


COMMANDS = {"perf": (add_parser, cmd_perf)}
