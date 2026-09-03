"""四个抽象的 CLI：`guji` 入口，也以非冲突名注册进 `python -m open_guji_cv`。

    guji pipeline <pipeline> <book> [--from S] [--to S] [--pages dev_set|all|3-6,9] [--force] [--params JSON]
    guji step <step> <book> [--pages …] [--force]          # 只跑一步
    guji status <book> [--pipeline P] [--pages …] [--json]
    guji console [--port 8640] [--no-browser]
    guji cache usage|prune [--limit-gb N]

旧 `python -m open_guji_cv run …`（v1 一键管线）名字不动，这里的「跑一条 pipeline」叫 `pipeline`。
本模块顶层不 import 任何重依赖，保证 CLI 冷启动快。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PIPELINE = "keben_body_v2"
DEFAULT_CONSOLE_PORT = 8640


# ── handlers ─────────────────────────────────────────────────────────
def _engine(book_id: str, pipeline_id: str, params: str | None = None, quiet: bool = False):
    from .core.book import load_book
    from .core.engine import Engine
    from .core.pipeline import load_pipeline
    pl = load_pipeline(pipeline_id)
    book = load_book(book_id)
    overrides = json.loads(params) if params else None
    return Engine(book, pl, params=overrides, log=(lambda s: None) if quiet else None)


def cmd_pipeline(args) -> None:
    eng = _engine(args.book, args.pipeline, getattr(args, "params", None))
    steps = eng.pipeline.slice(getattr(args, "from_step", None), getattr(args, "to_step", None))
    pages = eng.book.resolve_pages(args.pages)
    rep = eng.run(steps=steps, pages=pages, force=args.force, stop_on_error=args.stop_on_error)
    if getattr(args, "json", False):
        print(json.dumps(rep.to_dict(), ensure_ascii=False))
    n_failed = sum(1 for o in rep.outcomes if o.status == "failed")
    sys.exit(1 if n_failed and args.stop_on_error else 0)


def cmd_step(args) -> None:
    args.from_step = args.to_step = args.step
    cmd_pipeline(args)


def cmd_status(args) -> None:
    eng = _engine(args.book, args.pipeline, quiet=True)
    pages = eng.book.resolve_pages(args.pages)
    st = eng.status(pages=pages)
    if args.json:
        print(json.dumps(st, ensure_ascii=False))
        return
    print(f"{st['book']} · {st['pipeline']} · {len(pages)} 页")
    for sid, d in st["steps"].items():
        c = d["counts"]
        print(f"  {sid:16s} 新鲜 {c['fresh']:3d}  过期 {c['stale']:3d}  缺失 {c['missing']:3d}  "
              f"失败 {c['failed']:3d}  阻塞 {c['blocked']:3d}")


def cmd_console(args) -> None:
    from .console.app import serve
    serve(port=args.port, open_browser=not args.no_browser)


def cmd_cache(args) -> None:
    from .products.cache import ImageCache
    cache = ImageCache()
    if args.action == "usage":
        n_bytes, n_files = cache.usage()
        print(f"{cache.root}: {n_bytes / (1 << 20):.1f} MB, {n_files} 个文件")
    elif args.action == "prune":
        limit = int(args.limit_gb * (1 << 30)) if args.limit_gb is not None else None
        freed = cache.prune(limit)
        print(f"释放 {freed / (1 << 20):.1f} MB")


COMMANDS_V2 = {
    "pipeline": cmd_pipeline,
    "step": cmd_step,
    "status": cmd_status,
    "console": cmd_console,
    "cache": cmd_cache,
}


# ── parsers ──────────────────────────────────────────────────────────
def _add_pages(p: argparse.ArgumentParser) -> None:
    p.add_argument("--pages", default="dev_set",
                   help="dev_set（默认）| all | 3-6,9 之类的页号表达式")
    p.add_argument("--force", action="store_true", help="无视指纹，强制重跑")
    p.add_argument("--stop-on-error", action="store_true", help="一页失败就停")
    p.add_argument("--params", default=None, help='参数覆盖 JSON，如 {"column_gate": {"width_tol": 0.2}}')
    p.add_argument("--json", action="store_true", help="结束时打印 JSON 报告")


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("pipeline", help="[v2] 跑一条 pipeline（或其中一段）")
    p.add_argument("pipeline", help=f"pipeline id，如 {DEFAULT_PIPELINE}")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--from", dest="from_step", default=None, help="起始步骤 id")
    p.add_argument("--to", dest="to_step", default=None, help="终止步骤 id（含）")
    _add_pages(p)

    p = sub.add_parser("step", help="[v2] 只跑一步")
    p.add_argument("step", help="步骤 id")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    _add_pages(p)

    p = sub.add_parser("status", help="[v2] 各步各页的新鲜 / 过期 / 缺失")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="dev_set")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("console", help="[v2] 启动控制台（FastAPI）")
    p.add_argument("--port", type=int, default=DEFAULT_CONSOLE_PORT)
    p.add_argument("--no-browser", action="store_true")

    p = sub.add_parser("cache", help="[v2] 图像缓存：usage | prune")
    p.add_argument("action", choices=["usage", "prune"])
    p.add_argument("--limit-gb", type=float, default=None)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="guji", description="open-guji-cv 四个抽象的 CLI")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    register_subcommands(sub)
    args = parser.parse_args(argv)
    handler = COMMANDS_V2.get(args.command)
    if handler is None:
        parser.print_help()
        return
    handler(args)


if __name__ == "__main__":
    main()
