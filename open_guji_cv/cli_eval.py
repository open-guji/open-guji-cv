# -*- coding: utf-8 -*-
"""评测与看板命令：eval、check（判据与体检）、groups（字组）、cards（待审卡片）、progress（9.0 进度）、collate（9.3 对勘）。

拆分 P1（`doc/design/拆分-pipeline与manager.md`）从 `cli_v2` 原样搬出；经 `cli_v2.MANAGER_CLI_MODULES` 登记。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import cli_v2   # 共用辅助现取（测试 monkeypatch cli_v2 照样生效）


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
        # 不给 --pages 时以前悄悄按 dev_set 算：书级 dev_set 为空会退化成全书（凑巧对），
        # 非空就悄悄只算子集、且不报警（任务卡 #54 第1条）。改成不给就是 all，
        # 并且不论给不给都把「用的是哪个页集、实算了几页」打到 stderr——JSON 走 stdout，
        # 接 jq 的管道不受影响。
        pages_sel = args.pages if args.pages is not None else "all"
        pgs = load_book(args.book).resolve_pages(pages_sel)
        print(f"check quality: 页集={pages_sel!r}，共 {len(pgs)} 页", file=sys.stderr)
        cli_v2._out(quality(args.book, pages_sel, st))
    elif args.action == "rulers":
        from .eval.rulers import measure
        pages_sel = args.pages if args.pages is not None else "all"
        pgs = load_book(args.book).resolve_pages(pages_sel)
        print(f"check rulers: 页集={pages_sel!r}，共 {len(pgs)} 页", file=sys.stderr)
        detail = getattr(args, "detail", None)   # 程序化调用（测试、控制台）造的 Namespace 可能没有这个键
        res = measure(args.book, pgs, st, full=args.full or bool(detail))
        if detail:
            # `--detail R2c`：只印这把尺子的逐条页／列明细（#174），一行一条，方便 grep／排错例
            r = next((x for x in res["rulers"] if x["key"].lower() == detail.lower()), None)
            if r is None:
                raise SystemExit(f"没有尺子 {detail!r}；可选："
                                 + " ".join(x["key"] for x in res["rulers"]))
            print(f"{r['key']} {r['title']}：{r['num']}/{r['den']}（{r['value']}{r['unit']}）")
            for pg, e in r["by_page"].items():
                print(f"  p{pg}  {e['n']:3d} 条  列 {','.join(map(str, e['cols']))}")
            for d in r["detail"]:
                extra = "  ".join(f"{k}={v}" for k, v in d.items() if k not in ("page", "col"))
                print(f"p{d.get('page')}\tc{d.get('col')}\t{extra}")
            return
        cli_v2._out(res)
    elif args.action == "round":
        from .eval import round_check as rc
        # round/rate/throughput/ledger 不在任务卡#54第1条范围内，不给 --pages 时
        # 按老规矩仍然是 dev_set，不跟着 quality/rulers 一起改，避免动了别人没求的地方。
        pages_sel = args.pages if args.pages is not None else "dev_set"
        out = {"next": rc.next_batch(args.book)}
        if pages_sel:
            out.update(rc.check(args.book, load_book(args.book).resolve_pages(pages_sel)))
        cli_v2._out(out)
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
            cli_v2._out({"added": added})
        else:
            rows = [r for r in rate_history.history()
                    if not args.book or r.get("book") == args.book]
            rows.sort(key=lambda r: (r.get("book", ""), r.get("ts") or r.get("date", "")))
            cli_v2._out({"rows": rows})
    elif args.action == "throughput":
        from .eval import throughput as tp
        # 同 round：不在 #54 第1条范围内，不给 --pages 时维持老默认 dev_set（原样传字符串给
        # per_page/channel_breakdown 的 `resolve_pages(pages) if pages else _all_pages(...)`）。
        pages = None if args.all_pages else (args.pages if args.pages is not None else "dev_set")
        cli_v2._out(tp.full_report(args.book, pages, st))
    elif args.action == "ledger":
        # 字形库 × 工作区记录对账（H 人裁单写者任务书件 3）：只读，不改库。
        # `book` 过滤到这一本（一个工作区常挂好几本书，如四庫 vol01–vol10 共用一个 glyph.db）。
        from .clustering.glyph_ledger import crosscheck
        from .core.workspace import glyph_db_path
        res = crosscheck(glyph_db_path(), book=args.book, drift=args.drift)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                for x in res["findings"]:
                    f.write(json.dumps(x, ensure_ascii=False) + "\n")
        cli_v2._out({"book": args.book, "n_lib": res["n_lib"], "counts": res["counts"],
             "n_findings": len(res["findings"]), "drift_missing": res["drift_missing"],
             "out": args.out or None})


def cmd_groups(args) -> None:
    """字组：table 由注册表重生成 doc/字组/字组总表.md（--check 只比对）；status 一轮产物 × 人工数据 → 每组状态报告。"""
    if args.action == "table":
        from .groups import catalog
        raise SystemExit(catalog.main(["--check"] if args.check else []))
    from .eval import group_status
    if not args.prod or not args.out:
        raise SystemExit("groups status 要 --prod 与 --out")
    pj, pm = group_status.run([Path(p) for p in args.prod.split(",")], Path(args.out),
                              labels=Path(args.labels) if args.labels else None,
                              codepoints=Path(args.codepoints) if args.codepoints else None, tag=args.tag,
                              prev=Path(args.prev) if args.prev else None)
    print("写", pj, "\n写", pm)
    if args.progress:                  # 网站后台「文本整理 · 形近字」栏（Neon 正式库）
        import json
        from .eval import group_progress
        prev = json.loads(Path(args.prev).read_text(encoding="utf-8")) if args.prev else None
        rs = group_progress.rows(json.loads(pj.read_text(encoding="utf-8")), args.progress, prev)
        print("写后台", group_progress.write(rs), "行")


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
        cli_v2._out(cards(args.book, args.pages, args.limit, args.only, st))
    elif args.action == "jiazhu":
        from .review.jiazhu_cards import jiazhu_segments
        cli_v2._out(jiazhu_segments(args.book, args.pages, args.only, args.batch, st, EventLog()))
    elif args.action == "groups":
        from .review.group_view import group_view
        cli_v2._out(group_view(args.book, args.pages, args.edition, args.limit, st))
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
        cli_v2._out({"book": args.book, "n_r2s": n_all, "n_done": len(done),
              "n": len(cases), "cases": T.pick_cases(cases, args.limit, seed=args.seed)})


def cmd_collate(args) -> None:
    """Step9-9.3 对勘：字位流 × 整理本 → JSON 正本（＋可选 HTML ＋可选截图）。

    证人默认读书配置的 `references:`，没配就退回单证人（光盘版）。
    **不进管线**：跨页跨册汇总，不属于任何一页，同 Step8（见 `report/__init__.py`）。

    `--strips`：生成截条图（`report/strips.py`），写在 `<out 同目录>/strips/<证人>/`。
    离线交付包配 `--console ""`：深链自动退到包内的静态截图，不依赖正在跑的控制台
    （见 `report/html.py` 模块头「分层 + 截条图」）——**把 JSON/HTML 与 `strips/`
    目录一起打包**才是完整的离线交付物，单拷 HTML 不带 `strips/` 目录，图会显示不出来。
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
    if args.strips:
        from .report.strips import write_diff_strips, write_variant_thumbs
        n_strip = write_diff_strips(doc, out.parent, radius=args.strip_radius,
                                    h=args.strip_h, limit=args.limit_strips)
        n_thumb = write_variant_thumbs(doc, out.parent)
        print(f"截图 → {out.parent / 'strips'}"
              f"（差异 {sum(n_strip.values())} 条，异体例图 {sum(n_thumb.values())} 张）")
        write_report(doc, out)   # 截图路径写回了 doc["diffs"][*]["strip"]，JSON 正本要跟着更新
    if not args.no_html:
        h = write_html(doc, out.with_suffix(".html"), args.console)
        print(f"HTML → {h}  ({h.stat().st_size / 1e6:.1f} MB)")
    for label, s in doc["summary"]["by_witness"].items():
        c = s["counts"]
        print(f"  {label}：一致 {s['n_equal']:,} · "
              + " · ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))
              + (f" · 列 {s['cols']}" if s["cols"] else ""))
    un = {k: len(v) for k, v in doc["unanchored"].items()}
    print(f"  未锚定页：{un}" + (f" · 数据版本不同步 {len(doc['stale'])} 处" if doc["stale"] else "")
          + (f" · 崩溃页 {len(doc['page_errors'])} 处：{[e['page'] for e in doc['page_errors']]}"
             if doc.get("page_errors") else ""))


def cmd_progress(args) -> None:
    """Step9-9.0 进度复查：页范围内每页还挂着哪些待办（看板，不是闸）。口径见 `report/progress.py`。"""
    from .core.book import load_book
    from .report.progress import format_table, page_progress
    bk = load_book(args.book)
    cli_v2._guard_cv_version(bk, warn_only=True)
    doc = page_progress(args.book, bk.resolve_pages(args.pages))
    if args.json:
        cli_v2._out(doc)
        return
    print(format_table(doc))


def add_parser(sub) -> None:
    p = sub.add_parser("eval", help="[v2] 评测：list | run")
    p.add_argument("action", choices=["list", "run"])
    p.add_argument("evals", nargs="*", help="评测器 id；留空跑全部轻量的")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="有跑不起来的就以 1 退出")
    p.add_argument("--from-raw", action="store_true",
                   help="缺产物时从原图现跑 Step1-3 补齐（云端 clone 无 products/ 时用，"
                        "同 seg_harness.py 的同名开关）")
    p = sub.add_parser("check", help="[v2] 判据与体检：quality | rulers | round | rate | throughput | ledger")
    p.add_argument("action", choices=["quality", "rulers", "round", "rate", "throughput", "ledger"])
    p.add_argument("book", nargs="?", default="vol01")
    p.add_argument("--pages", default=None,
                   help="不给：quality/rulers 默认 all，round/rate/throughput/ledger 仍默认 "
                        "dev_set（历史行为不变）。也可显式给 dev_set | all | 3-6,9 | 命名集")
    p.add_argument("--snapshot", action="store_true", help="rate：记一行台账（默认只读）")
    p.add_argument("--note", default="", help="rate --snapshot 的说明")
    p.add_argument("--all-pages", action="store_true",
                   help="throughput：统计全书已有产物的页，不只 --pages（吞吐量/通道占比默认整册）")
    p.add_argument("--full", action="store_true",
                   help="rulers：detail 不截断（默认只带前 20 条，做全量错例统计要这个）")
    p.add_argument("--detail", default=None, metavar="RULER",
                   help="rulers：只印这把尺子（如 R2c）的全量页／列明细，一行一条（JSON 里另有 by_page 汇总）")
    p.add_argument("--drift", action="store_true",
                   help="ledger：另外核对库里的图与现在的字块图还像不像（较慢，逐条读图比对）")
    p.add_argument("--out", default="",
                   help="ledger：发现明细另存 jsonl（不给就只在 --json/文字里出汇总数与 counts）")
    p = sub.add_parser("groups", help="[v2] 字组：table 重生成字组总表 | status 每组状态报告（只读）")
    p.add_argument("action", choices=["table", "status"])
    p.add_argument("--check", action="store_true", help="table：只比对总表与注册表，不写")
    p.add_argument("--prod", default="", help="status：产物根，逗号分隔（下面是 <册>/seed_admit/p*.json）")
    p.add_argument("--labels", default="", help="status：dataset char-groups/labels/unified.jsonl")
    p.add_argument("--codepoints", default="", help="status：工作区 config/codepoints.yaml（核对人裁时先归一码位）")
    p.add_argument("--out", default="", help="status：输出目录（dataset char-groups/status）")
    p.add_argument("--tag", default="", help="status：这一轮产物的标签，进文件名")
    p.add_argument("--prev", default="", help="status：上一份报告的 json，表里写送审增减")
    p.add_argument("--progress", default="", metavar="BOOK_ID",
                   help="status：顺手写网站后台「文本整理」yiti／xingjin 两栏（给套书 id，如 96mid1ogzk；写 Neon 正式库）")
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
    p = sub.add_parser("collate", help="[v2] Step9-9.3 与整理本对勘（出 JSON + HTML）")
    p.add_argument("book")
    p.add_argument("--pages", default="", help="页表达式；空 = 全部有 Step7 产物的页")
    p.add_argument("--out", default=None,
                   help="JSON 落点（默认 <workspace>/reports/<book>/collation_<时间>.json）")
    p.add_argument("--console", default="http://127.0.0.1:8640",
                   help="HTML 里深链指向的控制台地址；空串则不出链接（离线交付包配 --strips 用）")
    p.add_argument("--no-html", action="store_true", help="只出 JSON")
    p.add_argument("--strips", action="store_true",
                   help="生成截条图（report/strips.py），写在 <out 同目录>/strips/；"
                        "离线交付包配 --console \"\" 让深链落到包内截图，不依赖控制台")
    p.add_argument("--strip-radius", type=int, default=2, help="截条图目标格前后各几格（横排）")
    p.add_argument("--strip-h", type=int, default=44, help="截条图每格缩放到多高（px）")
    p.add_argument("--limit-strips", type=int, default=1500, help="--strips 最多出多少条截图（控体积）")
    p = sub.add_parser("progress", help="[v2] Step9-9.0 进度复查：页范围内每页还挂着哪些待办（看板，不拦 9.1/9.2）")
    p.add_argument("book")
    p.add_argument("--pages", default="all", help="页表达式；默认全书")
    p.add_argument("--json", action="store_true", help="出 JSON（与控制台 /api/step9/progress 同形）")


#: 并进 `guji` 的子命令（同插件接口 `guji.commands`）
COMMANDS = {
    "eval": (add_parser, cmd_eval),
    "check": (add_parser, cmd_check),
    "groups": (add_parser, cmd_groups),
    "cards": (add_parser, cmd_cards),
    "progress": (add_parser, cmd_progress),
    "collate": (add_parser, cmd_collate),
}
