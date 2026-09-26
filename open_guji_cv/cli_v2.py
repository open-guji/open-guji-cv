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


def cli_steps(eng, from_step: str | None, to_step: str | None) -> list[str]:
    """`guji pipeline` 要跑的步骤：按 --from/--to 切片，再套**书级可选步骤开关**。

    2026-09-15 实锤：`Engine._default_steps` 只在 steps=None 时应用 `BookSpec.ocr_candidates`
    开关，而这里总是先切片再传显式列表——于是 vol02（整理本质量高、开关默认关）跑
    `guji pipeline keben_body_v2 vol02` 时 Step5-c OCR 候选照跑不误，一页 7 秒、188 页 22 分钟白花。
    控制台同一条 pipeline 走的是 steps=None，开关生效，CLI 与控制台不同参不同输出。
    只有 `guji step ocr_candidates`（from == to == 那一步，人手工点名）才不套开关。"""
    steps = eng.pipeline.slice(from_step, to_step)
    if from_step is not None and from_step == to_step:
        return steps
    enabled = eng._enabled(steps)
    skipped = [s for s in steps if s not in enabled]
    if skipped:
        print(f"按书级开关跳过：{', '.join(skipped)}（{eng.book.id}.yaml ocr_candidates: false）", flush=True)
    return enabled


def cmd_pipeline(args) -> None:
    if getattr(args, "allow_sample_db", False):
        import os
        os.environ["GUJI_ALLOW_SAMPLE_DB"] = "1"
    from .core.workspace import assert_workspace_declared
    assert_workspace_declared()
    eng = _engine(args.book, args.pipeline, getattr(args, "params", None))
    steps = cli_steps(eng, getattr(args, "from_step", None), getattr(args, "to_step", None))
    pages = eng.book.resolve_pages(args.pages)
    # 书级跑批锁：同一产物目录同一本书只许一个跑批在写（overview 进度/并行分工.md §三）
    from .core.runlock import book_run_lock, RunLockHeld
    try:
        with book_run_lock(eng.book.id, wait=getattr(args, "wait", False)):
            rep = eng.run(steps=steps, pages=pages, force=args.force, stop_on_error=args.stop_on_error,
                          jobs=getattr(args, "jobs", 1))
    except RunLockHeld as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(3)
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
        drift = f"  漂移 {d['drift']:3d}" if d.get("drift") else ""
        print(f"  {sid:16s} 新鲜 {c['fresh']:3d}  过期 {c['stale']:3d}  缺失 {c['missing']:3d}  "
              f"失败 {c['failed']:3d}  阻塞 {c['blocked']:3d}{drift}")
    if any(d.get("drift") for d in st["steps"].values()):
        print("  （漂移 = 产物对着旧的外部状态判的，如字形库变了；不算过期、不自动重跑。"
              "要重算点名格用 `guji recheck`）")


def cmd_recheck(args) -> None:
    """Step5-a 点名重算：按字 / 判档 / 命中条目已撤，把格写进 manifest 的格级失效。
    只标不跑——跑还是 `guji pipeline <p> <book> --from glyph_match`，只重算点名格。"""
    from .core.spec import page_key
    from .steps.glyph_match import live_exemplars, recheck_reasons
    eng = _engine(args.book, args.pipeline, quiet=True)
    step = eng.pipeline.producer_of("glyph_match")
    sid = step.spec.id
    p = eng.ctx.params_for(step)
    chars = set((args.chars or "").replace(",", "").replace("，", "").replace(" ", ""))
    verdicts = {v for v in (args.verdicts or "").split(",") if v}
    if not (chars or verdicts or args.dead or args.all):
        raise SystemExit("至少给一个：--chars / --verdicts / --dead / --all")
    live = None
    if args.dead:
        edition = p.edition
        if edition is None and getattr(eng.book, "edition", "keben") == "modern":
            edition = f"modern:{eng.book.id}"
        live = live_exemplars(p.db_path, edition)
    manifest = eng.store.manifest(eng.book.id, sid)
    pages = eng.book.resolve_pages(args.pages)
    reason = "recheck " + " ".join(x for x in (
        f"chars={''.join(sorted(chars))}" if chars else "",
        f"verdicts={','.join(sorted(verdicts))}" if verdicts else "",
        "dead" if args.dead else "", "all" if args.all else "") if x)
    n_pages = n_cells = n_total = 0
    by_why: dict[str, int] = {}
    for pg in pages:
        key = page_key(pg)
        if manifest.get(key) is None:
            continue
        if args.all:
            n_pages += 1
            if not args.dry_run:
                manifest.invalidate(key, reason)
            continue
        pm = eng.store.read(eng.book.id, sid, key, "glyph_match")
        if pm is None:
            continue
        ids: list[str] = []
        for col in pm.columns:
            for r in col.chars if col.ok else []:
                n_total += 1
                why = recheck_reasons(r, chars, verdicts, live)
                for w in why:
                    by_why[w] = by_why.get(w, 0) + 1
                if why:
                    ids.append(r.id)
        if ids:
            n_pages += 1
            n_cells += len(ids)
            if not args.dry_run:
                manifest.invalidate(key, reason, cells=ids)
    head = "[dry-run] " if args.dry_run else ""
    if args.all:
        print(f"{head}{sid}：{n_pages} 页整页失效")
    else:
        pct = f"{n_cells * 100 / n_total:.1f}%" if n_total else "-"
        print(f"{head}{sid}：{n_pages} 页 {n_cells}/{n_total} 格点名重算（{pct}）  "
              + "  ".join(f"{k} {v}" for k, v in sorted(by_why.items())))
    if n_pages and not args.dry_run:
        print(f"下一步：guji pipeline {eng.pipeline.id} {eng.book.id} --from {sid} "
              f"--pages {args.pages} -w <workspace>")


def cmd_console(args) -> None:
    from .console.app import serve
    from .console.auth import config as auth_config
    from .core.workspace import describe, using_sample_corpus, using_sample_db

    host = getattr(args, "host", None) or "127.0.0.1"
    loopback = host in ("127.0.0.1", "localhost")
    no_auth = bool(getattr(args, "no_auth", False))
    if no_auth and not loopback:
        print(f"✗ --no-auth 只能在本机（127.0.0.1/localhost）用，绑 {host} 时必须过身份接口鉴权，"
              "拒绝启动——对外开放校对平台不能关掉登录。", file=sys.stderr)
        sys.exit(1)
    root_path = getattr(args, "root_path", "") or ""
    dev_idp = bool(getattr(args, "dev_idp", False))
    auth_config.set_config(no_auth=no_auth, root_path=root_path, dev_idp=dev_idp)

    # 向后兼容（协调者 09-26 20:10 验收意见）：OAuth 还没配（网站两个端点
    # 10 月上旬才有 PR），服务器的 systemd 单元现在起控制台**没带任何鉴权参数**。
    # 不补这条的话，这次改动一合 main、服务器一重启，控制台就变成一个当下
    # 用不了的登录页，把正在用的人全挡在外面。
    oauth_configured = bool(auth_config.get().client_secret)
    if not no_auth and not dev_idp and not oauth_configured:
        if loopback:
            no_auth = True
            auth_config.set_config(no_auth=True)
            print("  ⚠️⚠️  未配置 OAuth（GUJI_OAUTH_CLIENT_SECRET 为空）且未加 --dev-idp/--no-auth，"
                  "绑的是本机地址——按本机免鉴权运行。生产部署前必须配置 OAuth 或显式加"
                  " --no-auth/--dev-idp。\n")
        else:
            print(f"✗ 绑 {host} 但没配置 OAuth（GUJI_OAUTH_CLIENT_SECRET 为空）也没加 --dev-idp——"
                  "登录流程打不通，拒绝启动。要么配好 OAuth，要么本机开发用 --dev-idp。",
                  file=sys.stderr)
            sys.exit(1)

    # 起控制台时把解析结果打出来——控制台是长跑进程，环境变量漏带的代价是
    # 之后每一次审阅都读错库/错语料，而页面上不会有任何报错。2026-09-12 实锤：
    # `GUJI_WORKSPACE` 只写在 ~/.bashrc 里，从 PowerShell/VS Code 起的控制台
    # 读到仓内 17 KB 样本语料，vol02 全书 186 页锚定失败、Step7 卡片上的
    # 「整理本期望」全是噪声，排查了很久才想到是环境变量。
    for k, v in describe().items():
        print(f"  {k:12} {v}")
    if using_sample_db() or using_sample_corpus():
        print("\n  ⚠️  没设 GUJI_WORKSPACE（或工作区数据不全）——库/语料会落到仓内小样本，\n"
              "     整理本锚不上、库匹配全是 unsure。真跑书请先：\n"
              "     export GUJI_WORKSPACE=/path/to/guji-workspace/<id>-<书名>\n")
    if no_auth:
        print("  ⚠️  --no-auth：鉴权已关闭，任何能连上本机端口的人都能起跑批、写裁决——"
              "只许本机开发用。\n")
    if dev_idp:
        print("  ⚠️  --dev-idp：登录走本机假登录页，不是网站真授权——只许本机开发用。\n")
    serve(port=args.port, open_browser=not args.no_browser, host=host, root_path=root_path)


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
        img = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
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
        # 消费落 workspace 裁决表，不落 open-guji-dataset（2026-09-13 三仓边界）
        from .feedback.consumers import verdict_store
        table = RouteTable.load(log.root / "routes.yaml")
        out = route_and_consume(log, args.batch, table, verdict_store(), dry_run=args.dry_run)
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
    from .feedback.consumers import verdict_store
    from .gold.store import GoldStore
    # 默认看测试集仓；--verdicts 看 workspace 裁决表（同格式，同一套命令）
    store = verdict_store() if getattr(args, "verdicts", False) else GoldStore()
    if args.action == "import":
        # 裁决表 → 测试集：唯一往 dataset 写人裁数据的入口，必须人显式发起
        from .gold.transfer import ImportFilter, import_to_dataset, parse_pages
        if not args.shard:
            print("需要分片名，如 char-segmentation/touching-cuts")
            sys.exit(1)
        ids = None
        if args.ids:
            ids = {l.strip() for l in Path(args.ids).read_text(encoding="utf-8").splitlines() if l.strip()}
        flt = ImportFilter(book=args.book, pages=parse_pages(args.pages), stratum=args.stratum,
                           ids=ids, include_uncertain=args.include_uncertain)
        res = import_to_dataset(args.shard, verdict_store(), GoldStore(), flt,
                                why=args.why or "", dry_run=args.dry_run)
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=1))
        if args.dry_run:
            print("（试算，未写入；去掉 --dry-run 才导入）")
        return
    if args.action == "export":
        # 测试集仓 → workspace 裁决表（书的事实类分片，如 page-type）
        from .gold.transfer import export_to_workspace
        if not args.shard:
            print("需要分片名，如 page-type")
            sys.exit(1)
        res = export_to_workspace(args.shard, GoldStore(), verdict_store(),
                                  why=args.why or "", dry_run=args.dry_run)
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=1))
        return
    if args.action == "rebuild":
        # 事件日志 → 裁决表（重放）。裁决表是派生物，事件才是真源。
        from .feedback.events import EventLog
        from .gold.transfer import rebuild_verdicts
        out = rebuild_verdicts(EventLog(), verdict_store(),
                               batches=[args.shard] if args.shard else None)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
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
            return cv_imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None

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


def cmd_split(args) -> None:
    """Step0 分页：按 book.yaml 的 page_split 段把扫描页裁成逻辑页，写进 raw_dir。

    一张扫描页装着多页原书（上下两栏拼一页）时用；逻辑页才是管线的「原图」。
    `--pages` 是**扫描页**号（不是逻辑页）。见 utils/page_split.py。
    """
    from .core.book import load_book
    from .utils.page_split import split_book

    book = load_book(args.book)
    pages = None
    if args.pages:
        pages = book.resolve_pages(args.pages)      # 只当页号表达式用；dev_set 之类的名字不适用
    recs = split_book(book, pages=pages, force=args.force)
    n_empty = sum(1 for r in recs if r.empty)
    print(f"分出 {len(recs)} 个逻辑页（其中空栏 {n_empty}），产物在 {book.raw_dir}")


def cmd_witness_align(args) -> None:
    """列级证人对齐：`line_is_column` 的整理本 → 逐字位候选标签（utils/witness_align.py）。

    影印页码与扫描页的对应由 `--first-page`（扫描页 1 对应的影印页码）给；不给则读
    book.yaml `references[0].first_page_no`。
    """
    from .core.book import load_book
    from .core.workspace import corpus_path, products_root
    from .utils.witness_align import align_book

    book = load_book(args.book)
    ref = (book.references or [{}])[0]
    first = args.first_page if args.first_page is not None else ref.get("first_page_no")
    if first is None:
        print("需要 --first-page（扫描页 1 对应的影印页码），或在 book.yaml references[0] 写 first_page_no")
        sys.exit(1)
    witness = Path(args.witness) if args.witness else corpus_path(ref["file"])
    stats = align_book(book, first_page_no=int(first), witness=witness, products_root=products_root())
    print(json.dumps(stats, ensure_ascii=False))


def cmd_witness_align_stream(args) -> None:
    """字流证人对齐：换行与刻本不同的证人（`line_is_column: false`）→ 逐字位标签
    （utils/witness_align_stream.py）。同书异版用这条，列级那条对不上。

    OCR 只当锚，标签一律取证人字；只收长度 ≥ `--min-block` 的 `equal` 块。
    """
    from .core.book import load_book
    from .core.workspace import corpus_path, products_root
    from .utils.witness_align_stream import align_stream, write_labels

    book = load_book(args.book)
    ref = (book.references or [{}])[0]
    witness = Path(args.witness) if args.witness else corpus_path(ref["file"])
    res = align_stream(book, witness=witness, products_root=products_root(),
                       min_block=args.min_block)
    out = products_root() / book.id / "witness_align" / "labels.jsonl"
    write_labels(res, out)
    blocks = sorted(res.blocks, reverse=True)
    stats = {
        "n_cells": res.n_cells, "n_witness": res.n_witness, "n_ocr": res.n_ocr,
        "n_equal": res.n_equal, "n_labeled": res.n_labeled,
        "coverage": round(res.n_labeled / max(1, res.n_cells), 4),
        "ocr_agree_at_labels": res.ocr_agree,
        "n_blocks": len(blocks), "longest_blocks": blocks[:10],
        "min_block": args.min_block,
    }
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"→ {out}")


def cmd_calibrate(args) -> None:
    """册级先验复核：把 `measure_*` 跑一遍，和 `books/<id>.yaml` 里的现值对照。

    **只印表，不改 yaml**（理由见 `utils/calibrate.py` 模块头：自动回写会让一次
    坏标定悄悄固化，还容易冲掉人写的 note）。
    """
    from .core.book import load_book
    from .products.store import ProductStore
    from .utils.calibrate import calibrate, format_table

    book = load_book(args.book)
    pages = book.resolve_pages(args.pages) if args.pages else None
    rows, diag = calibrate(book, ProductStore(), pages=pages,
                           with_bottom_gap=args.with_bottom_gap)
    print(format_table(rows, diag, book.id))
    if args.json:
        payload = {"book": book.id, "diag": diag,
                   "rows": [{"field": r.field, "current": r.current, "measured": r.measured,
                             "verdict": r.verdict, "drift_pct": r.drift_pct, "note": r.note}
                            for r in rows]}
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print("")
        print("已写 " + str(args.json))


def cmd_calibrate_font(args) -> None:
    """字体判定（三模式方案 §五.1）：拿 witness-align / 人裁的标签当查询，逐套字体量
    recall@1/@5 与可分性 margin（utils/font_calibrate.py）。字体字形先用
    `glyph-db import-font --manifest <工作区清单>` 导进工作区库。"""
    from .clustering.glyph_db import GlyphDB
    from .core.book import load_book
    from .core.workspace import cache_root, glyph_db_path, products_root
    from .utils.font_calibrate import format_table, load_labels, score_fonts

    book = load_book(args.book)
    labels_path = Path(args.labels) if args.labels else products_root() / book.id / "witness_align" / "labels.jsonl"
    labels = load_labels(labels_path, max_per_char=args.per_char, max_chars=args.max_chars)
    if args.manifest:
        # 直接比对（不经库）：字体按书的笔宽加粗后再比，见 utils/font_calibrate_direct.py
        from .clustering.font_glyphs import load_charset, load_manifest
        from .utils.font_calibrate_direct import score_fonts_direct
        specs, data = load_manifest(args.manifest)
        if args.editions:
            want = args.editions.split(",")
            specs = [sp for sp in specs if sp.edition_tag in want]
        charset = load_charset(args.charset or data["charset"])
        strokes = None
        if args.strokes:
            strokes = {kv.split("=")[0]: int(kv.split("=")[1]) for kv in args.strokes.split(",")}
        scores = score_fonts_direct(book.id, labels, cache_root(), specs, charset, k=args.k,
                                    strokes=strokes, match_stroke=not args.no_stroke_match,
                                    norm_stroke=args.norm_stroke)
    else:
        db = GlyphDB(glyph_db_path())
        try:
            editions = args.editions.split(",") if args.editions else [
                r[0] for r in db.conn.execute("SELECT DISTINCT edition_tag FROM sources WHERE kind='font' ORDER BY 1")]
            scores = score_fonts(db, book.id, labels, cache_root(), editions, k=args.k,
                                 exclude_self=args.exclude_self)
        finally:
            db.close()
    print(format_table(scores))
    if args.json:
        Path(args.json).write_text(json.dumps([s.__dict__ for s in scores], ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"→ {args.json}")


def cmd_seed_witness(args) -> None:
    """从证人标签播种字形库（utils/seed_witness.py）：证人字 × 字体 top-1 一致才进
    `modern:<book>`。先跑 witness-align 与 glyph-db import-font。"""
    from .clustering.glyph_db import GlyphDB
    from .core.book import load_book
    from .core.workspace import cache_root, glyph_db_path, products_root
    from .utils.seed_witness import seed_from_witness

    book = load_book(args.book)
    # 不显式传就用册配置的（与 Step5-a 读同一个字段）——两边必须同一把尺子，
    # 否则库被一把尺子筛、又被另一把尺子查，等于白播。
    if args.norm_stroke is None and getattr(book, "norm_stroke", None):
        args.norm_stroke = int(book.norm_stroke)
        print(f"[seed] --norm-stroke 取册配置 {args.norm_stroke}")
    labels_path = Path(args.labels) if args.labels else products_root() / book.id / "witness_align" / "labels.jsonl"
    db = GlyphDB(glyph_db_path())
    try:
        stats = seed_from_witness(db, book, labels_path=labels_path, cache_root=cache_root(),
                                  font_editions=args.fonts.split(","), edition_tag=args.edition,
                                  limit=args.limit, products_root=products_root(),
                                  norm_stroke=args.norm_stroke, jobs=args.jobs,
                                  only_chars=args.only_chars, source_kind=args.source_kind,
                                  binarize=not args.keep_gray)
    finally:
        db.close()
    out = products_root() / book.id / "witness_align" / "seed_stats.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "reject_samples"}, ensure_ascii=False))
    print(f"→ {out}")


def _pdf_embedded_image(doc, pg):
    """扫描页里那张**唯一的内嵌图**的 (xref, 宽, 高)；不是「一页一张图」就返回 None。

    扫描 PDF 的正常形态是一页一张整版位图。有多张（或没有）的页多半是矢量/文字页
    或拼贴页，只能走渲染。
    """
    try:
        imgs = pg.get_images(full=True)
    except Exception:
        return None
    if len(imgs) != 1:
        return None
    xref = imgs[0][0]
    try:
        info = doc.extract_image(xref)
    except Exception:
        return None
    return xref, info.get("width", 0), info.get("height", 0)


def _salvage_jpx(raw: bytes) -> bytes:
    """JPEG2000 末 tile 残缺时的抢救：在最后一个 SOT 处截断、补 EOC。

    国图北行日錄刻本实测：某页 25 个 tile-part 的最后一个数据不全，**MuPDF 渲染
    出一张全白图并且 exit 0**（静默坏页），OpenCV 报 `Stream too short`。丢掉残缺
    的那个 tile 就能解出其余的——丢的那块通常只占页面一小角。
    """
    sots: list[int] = []
    i = 0
    while i < len(raw) - 1:
        if raw[i] == 0xFF and raw[i + 1] == 0x90:          # SOT
            lsot = int.from_bytes(raw[i + 2:i + 4], "big")
            sots.append(i)
            i += 2 + max(lsot, 2)
            continue
        i += 1
    if not sots:
        return raw
    return raw[:sots[-1]] + b"\xff\xd9"


def _warn_downscale(problems: list, page_no: int, pg, got, dpi) -> None:
    """渲染出来比内嵌图小很多时告警——这是「静默降分辨率」那个坑的正面拦截。"""
    if got is None or not got[1]:
        return
    pr = pg.rect
    if not pr.width:
        return
    eff = (dpi / 72.0) if dpi else 1.0
    ratio = got[1] / (float(pr.width) * eff)
    if ratio > 1.2:
        problems.append(
            f"页 {page_no}：**渲染结果比内嵌图小 {ratio:.2f} 倍**"
            f"（页框 {pr.width:.0f}×{pr.height:.0f} pt vs 内嵌图 {got[1]}×{got[2]} px）"
            f"——分辨率丢了，改用 --mode embedded，或 --dpi {int(round(72 * ratio * eff))}")


def cmd_import_pdf(args) -> None:
    """把 PDF 逐页抽成灰度 PNG（`<out>/<页号>.png`，从 1 起）。

    ## 默认取**内嵌图**，不是渲染

    扫描 PDF 的页框尺寸（pt）**不一定**等于内嵌图像的像素数。北行日錄刻本那两个
    PDF 页框 672×562 pt、内嵌图 2801×2343 px——按页框 1:1 渲染只有原生分辨率的
    1/4.17，字身从 71px 缩到 17px，Step3 根本没法切，而且 exit 0 不报任何警告。

    所以默认路径是 `extract_image` 取内嵌码流（`--mode embedded`，缺省）：
    一页一张图时直接拿原始像素，拿不到才退回渲染并**明确告知**。
    `--mode render` 强制渲染（矢量/文字 PDF、或内嵌图是分块拼的）；给了 `--dpi`
    即隐含 render。

    ## 每页都体检

    抽完逐页报「尺寸异常 / 近乎全白全黑」——**静默坏页是最难发现的一类坏数据**，
    全白页会一路往下跑，到 Step3 才莫名其妙零列。见 `_salvage_jpx`。
    """
    from pathlib import Path
    import numpy as np
    import pymupdf
    from .utils.image_io import imwrite

    doc = pymupdf.open(args.pdf)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sel = None
    if args.pages:
        sel = set()
        for part in args.pages.split(","):
            a, _, b = part.partition("-")
            sel.update(range(int(a), int(b or a) + 1))

    mode = args.mode
    if args.dpi and mode == "embedded":
        mode = "render"                      # 显式给了 dpi 就是要渲染

    def _render(pg) -> np.ndarray:
        if args.dpi:
            pix = pg.get_pixmap(dpi=args.dpi, colorspace=pymupdf.csGRAY)
        else:
            pix = pg.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    n = n_skip = 0
    n_embedded = n_render = n_salvaged = 0
    problems: list[str] = []
    tmp = out / "_import_tmp.bin"

    for i in range(len(doc)):
        page_no = i + 1
        if sel is not None and page_no not in sel:
            continue
        target = out / f"{page_no}.png"
        if target.exists() and not args.force:
            n_skip += 1
            continue
        pg = doc[i]
        img = None

        if mode == "embedded":
            got = _pdf_embedded_image(doc, pg)
            if got is not None:
                xref, iw, ih = got
                import cv2
                raw = doc.extract_image(xref)["image"]
                tmp.write_bytes(raw)
                img = cv_imread(str(tmp), cv2.IMREAD_UNCHANGED)
                if img is None:                      # 码流坏了，试抢救
                    tmp.write_bytes(_salvage_jpx(raw))
                    img = cv_imread(str(tmp), cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        n_salvaged += 1
                        problems.append(f"页 {page_no}：内嵌码流残缺，已截断末 tile 抢救"
                                        f"（丢失部分通常在页面一角，**务必目视核对**）")
                if img is not None:
                    if img.ndim == 3:
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    n_embedded += 1
                else:
                    problems.append(f"页 {page_no}：内嵌图解不开（抢救也失败），退回渲染")
            if img is None:
                img = _render(pg)
                n_render += 1
                _warn_downscale(problems, page_no, pg, got, args.dpi)
        else:
            img = _render(pg)
            n_render += 1
            _warn_downscale(problems, page_no, pg,
                            _pdf_embedded_image(doc, pg), args.dpi)

        if img is None:
            problems.append(f"页 {page_no}：抽不出图，已跳过")
            continue

        ink = float((img < 192).mean())
        if ink < 0.002:
            problems.append(f"页 {page_no}：**近乎全白**（墨占比 {ink:.4f}）——疑似坏页或空页")
        elif ink > 0.98:
            problems.append(f"页 {page_no}：近乎全黑（墨占比 {ink:.4f}）——疑似扫描背面或封面")
        imwrite(str(target), img)
        n += 1

    tmp.unlink(missing_ok=True)

    sizes: dict[tuple[int, int], int] = {}
    for f in out.glob("*.png"):
        try:
            import cv2
            im = cv_imread(str(f), cv2.IMREAD_UNCHANGED)
            if im is not None:
                sizes[(im.shape[1], im.shape[0])] = sizes.get((im.shape[1], im.shape[0]), 0) + 1
        except Exception:
            pass

    print(f"抽出 {n} 页（内嵌 {n_embedded} / 渲染 {n_render}"
          f"{f' / 抢救 {n_salvaged}' if n_salvaged else ''}），"
          f"跳过 {n_skip} 页 → {out}（PDF 共 {len(doc)} 页）")
    if len(sizes) > 1:
        top = sorted(sizes.items(), key=lambda kv: -kv[1])
        print("  ⚠️ 尺寸不一致：" + "；".join(f"{w}×{h} × {c} 页" for (w, h), c in top[:4]))
    for p in problems:
        print("  ⚠️ " + p)


def cmd_binarize(args) -> None:
    """整页二值副本：灰度扫描 → `binarized/<book>/<page>.png`（白底黑字）。

    进字形库的图一定是二值的（用户 2026-09-16），审阅时看二值的也更准。
    这条把二值化统一到**页级**做一次落盘，而不是每个消费点各二值各的。
    默认 Sauvola 31/0.2 —— 固定阈 128 会砍掉一半界行，见 `utils/binarized.py`。
    """
    from .core.book import load_book
    from .utils.binarized import binarized_root, build_binarized

    book = load_book(args.book)
    pages = book.resolve_pages(args.pages) if args.pages else book.all_pages()
    written = build_binarized(book, pages, force=args.force,
                              window=args.window, k=args.k)
    print(json.dumps({"book": book.id, "pages": len(pages), "written": len(written),
                      "dir": str(binarized_root() / book.id),
                      "window": args.window, "k": args.k}, ensure_ascii=False))


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
        _write(args.out, encode_png(cv_imread(str(f)), args.scale))
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
    elif args.action == "throughput":
        from .eval import throughput as tp
        pages = None if args.all_pages else args.pages
        _out(tp.full_report(args.book, pages, st))


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
    from .clustering.rare_panel import ids_fallback, rare_batch, rare_for, rare_patch

    if args.top or args.slot_comp or args.comp:
        # IDS 兜底：`rare vol01 --top ⿰ --slot-comp L=言 --comp 俞 [page col slot]`
        slots = dict(x.split("=", 1) for x in args.slot_comp)
        img = rare_patch(args.book, args.page, args.col, args.slot, args.sub) if args.page else None
        _out({"query": {"top": args.top, "slots": slots, "components": args.comp},
              "with_image": img is not None,
              "candidates": ids_fallback(args.top, slots, args.comp, img, args.k, args.book)})
        return
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


def cmd_collate(args) -> None:
    """Step9-9.3 对勘：字位流 × 整理本 → JSON 正本（＋可选 HTML）。

    证人默认读书配置的 `references:`，没配就退回单证人（光盘版）。
    **不进管线**：跨页跨册汇总，不属于任何一页，同 Step8（见 `report/__init__.py`）。
    """
    from .core.book import load_book
    from .report.html import write_html
    from .report.run import body_pages, collate_book, write_report
    from .report.witness import load_witnesses

    bk = load_book(args.book)
    pages = bk.resolve_pages(args.pages) if args.pages else body_pages(args.book)
    witnesses = load_witnesses(bk.references)
    print(f"{args.book}：{len(pages)} 页，证人 "
          + "、".join(f"{w.label}({w.quality})" for w in witnesses), flush=True)

    def progress(n, total, page):
        if n % 20 == 0 or n == total:
            print(f"  {n}/{total} …p{page}", flush=True)

    doc = collate_book(args.book, pages, witnesses, progress=progress)
    out = write_report(doc, args.out)
    print(f"JSON → {out}")
    if not args.no_html:
        h = write_html(doc, out.with_suffix(".html"), args.console)
        print(f"HTML → {h}  ({h.stat().st_size / 1e6:.1f} MB)")
    for label, s in doc["summary"]["by_witness"].items():
        c = s["counts"]
        print(f"  {label}：一致 {s['n_equal']:,} · "
              + " · ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))
              + (f" · 列 {s['cols']}" if s["cols"] else ""))
    un = {k: len(v) for k, v in doc["unanchored"].items()}
    print(f"  未锚定页：{un}" + (f" · 数据版本不同步 {len(doc['stale'])} 处" if doc["stale"] else ""))


def cmd_progress(args) -> None:
    """Step9-9.0 进度复查：页范围内每页还挂着哪些待办（看板，不是闸）。口径见 `report/progress.py`。"""
    from .core.book import load_book
    from .report.progress import format_table, page_progress
    bk = load_book(args.book)
    doc = page_progress(args.book, bk.resolve_pages(args.pages))
    if args.json:
        _out(doc)
        return
    print(format_table(doc))


def cmd_snapshot(args) -> None:
    """把一本书若干步的产物冻结成快照，供下游用 GUJI_PRODUCTS_DIR 读（并行分工 §三·2）。"""
    from .core.runlock import make_snapshot, snapshots_root, RunLockHeld
    if args.action == "list":
        root = snapshots_root() / args.book
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            meta = d / "SNAPSHOT.json"
            info = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
            print(f"{d}  steps={','.join(info.get('steps', []))}  rev={info.get('code_rev')}  {info.get('created', '')}")
        return
    steps = [s for s in (args.steps or "").split(",") if s] or None
    try:
        out = make_snapshot(args.book, steps, args.name)
    except RunLockHeld as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(3)
    print(f"快照：{out}")
    print(f"下游这样读：GUJI_PRODUCTS_DIR='{out}'")


def cmd_release(args) -> None:
    """`guji release check`：候选提交跟上一个 `cv-*` tag 比（K 道，2026-09-26）。
    见 `open_guji_cv/ops/release_check.py` 模块头。"""
    from .ops import release_check as rc
    if args.action != "check":
        print(f"未知 action: {args.action}", file=sys.stderr)
        sys.exit(1)
    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent
    res = rc.release_check(repo, args.candidate, against=args.against, version=args.version,
                           run_tests=not args.no_tests)
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(res.draft)
    if args.write_baseline:
        import json as _json
        baseline_path = repo / rc.BASELINE_REL
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(_json.dumps({"failed": res.test_result["failed"],
                                              "skipped": res.test_result["skipped"],
                                              "version": res.version},
                                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写基线：{baseline_path}", file=sys.stderr)
    if res.test_diff["regressed"]:
        print("✗ 全量测试比上一版多了失败/跳过——这是发布前唯一的硬门槛，见上面「全量测试」一节",
              file=sys.stderr)
        sys.exit(1)


def cmd_deploy(args) -> None:
    """`guji deploy check`：服务器定时器跑，拉模式部署 `production` 分支（K 道，2026-09-26）。
    见 `open_guji_cv/ops/deploy_check.py` 模块头。"""
    from .ops import deploy_check as dc
    if args.action != "check":
        print(f"未知 action: {args.action}", file=sys.stderr)
        sys.exit(1)
    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent
    products_root = Path(args.products).resolve() if args.products else None
    result = dc.deploy_check(repo, branch=args.branch, service=args.service, base_url=args.base_url,
                             products_root=products_root, dry_run=args.dry_run)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    stale = None
    if result.status == dc.DEPLOYED and args.workspace:
        stale = dc.collect_stale_summary(Path(args.workspace).resolve())
        if stale:
            print("过期步（排进夜间重算队列，只写清单不自动起跑批）：", file=sys.stderr)
            for book, steps in sorted(stale.items()):
                print(f"  {book}: {', '.join(steps)}", file=sys.stderr)
    if args.overview and not args.dry_run and result.status != dc.NO_UPDATE:
        path = dc.write_deploy_record(Path(args.overview).resolve(), result, stale_summary=stale)
        print(f"部署记录：{path}", file=sys.stderr)
    if result.status in (dc.FETCH_FAILED, dc.MERGE_FAILED, dc.ROLLED_BACK):
        sys.exit(1)


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
    "binarize": cmd_binarize,
    "split": cmd_split,
    "import-pdf": cmd_import_pdf,
    "witness-align": cmd_witness_align,
    "witness-align-stream": cmd_witness_align_stream,
    "calibrate": cmd_calibrate,
    "calibrate-font": cmd_calibrate_font,
    "seed-witness": cmd_seed_witness,
    "eval": cmd_eval,
    "pipeline": cmd_pipeline,
    "step": cmd_step,
    "status": cmd_status,
    "recheck": cmd_recheck,
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
    "collate": cmd_collate,
    "progress": cmd_progress,
    "runs": cmd_runs,
    "snapshot": cmd_snapshot,
    "release": cmd_release,
    "deploy": cmd_deploy,
}


WORKSPACE_HELP = ("工作区仓根（含 books/<book>.yaml、products/、cache/、output/）。**必填**——"
                  "凡带 book 的命令都不再读 GUJI_WORKSPACE 环境变量兜底：那个变量漏设/设错都不报错，"
                  "产物会静默写到别的工作区（2026-09-19 一天里两次栽在这上面）。")


def _needs_workspace(sp: argparse.ArgumentParser) -> bool:
    return any(a.dest == "book" for a in sp._actions)


def resolve_workspace(args, parser: argparse.ArgumentParser) -> Path | None:
    """带 book 的命令：`--workspace` 必填、必须存在、必须有这册书的定义；解析结果写进
    `GUJI_WORKSPACE` 供下游（`core.workspace.workspace_root` 及其之下一切）使用。

    环境变量若已设且指向别处，以 `--workspace` 为准并提示——环境变量常是上一本书留下的。
    """
    if not hasattr(args, "book"):
        return None
    ws = getattr(args, "workspace", None)
    if not ws:
        parser.error("缺 -w/--workspace：跑真书必须显式给工作区，例如 "
                     f"`-w D:/workspace/<book>-workspace`（books/{args.book}.yaml 所在的仓根）。"
                     "不再读 GUJI_WORKSPACE 兜底。")
    root = Path(ws).expanduser().resolve()
    spec = root / "books" / f"{args.book}.yaml"
    if not spec.exists():
        parser.error(f"--workspace {root} 下没有 books/{args.book}.yaml——路径给错了，或这不是「{args.book}」的工作区")
    import os
    env = os.environ.get("GUJI_WORKSPACE")
    if env and Path(env).expanduser().resolve() != root:
        print(f"  ⚠️  GUJI_WORKSPACE={env} 与 --workspace 不同，以 --workspace 为准", file=sys.stderr)
    os.environ["GUJI_WORKSPACE"] = str(root)
    print(f"  工作区 {root}  册 {args.book}", file=sys.stderr)
    return root


def _with_workspace(handler, sp: argparse.ArgumentParser):
    def run(args):
        resolve_workspace(args, sp)
        return handler(args)
    run._workspace_wrapped = True     # type: ignore[attr-defined]
    return run


def install_workspace_option(sub: argparse._SubParsersAction) -> None:
    """给每个带 book 的子命令加 `-w/--workspace`（必填，见 WORKSPACE_HELP），并把它的
    处理函数包一层做校验。`register_subcommands` 末尾调用；两个入口（`guji` 与
    `python -m open_guji_cv`）都经这里，幂等。"""
    for name, sp in sub.choices.items():
        handler = COMMANDS_V2.get(name)
        if handler is None or not _needs_workspace(sp):
            continue
        # 参数每次都要加（每次调用建的是新的 parser 对象）；处理函数只包一层
        sp.add_argument("-w", "--workspace", default=None, help=WORKSPACE_HELP)
        if not getattr(handler, "_workspace_wrapped", False):
            COMMANDS_V2[name] = _with_workspace(handler, sp)


# ── parsers ──────────────────────────────────────────────────────────
def _add_pages(p: argparse.ArgumentParser) -> None:
    import os
    p.add_argument("--pages", default="dev_set",
                   help="dev_set（默认）| all | 3-6,9 之类的页号表达式")
    p.add_argument("--force", action="store_true", help="无视指纹，强制重跑")
    p.add_argument("--stop-on-error", action="store_true", help="一页失败就停")
    p.add_argument("--params", default=None, help='参数覆盖 JSON，如 {"column_gate": {"width_tol": 0.2}}')
    p.add_argument("--json", action="store_true", help="结束时打印 JSON 报告")
    p.add_argument("--wait", action="store_true",
                   help="这本书正有别的跑批在写时排队等它跑完（默认直接报持有者并退出，退出码 3）")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                   help="页级并行进程数（默认=本机 CPU 数）。只对声明过 "
                        "`StepSpec.parallel_safe=True` 的 Step 生效，其余 Step 仍串行，"
                        "混跑一条 pipeline 时不用分开调。别超过 CPU 数——超订只会更慢，"
                        "有一次性初始化（模型/字形库）的 Step 并行时这部分开销按进程数摊，"
                        "不是按页摊，进程数越多单个 worker 越快建好摊得越薄，但仍不该超核数")
    p.add_argument("--allow-sample-db", action="store_true",
                   help="没设 GUJI_WORKSPACE 时，显式声明「就是要用仓内那份几百条的示例库」再跑"
                        "（不加这个、又没设 GUJI_WORKSPACE，直接报错——2026-09-09 吃过亏：漏设变量"
                        "对着示例库跑了一批，产物 status:ok 但库匹配全错，锚不上整理本）")


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

    p = sub.add_parser("binarize",
                       help="[v2] 整页二值副本 → binarized/<book>/（进库与人裁看的都是它）")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--pages", default=None, help="只做这些页（默认全书）")
    p.add_argument("--force", action="store_true", help="已有也重做")
    p.add_argument("--window", type=int, default=31,
                   help="Sauvola 窗口（默认 31，与 normalize_patch 同一组常数）")
    p.add_argument("--k", type=float, default=0.2, help="Sauvola k（默认 0.2）")

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

    p = sub.add_parser("split",
                       help="[v2] Step0 分页：按 yaml 的 page_split 段把扫描页裁成逻辑页（上下两栏拼一页的影印本）")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--pages", default=None, help="只做这些**扫描页**（页号表达式，如 1-5,9）；默认全部")
    p.add_argument("--force", action="store_true", help="已有产物也重做")

    p = sub.add_parser("witness-align",
                       help="[v2] 列级证人对齐：一行一列的整理本 → 逐字位候选标签（现代链播种/评测用）")
    p.add_argument("book")
    p.add_argument("--first-page", type=int, default=None, help="扫描页 1 对应的影印页码")
    p.add_argument("--witness", default=None, help="整理本文件；默认 references[0].file")

    p = sub.add_parser("witness-align-stream",
                       help="[v2] 字流证人对齐：换行与刻本不同的证人（同书异版）→ 逐字位标签")
    p.add_argument("book")
    p.add_argument("--witness", default=None, help="证人文件；默认 references[0].file")
    p.add_argument("--min-block", type=int, default=8,
                   help="只收长度 ≥ 这个的 equal 块（默认 8，与 align_label 的 8-gram 同量级）")

    p = sub.add_parser("calibrate",
                       help="[v2] 册级先验复核：measure_* 实测 vs books/<id>.yaml 现值的对照表（不改 yaml）")
    p.add_argument("book")
    p.add_argument("--pages", default=None, help="页号表达式；默认 yaml 的 pages")
    p.add_argument("--with-bottom-gap", action="store_true",
                   help="连 bottom_gap 一起量（要读整册原图，慢）")
    p.add_argument("--json", default=None)

    p = sub.add_parser("calibrate-font",
                       help="[v2] 字体判定：标签字位在各套字体来源里的 recall@1/@5 与可分性 margin")
    p.add_argument("book")
    p.add_argument("--labels", default=None, help="labels.jsonl；默认 products/<book>/witness_align/labels.jsonl")
    p.add_argument("--editions", default=None, help="逗号分隔的 edition_tag；默认库里全部 kind=font 的来源")
    p.add_argument("--per-char", type=int, default=3)
    p.add_argument("--max-chars", type=int, default=600)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--exclude-self", action="store_true",
                   help="留一法：查询字位自己已在库里（modern:<book>）时摘掉再检索")
    p.add_argument("--manifest", default=None,
                   help="给了就走直接比对（不经库）：按清单渲染字体、按书的笔宽加粗后再比")
    p.add_argument("--charset", default=None, help="直接比对用的模板字表；默认清单里的")
    p.add_argument("--strokes", default=None, help="显式加粗值，如 font:simsun=2,font:zhonghuasong=4")
    p.add_argument("--no-stroke-match", action="store_true", help="直接比对时不按笔宽加粗")
    p.add_argument("--norm-stroke", type=int, default=None,
                   help="直接比对时两边都骨架化再统一细化到 N px（加粗那条路会饱和，见 font_calibrate_direct.py）")
    p.add_argument("--json", default=None)

    p = sub.add_parser("seed-witness",
                       help="[v2] 证人标签 × 字体 top-1 一致 → 播种 modern:<book> 字形库")
    p.add_argument("book")
    p.add_argument("--fonts", default="font:simsun,font:iming", help="逗号分隔的字体 edition_tag（任一 top-1 一致即可）")
    p.add_argument("--labels", default=None)
    p.add_argument("--edition", default=None, help="默认 modern:<book>")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--norm-stroke", type=int, default=None,
                   help="形状证人这一路两边骨架化再细化到 N px——要与管线 glyph_match.norm_stroke 一致（现代链 3）；"
                        "不给就走库检索（不归一，量的是粗细，字/旦/宣 会整批被拒）")
    p.add_argument("--jobs", type=int, default=1,
                   help="读图+归一并行进程数（检索本身不并行：matcher 带着上千模板的特征矩阵，"
                        "进程间传它比算还贵）")
    p.add_argument("--only-chars", default=None,
                   help="只播这些字头（连写，如 「」《》）。进库幂等，可反复补播——"
                        "修好某一类字的形状证人后补这一类，不必全量重播")
    p.add_argument("--keep-gray", action="store_true",
                   help="进库存灰度裁片（旧行为）。缺省存**二值**——用户 2026-09-16："
                        "最后进字形库的一定是二值的，灰度值会干扰")
    p.add_argument("--source-kind", default="print", choices=["print", "woodblock"],
                   help="这本书的来源类型（默认 print，现代排印本）。**刻本必须传 woodblock**："
                        "候选检索默认只查 kinds=('woodblock',)，记成 print 会让播进去的字形"
                        "在检索里静默查不到")

    p = sub.add_parser("import-pdf", help="[v2] PDF 逐页抽成灰度 PNG（<out>/<页号>.png）")
    p.add_argument("pdf")
    p.add_argument("--out", required=True, help="输出目录")
    p.add_argument("--mode", choices=["embedded", "render"], default="embedded",
                   help="embedded（缺省）= 取内嵌图原始像素，扫描 PDF 用这个；"
                        "render = 按页框渲染，矢量/文字 PDF 用这个（给了 --dpi 即隐含 render）")
    p.add_argument("--dpi", type=int, default=None,
                   help="渲染 dpi（隐含 --mode render）；不给且走 render 时按页框 1:1——"
                        "⚠️ 页框 pt 数不一定等于内嵌图像素数，那样会静默降分辨率")
    p.add_argument("--pages", default=None, help="只抽这些页，如 1-5,9")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("snapshot", help="[v2] 冻结一本书若干步的产物，供下游用 GUJI_PRODUCTS_DIR 读")
    p.add_argument("action", choices=["make", "list"])
    p.add_argument("book")
    p.add_argument("--steps", default=None, help="逗号分隔的步骤 id，默认该书已有的全部步")
    p.add_argument("--name", default=None, help="快照名，默认 <日期-时刻>-<commit>")

    p = sub.add_parser("release", help="[v2] 发版前检查：release check <commit>（K 道，2026-09-26）")
    p.add_argument("action", choices=["check"])
    p.add_argument("candidate", nargs="?", default="HEAD", help="候选提交，默认当前 HEAD")
    p.add_argument("--against", default=None, help="对比的旧提交/tag，默认上一个 cv-* tag")
    p.add_argument("--version", default=None, help="版本号，默认 cv-YYYY.MM.DD（当天已有就加 -2/-3）")
    p.add_argument("--repo", default=None, help="cv 仓根，默认本模块所在的仓")
    p.add_argument("--no-tests", action="store_true", help="跳过全量测试（只看指纹影响清单，调试用）")
    p.add_argument("--write-baseline", action="store_true",
                   help="把这次的失败/跳过写成新基线（ops/baseline_tests.json），发布通过后再加")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("deploy", help="[v2] 服务器部署检查：deploy check（K 道，2026-09-26）")
    p.add_argument("action", choices=["check"])
    p.add_argument("--repo", default=None, help="cv 仓（服务器上跟 production 分支的那个 checkout），默认本模块所在的仓")
    p.add_argument("--branch", default="production")
    p.add_argument("--service", default="guji-cv-console", help="systemd --user 服务名")
    p.add_argument("--base-url", default="http://127.0.0.1:8640", help="健康检查打的地址")
    p.add_argument("--products", default=None, help="products 根目录，探测跑批锁用；不给就不查锁")
    p.add_argument("--workspace", default=None, help="部署成功后 guji status 各书要用的工作区")
    p.add_argument("--overview", default=None, help="overview 仓路径，成功/失败都写一张部署记录并推")
    p.add_argument("--dry-run", action="store_true", help="只打印会做什么，不改任何东西")

    p = sub.add_parser("status", help="[v2] 各步各页的新鲜 / 过期 / 缺失")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="dev_set")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("recheck",
                       help="[v2] Step5-a 点名重算：库变了不自动重跑，要吃新库就在这里点名格")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="all")
    p.add_argument("--chars", default=None, help="记录里出现这些字的格（判定字/候选），如 𠊓,虜")
    p.add_argument("--verdicts", default=None, help="这些判档的格，如 unsure,diff")
    p.add_argument("--dead", action="store_true",
                   help="same 档命中的库条目已撤或字头已改（撤库后建议跑一次）")
    p.add_argument("--all", action="store_true", help="整页失效（不复用任何格）")
    p.add_argument("--dry-run", action="store_true", help="只数不写")

    p = sub.add_parser("console", help="[v2] 启动控制台（FastAPI）")
    p.add_argument("--port", type=int, default=DEFAULT_CONSOLE_PORT)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--host", default="127.0.0.1",
                   help="监听地址，默认 127.0.0.1（对外开放校对平台生产环境仍应绑回环地址，"
                        "由反向代理转发，见 overview 总览/16）")
    p.add_argument("--no-auth", action="store_true",
                   help="关掉鉴权（本机开发用）。只在 --host 是 127.0.0.1/localhost 时允许，"
                        "绑别的地址会拒绝启动")
    p.add_argument("--root-path", default="",
                   help="挂在反向代理前缀下时用，如 /collate（网站把 /collate/* 转发到这里）")
    p.add_argument("--dev-idp", action="store_true",
                   help="登录走本机假登录页，不打网站真的 /oauth/authorize|token（网站两个端点"
                        "10 月上旬才有 PR，本机开发/测试先用这个）。跟 --no-auth 不是一回事："
                        "这个仍然走一遍完整的 OAuth 回调，只是身份接口是假的")

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

    p = sub.add_parser("gold", help="[v2] 金标：shards | show | migrate | drift | import | export | rebuild")
    p.add_argument("action", choices=["shards", "show", "migrate", "drift", "import", "export", "rebuild"])
    p.add_argument("shard", nargs="?", default=None,
                   help="分片名；rebuild 时是批次名（留空=全部批次）")
    p.add_argument("--dry-run", action="store_true", help="migrate / import：只报数不写")
    p.add_argument("--apply", action="store_true", help="drift：把漂移条目标成 stale")
    p.add_argument("--verdicts", action="store_true",
                   help="shards / show 看 workspace 裁决表而不是测试集仓")
    # import：裁决表 → 测试集的过滤条件（都可省；省了就是整个分片的 active 条目）
    p.add_argument("--book", default=None, help="import：只导这本书")
    p.add_argument("--pages", default=None, help="import：页号表达式，如 1-50,60")
    p.add_argument("--stratum", default=None, help="import：只导这个分层，如 flip_unique_top1")
    p.add_argument("--ids", default=None, help="import：id 清单文件（一行一个）")
    p.add_argument("--include-uncertain", action="store_true",
                   help="import：连 uncertain（idk）也导；默认只导 active")
    p.add_argument("--why", default="", help="import：写进 history 的理由")

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

    p = sub.add_parser("check", help="[v2] 判据与体检：quality | rulers | round | rate | throughput")
    p.add_argument("action", choices=["quality", "rulers", "round", "rate", "throughput"])
    p.add_argument("book", nargs="?", default="vol01")
    p.add_argument("--pages", default="dev_set")
    p.add_argument("--snapshot", action="store_true", help="rate：记一行台账（默认只读）")
    p.add_argument("--note", default="", help="rate --snapshot 的说明")
    p.add_argument("--all-pages", action="store_true",
                   help="throughput：统计全书已有产物的页，不只 --pages（吞吐量/通道占比默认整册）")

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
    p.add_argument("--top", default="", help="IDS 兜底：顶层结构，如 ⿰ ⿱ ⿸")
    p.add_argument("--slot-comp", action="append", default=[], metavar="槽=部件",
                   help="IDS 兜底：某槽位的部件，如 L=言（可重复）")
    p.add_argument("--comp", action="append", default=[], help="IDS 兜底：任意位置含此部件（可重复）")

    p = sub.add_parser("variants", help="[v2] 本书用字账（只读）")
    p.add_argument("action", nargs="?", default="book", choices=["book"])
    p.add_argument("--edition", default="")

    p = sub.add_parser("collate", help="[v2] Step9-9.3 与整理本对勘（出 JSON + HTML）")
    p.add_argument("book")
    p.add_argument("--pages", default="", help="页表达式；空 = 全部有 Step7 产物的页")
    p.add_argument("--out", default=None,
                   help="JSON 落点（默认 <workspace>/reports/<book>/collation_<时间>.json）")
    p.add_argument("--console", default="http://127.0.0.1:8640",
                   help="HTML 里深链指向的控制台地址；空串则不出链接")
    p.add_argument("--no-html", action="store_true", help="只出 JSON")

    p = sub.add_parser("progress", help="[v2] Step9-9.0 进度复查：页范围内每页还挂着哪些待办（看板，不拦 9.1/9.2）")
    p.add_argument("book")
    p.add_argument("--pages", default="all", help="页表达式；默认全书")
    p.add_argument("--json", action="store_true", help="出 JSON（与控制台 /api/step9/progress 同形）")

    p = sub.add_parser("runs", help="[v2] 控制台任务：list | show | cancel | log")
    p.add_argument("action", choices=["list", "show", "cancel", "log"])
    p.add_argument("id", nargs="?", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("-f", "--follow", action="store_true", help="log：跟着刷")

    install_workspace_option(sub)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        from .utils.batch_slice import enter_batch_slice
        enter_batch_slice(sys.argv[1:])   # 服务器上跑批自动进内存额度切片
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
