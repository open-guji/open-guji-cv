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


def cmd_batch(args) -> None:
    from .feedback.events import EventLog
    from .review.batches import Batch, BatchStore, render_registry_markdown
    store, log = BatchStore(), EventLog()
    if args.action == "list":
        bs = [store.refresh_counts(b, log) for b in store.list()]
        if args.json:
            print(json.dumps([b.to_dict() for b in bs], ensure_ascii=False))
        elif args.md:
            print(render_registry_markdown(bs), end="")
        else:
            for b in bs:
                print(f"  {b.id:24s} {b.step:14s} {b.transport:8s} 卡 {b.n_cards:4d} "
                      f"裁 {b.n_events:4d} 消费 {b.n_consumed:4d}  {b.status}")
    elif args.action == "new":
        if store.get(args.id):
            print(f"批次 {args.id} 已存在")
            sys.exit(1)
        b = Batch(id=args.id, title=args.title or args.id, step=args.step, kind=args.kind,
                  book=args.book, transport=args.transport, url=args.url, shard=args.shard,
                  cards_ref=args.cards_ref, n_cards=args.n_cards)
        print(f"已建 {store.save(b)}")
    elif args.action == "show":
        b = store.get(args.id)
        if not b:
            print(f"没有批次 {args.id}")
            sys.exit(1)
        print(json.dumps(store.refresh_counts(b, log).to_dict(), ensure_ascii=False, indent=1))


def cmd_events(args) -> None:
    from .feedback.consumers import route_and_consume
    from .feedback.events import EventLog
    from .feedback.harvest import harvest_file
    from .feedback.routes import RouteTable
    from .gold.store import GoldStore
    from .review.batches import BatchStore
    log = EventLog()
    if args.action == "harvest":
        b = BatchStore().get(args.batch)
        step = args.step or (b.step if b else "")
        if not step:
            print("需要 --step（或先建批次）")
            sys.exit(1)
        evs = harvest_file(Path(args.file), args.batch, step, args.unit, args.kind)
        n = log.append(evs)
        print(f"解析 {len(evs)} 条，新增 {n} 条 → {log.batch_path(args.batch)}")
    elif args.action == "route":
        table = RouteTable.load(log.root / "routes.yaml")
        out = route_and_consume(log, args.batch, table, GoldStore(), dry_run=args.dry_run)
        print(json.dumps(out, ensure_ascii=False, indent=1))
    elif args.action == "list":
        evs = log.read(args.batch) if args.batch else sorted(log.iter_all(), key=lambda e: e.order)
        for e in evs[-args.limit:]:
            print(f"  {e.id}  {e.kind:12s} {e.target.key:28s} {json.dumps(e.payload, ensure_ascii=False)}")
        print(f"  共 {len(evs)} 条")


def cmd_gold(args) -> None:
    from .gold.store import GoldStore
    store = GoldStore()
    if args.action == "shards":
        for s in store.shards():
            d = store.summary(s)
            print(f"  {d['shard']:44s} {d['n']:5d} 条  {d['status']}")
    elif args.action == "show":
        print(json.dumps(store.summary(args.shard), ensure_ascii=False, indent=1))


COMMANDS_V2 = {
    "pipeline": cmd_pipeline,
    "step": cmd_step,
    "status": cmd_status,
    "console": cmd_console,
    "cache": cmd_cache,
    "batch": cmd_batch,
    "events": cmd_events,
    "gold": cmd_gold,
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

    p = sub.add_parser("batch", help="[v2] 审查批次：list | new | show")
    p.add_argument("action", choices=["list", "new", "show"])
    p.add_argument("id", nargs="?", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--step", default="")
    p.add_argument("--kind", default="verdict")
    p.add_argument("--book", default=None)
    p.add_argument("--transport", default="server", choices=["server", "artifact"])
    p.add_argument("--url", default=None, help="artifact 模式的持久 URL")
    p.add_argument("--shard", default=None, help="目标金标分片")
    p.add_argument("--cards-ref", default=None)
    p.add_argument("--n-cards", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.add_argument("--md", action="store_true", help="出台账 markdown")

    p = sub.add_parser("events", help="[v2] 反馈事件：harvest | route | list")
    p.add_argument("action", choices=["harvest", "route", "list"])
    p.add_argument("batch", nargs="?", default=None)
    p.add_argument("--file", default=None, help="收割源：审查页 HTML / JSONL / 日志")
    p.add_argument("--step", default=None)
    p.add_argument("--unit", default="page")
    p.add_argument("--kind", default="verdict")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=30)

    p = sub.add_parser("gold", help="[v2] 金标：shards | show")
    p.add_argument("action", choices=["shards", "show"])
    p.add_argument("shard", nargs="?", default=None)


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
