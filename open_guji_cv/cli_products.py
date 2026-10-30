"""`guji products`：产物前后对比、产物包（存取 R2）。不跑 Step，不进任何 Step 的 `code_deps`。

    guji products diff <册> --a <产物根> [--b <产物根>] [--pages …] [--out 目录] [--images N] -w <工作区>
    guji products pack  push <册> [--change 名] [--main] [--report diff目录] -w <工作区>  # 本机产物打包存 R2，并在工作区仓写实验记录
    guji products pack  fetch <册> [--label 名] [--to 产物根] -w <工作区>    # 取回，缺省落在本机产物根
    guji products pack  list [<册>] -w <工作区>                            # ★ = 该册 main
    guji products pack  promote <册> --label 名 -w <工作区>                # 把已存的包标成该册 main
    guji products exclusions <册> --a <重切前产物根> [--b <重切后>] [--apply] -w <工作区>  # 排除清单按框跟着重切走
    guji products pack  push-index | fetch-index                           # 生僻字 embedding 索引（models/*/emb_*.npz）；push-index 另推训好的语言模型

产物根就是含 `<册>/<步>/p0001.json` 的那一层（`products/`、`guji snapshot make` 出的目录、实验变体目录）。
细则见 doc/受控重跑.md。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ws(args) -> None:
    if args.workspace:
        os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())


def _root(p: str | None) -> Path:
    from .products.store import default_products_root
    return Path(p).expanduser().resolve() if p else default_products_root()


def cmd_diff(args) -> None:
    from .core.book import load_book
    from .ops import products_diff as PD
    book = load_book(args.book)
    a, b = _root(args.a), _root(args.b)
    if a == b:
        print("✗ --a 和 --b 是同一个目录", file=sys.stderr)
        sys.exit(2)
    pages = book.resolve_pages(args.pages)
    res = PD.diff_book(a, b, book.id, pages)
    out = Path(args.out).expanduser() if args.out else Path.cwd() / f"diff-{book.id}"
    if args.images:
        from .cli_v2 import _engine
        eng = _engine(book.id, args.pipeline, quiet=True)
        n = PD.render_images(res, out, eng.ctx.raw_page, args.images, str(a), str(b))
        print(f"看图 {n} 列：{out / 'index.html'}")
    rep = PD.write_report(res, out, str(a), str(b))
    s = res["summary"]
    ra, rb = s["a"]["review_rate"], s["b"]["review_rate"]
    f = (lambda x: "—" if x is None else f"{x * 100:.2f}%")
    print(f"{book.id} {s['pages']} 页：送审 {s['a']['review']} → {s['b']['review']}（人审率 {f(ra)} → {f(rb)}）；"
          f"变了的列 " + "、".join(f"{k} {s['columns'].get(k, 0)}" for k in PD.KINDS))
    if s["flips"].get("放行字变"):
        print(f"  ⚠ 放行字变 {s['flips']['放行字变']} 格（两边都放行、字不同），逐个看图")
    print(f"报告：{rep}")


def book_versions(book: str, root: Path | None = None) -> dict:
    """一份结果由三样版本共同决定：cv、语料库（册 yaml `corpus: N`，两级清单另记底库号）、字形库
    （`glyph_pin: N`；没钉就记人裁内容指纹）。全记进产物包的 manifest，标签前三段由它拼。

    钉了有快照的字形库版本时另记 `glyph_digest`（快照内容）与 `glyph_rev`（出快照时的中心库 rev）。
    旧做法的 `glyph_pin` 只钉指纹、不钉字形库内容，所以另记中心库 rev：`db_rev` 是存包时本机数据对应的版本，
    `db_revs` 是 seed_admit 各页跑时记下的版本及页数（产物 manifest 的 `db_rev`，老产物没有）。
    要精确复现某份包读的库，从那个 rev 开 Neon 实验分支。"""
    from .core import cv_version as CV
    from .core.workspace import central_rev
    ver, commit = CV.describe()
    out = {"cv": ver, "cv_commit": commit, "corpus": None, "corpus_base": None, "glyph_pin": None,
           "human_fp": None, "db_rev": central_rev(), "db_revs": None}
    try:
        from .core.book import load_book
        b = load_book(book)
        out["corpus"] = getattr(b, "corpus", None)
        out["glyph_pin"] = getattr(b, "glyph_pin", None)
    except Exception:          # noqa: BLE001 —— 读不到册配置：只记 cv
        pass
    if out["corpus"] is not None:
        try:
            from .core.corpus_pin import load_manifest
            from .core.workspace import workspace_root
            out["corpus_base"] = load_manifest(workspace_root(), int(out["corpus"])).get("base")
        except Exception:      # noqa: BLE001
            pass
    if out["glyph_pin"] is not None:          # 有快照的钉号（GUJI-727）：另记快照内容与它对应的中心库 rev
        try:
            from .core.glyph_pin import load_manifest as glyph_manifest
            from .core.workspace import workspace_root
            gm = glyph_manifest(workspace_root(), int(out["glyph_pin"]))
            if gm:
                out["glyph_digest"], out["glyph_rev"] = gm["digest"], gm.get("rev")
        except Exception:      # noqa: BLE001
            pass
    if out["glyph_pin"] is None:
        try:
            from .clustering.glyph_fp import human_shapes_fingerprint
            from .core.workspace import glyph_db_path
            out["human_fp"] = human_shapes_fingerprint(glyph_db_path())
        except Exception:      # noqa: BLE001
            pass
    if root is not None:
        from .products.manifest import Manifest
        m = Path(root) / book / "seed_admit" / "_manifest.jsonl"
        if m.exists():
            revs: dict[str, int] = {}
            for e in Manifest(m).all().values():
                if e.status == "ok":
                    k = e.db_rev or "未记"
                    revs[k] = revs.get(k, 0) + 1
            out["db_revs"] = revs or None
    return out


def _book_yaml_text(book: str) -> str | None:
    from .core.workspace import books_dir
    d = books_dir()
    p = d / f"{book}.yaml" if d is not None else None
    return p.read_text(encoding="utf-8") if p is not None and p.is_file() else None


def _record(book: str, info: dict, base_label: str | None, report: str | None,
            summary: str | None = None, root: Path | None = None) -> None:
    """存包后在工作区仓 `experiments/<册>/<标签>.md` 留实验记录（只写文件，提交由人做）。"""
    from .core.workspace import workspace_root
    from .ops import exp_record as ER
    ws = workspace_root()
    if ws is None:
        return
    p = ER.write_record(ws, book, info, base_label=base_label, book_yaml=_book_yaml_text(book),
                        report_dir=Path(report).expanduser() if report else None,
                        summary=summary, products_root=root)
    print(f"实验记录：{p}（在工作区仓里，记得提交）")


def cmd_pack(args) -> None:
    from .datastore import packs as PK
    if args.pack_action in ("push-index", "fetch-index"):
        if args.pack_action == "push-index":
            # 生僻字 embedding 索引 + 训好的语言模型（2026-10-20；LM 取是自动的，见 packs.fetch_derived）
            done = PK.push_rare_indexes() + PK.push_derived()
        else:
            done = PK.fetch_rare_indexes()
        print(("已存：" if args.pack_action == "push-index" else "已取：") + ("、".join(done) or "无（都已有）"))
        return
    if args.pack_action == "list":
        for row in PK.list_packs(args.book):
            star = "★" if row.get("main") else " "
            v = row.get("versions") or {}
            vs = (f"cv {v.get('cv')} 语料 {v.get('corpus') if v.get('corpus') is not None else '-'} "
                  f"字形 {v.get('glyph_pin') if v.get('glyph_pin') is not None else (v.get('human_fp') or '-')}") if v else ""
            print(f"{star} {row['name']}\t{row.get('bytes', '')}\t{row.get('created', '')}\t{vs}\t{row.get('note', '')}")
        return
    if args.pack_action == "promote":
        if not (args.book and args.label):
            print("✗ 用法：guji products pack promote <册> --label <标签>", file=sys.stderr)
            sys.exit(2)
        try:
            print(f"已标 main：{PK.promote(args.book, args.label, note=args.note or '', why=args.why)}")
            _warn_impure(args.book, args.label)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(2)
        _note_main(args.book, args.label, args.note or "")
        return
    if not args.book:
        print("✗ push/fetch 要给册", file=sys.stderr)
        sys.exit(2)
    if args.pack_action == "push":
        root = _root(args.root)
        first_run = False
        try:
            base_label = PK.main_label(args.book)
            first_run = base_label is None
        except Exception:      # noqa: BLE001 —— 列不到指针不挡存包
            base_label = None
        vers = book_versions(args.book, root)
        if args.main and not _main_ok(vers.get("cv"), args.why):
            sys.exit(2)
        auto_main = _auto_main_first(first_run, args.main, vers.get("cv"))
        purity = None if (args.steps or args.no_purity) else _purity(args.book, root)
        info = PK.push_products(args.book, root, label=args.label, change=args.change,
                                vers=vers, purity=purity,
                                steps=args.steps.split(",") if args.steps else None, note=args.note or "")
        print(f"已存：{info['name']}（{info['bytes'] / 1e6:.1f} MB，{info['files']} 个文件，{len(info['parts'])} 段）")
        if not args.no_record:
            _record(args.book, info, base_label, args.report, _summary_text(args.summary), root)
        if args.main or auto_main:
            try:
                print(f"已标 main：{PK.promote(args.book, info['label'], note=args.note or '', why=args.why)}"
                      + ("（新册首跑，还没有 main，自动标）" if auto_main else ""))
            except ValueError as e:
                print(f"✗ 包已存，没标 main：{e}", file=sys.stderr)
                sys.exit(2)
            _warn_impure(args.book, info["label"])
            _note_main(args.book, info["label"], args.note or "")
    else:
        info = PK.fetch_products(args.book, _root(args.to or args.root), label=args.label, force=args.force)
        print(f"已取：{info['name']} → {info['dest']}（{info['files']} 个文件）")


def _purity(book: str, root: Path) -> dict:
    """存包前查纯净性（`ops/pack_purity`，A32 精校前移 A2/A3）：混版本、图源对不上。只读；查不成记 error，不挡存包。"""
    from .ops import pack_purity as PP
    try:
        pur = PP.check(book, root)
    except Exception as e:  # noqa: BLE001
        pur = {"pure": None, "error": f"{type(e).__name__}: {e}"[:300]}
    print(f"纯净性：{PP.describe(pur)}", file=sys.stderr if pur.get("pure") is False else sys.stdout)
    return pur


def _warn_impure(book: str, label: str) -> None:
    """标了 main 的包存包时查出不纯（混版本、图源对不上）就提醒一句；不拦（见 datastore/packs.promote）。"""
    import json
    from .datastore import packs as PK
    from .ops.pack_purity import describe
    try:
        man = json.loads(PK._call(PK._client(), "GET", f"{PK._prefix(PK._ws_name(), book)}/{label}/manifest.json", raw=True))
    except Exception:  # noqa: BLE001
        return
    pur = man.get("purity")
    if pur and pur.get("pure") is False:
        print(f"⚠ 这份 main 包{describe(pur)}（指针里已记一笔）", file=sys.stderr)


def _auto_main_first(first_run: bool, main_flag: bool, cv: str | None) -> bool:
    """新册首跑（这册还没有 main 指针）存包后自动标 main（sheldon 10-25 定：新册的第一个包只能是 main）。
    只在正式库、装的是正式版 cv 时自动标；实验分支、dev／rc 版不自动，只提示。"""
    from .core.cv_version import is_formal
    from .core.workspace import active_branch
    from .datastore.client import is_exp_branch
    if not first_run or main_flag or is_exp_branch(active_branch()):
        return False
    if not is_formal(cv):
        print(f"ⓘ 这册还没有 main，但装的 cv 是 {cv or '未知版本'}（非正式版），不自动标 main", file=sys.stderr)
        return False
    return True


def _main_ok(cv: str | None, why: str | None) -> bool:
    """`push --main` 先查：装的不是正式版 cv、又没给 --why，就别存了（存完 promote 也会拒）。实验分支不查。"""
    from .core.cv_version import is_formal
    from .core.workspace import active_branch
    from .datastore.client import is_exp_branch
    if is_formal(cv) or (why or "").strip() or is_exp_branch(active_branch()):
        return True
    print(f"✗ 装的 cv 是 {cv or '未知版本'}，不是正式版，产物不能标 main：发正式 tag 后在它上面重跑再存；"
          f"只存不标去掉 --main；确要标加 --why \"<理由>\"", file=sys.stderr)
    return False


def _summary_text(s: str | None) -> str | None:
    """`--summary` 可直接给文字，也可给 `@文件`（多行摘要写文件里）。"""
    if s and s.startswith("@"):
        return Path(s[1:]).expanduser().read_text(encoding="utf-8")
    return s


def _note_main(book: str, label: str, note: str) -> None:
    from .core.workspace import workspace_root
    from .ops import exp_record as ER
    ws = workspace_root()
    p = ER.note_main(ws, book, label, note) if ws is not None else None
    if p:
        print(f"实验记录已记「标为 main」：{p}")
    _run_post_promote(book, label, str(ws) if ws is not None else None)


POST_PROMOTE_GROUP = "guji.post_promote"


def _run_post_promote(book: str, label: str, ws: str | None) -> None:
    """标 main 之后的插件钩子（入口点组 `guji.post_promote`，函数签名 `(book, label, ws)`）。

    manager 用它在标 main 后自动重出线上待审单；pipeline 自己不知道有哪些插件。插件抛错只提示，不挡标 main。"""
    from importlib.metadata import entry_points
    try:
        eps = entry_points(group=POST_PROMOTE_GROUP)
    except Exception:  # noqa: BLE001
        return
    for ep in eps:
        try:
            ep.load()(book, label, ws)
        except Exception as e:  # noqa: BLE001
            print(f"（标 main 后的插件 {ep.name} 出错，已忽略：{e}）", file=sys.stderr)


def cmd_exclusions(args) -> None:
    """排除清单按框跟着重切走（`ops/exclusion_rebind.py`）。缺省只报计划，`--apply` 才改本机名单。"""
    from .core.book import load_book
    from .core.workspace import exclusions_path
    from .ops import exclusion_rebind as XR
    book = load_book(args.book)
    a, b = _root(args.a), _root(args.b)
    ex = exclusions_path()
    rows = XR.plan(book.id, a, b, ex)
    c = XR.counts(rows)
    print(f"{book.id} 排除清单 {len(rows)} 条：" + "、".join(
        f"{k} {c.get(k, 0)}" for k in ("same", "moved", "gone", "dup", "no_old")) + f"（名单 {ex}）")
    for p in rows:
        if p["status"] in ("moved", "gone", "dup"):
            print(f"  {p['status']:5s} {p['iid']}" + (f" → {p['new']}" if p["new"] and p["status"] != "gone" else "")
                  + f"  IoU {p['iou']}")
    if args.apply:
        XR.apply(rows, ex)
        print("已改本机名单；改完 guji db sync 推回中心库（名单一变各册 seed_admit 都会过期）")
    elif c.get("moved") or c.get("gone") or c.get("dup"):
        print("（只是计划；加 --apply 才改）")


def cmd_products(args) -> None:
    _ws(args)
    if args.action == "diff":
        cmd_diff(args)
    elif args.action == "exclusions":
        cmd_exclusions(args)
    else:
        cmd_pack(args)


def add_parser(sub) -> None:
    p = sub.add_parser("products", help="[v2] 产物前后对比（diff）、产物包存取 R2（pack）")
    p.add_argument("action", choices=["diff", "pack", "exclusions"])
    p.add_argument("pos", nargs="*", help="diff：<册>；pack：push|fetch|list|promote [<册>]、push-index、fetch-index")
    p.add_argument("-w", "--workspace", default=None, help="工作区（册配置、原图）")
    p.add_argument("--a", default=None, help="diff：前（基线）产物根")
    p.add_argument("--b", default=None, help="diff／exclusions：后产物根，缺省本机产物根")
    p.add_argument("--apply", action="store_true", help="exclusions：按计划改本机排除清单（缺省只报）")
    p.add_argument("--pages", default="all")
    p.add_argument("--out", default=None, help="diff：报告目录，缺省 ./diff-<册>")
    p.add_argument("--images", type=int, default=0, help="diff：前 N 个变了的列出看图页（要原图）")
    p.add_argument("--pipeline", default="keben_body_v2")
    p.add_argument("--label", default=None, help="pack：整个标签（ASCII）；push 缺省按版本三段拼（见 --change）；fetch 缺省取 main")
    p.add_argument("--steps", default=None, help="pack push：只打这几步，逗号分隔；缺省全部")
    p.add_argument("--root", default=None, help="pack：产物根，缺省本机产物根")
    p.add_argument("--to", default=None, help="pack fetch：解到哪个产物根")
    p.add_argument("--force", action="store_true", help="pack fetch：目标已有该册产物也覆盖")
    p.add_argument("--note", default=None, help="pack push／promote：说明（谁、为什么）")
    p.add_argument("--change", default=None, help="pack push：改动名（ASCII），接在自动版本标签后，如 layout → cv0.4.7-c1-g2-layout")
    p.add_argument("--main", action="store_true",
                   help="pack push：存完顺手标成该册 main（正式结果；只收正式版 cv 出的包，见 --why）")
    p.add_argument("--why", default=None,
                   help="pack promote／push --main：包不是正式版 cv 出的（dev、rc、任意提交），也要标 main 时的理由，记进指针；存包时查出不纯的包也记进指针")
    p.add_argument("--report", default=None, help="pack push：这次 diff 的报告目录（含 report.md），抄进实验记录")
    p.add_argument("--summary", default=None,
                   help="pack push：实验记录开头的摘要（目的、改了什么、怎么跑、结论）；@文件 读文件")
    p.add_argument("--no-purity", action="store_true",
                   help="pack push：不查纯净性（混版本、图源，见 ops/pack_purity）")
    p.add_argument("--no-record", action="store_true",
                   help="pack push：不在工作区仓 experiments/<册>/<标签>.md 写实验记录（试存、测试用）")


def cmd_products_entry(args) -> None:
    """位置参数整理：diff <册>；exclusions <册>；pack <push|fetch|list> [<册>]。"""
    pos = list(args.pos or [])
    if args.action in ("diff", "exclusions"):
        if len(pos) != 1:
            print(f"✗ 用法：guji products {args.action} <册> --a <产物根> [--b …]", file=sys.stderr)
            sys.exit(2)
        args.book = pos[0]
        if not args.a:
            print(f"✗ {args.action} 要 --a（前一份产物根，如 guji snapshot make 出的目录、产物包取回的目录）", file=sys.stderr)
            sys.exit(2)
    else:
        if not pos or pos[0] not in ("push", "fetch", "list", "promote", "push-index", "fetch-index"):
            print("✗ 用法：guji products pack push|fetch|list|promote [<册>]｜push-index｜fetch-index", file=sys.stderr)
            sys.exit(2)
        args.pack_action, args.book = pos[0], (pos[1] if len(pos) > 1 else None)
    cmd_products(args)
