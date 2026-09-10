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
    elif args.action == "get":
        # 缺图就现算（与 GET /api/cache/… 同一条路：ctx.materialize）
        from .core.book import load_book
        from .core.step import KINDS, RunContext
        from .products.store import ProductStore
        from . import steps as _s  # noqa: F401
        if args.kind not in KINDS or KINDS[args.kind].storage != "image_cache":
            print(f"不是缓存图像种类: {args.kind}"); sys.exit(1)
        ctx = RunContext(load_book(args.book), ProductStore(), cache, log=lambda _: None)
        try:
            path = ctx.materialize(args.kind, args.key)
        except Exception as e:                                  # noqa: BLE001
            print(f"拿不到图像: {e}"); sys.exit(1)
        _write(args.out, Path(path).read_bytes())
    elif args.action == "column":
        import cv2
        from .core.spec import column_key
        path = cache.get(args.book, "column_image", column_key(args.page, args.col))
        if path is None:
            print("没有列图"); sys.exit(1)
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            print("列图读不出来"); sys.exit(1)
        h = img.shape[0]
        y0 = max(0, min(h - 1, args.y0)); y1 = max(y0 + 1, min(h, args.y1 or h))
        from .render.overlay import encode_png
        _write(args.out, encode_png(img[y0:y1]))


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
    elif args.action == "verdicts":
        # 读回本批已裁的字位／已拖的切线。与控制台的两条 verdicts 路由同一份装配
        from .review.verdict_view import cutline_verdicts, review_verdicts
        fn = cutline_verdicts if args.kind == "cutline" else review_verdicts
        _out(fn(args.batch, log))
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
            print(f"  {d['shard']:44s} {store.carrier(s):14s} {d['n']:5d} 条  {d['status']}")
    elif args.action == "show":
        print(json.dumps(store.summary(args.shard), ensure_ascii=False, indent=1))
    elif args.action == "migrate":
        shards = [args.shard] if args.shard else store.shards()
        for sh in shards:
            if store.items_path(sh).exists() and not args.shard:
                continue
            print(json.dumps(store.migrate(sh, dry_run=args.dry_run), ensure_ascii=False))
    elif args.action == "drift":
        from .gold.drift import check_shard, mark_drifted
        import cv2
        root = Path(__file__).resolve().parent.parent
        items = store.list(args.shard)

        def image_of(it):
            p = (it.input.get("input") or {}).get("column_image")
            if not p:
                return None
            f = root / p.replace("open-guji-cv ", "")
            return cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None

        rep = check_shard(args.shard, items, image_of)
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1))
        if args.apply:
            print(f"标 stale: {mark_drifted(store, args.shard, rep)} 条")


def cmd_eval(args) -> None:
    from .eval import run_eval
    from .eval.registry import EVALS, runnable
    if args.action == "list":
        print(f"{'评测器':20s} {'分片':40s} {'状态':22s} 说明")
        for s in sorted(EVALS.values(), key=lambda x: x.id):
            ok, why = runnable(s)
            print(f"  {s.id:18s} {s.shard:40s} {'可跑' if ok else why:22s} {s.title}")
        return
    keys = args.evals or [k for k, s in EVALS.items()
                          if not ({"heavy", "engine", "corpus", "dump", "intermediate"} & set(s.needs))]
    reports = []
    for k in sorted(keys):
        r = run_eval(k, timeout=args.timeout, from_raw=args.from_raw)
        reports.append(r)
        mark = {"ok": "✓", "regressed": "⚠", "failed": "✗", "skipped": "–"}[r.status]
        print(f"{mark} {r.summary_line()}")
        for w in r.warnings():
            print(f"    ⚠ {w}")
        if r.status == "failed":
            print(f"    {r.error[:160]}")
    if args.json:
        print(json.dumps([r.to_dict() for r in reports], ensure_ascii=False))
    n_bad = sum(1 for r in reports if r.status == "failed")
    n_reg = sum(1 for r in reports if r.status == "regressed")
    print(f"\n通过 {sum(1 for r in reports if r.status=='ok')} / 回归门失败 {n_reg} / 跑不起来 {n_bad}")
    sys.exit(1 if n_bad and args.strict else 0)


def cmd_preclean(args) -> None:
    """Step0：按 book.yaml 的 preclean 段生成修好的页图，落在 precleaned/<book>/。

    只处理登记过的页；其余页碰都不碰。生成后 Step1 起自动读修好的那张。
    `--calibrate` 是另一条路：不生成产物，在没登记 preclean 的「正常页」上量
    正文本底的墨占比分布（中位/p95/p99），换书时用它重新标 `utils/preclean.py`
    里的 `BODY_INK_GATE` 等常量。
    """
    from .core.book import load_book

    book = load_book(args.book)
    rules = getattr(book, "preclean", {}) or {}

    if getattr(args, "calibrate", False):
        import numpy as np
        from .utils.preclean import BODY_INK_GATE, sample_body_baseline

        pages = book.resolve_pages(args.pages) if args.pages else book.all_pages()
        normal_pages = [p for p in pages if p not in rules]
        skipped = sorted(set(pages) - set(normal_pages))
        if skipped:
            print(f"跳过已登记 preclean 的页（本来就不是「正常页」）: {skipped}")
        ratios = sample_body_baseline(book, normal_pages)
        if ratios.size == 0:
            print("没量到任何窗口——检查 --pages 是不是给对了")
            return
        med, p95, p99 = np.percentile(ratios, [50, 95, 99])
        over = int((ratios > BODY_INK_GATE).sum())
        print(f"{book.id} 本底标定：{len(normal_pages)} 个正常页，{len(ratios)} 个窗口")
        print(f"  中位 {med:.3f} / p95 {p95:.3f} / p99 {p99:.3f} / 最大 {ratios.max():.3f}")
        print(f"  当前闸阈 BODY_INK_GATE={BODY_INK_GATE:.3f}："
              f"{over}/{len(ratios)}（{over / len(ratios):.2%}）个正常窗口会被误拦")
        return

    from .utils.preclean import build_precleaned, precleaned_root

    if not rules:
        print(f"{book.id} 没登记任何预清理页（books/{book.id}.yaml 的 preclean 段是空的）")
        return
    pages = book.resolve_pages(args.pages) if args.pages else None
    print(f"{book.id} 登记的预清理页: {sorted(rules)}")
    written = build_precleaned(book, pages, force=args.force)
    print(f"写出 {len(written)} 页 -> {precleaned_root() / book.id}")



# ── C5：把控制台能干的事开到命令行 ────────────────────────────────────
#
# 控制台重构方案 §二 实测出来的那个数字：**本地专属面积 = 0/46**。46 条路由
# 在无 HTTP、无浏览器、无 GPU、无人在场的云端各真调了一次，45 条跑通，唯一
# 失败那条是缺数据不是耦合。也就是说「控制台现在能干的事，云端道现在就能干，
# 只差一层 CLI 出口」——下面这几个子命令就是那层出口。
#
# 纪律：**每个命令与对应路由调的是同一个领域函数**，不另写一份。
# 「同参同输出」是 C5 的验收判据（tests/test_console_routes.py::test_cli_matches_routes
# 逐条比对 CLI 的 JSON 与路由的返回值）。


def _out(d) -> None:
    """统一出 JSON。管道接 jq 用。"""
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str))


def _write(path: str, data: bytes) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    print(f"{path}  {len(data) / 1024:.1f} KB")


def cmd_product(args) -> None:
    """产物与图像：show | manifest | raw | overlay | patch。

    对应控制台第二类 6 条路由。图像类要 `--out`——云端跑完把 PNG 交回本地看，
    这是「云端能出叠图」那条路的落点。
    """
    from .core.spec import cell_key, page_key
    from .products.cache import ImageCache
    from .products.store import ProductStore
    from .render.overlay import encode_png, overlay
    import cv2

    st = ProductStore()
    if args.action == "show":
        d = st.read_raw(args.book, args.step, args.key)
        if d is None:
            print(f"没有这份产物: {args.book}/{args.step}/{args.key}"); sys.exit(1)
        entry = st.manifest(args.book, args.step).get(args.key)
        _out({"book": args.book, "step": args.step, "key": args.key,
              "manifest": (entry.__dict__ if entry else None), "products": d})
    elif args.action == "manifest":
        _out({k: v.__dict__ for k, v in st.manifest(args.book, args.step).all().items()})
    elif args.action == "raw":
        from .core.book import load_book
        f = load_book(args.book).raw_path(args.page)
        if not f.exists():
            print("原图缺失"); sys.exit(1)
        _write(args.out, encode_png(cv2.imread(str(f)), args.scale))
    elif args.action == "overlay":
        _write(args.out, encode_png(overlay(args.book, args.step, args.page, st), args.scale))
    elif args.action == "patch":
        key = cell_key(args.page, args.col, args.slot) + (args.sub or "")
        f = ImageCache().get(args.book, "char_patch", key)
        if f is None:
            print(f"没有字块 {key}"); sys.exit(1)
        _write(args.out, Path(f).read_bytes())


def cmd_check(args) -> None:
    """判据与体检：quality | rulers | round | rate。

    对应控制台第五类。四条判准的事实源全在 `eval/` 下（quality.py / rulers.py /
    round_check.py / rate_history.py），控制台与这里读的是同一份，**阈值只写一处**。
    """
    from .core.book import load_book
    from .products.store import ProductStore

    st = ProductStore()
    if args.action == "quality":
        from .eval.quality import quality
        _out(quality(args.book, args.pages, st))
    elif args.action == "rulers":
        from .eval.rulers import measure
        _out(measure(args.book, load_book(args.book).resolve_pages(args.pages), st))
    elif args.action == "round":
        from .eval import round_check as rc
        out = {"next": rc.next_batch(args.book)}
        if args.pages:
            out.update(rc.check(args.book, load_book(args.book).resolve_pages(args.pages)))
        _out(out)
    elif args.action == "rate":
        from .eval import rate_history
        if args.snapshot:
            rate_history.HIST.parent.mkdir(parents=True, exist_ok=True)
            added = []
            with open(rate_history.HIST, "a", encoding="utf-8") as f:
                for b in [x.strip() for x in args.book.split(",") if x.strip()]:
                    rec = rate_history.measure(b, st)
                    if rec is None:
                        continue
                    if args.note:
                        rec["note"] = args.note
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    added.append(rec)
            _out({"added": added})
        else:
            rows = [r for r in rate_history.history()
                    if not args.book or r.get("book") == args.book]
            rows.sort(key=lambda r: (r.get("book", ""), r.get("ts") or r.get("date", "")))
            _out({"rows": rows})


def cmd_cards(args) -> None:
    """待审卡片的数据：dingzi | cutline | jiazhu | groups，一律出 JSON。

    对应控制台第六类。**这不是给人看卡片用的**——是给云端道用来
    「统计还剩多少待审、抽查自动放行那批、量一刀改动前后的待审率变化」
    （方案 §二 第六类：需要人在场的是浏览器里那个页面，不是这些接口）。
    """
    from .feedback.events import EventLog
    from .products.store import ProductStore

    st = ProductStore()
    if args.action == "dingzi":
        from .review.cards import cards
        _out(cards(args.book, args.pages, args.limit, args.only, st))
    elif args.action == "jiazhu":
        from .review.jiazhu_cards import jiazhu_segments
        _out(jiazhu_segments(args.book, args.pages, args.only, args.batch, st, EventLog()))
    elif args.action == "groups":
        from .review.group_view import group_view
        _out(group_view(args.book, args.pages, args.edition, args.limit, st))
    elif args.action == "cutline":
        from .eval import touching as T
        from .core.book import load_book
        pg = (T.body_pages(args.book) if args.pages == "body"
              else load_book(args.book).resolve_pages(args.pages))
        if args.kind == "split_char":
            cases = T.split_char_boundaries(args.book, pg, st)
        elif args.kind == "all":
            cases = T.r2s_boundaries(args.book, pg, st) + T.split_char_boundaries(args.book, pg, st)
        else:
            cases = T.r2s_boundaries(args.book, pg, st)
        n_all = len(cases)
        done = T.gold_ids() if args.skip_done else set()
        if args.batch:
            done |= {e.target.key for e in EventLog().read(args.batch) if e.kind == "cutline"}
        cases = [c for c in cases if c["id"] not in done]
        _out({"book": args.book, "n_r2s": n_all, "n_done": len(done),
              "n": len(cases), "cases": T.pick_cases(cases, args.limit, seed=args.seed)})


def cmd_rare(args) -> None:
    """生僻字候选：单查一个字位，或 `--slots` 批量。

    引擎在 `clustering/rare_panel.py`，与控制台同一份。**不需要 GPU**
    （CNN checkpoint 走 CPU 前向）。⚠️ 首次要建字体索引，方案 §十一·4 实测
    112 秒，之后 0.1 秒——别当它挂了。
    """
    from .clustering.rare_panel import rare_batch, rare_for, rare_patch

    if args.slots:
        _out(rare_batch(args.book, [x.strip() for x in args.slots.split(",") if x.strip()], args.k))
        return
    img = rare_patch(args.book, args.page, args.col, args.slot, args.sub)
    if img is None:
        print(f"没有字块 p{args.page:04d}c{args.col:02d}s{args.slot}{args.sub or ''}")
        sys.exit(1)
    _out({"id": f"{args.book}:{args.page}:{args.col}:{args.slot}{args.sub or ''}",
          "candidates": rare_for(img, args.k)})


def cmd_variants(args) -> None:
    """本书用字账（只读）。账本由 `scripts/build_book_variants.py` 派生，这里不算任何东西。"""
    from .variant_ledger import DEFAULT_EDITION, ledger_path
    p = ledger_path(args.edition or DEFAULT_EDITION)
    if not p.exists():
        print(f"没有用字账 {p.name}——先跑 python scripts/build_book_variants.py "
              f"--edition {args.edition or DEFAULT_EDITION}")
        sys.exit(1)
    _out(json.loads(p.read_text(encoding="utf-8")))


def cmd_runs(args) -> None:
    """控制台的任务队列：list | show | cancel | log。

    队列是**控制台进程内**的（`console/jobs.py` 的单 worker），所以这几条读的是
    它落在 `runs/` 下的记录。控制台没在跑的时候 list 是空的，这不是错。
    """
    from .console.jobs import JobRunner
    runner = JobRunner()
    if args.action == "list":
        _out(runner.list(args.limit))
    elif args.action == "show":
        job = runner.get(args.id)
        if not job:
            print("没有这个任务"); sys.exit(1)
        _out(job.to_dict())
    elif args.action == "cancel":
        _out({"ok": runner.cancel(args.id)})
    elif args.action == "log":
        f = runner.log_path(args.id)
        if not f.exists():
            print("还没有日志"); sys.exit(1)
        if not args.follow:
            print(f.read_text(encoding="utf-8", errors="replace"), end="")
            return
        from .console.sse import tail_job
        for ev in tail_job(runner, args.id):
            if ev is None:
                continue
            print(ev.get("line") or f"[{ev['type']}]", flush=True)
            if ev["type"] in ("complete", "error"):
                return


COMMANDS_V2 = {
    "preclean": cmd_preclean,
    "eval": cmd_eval,
    "pipeline": cmd_pipeline,
    "step": cmd_step,
    "status": cmd_status,
    "console": cmd_console,
    "cache": cmd_cache,
    "batch": cmd_batch,
    "events": cmd_events,
    "gold": cmd_gold,
    "product": cmd_product,
    "check": cmd_check,
    "cards": cmd_cards,
    "rare": cmd_rare,
    "variants": cmd_variants,
    "runs": cmd_runs,
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

    p = sub.add_parser("preclean",
                       help="[v2] Step0：生成预清理后的页图（只处理 yaml 里登记的页）")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--pages", default=None,
                   help="只做这些页（默认：不带 --calibrate 时是 yaml 里登记的全部，"
                        "带 --calibrate 时是全书）")
    p.add_argument("--force", action="store_true", help="已有产物也重做")
    p.add_argument("--calibrate", action="store_true",
                   help="不生成产物，改在没登记 preclean 的正常页上标定闸0阈值"
                        "（本底墨占比的中位/p95/p99），换书时用")

    p = sub.add_parser("status", help="[v2] 各步各页的新鲜 / 过期 / 缺失")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="dev_set")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("console", help="[v2] 启动控制台（FastAPI）")
    p.add_argument("--port", type=int, default=DEFAULT_CONSOLE_PORT)
    p.add_argument("--no-browser", action="store_true")

    p = sub.add_parser("cache", help="[v2] 图像缓存：usage | prune | get | column")
    p.add_argument("action", choices=["usage", "prune", "get", "column"])
    p.add_argument("--limit-gb", type=float, default=None)
    p.add_argument("--book", default="")
    p.add_argument("--kind", default="char_patch", help="get：产物种类")
    p.add_argument("--key", default="", help="get：缓存键，如 p0024c01s10")
    p.add_argument("--page", type=int, default=0, help="column：页号")
    p.add_argument("--col", type=int, default=0, help="column：列号")
    p.add_argument("--y0", type=int, default=0)
    p.add_argument("--y1", type=int, default=0, help="column：裁到哪（0 = 到底）")
    p.add_argument("--out", default="", help="get / column 的输出路径")

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

    p = sub.add_parser("events", help="[v2] 反馈事件：harvest | route | list | verdicts")
    p.add_argument("action", choices=["harvest", "route", "list", "verdicts"])
    p.add_argument("batch", nargs="?", default=None)
    p.add_argument("--file", default=None, help="收割源：审查页 HTML / JSONL / 日志")
    p.add_argument("--step", default=None)
    p.add_argument("--unit", default="page")
    p.add_argument("--kind", default="verdict")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=30)

    p = sub.add_parser("eval", help="[v2] 评测：list | run")
    p.add_argument("action", choices=["list", "run"])
    p.add_argument("evals", nargs="*", help="评测器 id；留空跑全部轻量的")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="有跑不起来的就以 1 退出")
    p.add_argument("--from-raw", action="store_true",
                   help="缺产物时从原图现跑 Step1-3 补齐（云端 clone 无 products/ 时用，"
                        "同 seg_harness.py 的同名开关）")

    p = sub.add_parser("gold", help="[v2] 金标：shards | show | migrate | drift")
    p.add_argument("action", choices=["shards", "show", "migrate", "drift"])
    p.add_argument("shard", nargs="?", default=None)
    p.add_argument("--dry-run", action="store_true", help="migrate：只报数不写")
    p.add_argument("--apply", action="store_true", help="drift：把漂移条目标成 stale")

    # ── C5：控制台的出口（与对应路由同参同输出）────────────────────
    p = sub.add_parser("product", help="[v2] 产物与图像：show | manifest | raw | overlay | patch")
    p.add_argument("action", choices=["show", "manifest", "raw", "overlay", "patch"])
    p.add_argument("book")
    p.add_argument("step", nargs="?", default="", help="show / manifest / overlay 要")
    p.add_argument("--key", default="", help="show：产物键，如 p0024")
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--col", type=int, default=0)
    p.add_argument("--slot", type=int, default=0)
    p.add_argument("--sub", default="", help="夹注 a/b")
    p.add_argument("--scale", type=float, default=0.35, help="raw / overlay 的缩放")
    p.add_argument("--out", default="", help="图像输出路径（raw / overlay / patch 必给）")

    p = sub.add_parser("check", help="[v2] 判据与体检：quality | rulers | round | rate")
    p.add_argument("action", choices=["quality", "rulers", "round", "rate"])
    p.add_argument("book", nargs="?", default="vol01")
    p.add_argument("--pages", default="dev_set")
    p.add_argument("--snapshot", action="store_true", help="rate：记一行台账（默认只读）")
    p.add_argument("--note", default="", help="rate --snapshot 的说明")

    p = sub.add_parser("cards", help="[v2] 待审卡片数据：dingzi | cutline | jiazhu | groups")
    p.add_argument("action", choices=["dingzi", "cutline", "jiazhu", "groups"])
    p.add_argument("book")
    p.add_argument("--pages", default="dev_set")
    p.add_argument("--only", default="review", choices=["review", "auto", "all"],
                   help="dingzi 默认 review；jiazhu 默认 all")
    p.add_argument("--limit", type=int, default=400)
    p.add_argument("--edition", default="", help="groups：用字账版本")
    p.add_argument("--batch", default=None, help="cutline / jiazhu：跳过这批已裁的")
    p.add_argument("--kind", default="r2s", choices=["r2s", "split_char", "all"],
                   help="cutline：用例类型")
    p.add_argument("--seed", type=int, default=0, help="cutline：抽样种子")
    p.add_argument("--no-skip-done", dest="skip_done", action="store_false",
                   help="cutline：连已进金标的也出")

    p = sub.add_parser("rare", help="[v2] 生僻字候选（单查或 --slots 批量）")
    p.add_argument("book")
    p.add_argument("page", nargs="?", type=int, default=0)
    p.add_argument("col", nargs="?", type=int, default=0)
    p.add_argument("slot", nargs="?", type=int, default=0)
    p.add_argument("--sub", default="")
    p.add_argument("-k", type=int, default=10, help="出几个候选")
    p.add_argument("--slots", default="", help='批量："24:1:10,24:2:3a"')

    p = sub.add_parser("variants", help="[v2] 本书用字账（只读）")
    p.add_argument("action", nargs="?", default="book", choices=["book"])
    p.add_argument("--edition", default="")

    p = sub.add_parser("runs", help="[v2] 控制台任务：list | show | cancel | log")
    p.add_argument("action", choices=["list", "show", "cancel", "log"])
    p.add_argument("id", nargs="?", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("-f", "--follow", action="store_true", help="log：跟着刷")


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
