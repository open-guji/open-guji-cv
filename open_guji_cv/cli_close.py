# -*- coding: utf-8 -*-
"""定版检查命令：close-check、exit-check、audit、char-diff。

拆分 P1（`doc/design/拆分-pipeline与manager.md`）从 `cli_v2` 原样搬出；经 `cli_v2.MANAGER_CLI_MODULES` 登记。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import cli_v2   # 共用辅助现取（测试 monkeypatch cli_v2 照样生效）
from .ops import prep


def cmd_close_check(args) -> None:
    """一册书交付前逐项体检（只读）。标准见 doc/runbook/整理一册书.md 第五节。"""
    from .core.workspace import workspace_root, reports_root
    from .ops import close_check as CC
    eng = cli_v2._engine(args.book, args.pipeline, quiet=True)
    pages = eng.book.resolve_pages(args.pages)
    res = CC.run(eng, workspace_root() or Path.cwd(), pages,
                 export_dir=Path(args.export_dir) if args.export_dir else None,
                 chapter=args.chapter, notes=Path(args.notes) if args.notes else None,
                 reports=reports_root(), tier=getattr(args, "tier", "final"),
                 pending=getattr(args, "pending", None),
                 strict_cv=getattr(args, "strict_cv", False))
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        CC.print_report(res)
        prep.print_unpacked(eng.book.id, eng.store)
    sys.exit(0 if res["machine_ok"] else 1)


def cmd_exit_check(args) -> None:
    """一册文本出 1.0 时的出口动作逐项核（只读；M10 G8，GUJI-685）。见 `ops/exit_check.py` 模块头。"""
    from .ops import exit_check as EC
    from .core.volume_id import chapter_of
    chapter = chapter_of(args.book, args.chapter)
    if not chapter:
        sys.exit("推不出章号：册 yaml 写上 volume，或给 --chapter NNN")
    from .core.book import load_book
    b = load_book(args.book)
    frozen = None
    if args.frozen_char:
        from .ops import text_diff as TD
        frozen = TD.load(args.frozen_char)
    res = EC.run(Path(args.text_dir), chapter, b.freeze, b.cv_version,
                 repo=Path(args.repo) if args.repo else None, frozen_char=frozen)
    if args.diff_out and res.get("diff") is not None:
        from .ops import text_diff as TD
        TD.write_tsv(res["diff"], json.loads((Path(args.text_dir) / f"{chapter}.char.json").read_text(encoding="utf-8")),
                     frozen, Path(args.diff_out))
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        EC.print_report(res)
    sys.exit(0 if res["ok"] else 1)


def cmd_char_diff(args) -> None:
    """`guji char-diff <文本 char.json> <冻结导出 char.json>`：逐格比（只读；1.0 标准 G2）。见 `ops/text_diff.py`。"""
    from .ops import text_diff as TD
    text, frozen = TD.load(args.text), TD.load(args.frozen)
    res = TD.diff(text, frozen)
    if args.out:
        TD.write_tsv(res, text, frozen, Path(args.out))
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"{res['n']} 处差异：{TD.summary(res)}" + (f"（明细 {args.out}）" if args.out and res["n"] else ""))
    sys.exit(0 if not res["n"] else 1)


def cmd_audit(args) -> None:
    """`guji audit admitted|jys <册>`：定版检查清单（只读；runbook S8、S10）。"""
    from .core.workspace import reports_root
    from .ops import audit as A
    eng = cli_v2._engine(args.book, args.pipeline, quiet=True)
    book = eng.book.id
    out_dir = Path(args.out) if args.out else reports_root() / book
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.action == "admitted":
        col = Path(args.collation) if args.collation else A.latest_collation(reports_root() / book)
        if not col or not col.exists():
            print("✗ 没有对勘 JSON：先跑 `guji collate <册> --console \"\" -w <工作区>`", file=sys.stderr); sys.exit(2)
        res = A.admitted(col)
        md = out_dir / f"{book}.放行错穷举.md"
        md.write_text(A.admitted_md(res), encoding="utf-8")
        (out_dir / f"{book}.放行错穷举.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{book} 放行错穷举：{res['n']} 格（认字差异 {res['n_non_systematic']} 要逐格看图；"
              f"异体 {res['n_variant']}；系统性 {res['n_systematic']}）→ {md}")
    elif args.action == "sheet":
        from .review.cards import cards
        from .review.verdict_view import closure_gaps, closure_mismatches
        pages = eng.book.resolve_pages("all")
        q = cards(book, "all", limit=1, only="review", store=eng.store, gate_cut=False,
                  skip_decided=True, cls="*").get("class_counts") or {}
        import re
        from .feedback.vision import vision_checks, vision_pending
        chk = vision_checks(book)
        vis = [{**v, "note": (chk.get(v["id"]) or {}).get("note")} for v in vision_pending(book, pages, eng.store)]
        uns = [{"id": k, "shown": c.get("shown"), "note": c.get("note")} for k, c in sorted(chk.items(), key=lambda kv: [int(x) for x in re.findall(r"\d+", kv[0])])
               if c.get("v") == "unsure"]
        md = out_dir / f"{book}.请审单.md"
        md.write_text(A.review_sheet(book, q, closure_gaps(book, pages, eng.store),
                                     closure_mismatches(book, pages, eng.store), vision=vis, unsure=uns),
                      encoding="utf-8")
        print(f"{book} 请审单 → {md}（第 4 节看图判错 {len(vis)} 格、第 5 节看不清 {len(uns)} 格，已按看图结论填好）")
    elif args.action == "changes":
        # 放行变化必看图（M9 D5，GUJI-664）：对上一基线的产物根，列出新放行／放行字变了的格
        from .core.workspace import products_root
        if not args.base:
            print("✗ changes 要给 --base <上一基线的产物根>", file=sys.stderr); sys.exit(2)
        res = A.admit_changes(Path(args.base), products_root(), book)
        (out_dir / f"{book}.放行变化.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"{book}.放行变化.md").write_text(A.admit_changes_md(res), encoding="utf-8")
        print(f"{book} 放行变化：{res['n']} 格（字变了 {res['n_changed']}，新放行 {res['n_new']}）→ {out_dir / (book + '.放行变化.md')}")
    elif args.action == "reasons":
        # 待审格主成因码（M9 D6，GUJI-668）：按码派给切分、M7、字形库、语料（review/causes.py）
        from collections import Counter
        from .core.workspace import products_root
        from .review.causes import book_causes, causes_md
        res = book_causes(products_root(), book)
        (out_dir / f"{book}.reasons.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"{book}.reasons.md").write_text(causes_md(book, res), encoding="utf-8")
        cnt = Counter(v["cause"] for v in res.values())
        print(f"{book} 待审 {len(res)} 格成因：" + "、".join(f"{k} {v}" for k, v in cnt.most_common())
              + f" → {out_dir / (book + '.reasons.md')}")
    elif args.action == "alt":
        # 出待审单前给每张卡算好「相似字」（review/alt_cands.py；doc/research/人审找字-…md）：
        # 近似字的异体族（hanzi 库；本机字统网缓存照并）按字块图排序，挂成卡上 `alt`，
        # 再交 ai-team pending_list.py --cards 并进 pending.json（proof_fields 原样带出）。
        from .clustering.variant_sources import ZiCache
        from .review.alt_cands import ALT_K, alt_for_cards, attach
        if args.cards:
            doc = json.loads(Path(args.cards).read_text(encoding="utf-8"))
            cs = doc["cards"] if isinstance(doc, dict) else doc
        else:
            from .review.cards import cards
            cs = cards(book, "all", limit=10 ** 7, only="all", store=eng.store, gate_cut=False,
                       skip_decided=False, cls="*")["cards"]
        todo = [c for c in cs if not c.get("admit")]
        if getattr(args, "extra", None):
            # 复审格（republish prep --recheck）多已放行或人裁过，也要相似字，网站卡片才和别的格一样能点选
            want = {ln.split("\t")[0].strip() for ln in Path(args.extra).read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")}
            want = {w if w.startswith(f"{book}:") else f"{book}:{w}" for w in want}
            todo += [c for c in cs if c.get("admit") and c.get("id") in want]
        if args.reviewed:
            # 人裁过的格也算（它们多已放行、不在待审里）：给 alt-eval 拿历史人裁量真实命中，不进待审单
            from .feedback.lookup import human_chars
            done = human_chars(book)
            todo += [c for c in cs if c.get("admit") and c.get("id") in done]
        zi = ZiCache(Path(args.zi_cache) if args.zi_cache else None, fetch=args.fetch_zi)
        alt = alt_for_cards(book, todo, k=args.k or ALT_K, zi=zi, ctx=eng.ctx, log=lambda m: print(m, file=sys.stderr))
        n = attach(cs, alt)
        dst = Path(args.cards_out) if args.cards_out else out_dir / f"{book}.cards.alt.json"
        dst.write_text(json.dumps(cs, ensure_ascii=False), encoding="utf-8")
        print(f"{book} 相似字：待审 {len(todo)} 格，出 alt {n} 格（字统网新取 {zi.n_fetched} 字）→ {dst}")
        if todo and not n:
            # 一格都没出多半是环境问题（缺 torch／checkpoint、取不到字块图），不能让下游照出一张没有相似字的单子
            print(f"✗ {book} 待审 {len(todo)} 格一格相似字都没出，见上面的原因", file=sys.stderr); sys.exit(1)
    elif args.action == "alt-eval":
        # 相似字效果：人裁过之后，拿人定的字回头看 alt 里排第几（doc/research/人审找字-…md §6）
        from .feedback.lookup import human_chars
        from .review.alt_cands import alt_eval
        src = Path(args.cards) if args.cards else out_dir / f"{book}.cards.alt.json"
        if not src.exists():
            print(f"✗ 没有 {src}：先跑 `guji audit alt {book} -w <工作区>`", file=sys.stderr); sys.exit(2)
        doc = json.loads(src.read_text(encoding="utf-8"))
        res = alt_eval(doc["cards"] if isinstance(doc, dict) else doc, human_chars(book))
        print(json.dumps(res, ensure_ascii=False, indent=1))
        for name, label in (("all", "全部"), ("hard", "难格（人定的字不在卡上原有候选里）")):
            t = res[name]
            if t["n"]:
                print(f"{label} {t['n']} 格：第 1 名 {t['top1']}，前 5 {t['top5']}，前 10 {t['top10']}"
                      f"（{t['top10'] / t['n']:.0%}），在相似字里的平均名次 {t['mean_rank_when_hit']}", file=sys.stderr)
    elif args.action == "count":
        from .core.workspace import feedback_root
        if not args.since:
            print("✗ count 要 --since（请审单发出的时间）", file=sys.stderr); sys.exit(2)
        exp = None
        if args.expect:
            exp = [ln.strip().strip("`") for ln in Path(args.expect).read_text(encoding="utf-8").splitlines() if ln.strip()]
        res = A.review_count(feedback_root() / "events", book, args.since, exp)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        bad = res["no_anchor"] or res.get("missing")
        print(f"\n{book} 自 {args.since}：{res['n_events']} 条事件、{res['n_cells']} 个字位；"
              f"同格多次 {len(res['repeated'])}；没带锚点 {len(res['no_anchor'])}"
              + (f"；漏审 {len(res['missing'])}、单外 {len(res['extra'])}" if exp is not None else ""))
        sys.exit(1 if bad else 0)
    else:
        if not args.export_dir:
            print("✗ jys 要 --export-dir（先跑 `guji export format <册>`）", file=sys.stderr); sys.exit(2)
        res = A.jys(Path(args.export_dir), args.chapter, book=book)
        md = out_dir / f"{book}.己已巳.md"
        md.write_text(A.jys_md(res, book), encoding="utf-8")
        (out_dir / f"{book}.己已巳.muse_input.jsonl").write_text(A.jys_muse_jsonl(res), encoding="utf-8")
        print(f"{book} 己/已/巳：{res['n']} 格 {res['by_char']}，人裁过 {res['n_human']} → {md}")


def add_parser(sub) -> None:
    p = sub.add_parser("close-check",
                       help="[v2] 一册书交付前逐项体检（只读）：新鲜、缓存、待审、收尾闸、真源已提交、lines/pages 自洽、Step9")
    p.add_argument("book")
    p.add_argument("--pipeline", default=cli_v2.DEFAULT_PIPELINE)
    p.add_argument("--pages", default="all")
    p.add_argument("--export-dir", default=None, help="export_guji_format 的输出目录（查 lines.md 与 pages.json）")
    p.add_argument("--chapter", default=None, help="章号 NNN；目录里有多章时用")
    p.add_argument("--notes", default=None, help="overview 里本册的记录目录（查避諱表、收尾记录）")
    p.add_argument("--tier", choices=["final", "rough"], default="final",
                   help="final（缺省，终校档）：待审必须清零；rough（粗校档）：第 2 项待审只报数、不计"
                        "（出 0.1.0 用；整理设计 R5）")
    p.add_argument("--strict-cv", action="store_true", dest="strict_cv",
                   help="1a 用旧口径：代码／版本变了也算过期（缺省只因代码变、产物记着正式版 cv_version 的页算新鲜）")
    p.add_argument("--pending", nargs="?", const="", default=None,
                   help="公众人审页的待审单，第 2c 项认它上面的格为「□ 有去向」。不给或只写 --pending：读中心库"
                        "本册本章的 feedback/lists/proofing/<书>/<章>.pending.json（数据目录里，先 guji db sync）；"
                        "也可给册（vol04）、章号（004）、<书>/<章> 或文件路径。book-text 的旧路径已不用（10-20 迁中心库）")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("exit-check",
                       help="[v2] 一册文本出 1.0 的出口动作逐项核（只读）：proofing、review、decision、阙文、冻结登记（M10 G8）")
    p.add_argument("book")
    p.add_argument("--text-dir", required=True, help="book-text 本书 default 目录（含 index.json、NNN.char.json）")
    p.add_argument("--chapter", default=None, help="章号 NNN；缺省按 volNN 推")
    p.add_argument("--repo", default=None, help="查 tag 用的 cv 仓目录；缺省本包所在仓")
    p.add_argument("--frozen-char", default=None, dest="frozen_char",
                   help="冻结快照导出的 NNN.char.json；给了就核 E9（发布文本＝冻结导出）")
    p.add_argument("--diff-out", default=None, dest="diff_out", help="E9 的逐格差异写成 tsv")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("char-diff", help="[v2] 两份 char.json 逐格比：发布文本 vs 冻结导出（只读，1.0 标准 G2）")
    p.add_argument("text", help="发布（候选）文本的 NNN.char.json")
    p.add_argument("frozen", help="冻结快照导出的 NNN.char.json")
    p.add_argument("--out", default=None, help="差异明细 tsv")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("audit", help="[v2] 定版检查清单：admitted = 放行错穷举；jys = 己/已/巳 全族；"
                                     "count = 用户审完当场核数；sheet = 生成请审单（只读）；"
                                     "alt = 给待审卡算好相似字（并进待审单）；alt-eval = 人裁后量相似字命中")
    p.add_argument("action", choices=["admitted", "jys", "count", "sheet", "reasons", "changes", "alt", "alt-eval"])
    p.add_argument("--base", default=None, help="changes：上一基线的产物根（与它比放行变化）")
    p.add_argument("--since", default=None, help="count：只数这个时间之后的事件（ISO，如 2026-10-06T08:00）")
    p.add_argument("--expect", default=None, help="count：请审单字位清单文件，一行一个，报漏审与单外多审")
    p.add_argument("book")
    p.add_argument("--pipeline", default=cli_v2.DEFAULT_PIPELINE)
    p.add_argument("--collation", default=None, help="admitted：对勘 JSON，缺省 reports/<册>/ 下最新一份")
    p.add_argument("--export-dir", default=None, help="jys：guji export format 的输出目录")
    p.add_argument("--chapter", default=None)
    p.add_argument("--out", default=None, help="输出目录；缺省 reports/<册>/")
    p.add_argument("--cards", default=None, help="alt：卡片列表 JSON（cards(cls='*') 的输出），缺省现算全册；"
                                                 "alt-eval：带 alt 的卡片 JSON，缺省 reports/<册>/<册>.cards.alt.json")
    p.add_argument("--cards-out", default=None, help="alt：带 alt 的卡片 JSON 写到这里；缺省 reports/<册>/<册>.cards.alt.json")
    p.add_argument("--k", type=int, default=0, help="alt：每格最多几个相似字（缺省 30）")
    p.add_argument("--fetch-zi", action="store_true",
                   help="alt：字统网缓存里没有的近似字去取一次（≥3 秒一次，取到写缓存）；缺省只读缓存")
    p.add_argument("--reviewed", action="store_true",
                   help="alt：人裁过、已放行的格也算相似字（给 alt-eval 用历史人裁量命中；pending_list 只取待审格，不受影响）")
    p.add_argument("--zi-cache", default=None, help="alt：字统网缓存目录，缺省 $GUJI_ZITOOLS_CACHE 或 $GUJI_DATA_HOME/_shared/zitools")
    p.add_argument("--extra", default=None,
                   help="alt：另外也要算相似字的格（复审清单，一行一格，第一列格号，可带「册:」前缀）：已放行的复审格也挂上 alt")


#: 并进 `guji` 的子命令（同插件接口 `guji.commands`）
COMMANDS = {
    "close-check": (add_parser, cmd_close_check),
    "exit-check": (add_parser, cmd_exit_check),
    "audit": (add_parser, cmd_audit),
    "char-diff": (add_parser, cmd_char_diff),
}
