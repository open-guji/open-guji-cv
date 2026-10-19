"""`guji products`：产物前后对比、产物包（存取 R2）。不跑 Step，不进任何 Step 的 `code_deps`。

    guji products diff <册> --a <产物根> [--b <产物根>] [--pages …] [--out 目录] [--images N] -w <工作区>
    guji products pack  push <册> [--label 名] [--steps a,b] -w <工作区>     # 本机产物打包存 R2
    guji products pack  fetch <册> [--label 名] [--to 产物根] -w <工作区>    # 取回，缺省落在本机产物根
    guji products pack  list [<册>] -w <工作区>
    guji products pack  push-index | fetch-index                           # 生僻字 embedding 索引（models/*/emb_*.npz）

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


def cmd_pack(args) -> None:
    from .datastore import packs as PK
    if args.pack_action in ("push-index", "fetch-index"):
        fn = PK.push_rare_indexes if args.pack_action == "push-index" else PK.fetch_rare_indexes
        done = fn()
        print(("已存：" if args.pack_action == "push-index" else "已取：") + ("、".join(done) or "无（都已有）"))
        return
    if args.pack_action == "list":
        for row in PK.list_packs(args.book):
            print(f"{row['name']}\t{row.get('bytes', '')}\t{row.get('created', '')}\t{row.get('note', '')}")
        return
    if not args.book:
        print("✗ push/fetch 要给册", file=sys.stderr)
        sys.exit(2)
    if args.pack_action == "push":
        info = PK.push_products(args.book, _root(args.root), label=args.label,
                                steps=args.steps.split(",") if args.steps else None, note=args.note or "")
        print(f"已存：{info['name']}（{info['bytes'] / 1e6:.1f} MB，{info['files']} 个文件，{len(info['parts'])} 段）")
    else:
        info = PK.fetch_products(args.book, _root(args.to or args.root), label=args.label, force=args.force)
        print(f"已取：{info['name']} → {info['dest']}（{info['files']} 个文件）")


def cmd_products(args) -> None:
    _ws(args)
    if args.action == "diff":
        cmd_diff(args)
    else:
        cmd_pack(args)


def add_parser(sub) -> None:
    p = sub.add_parser("products", help="[v2] 产物前后对比（diff）、产物包存取 R2（pack）")
    p.add_argument("action", choices=["diff", "pack"])
    p.add_argument("pos", nargs="*", help="diff：<册>；pack：push|fetch|list [<册>]、push-index、fetch-index")
    p.add_argument("-w", "--workspace", default=None, help="工作区（册配置、原图）")
    p.add_argument("--a", default=None, help="diff：前（基线）产物根")
    p.add_argument("--b", default=None, help="diff：后产物根，缺省本机产物根")
    p.add_argument("--pages", default="all")
    p.add_argument("--out", default=None, help="diff：报告目录，缺省 ./diff-<册>")
    p.add_argument("--images", type=int, default=0, help="diff：前 N 个变了的列出看图页（要原图）")
    p.add_argument("--pipeline", default="keben_body_v2")
    p.add_argument("--label", default=None, help="pack：包名后缀，缺省 cv 版本号")
    p.add_argument("--steps", default=None, help="pack push：只打这几步，逗号分隔；缺省全部")
    p.add_argument("--root", default=None, help="pack：产物根，缺省本机产物根")
    p.add_argument("--to", default=None, help="pack fetch：解到哪个产物根")
    p.add_argument("--force", action="store_true", help="pack fetch：目标已有该册产物也覆盖")
    p.add_argument("--note", default=None, help="pack push：说明（谁、为什么）")


def cmd_products_entry(args) -> None:
    """位置参数整理：diff <册>；pack <push|fetch|list> [<册>]。"""
    pos = list(args.pos or [])
    if args.action == "diff":
        if len(pos) != 1:
            print("✗ 用法：guji products diff <册> --a <产物根> [--b …]", file=sys.stderr)
            sys.exit(2)
        args.book = pos[0]
        if not args.a:
            print("✗ diff 要 --a（前一份产物根，如 guji snapshot make 出的目录、产物包取回的目录）", file=sys.stderr)
            sys.exit(2)
    else:
        if not pos or pos[0] not in ("push", "fetch", "list", "push-index", "fetch-index"):
            print("✗ 用法：guji products pack push|fetch|list [<册>]｜push-index｜fetch-index", file=sys.stderr)
            sys.exit(2)
        args.pack_action, args.book = pos[0], (pos[1] if len(pos) > 1 else None)
    cmd_products(args)
