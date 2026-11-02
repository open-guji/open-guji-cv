# -*- coding: utf-8 -*-
"""人裁与金标命令：events（反馈事件）、gold（金标）、batch（审查批次）、label-batch（L3 补标签）。

拆分 P1（`doc/design/拆分-pipeline与manager.md`）从 `cli_v2` 原样搬出；经 `cli_v2.MANAGER_CLI_MODULES` 登记。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import cli_v2   # 共用辅助现取（测试 monkeypatch cli_v2 照样生效）
from .utils.image_io import imread as cv_imread


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


def cmd_label_batch(args) -> None:
    """L3 补标签两批：make（出批次）| harvest（收割进 dataset）| migrate-legacy（旧 overview 列端卡入新分片）。"""
    from . import steps as _s  # noqa: F401 —— 兜底：确保 Step 先注册，否则 store.read 的 kind_of() 查不到产物种类
    from .review import label_batches as LB
    try:
        if args.action == "make":
            fn = {"cutline-gold": LB.build_cutline_gold, "column-end": LB.build_column_end}[args.kind]
            if not args.book:
                raise ValueError("make 需要册 id：guji label-batch make <cutline-gold|column-end> <册>")
            n = args.n or (200 if args.kind == "cutline-gold" else 240)
            out = fn(args.book, n=n, batch_id=args.id, pages=args.pages, seed=args.seed)
            print(json.dumps(out, ensure_ascii=False, indent=1))
            where = ("Step3「拖切线」页码框填 " + out["console_pages"] if "console_pages" in out
                     else "Step1 页「Step2 上下版框核校」页码框填 batch:" + out["batch"])
            print(f"\n控制台：{where}；批次框填 {out['batch']}")
        elif args.action == "harvest":
            from .gold.store import GoldStore
            ds = GoldStore(Path(args.dataset)) if args.dataset else None
            print(json.dumps(LB.harvest_batch(args.kind, dataset=ds), ensure_ascii=False, indent=1))
        elif args.action == "migrate-legacy":
            from .gold.store import GoldStore
            ds = GoldStore(Path(args.dataset)) if args.dataset else None
            print(json.dumps(LB.migrate_legacy_overview(Path(args.kind), book=args.book or "vol02", dataset=ds),
                             ensure_ascii=False, indent=1))
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:                                  # noqa: BLE001
        from .errors import ProductMissing
        if isinstance(e, ProductMissing):
            print(f"错误：{e}", file=sys.stderr)
            sys.exit(1)
        raise


def cmd_events(args) -> None:
    from .feedback.consumers import route_and_consume
    from .feedback.events import EventLog
    from .feedback.harvest import harvest_file
    from .feedback.routes import RouteTable
    from .review.batches import BatchStore
    if args.action == "import-vision":
        _import_vision(args)
        return
    if args.action == "lint":
        # 按 doc/formats/人裁事件规范.md 体检事件日志（只读）；有 E- 级问题以 1 退出
        from .feedback.lint import lint
        rep = lint(EventLog().root)
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1) if args.json else rep.render())
        sys.exit(1 if rep.n_errors else 0)
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
        cli_v2._out(fn(args.batch, log))
    elif args.action == "list":
        evs = _select_events(log, args.batch, args.book)
        for e in evs[-args.limit:]:
            print(f"  {e.id}  {e.kind:12s} {e.target.key:28s} {json.dumps(e.payload, ensure_ascii=False)}")
        print(f"  共 {len(evs)} 条")


def _select_events(log, batch: str | None, book: str | None = None) -> list:
    """`events list` 的取数：批次名可带通配（`vol03-*`，按文件名匹配后合并）；`book` 只留
    target.key 以 `<册>:` 开头的事件——通配批次里混进别册的 key 时（GUJI-77）不串册。只读。"""
    import fnmatch
    from .feedback.events import replay_key
    if batch and any(c in batch for c in "*?["):
        evs = sorted((e for b in log.batches() if fnmatch.fnmatch(b, batch)
                      for e in log.read(b)), key=replay_key)
    elif batch:
        evs = log.read(batch)
    else:
        evs = sorted(log.iter_all(), key=replay_key)
    if book:
        evs = [e for e in evs if e.target.key.startswith(f"{book}:")]
    return evs


def _import_vision(args) -> None:
    """`guji events import-vision <jsonl> -w <工作区> [--book 册]`：看图结论 → `feedback/vision/`
    （overview#428；格式见 `feedback/vision.py` 模块头与 runbook S8/S10）。不是人裁：不进字形库、
    不算已裁，判错的格回待审队列（doubt `vision_flag`）。"""
    from .feedback.vision import import_vision
    if not args.workspace:
        print("✗ import-vision 要 -w <工作区>（看图结论写进工作区的 feedback/vision/）", file=sys.stderr)
        sys.exit(2)
    if not args.batch:
        print("✗ 要给 jsonl 路径：guji events import-vision reports/vol04/看图结论.jsonl -w <工作区>",
              file=sys.stderr)
        sys.exit(2)
    path = Path(args.batch)
    if not path.exists():
        print(f"✗ 文件不存在：{path}", file=sys.stderr)
        sys.exit(2)
    res = import_vision(path, batch=args.as_batch, judge=args.judge, book=args.book,
                        gold=not args.no_gold, dry_run=args.dry_run, source_rev=getattr(args, "source_rev", None))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if res["errors"]:
        print(f"✗ {len(res['errors'])} 处格式错，整批没写", file=sys.stderr)
        sys.exit(1)
    if args.dry_run:
        print("（试算，未写入；去掉 --dry-run 才导入）")


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
        if not args.shard:
            # 看图结论另放 feedback/vision/（overview#428），全量重建时一并重放，label_origin=vision
            from .feedback.vision import rebuild_vision_gold
            out["vision"] = rebuild_vision_gold(store=verdict_store())
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
        out = rep.to_dict()
        if args.apply:
            out["marked_stale"] = mark_drifted(store, args.shard, rep)
        if getattr(args, "json", False):
            print(json.dumps(out, ensure_ascii=False))
            return
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1))
        if args.apply:
            print(f"标 stale: {out['marked_stale']} 条")


def add_parser(sub) -> None:
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
    p = sub.add_parser("label-batch", help="[v2] L3 补标签两批：make cutline-gold|column-end <册> | harvest <批次> | migrate-legacy <文件>")
    p.add_argument("action", choices=["make", "harvest", "migrate-legacy"])
    p.add_argument("kind", help="make 时：cutline-gold | column-end；harvest 时：批次 id；migrate-legacy 时：旧 verdicts.jsonl 路径")
    p.add_argument("book", nargs="?", default=None, help="make：册 id；migrate-legacy：册（缺省 vol02）")
    p.add_argument("--n", type=int, default=0, help="张数（缺省：切线 200 / 列端 240）")
    p.add_argument("--id", default=None, help="批次 id（缺省自动命名）")
    p.add_argument("--pages", default="body", help="body（缺省，21 格标准版式页）| dev_set | 页号表达式")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--dataset", default=None, help="测试集仓路径（缺省 GUJI_DATASET_DIR 或 ../open-guji-dataset）")
    p = sub.add_parser("events", help="[v2] 反馈事件：harvest | route | list | verdicts | import-vision | lint")
    p.add_argument("action", choices=["harvest", "route", "list", "verdicts", "import-vision", "lint"])
    p.add_argument("batch", nargs="?", default=None, help="批次名；import-vision 时是 jsonl 路径")
    p.add_argument("--file", default=None, help="收割源：审查页 HTML / JSONL / 日志")
    p.add_argument("--step", default=None)
    p.add_argument("--unit", default="page")
    p.add_argument("--kind", default="verdict")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    # import-vision（overview#428）：看图结论 jsonl → feedback/vision/
    p.add_argument("--book", default=None, help="list：只列 target.key 以 <册>: 开头的事件（批次名可带通配 *）；import-vision：只认这一册的格（给了就校验 books/<册>.yaml）")
    p.add_argument("--judge", default=None, help="import-vision：行里没写 judge 时用的模型名")
    p.add_argument("--as-batch", default=None, help="import-vision：批次名，缺省 vision-<文件名>")
    p.add_argument("--no-gold", action="store_true", help="import-vision：只写事件，不落裁决表")
    p.add_argument("--source-rev", type=int, default=None,
                   help="import-vision：结论是在哪一版页表的产物上判的，写进锚 anchor.source_rev；换过图源的册必给（须与册 yaml 相同）")
    p.add_argument("--json", action="store_true", help="lint：出机读结果")
    p = sub.add_parser("gold", help="[v2] 金标：shards | show | migrate | drift | import | export | rebuild")
    p.add_argument("action", choices=["shards", "show", "migrate", "drift", "import", "export", "rebuild"])
    p.add_argument("shard", nargs="?", default=None,
                   help="分片名；rebuild 时是批次名（留空=全部批次）")
    p.add_argument("--dry-run", action="store_true", help="migrate / import：只报数不写")
    p.add_argument("--apply", action="store_true", help="drift：把漂移条目标成 stale")
    p.add_argument("--json", action="store_true", help="drift：只出一个 JSON（含 marked_stale），控制台调用用")
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


#: 并进 `guji` 的子命令（同插件接口 `guji.commands`）
COMMANDS = {
    "events": (add_parser, cmd_events),
    "gold": (add_parser, cmd_gold),
    "batch": (add_parser, cmd_batch),
    "label-batch": (add_parser, cmd_label_batch),
}
