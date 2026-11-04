"""`guji rerun / pagekinds / cache / product`：从 cli_v2 拆出（拆分 P4，2026-11-04；这几条归 manager，随后整模块搬去 guji-manager）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from .utils.image_io import imread as cv_imread
from .cli_v2 import DEFAULT_PIPELINE, _add_override, _engine, _guard_cv_version, _out, cli_steps


def cmd_rerun(args) -> None:
    """`guji rerun --stale <册>`：只重跑显式标了失效的页及其下游（GUJI-578）。"""
    if not args.stale:
        print("✗ 目前只支持 --stale（只跑显式失效的页）", file=sys.stderr)
        sys.exit(2)
    from .core.workspace import assert_workspace_declared
    assert_workspace_declared()
    from .ops import rerun_stale as RS
    eng = _engine(args.book, args.pipeline, None)
    # 写产物，和 pipeline／step 一样过 cv 版本护栏（GUJI-577）；--dry-run 只提醒
    _guard_cv_version(eng.book, allow=getattr(args, "allow_cv_mismatch", False),
                      warn_only=args.dry_run, why=getattr(args, "why", None), eng=eng)
    pages = eng.book.resolve_pages(args.pages)

    def steps_after(first, to):
        return cli_steps(eng, first, to)

    if args.dry_run:
        RS.run(eng, steps_after, pages=pages, to_step=args.to_step, dry_run=True)
        return
    from .core.runlock import RunLockHeld, book_run_lock
    try:
        with book_run_lock(eng.book.id, wait=args.wait):
            _, rep = RS.run(eng, steps_after, pages=pages, to_step=args.to_step, jobs=args.jobs)
    except RunLockHeld as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(3)
    if rep is not None and args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False))
    n_failed = sum(1 for o in (rep.outcomes if rep else []) if o.status == "failed")
    sys.exit(1 if n_failed else 0)


def cmd_pagekinds(args) -> None:
    """页型对账（只读）：册配置点名的 / 页型规则判的 / 最后怎么处理的，对不上的列出来。见 `ops/page_kinds_report.py`。"""
    from .ops import page_kinds_report as PKR
    eng = _engine(args.book, args.pipeline, quiet=True)
    pages = eng.book.resolve_pages(args.pages)
    res = PKR.build(eng.book, eng.store, pages)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        PKR.print_report(res)


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
    elif args.action == "warm":
        # 多进程预渲字块（overview#429）：快照导入后 cache/ 是空的，串行步（rare_candidates）
        # 逐格现切字块占了每页九成时间。并发安全的做法见 ops/cache_warm.py 模块头。
        from .core.book import load_book
        from .core.pipeline import default_pipeline_id, load_pipeline
        from .core.step import RunContext
        from .ops.cache_warm import warm
        from .products.store import ProductStore
        from . import steps as _s  # noqa: F401
        if not args.book:
            print("必须给 --book"); sys.exit(1)
        book = load_book(args.book)
        pid = args.pipeline or default_pipeline_id(book)
        ctx = RunContext(book, ProductStore(), cache, log=lambda _: None, pipeline=load_pipeline(pid))
        res = warm(ctx, pid, book.resolve_pages(args.pages), max(1, args.jobs or 1),
                   log=lambda s: print(s, flush=True))
        print(f"预渲完成：{res['pages']} 页，{res['patches']} 个字块，{res['seconds']}s，"
              f"失败 {len(res['failed'])} 页")
        for pg, err in sorted(res["failed"].items())[:20]:
            print(f"  p{pg}: {err}")
    elif args.action == "verify":
        # 缓存是不是对着现行产物切的（产物从别处换进来没清缓存的话会错位，见 ops/cache_verify.py）
        from .ops.cache_verify import main_print, verify_book
        from .core.book import load_book
        from .core.pipeline import default_pipeline_id
        pid = args.pipeline or default_pipeline_id(load_book(args.book))
        eng = _engine(args.book, pid, quiet=True)
        res = verify_book(eng, eng.book.resolve_pages(args.pages), fix=args.fix,
                          full=getattr(args, "full", False))
        main_print(res)
        sys.exit(1 if res["bad_columns"] and not args.fix else 0)
    elif args.action == "build-rare-index":
        _cmd_cache_build_rare_index(args)
    elif args.action == "build-font-index":
        _cmd_cache_build_font_index(args)
    elif args.action == "pull-rare-index":
        _cmd_cache_pull_rare_index(args)
    elif args.action == "build-emb-pack":
        from .clustering import emb_pack
        from .hanzi.build import data_root
        from .ops.emb_pack_build import build
        m = build(data_root() / "emb-build", jobs=max(1, args.jobs or 1))
        print(f"清单 {emb_pack.EMB_DIR / (m['version'] + '.json')}；三个文件在 {data_root() / 'emb-build'}，"
              "传 R2：python scripts/build_hanzi_db.py --no-build --upload-emb")


def _cmd_cache_pull_rare_index(args) -> None:
    """`guji cache pull-rare-index [--book <book>]`：用全字表向量包（hanzi 库 B2）落成 Step5-b 的
    `emb_<key>.npz`，代替 `build-rare-index` 的现建（4 核约 45 分钟）。

    只认**与本机现役同规格**的包（模型、字体、渲染代码、额外图源四样指纹全对上，见
    `clustering/emb_pack.py`）；对不上就明说，照旧用 `build-rare-index` 现建，不拿旧向量冒充。
    落盘的 key、路径与 `build-rare-index` 是同一个函数算的，`_emb_index` 照旧命中。
    不给 `--book` 时只把向量包拉到本机（控制台「以字找字」排序用）。

    精度（`--precision`）缺省 int8（用户 10-20 定；真刻本评测过了判据，读数见总设计 §10「B2 续：精度」）。
    表旁边写 `emb_<key>.npz.source.json`（向量包版本＋精度）；已有的表来源不同（含本地现建、没有来源记录的）
    就替换，全队统一到同一版本同一精度——同一册在不同机器上 5-b 候选逐位一致。"""
    from .clustering import cnn_candidates as cc
    from .clustering import emb_pack

    spec = emb_pack.current_spec()
    m = emb_pack.find(spec)
    if m is None:
        have = ", ".join(x["version"] + f"（模型 {x['ckpt_fp']}）" for x in emb_pack.manifests()) or "无"
        print(f"没有与本机同规格的向量包：本机 {emb_pack.version_of(spec)} {spec}；已发布：{have}。"
              f"用 `guji cache build-rare-index` 现建，或先 `guji cache build-emb-pack` 出一版。")
        sys.exit(1)
    prec = args.precision or emb_pack.DEFAULT_PRECISION
    pk = emb_pack.EmbPack.load(m, precision=prec)
    if pk is None:
        print(f"向量包 {m['version']} 没有 {prec} 精度（有 {m.get('precisions', ['fp32'])}）")
        sys.exit(1)
    print(f"向量包 {pk.version}（{prec}）：{len(pk.chars)} 字（模型 {m['ckpt']} {m['ckpt_fp']}）")
    charset = getattr(args, "charset", "") or ""
    if not args.book and not charset:
        return
    tables: list[tuple[str, tuple]] = []
    if args.book:
        from .clustering.rare_panel import book_charsets
        from .steps.align_ref import book_corpus
        cs_base, cs_esc, _spec = book_charsets(args.book, book_corpus(args.book))
        tables += [("base", cs_base), ("escalate", cs_esc)]
    if charset:
        # 评测用（eval_oov / degradation / zero_shot_fusion 缺省 unicode-cjk-ab 全表 70,304 字）：
        # 现建 4 核要几小时，用向量包落成同 key 的表（2026-11-04 修 5b 评测链时补）
        from .clustering.charset_spec import base_charset
        tables.append((f"charset:{charset}", tuple(base_charset(charset))))
    inst = cc.CnnCandidates(ckpt=cc.DEFAULT_CKPT)

    def compute(chars):
        if not inst._ensure():
            raise SystemExit(f"{len(chars)} 字不在包里、本机又没有 torch/checkpoint，落不成完整索引")
        from .clustering.synth import render_char
        return cc.build_emb_matrix(inst._net, inst._dev, tuple(chars), {}, render_char)

    for name, cs in tables:
        if not cs:
            continue
        key, f, _extra = inst.emb_index_key(cs)
        side = f.with_name(f.name + ".source.json")
        want = {"emb": pk.version, "precision": prec}
        if f.exists():
            try:
                have = json.loads(side.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                have = None
            if have == want:
                print(f"{name}：已有 {f}（{pk.version}／{prec}），跳过")
                continue
            print(f"{name}：替换 {f.name}（原表来源：{have or '本地现建或旧快照，无来源记录'}）")
        mat, names = pk.materialize(cs, compute)
        cc._save_emb_index(f, mat, names)
        side.write_text(json.dumps(want, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{name}：{f}（key={key}），{len(names)}/{len(cs)} 字，来自 {pk.version}（{prec}）")


def _cmd_cache_build_rare_index(args) -> None:
    """`guji cache build-rare-index <book>`：云端预建 Step5-b 的 embedding 模板索引
    （2026-09-27，任务书-R-rare冷启动内存与索引预建）。

    这是解服务器工单 1715「vol02 冷启动 5 分钟、RSS 2.41G 还在涨」的正解：
    冷启动开销**量清楚了没找到能在原地压到 ≤1.2G 的办法**（见
    `clustering.cnn_candidates._emb_index` 模块头的实测记录），真正能让服务器
    峰值归零的办法是**根本不在服务器上建**——这里在云端把 `emb_<key>.npz` 建
    好，跟快照/checkpoint 一起分发，服务器 `git pull` 之后 `_emb_index` 第一次
    调用就直接命中磁盘缓存，连建索引的分支都不会进。

    只建 `rare_for_batch` 实际会用到的两张表：`book_charsets()` 的基集
    （`cs_base`）与升级档（`cs_esc`，配了 `escalate` 才有）——与产线用的是
    **同一个函数**，算出来的 key 必然一致，不会出现「预建的文件产线用不上」。
    """
    import time

    from .clustering import cnn_candidates as cc
    from .clustering.rare_panel import book_charsets
    from .steps.align_ref import book_corpus

    book = args.book
    if not book:
        print("必须给 --book"); sys.exit(1)
    corpus = book_corpus(book)
    cs_base, cs_esc, spec = book_charsets(book, corpus)
    print(f"book={book} corpus={corpus} base={spec['base']}（{len(cs_base)} 字）"
         f" escalate={spec['escalate']}（{len(cs_esc)} 字）")

    inst = cc.CnnCandidates(ckpt=cc.DEFAULT_CKPT)
    if not inst.available:
        print(f"checkpoint 不可用（{inst.ckpt}）或没装 torch，建不了。"); sys.exit(1)
    inst._ensure()

    for name, cs in (("base", cs_base), ("escalate", cs_esc)):
        if not cs:
            print(f"{name}：空表，跳过")
            continue
        key, f, _extra = inst.emb_index_key(cs)
        if f.exists():
            print(f"{name}：已有缓存 {f}（key={key}），跳过重建；如需强制重建先删掉这个文件")
            continue
        t0 = time.time()
        jobs = getattr(args, "jobs", 1) or 1
        if jobs > 1:
            # 分片多进程建（overview#429）：与单进程逐位相同，见 `ops.rare_index_build`
            from .ops.rare_index_build import build_parallel
            mat, names = build_parallel(inst, cs, jobs)
            if mat.shape[0] == 0:
                print(f"{name}：建成 0 行（字表 {len(cs)} 字），不落盘。检查 fonts/。"); sys.exit(1)
            cc._save_emb_index(f, mat, names)
        else:
            mat, names = inst._emb_index(cs)
        dt = time.time() - t0
        print(f"{name}：{f} 建好，{len(names)}/{len(cs)} 字，{dt:.1f}s")

    print("")
    print("分发：把 models/<ckpt名>/emb_*.npz 这几个文件随 cv 仓快照或 Release 一起带走，")
    print("服务器上放到同一个相对路径（checkpoint 旁边）即可；`fingerprint()` 按内容算，")
    print("换机器 mtime 不同也照样命中。验证命中：服务器上 `git status`/校验 sha256 后跑一页，")
    print("看 `guji pipeline … --to rare_candidates --pages <该页>` 的日志里没有")
    print("「guji cache build-rare-index：…」这行进度（=直接读了缓存，没有现建）。")


def _cmd_cache_build_font_index(args) -> None:
    """`guji cache build-font-index [--book <book>]`：云端预建控制台 K19 的
    HOG 字体模板索引（2026-09-28，任务书-K-控制台常驻内存与字体索引预建）。

    控制台启动会起一个后台线程 `warm_font_index()`（`clustering/rare_panel.py`）
    现建这份索引——首次建大表要几分钟、峰值内存到 GB 量级（K19 done 单 §三：
    一份矩阵单独就有 495MB）。跟 `build-rare-index` 同一个解法：云端把
    `cache/font_index/<key>.npz` 建好，随快照/发布分发到服务器，控制台第一次
    调 `font_candidates._index()` 就直接命中磁盘缓存，连建索引的分支都不进。

    只建 `warm_font_index()` 实际会用到的两张表：`rare_panel._rare_charsets()`
    的 small 与 big——与 `warm()` 用的是**同一个函数**，算出来的
    `_index_key()` 必然一致。`--book` 给了就按那本书的整理本语料算字表
    （`rare_for` 单查时用的字表），不给就用 `DEFAULT_CORPUS`（控制台启动
    `warm_font_index()` 走的正是这条，不传 book）——预建哪张表要跟被预热的
    那张对上。

    `warm()` 内部已经把「被别的字表整体包含的字表」去重（K19：small⊆big 只建
    big 一份，small 查询借 big 的矩阵，见 `font_candidates.warm()` 模块头），
    这里直接调它，不用自己再判断包含关系。
    """
    import os

    from .clustering.font_candidates import _index_dir, _index_key, all_ready, warm
    from .clustering.rare_panel import _rare_charsets
    from .core.workspace import workspace_root
    from .steps.align_ref import book_corpus

    # 不给 --book 时字表取 DEFAULT_CORPUS、落盘在 cache_root()——两样都按工作区解析。没有工作区
    # 就会拿仓内 17 KB 样本语料建一张谁也用不上的表、写进仓内 cache/，所以要么 -w、要么 GUJI_CACHE_DIR。
    if workspace_root() is None and not os.environ.get("GUJI_CACHE_DIR"):
        print("✗ 要给 -w <工作区>（控制台起在哪个工作区就给哪个）：默认语料与 cache/font_index/ "
              "都按工作区解析，不给会拿仓内样本语料建一张用不上的表", file=sys.stderr)
        sys.exit(2)
    corpus = book_corpus(args.book) if args.book else None
    cs_small, cs_big = _rare_charsets(corpus)
    print(f"book={args.book or '(默认语料)'} corpus={corpus or '(DEFAULT_CORPUS)'} "
         f"small={len(cs_small)} 字 big={len(cs_big)} 字")
    for name, cs in (("small", cs_small), ("big", cs_big)):
        print(f"  {name} key={_index_key(cs, 'fonts', 'hog')}")
    if all_ready([cs_small, cs_big]):
        print(f"已有缓存，跳过重建；如需强制重建先删掉 {_index_dir()} 里对应文件")
        return
    warm([cs_small, cs_big])
    print(f"建好，落在 {_index_dir()}")
    print("")
    print("分发：把 <cache_root>/font_index/*.npz 随 cv 仓快照或 Release 一起带走，")
    print("服务器上放到同一个相对路径（`core.workspace.cache_root()` 算出来的那层）即可；")
    print("`font_set_fingerprint()` 按字体文件内容+大小+mtime 算，字表/字体没变就命中。")


def _write(path: str, data: bytes) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    print(f"{path}  {len(data) / 1024:.1f} KB")


def cmd_product(args) -> None:
    """产物与图像：show | manifest | raw | overlay | patch。

    对应控制台第二类 6 条路由。图像类要 `--out`——云端跑完把 PNG 交回本地看，
    这是「云端能出叠图」那条路的落点。
    """
    from .core.spec import cell_key
    from .products.cache import ImageCache
    from .products.store import ProductStore
    from .render.overlay import encode_png, overlay

    from .core.step import resolve_step_id
    st = ProductStore()
    if args.action in ("show", "manifest"):
        # `step` 位置参数常被当成产物种类(kind_id)传——多数步骤 step_id==kind_id
        # 恰好凑巧对，`context_decide`(step_id) 产 `context_decision`(kind_id)
        # 这种不同名的一查就悄悄 0 条（任务卡 #54 第21条）。这里按名字自动纠正，
        # 两边都不认得才报错，不再放过去变成一份「查到了空」的假阴性。
        try:
            step_id = resolve_step_id(args.step)
        except KeyError as e:
            print(str(e)); sys.exit(1)
        if step_id != args.step:
            print(f"『{args.step}』是产物种类(kind_id)，不是步骤名(step_id)——"
                 f"改查 {step_id!r}", file=sys.stderr)
    if args.action == "show":
        d = st.read_raw(args.book, step_id, args.key)
        if d is None:
            print(f"没有这份产物: {args.book}/{step_id}/{args.key}"); sys.exit(1)
        entry = st.manifest(args.book, step_id).get(args.key)
        _out({"book": args.book, "step": step_id, "key": args.key,
              "manifest": (entry.__dict__ if entry else None), "products": d})
    elif args.action == "manifest":
        _out({k: v.__dict__ for k, v in st.manifest(args.book, step_id).all().items()})
    elif args.action == "raw":
        from .core.book import load_book
        from .utils.image_io import imread as cv_imread
        f = load_book(args.book).raw_path(args.page)
        if not f.exists():
            print("原图缺失"); sys.exit(1)
        _write(args.out, encode_png(cv_imread(str(f)), args.scale))
    elif args.action == "overlay":
        _write(args.out, encode_png(overlay(args.book, args.step, args.page, st), args.scale))
    elif args.action == "patch":
        from .core.book import load_book
        from .core.step import RunContext
        key = cell_key(args.page, args.col, args.slot) + (args.sub or "")
        cache = ImageCache()
        f = cache.get(args.book, "char_patch", key)
        if f is None:
            # 缓存没有就现场重建（同控制台 /api/cache 那条路，见 console/routers/products.py::api_cache）：
            # 拿快照到云端时 products/ 有、cache/ 没有，字块图应当能从原图 + cell_shrink 重建，不该直接报错退出。
            try:
                ctx = RunContext(load_book(args.book), st, cache, log=lambda s: None)
                f = ctx.materialize("char_patch", key)
            except Exception as e:  # noqa: BLE001
                print(f"没有字块 {key}，现场重建也失败: {e}"); sys.exit(1)
        _write(args.out, Path(f).read_bytes())



def add_parser(sub) -> None:
    p = sub.add_parser("rerun", help="[v2] --stale：只重跑显式标了失效（人裁落定等）的页及其下游")
    p.add_argument("book")
    p.add_argument("--stale", action="store_true", help="只跑 manifest 里 invalidated 的页（目前必须给）")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="all", help="只在这些页里找失效（默认全书）")
    p.add_argument("--to", dest="to_step", default=None, help="跑到哪一步为止（含），默认管线末尾")
    p.add_argument("--dry-run", action="store_true", help="只列要跑哪些步哪些页")
    p.add_argument("--jobs", type=int, default=1, help="页级并行进程数（只对 parallel_safe 的步生效）")
    p.add_argument("--wait", action="store_true", help="这本书正有别的跑批时排队等")
    p.add_argument("--json", action="store_true")
    p.add_argument("--allow-cv-mismatch", action="store_true",
                   help="册配置固定了 cv_version 而装的不是它时照跑，须同时给 --why（实验分支上自动放行）")
    p.add_argument("--why", default=None, help="配 --allow-cv-mismatch：理由，记进产物 manifest 的 cv_override")
    p = sub.add_parser("pagekinds", help="[v2] 页型对账（只读）：册配置点名的页型 / 页型规则判的 / 最后怎么处理的，对不上的列出来")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="all", help="页范围，缺省整册")
    p.add_argument("--json", action="store_true")
    _add_override(p)
    p = sub.add_parser("cache", help="[v2] 图像缓存：usage | prune | get | column | verify | warm | "
                                     "build-rare-index | build-font-index | pull-rare-index | build-emb-pack")
    p.add_argument("action", choices=["usage", "prune", "get", "column", "verify", "warm",
                                      "build-rare-index", "build-font-index", "pull-rare-index",
                                      "build-emb-pack"])
    p.add_argument("--pipeline", default=None, help="verify：管线 id，缺省按册")
    p.add_argument("--pages", default="all", help="verify / warm：页表达式，缺省 all")
    p.add_argument("--fix", action="store_true", help="verify：把错位页的字块/列图缓存清掉，惰性重建")
    p.add_argument("--full", action="store_true",
                   help="verify：连戳与现行产物对得上的页也逐列渲染比对（缺省免查这些页，见 ops/cache_verify.py）")
    p.add_argument("--limit-gb", type=float, default=None)
    p.add_argument("--book", default="")
    p.add_argument("--jobs", type=int, default=1,
                   help="build-rare-index：分片多进程建（逐位相同；云端 4 核给 4，约快 4 倍）；"
                        "warm：预渲字块的进程数")
    p.add_argument("--charset", default="",
                   help="pull-rare-index：另落一张按字表规格的表（如 unicode-cjk-ab，评测 oov / degradation 用）")
    p.add_argument("--precision", choices=["int8", "fp16", "fp32"], default=None,
                   help="pull-rare-index：向量包精度，缺省 int8（真刻本评测与 fp32 持平，见总设计 B2 续）")
    p.add_argument("--kind", default="char_patch", help="get：产物种类")
    p.add_argument("--key", default="", help="get：缓存键，如 p0024c01s10")
    p.add_argument("--page", type=int, default=0, help="column：页号")
    p.add_argument("--col", type=int, default=0, help="column：列号")
    p.add_argument("--y0", type=int, default=0)
    p.add_argument("--y1", type=int, default=0, help="column：裁到哪（0 = 到底）")
    p.add_argument("--out", default="", help="get / column 的输出路径")



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


COMMANDS = {"rerun": (add_parser, cmd_rerun), "pagekinds": (add_parser, cmd_pagekinds), "cache": (add_parser, cmd_cache), "product": (add_parser, cmd_product)}
