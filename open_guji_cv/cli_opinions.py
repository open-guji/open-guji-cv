"""`guji opinions`：意见池（M11 第一阶段，设计 `doc/design/M11-分块-第一阶段最小闭环.md`）。不跑 Step，不进任何 Step 的 `code_deps`。

    guji opinions ingest  --book B --ws W [--remote] [--dry-run] [--live-vols 001,002] [--from-dir D]   # 三源入池，幂等
    guji opinions list    --book B --ws W [--status S] [--vol V]
    guji opinions show    <id> --book B --ws W
    guji opinions versions --book B --ws W --book-text <检出>      # 从 book-text CHANGES 生成 text_versions.json
    guji opinions locate  <id> --book B --ws W [--book-text <检出>]
    guji opinions normalize <fb_id> --into <json> --book B --ws W  # 会话把自由文字规整成一条或多条
    guji opinions pack    <id…> --out <目录> --book B --ws W [--book-text <检出>]   # 证据包＋sheet.png／sheet.md
    guji opinions triage  <id> --verdict … --confidence … --public … [--revision JSON] --judge 名 --book B --ws W
    guji opinions to-user --out <目录>／decide --from <裁决 JSON>
    guji opinions revise  --book B --vol 002 --book-text <检出> [--dry-run] --pr N
    guji opinions reply-drafts --book B --ws W

意见池在哪：缺省是本机数据目录 `$GUJI_DATA_HOME/<分支>/<工作区>/feedback/lists/opinions/<书>/`（`guji db sync` 推进中心库）；
`--root D` 用 `D/<书>/`（试跑、不进中心库的判定）；`--remote` 直接经 Worker 读写中心库（令牌取 `--token-env` 指的环境变量，不打印）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_BOOK_TEXT = os.environ.get("GUJI_BOOK_TEXT")


def _store(args, by: str | None = None):
    from .opinions.store import open_store
    return open_store(args.book, ws=args.ws, root=args.root, remote=args.remote, token_env=args.token_env,
                      branch=args.branch, by=by or getattr(args, "by", None) or "tool")


def _print(s: str = "") -> None:
    sys.stdout.write(s + "\n")


# ---------------- ingest ----------------

def cmd_ingest(args) -> None:
    from .opinions import ingest as I
    src = I.Sources()
    notes = []
    if args.from_dir:
        d = I.read_dir(Path(args.from_dir))
        src.fixes += d.fixes
        src.cellreview.update(d.cellreview)
        src.public_fixes += d.public_fixes
        src.feedback += d.feedback
        src.hidden |= d.hidden
        notes.append(f"离线目录 {args.from_dir}")
    if not args.no_central:
        from .datastore.client import WorkerSource
        tok = os.environ.get(args.web_token_env or args.token_env)
        if not tok:
            raise SystemExit(f"读中心库网站意见要环境变量 {args.web_token_env or args.token_env}（或 --no-central）")
        c = I.read_central_web(WorkerSource(token=tok, branch=args.branch), args.ws, args.book, args.branch)
        src.fixes += c.fixes
        src.cellreview.update(c.cellreview)
        src.hidden |= c.hidden
        notes += c.notes
    if args.live_vols:
        vols = [v.strip() for v in args.live_vols.split(",") if v.strip()]
        src.public_fixes += I.fetch_public_fixes(args.book, vols, args.site)
        notes.append(f"网站公开实时读 /api/fixes 章 {','.join(vols)}")
    if not args.no_feedback:
        src.feedback += I.fetch_public_feedback(args.site)
        notes.append(f"网站公开读 /api/feedback {len(src.feedback)} 条")
    st = _store(args, by=args.by)
    items = I.incoming(src, args.book)
    rep = I.ingest(st, items, by=args.by)
    for n in notes:
        _print("· " + n)
    _print(("[dry-run] 将入池：" if args.dry_run else "入池：") + st.backend.describe())
    for i in rep.added:
        tags = []
        if i in rep.forwarded:
            tags.append("转出")
        if any(i == d for d, _ in rep.dup):
            tags.append("重复→" + next(o for d, o in rep.dup if d == i))
        _print("  + " + I.describe(st.opinions[i]) + (f"  [{'；'.join(tags)}]" if tags else ""))
    for old, new in rep.superseded:
        _print(f"  ~ {old} 由 {new} 取代")
    _print(rep.summary())
    if args.dry_run:
        return
    st.touch("raw")
    res = st.save()
    _print(f"写入 {', '.join(res) or '（无改动）'}")


# ---------------- list / show ----------------

def cmd_list(args) -> None:
    from .opinions.ingest import describe, sort_key
    st = _store(args)
    stat = st.statuses()
    ops = sorted(st.opinions.values(), key=sort_key)
    n = 0
    for op in ops:
        if args.status and stat[op.id] not in args.status.split(","):
            continue
        if args.vol and op.vol != args.vol:
            continue
        if args.channel and op.channel != args.channel:
            continue
        n += 1
        _print(f"{stat[op.id]:<13} {describe(op)}")
    _print(f"共 {n} 条（池里 {len(ops)} 条；{st.backend.describe()}）")


def cmd_show(args) -> None:
    st = _store(args)
    op = st.get(args.id)
    _print(json.dumps(op.to_dict(), ensure_ascii=False, indent=1))
    _print(f"状态：{st.status(op.id)}")
    for e in st.events_of(op.id):
        _print(f"  {e.ts} {e.kind:<10} {e.by:<14} {json.dumps(e.data, ensure_ascii=False)[:300]}")


def cmd_schema(args) -> None:
    from .opinions.schema import json_schema
    _print(json.dumps(json_schema(), ensure_ascii=False, indent=1))


# ---------------- versions / locate ----------------

def _bt(args):
    from .opinions.textsrc import BookText, default_book_text
    return BookText(args.book, default_book_text(getattr(args, "book_text", None)))


def cmd_versions(args) -> None:
    from .opinions.textsrc import parse_changes
    bt = _bt(args)
    tv = parse_changes(bt.changes(), args.book)
    for vol in sorted(tv):
        for r in tv[vol]:
            miss = [k for k in ("rev", "snapshot", "cv_version") if not r.get(k)]
            _print(f"{vol} {r['text_version']:<7} {r['date']} {r['pr'] or '—':<6} {r['kind']:<9} "
                   f"rev={r['rev'] or '—'} cv={r['cv_version'] or r['cv_commit'] or '—'} 快照={r['snapshot'] or '—'}"
                   + (f"  缺 {','.join(miss)}" if miss else ""))
    _print(f"{sum(len(v) for v in tv.values())} 个文本版本，{len(tv)} 章（{bt.describe()}）")
    if args.dry_run:
        return
    st = _store(args, by="versions")
    if st.set_text_versions(tv):
        st.save(only=["versions"])
        _print(f"写入 text_versions.json（{st.backend.describe()}）")
    else:
        _print("text_versions.json 没变")


def cmd_locate(args) -> None:
    from .opinions.textsrc import locate
    st = _store(args)
    op = st.get(args.id)
    bt = _bt(args) if (args.book_text or os.environ.get("GUJI_BOOK_TEXT") or args.github) else None
    r = locate(op, st.text_versions, bt)
    if args.json:
        _print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    _print(f"{op.id}：第 {r['vol']} 章 {r['cell']}{('–' + r['end']) if r['end'] and r['end'] != r['cell'] else ''}"
           f"（提时 {r['asked_at'] or '—'}）")
    _print(f"  当前格号 {r['cell']}，当前 text_version {r['text_version'] or '—'}"
           + (f"，其间升过 {', '.join(r['since'])}" if r["since"] else "，其间没升过版本"))
    _print(f"  校验字 {r['check'] or '—'}，现文 {r['current_text'] if r['current_text'] is not None else '—'}"
           + (f"；⚠ {r['drift']}" if r["drift"] else ""))
    _print(f"  rev {r['rev'] or '缺'}；cv {r['cv_version'] or r['cv_commit'] or '缺'}；快照 {r['snapshot'] or '缺'}")
    if r.get("cord_producer"):
        _print(f"  cord 该页 producers.cv：{json.dumps(r['cord_producer'], ensure_ascii=False)}")
    if r["missing"]:
        _print(f"  缺：{'、'.join(r['missing'])}")


# ---------------- pack ----------------

def cmd_pack(args) -> None:
    from .opinions import evidence as E
    from .opinions.textsrc import locate
    st = _store(args)
    bt = _bt(args)
    fetch = E.ImageFetcher(Path(args.cache) if args.cache else None)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    evs = []
    texts: dict = {}
    for i in args.ids:
        op = st.get(i)
        if op.vol not in texts:
            texts[op.vol] = (bt.char(op.vol), bt.cord(op.vol))
        char, cord = texts[op.vol]
        if char is None or cord is None:
            raise SystemExit(f"book-text（{bt.describe()}）里没有第 {op.vol} 章的 char／cord")
        ev = E.build(op, char, cord, fetch, out, window=args.window, others=E.same_cell_others(st, op),
                     located=locate(op, st.text_versions, bt))
        evs.append(ev)
        nx = ev.get("next_after_target")
        _print(f"{op.id}：{ev['vol']} {'、'.join(ev['target'])}  上下文 {ev['context']}  "
               f"下一格 {nx['label'] + ('（' + nx['note'] + '）' if nx.get('note') else '') if nx else '—'}")
    png, md = E.sheet(evs, out)
    _print(f"证据包 {len(evs)} 条 → {out}（{png.name}、{md.name}）")


# ---------------- 注册 ----------------

def _common(p, store: bool = True) -> None:
    p.add_argument("--book", required=True, help="book-text 书 id，如 96mid1ogzk")
    if store:
        p.add_argument("--ws", default=os.environ.get("GUJI_OPINIONS_WS"),
                       help="中心库工作区 id（数据目录、--remote 用；环境变量 GUJI_OPINIONS_WS 可给缺省）")
        p.add_argument("--root", default=None, help="本地意见池根目录，文件在 <root>/<书>/（不给用数据目录）")
        p.add_argument("--remote", action="store_true", help="直接经 Worker 读写中心库（不经数据目录）")
        p.add_argument("--token-env", default="GUJI_DATA_TOKEN", help="--remote 的令牌在哪个环境变量（缺省 GUJI_DATA_TOKEN）")
        p.add_argument("--branch", default="main")


def add_parser(sub) -> None:
    op = sub.add_parser("opinions", help="[M11] 意见池：入池、证据包、初判、修订 book-text 冻结册")
    s = op.add_subparsers(dest="op_cmd", metavar="<子命令>")

    p = s.add_parser("ingest", help="三源入池（fixes.jsonl／<rev>.jsonl／公开读），幂等")
    _common(p)
    p.add_argument("--dry-run", action="store_true", help="只打印将入池的条目，不写")
    p.add_argument("--from-dir", default=None, help="离线来源目录（fixes.jsonl、<rev>.jsonl、api-fixes*.json、api-feedback*.json）")
    p.add_argument("--no-central", action="store_true", help="不读中心库 feedback/lists/web/<书>/")
    p.add_argument("--web-token-env", default=None, help="读中心库网站意见用的令牌环境变量（缺省同 --token-env）")
    p.add_argument("--live-vols", default="", help="另从网站公开实时读 /api/fixes 取这些章（逗号分隔，如 001,002,003）")
    p.add_argument("--no-feedback", action="store_true", help="不读网站公开 /api/feedback")
    p.add_argument("--site", default="https://www.openguji.com")
    p.add_argument("--by", default="ingest", help="log 里记谁入的池")
    p.set_defaults(func=cmd_ingest)

    p = s.add_parser("list", help="列意见与状态")
    _common(p)
    p.add_argument("--status", default="", help="只列这些状态（逗号分隔）")
    p.add_argument("--vol", default="")
    p.add_argument("--channel", default="")
    p.set_defaults(func=cmd_list)

    p = s.add_parser("show", help="看一条意见和它的 log")
    p.add_argument("id")
    _common(p)
    p.set_defaults(func=cmd_show)

    p = s.add_parser("versions", help="从 book-text CHANGES.md 生成 text_versions.json")
    _common(p)
    p.add_argument("--book-text", default=None, help="book-text 本地检出（缺省环境变量 GUJI_BOOK_TEXT，再缺走 GitHub raw）")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_versions)

    p = s.add_parser("locate", help="格号＋版本 → 当前格号、text_version、rev、快照")
    p.add_argument("id")
    _common(p)
    p.add_argument("--book-text", default=None, help="book-text 本地检出（核当前文本与校验字）")
    p.add_argument("--github", action="store_true", help="没有本地检出时从 GitHub raw 取当前文本")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_locate)

    p = s.add_parser("pack", help="出证据包（裁图、条带、上下文、marks）＋ sheet.png／sheet.md")
    p.add_argument("ids", nargs="+")
    _common(p)
    p.add_argument("--out", required=True)
    p.add_argument("--book-text", default=None, help="book-text 本地检出（缺省 GUJI_BOOK_TEXT，再缺走 GitHub raw）")
    p.add_argument("--cache", default=None, help="IIIF 整页原图缓存目录（缺省 $GUJI_DATA_HOME/_shared/iiif）")
    p.add_argument("--window", type=int, default=3, help="意见格前后各取几个单元（字格与 marks）")
    p.set_defaults(func=cmd_pack)

    p = s.add_parser("schema", help="打印 guji-opinion/0.1 的 JSON Schema")
    p.set_defaults(func=cmd_schema)


def cmd_opinions(args) -> None:
    f = getattr(args, "func", None)
    if f is None:
        raise SystemExit("guji opinions <子命令>；见 guji opinions -h")
    f(args)
