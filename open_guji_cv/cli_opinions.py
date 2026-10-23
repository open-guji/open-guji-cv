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
    guji opinions auto decide|prepare|finish-pr|finish-merged|digest --book B --ws W --remote ...   # 自动化调和器（rules.json 的 auto 段）
    guji opinions publish-status --book B --ws W [--remote] [--dry-run]  # 处理结论 → 中心库 feedback/lists/web/<书>/status.jsonl（网站回显）

意见池在哪：缺省是本机数据目录 `$GUJI_DATA_HOME/<分支>/<工作区>/feedback/lists/opinions/<书>/`（`guji db sync` 推进中心库）；
`--root D` 用 `D/<书>/`（试跑、不进中心库的判定）；`--remote` 直接经 Worker 读写中心库（令牌取 `--token-env` 指的环境变量，不打印）。
"""
from __future__ import annotations

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


# ---------------- normalize ----------------

def cmd_normalize(args) -> None:
    """会话把一条自由文字（fb_ 或别的待规整意见）规整成一条或多条：原条 superseded，新条带 normalized_by。"""
    from .opinions.ingest import describe
    from .opinions.schema import Opinion, make_id
    st = _store(args, by=args.by)
    src = st.get(args.id)
    if st.status(src.id) not in ("to_normalize", "new"):
        raise SystemExit(f"{src.id} 状态是 {st.status(src.id)}，不规整")
    raw = args.into.strip()
    parts = json.loads(raw if raw[:1] in "[{" else Path(raw).read_text(encoding="utf-8"))
    if isinstance(parts, dict):
        parts = [parts]
    new = []
    for k, p in enumerate(parts, 1):
        op = Opinion(id=make_id(src.channel, f"norm:{src.id}", k), book=src.book, vol=p.get("vol") or src.vol,
                     channel=src.channel, raw_id=src.raw_id, voter=src.voter, ts=src.ts, target=p.get("target") or {},
                     category=p["category"], proposal=p.get("proposal"), note=p.get("note") or src.note,
                     normalized_by=args.by, extra={"from": src.id})
        new.append(op)
    for op in new:
        st.add(op, log_data={"source": f"normalize {src.id}"})
    st.log(src.id, "superseded", {"by": new[0].id, "all": [o.id for o in new], "reason": "规整"})
    for op in new:
        _print("  + " + describe(op))
    if args.dry_run:
        _print("[dry-run] 不写")
        return
    st.save()
    _print(f"规整 {src.id} → {len(new)} 条（{st.backend.describe()}）")


# ---------------- triage ----------------

def _triage_one(st, bt, rules, op_id: str, a: dict) -> tuple:
    from .opinions import rules as R
    from .opinions.schema import Triage
    from .opinions.textsrc import char_cells, cord_page, locate
    op = st.get(op_id)
    status = st.status(op.id)
    located = locate(op, st.text_versions, bt) if bt is not None else None
    rev = R.parse_revision(a.get("revision"))
    if rev is None and bt is not None and (op.target or {}).get("start"):
        char, cord = bt.char(op.vol), bt.cord(op.vol)
        if char:
            page = int(op.target["start"].split(":")[0])
            rev = R.derive_revision(op, a["verdict"], char_cells(char), cord_page(cord, page) if cord else None,
                                    guess=a.get("guess"))
    if a["verdict"] in ("text_ok", "out_of_scope", "unclear"):
        rev = None
    route, why = R.route(op, verdict=a["verdict"], confidence=float(a["confidence"]), public=a.get("public") or "",
                         profile=a.get("profile") or "published", revision=rev, status=status, located=located,
                         evidence_agree=int(a.get("evidence_agree") or 0), human_cells=a.get("human_cells"),
                         store=st, rules=rules, requested=a.get("route"))
    if located and located.get("already"):
        rev = None
    reply = a.get("reply") or R.reply_template(a["verdict"], rev, op, a.get("public") or "")
    tri = Triage(verdict=a["verdict"], confidence=float(a["confidence"]), rationale_public=a.get("public") or "",
                 rationale_internal=a.get("internal") or "", evidence=a.get("evidence") or None, route=route,
                 revision=rev, reply_draft=reply, judge=a["judge"], profile=a.get("profile") or "published",
                 engine=a.get("engine") or "", rule=why, draft_event=R.draft_event(rev),
                 evidence_agree=int(a["evidence_agree"]) if a.get("evidence_agree") not in (None, "") else None)
    e = tri.errors()
    if e:
        raise SystemExit(f"{op.id}：" + "；".join(e))
    return op, tri


def cmd_triage(args) -> None:
    from .opinions import rules as R
    st = _store(args, by=args.judge)
    bt = _bt(args) if (args.book_text or os.environ.get("GUJI_BOOK_TEXT") or args.github) else None
    rules = R.load_rules(args.rules)
    human = set(Path(args.human_cells).read_text(encoding="utf-8").split()) if args.human_cells else None
    jobs = []
    if args.from_tsv:
        lines = [ln.rstrip("\n").split("\t") for ln in Path(args.from_tsv).read_text(encoding="utf-8").splitlines() if ln.strip()]
        head = lines[0]
        for row in lines[1:]:
            d = dict(zip(head, row))
            jobs.append((d.pop("id"), d))
    else:
        if not args.id or not args.verdict or args.confidence is None:
            raise SystemExit("要 <id> --verdict --confidence（或 --from TSV）")
        jobs.append((args.id, {"verdict": args.verdict, "confidence": args.confidence, "public": args.public,
                               "internal": args.internal, "revision": args.revision, "route": args.route,
                               "guess": args.guess, "evidence": args.evidence, "evidence_agree": args.evidence_agree,
                               "reply": args.reply, "profile": args.profile, "engine": args.engine}))
    for op_id, a in jobs:
        a.setdefault("judge", args.judge)
        a["judge"] = a.get("judge") or args.judge
        a["human_cells"] = human
        try:
            op, tri = _triage_one(st, bt, rules, op_id, a)
        except R.RuleError as e:
            raise SystemExit(f"{op_id}：{e}")
        st.log(op.id, "triaged", tri.to_dict(), by=args.judge)
        rv = tri.revision or {}
        _print(f"{op.id}：{tri.verdict}（{tri.confidence}）→ {tri.route}；{'；'.join(tri.rule or [])}")
        if rv:
            _print(f"  修订 {rv.get('class')}：{json.dumps(rv.get('cells'), ensure_ascii=False)}")
        if tri.draft_event:
            _print(f"  草稿事件 {json.dumps(tri.draft_event, ensure_ascii=False)}")
        _print(f"  回复草稿：{tri.reply_draft}")
    if args.dry_run:
        _print("[dry-run] 不写")
        return
    st.save()
    _print(f"写入判定 {len(jobs)} 条（{st.backend.describe()}）")


# ---------------- to-user / decide / reply-drafts ----------------

def cmd_to_user(args) -> None:
    """交用户的意见出成审阅页数据（review-artifact skill 发页）：items.json＋README.md；有证据包目录就带上裁图路径。"""
    import shutil
    st = _store(args)
    stat = st.statuses()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    items = []
    for op in st.opinions.values():
        if stat[op.id] != "to_user":
            continue
        tri = st.last(op.id, "triaged")
        d = tri.data if tri else {}
        imgs = []
        if args.pack:
            pd = Path(args.pack) / op.id
            for name in ("strip_marked.png",) + tuple(sorted(p.name for p in pd.glob("target-*.png"))):
                if (pd / name).is_file():
                    dst = out / "img" / f"{op.id}-{name}"
                    dst.parent.mkdir(exist_ok=True)
                    shutil.copyfile(pd / name, dst)
                    imgs.append(str(dst.relative_to(out)))
        items.append({"id": op.id, "vol": op.vol, "target": op.target, "category": op.category,
                      "proposal": op.proposal, "note": op.note, "verdict": d.get("verdict"),
                      "confidence": d.get("confidence"), "rationale_public": d.get("rationale_public"),
                      "rationale_internal": d.get("rationale_internal"), "rule": d.get("rule"),
                      "revision": d.get("revision"), "reply_draft": d.get("reply_draft"), "images": imgs,
                      "options": ["accept", "reject", "discuss"]})
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 交用户裁决的意见", "", "每条选 accept（采纳）／reject（不采纳）／discuss（公开讨论）。收回后 `guji opinions decide --from <裁决.json>`。", ""]
    for it in items:
        t = it["target"] or {}
        md += [f"## {it['id']}", f"- 第 {it['vol']} 章 {t.get('start')}–{t.get('end')}：{t.get('check')} → {(it['proposal'] or {}).get('text')}",
               f"- 判定 {it['verdict']}（{it['confidence']}）：{it['rationale_public']}", f"- 为什么交你：{'；'.join(it['rule'] or [])}",
               f"- 修订：{json.dumps(it['revision'], ensure_ascii=False)}", f"- 回复草稿：{it['reply_draft']}", ""]
    (out / "README.md").write_text("\n".join(md), encoding="utf-8")
    _print(f"交用户 {len(items)} 条 → {out / 'items.json'}")


def cmd_decide(args) -> None:
    """收回的裁决 → log ``decided``；采纳的把草稿事件追加进 cv_events_todo（第二阶段补写成 CV 人裁事件）。"""
    from .opinions.schema import DECISIONS, now_iso
    st = _store(args, by=args.by)
    rows = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("decisions") or [rows]
    n = 0
    for r in rows:
        oid = r.get("opinion") or r.get("id")
        dec = r.get("decision") or r.get("verdict") or r.get("choice")
        if not oid or dec not in DECISIONS:
            _print(f"  跳过 {r}")
            continue
        op = st.get(oid)
        st.log(op.id, "decided", {"decision": dec, "by": r.get("by") or args.by,
                                  **({"note": r["note"]} if r.get("note") else {})}, by=args.by)
        if dec == "accept":
            tri = st.last(op.id, "triaged")
            d = tri.data if tri else {}
            st.add_cv_todo({"opinion": op.id, "vol": op.vol, "draft_event": d.get("draft_event"),
                            "revision": d.get("revision"), "ts": now_iso()})
        n += 1
        _print(f"  {op.id} → {dec}")
    if args.dry_run:
        _print("[dry-run] 不写")
        return
    st.save()
    _print(f"记裁决 {n} 条（{st.backend.describe()}）")


def cmd_reply_drafts(args) -> None:
    st = _store(args)
    stat = st.statuses()
    n = 0
    for op in st.opinions.values():
        if stat[op.id] not in ("auto_accepted", "auto_rejected", "accepted", "rejected", "applied"):
            continue
        if st.last(op.id, "replied") is not None:
            continue
        tri = st.last(op.id, "triaged")
        n += 1
        _print(f"{op.id}\t{stat[op.id]}\t{(tri.data.get('reply_draft') if tri else '') or ''}")
    _print(f"待回复 {n} 条（回写网站归 B2，第一阶段只出草稿）")


# ---------------- publish-status ----------------

def cmd_publish_status(args) -> None:
    from .opinions import webstatus as W
    st = _store(args)
    backend = W.status_backend(args.book, ws=args.ws, root=args.root, remote=args.remote, token_env=args.token_env,
                               branch=args.branch)
    res = W.publish(st, backend, dry_run=args.dry_run)
    for r in res["rows"]:
        _print(json.dumps(r, ensure_ascii=False))
    for n in res["notes"]:
        _print(f"  注：{n}")
    c = res["counts"]
    tag = "[dry-run] " if args.dry_run else ""
    if not res["changed"]:
        _print(f"{tag}{res['where']}：{len(res['rows'])} 行，内容没变，不写")
    else:
        _print(f"{tag}{res['where']}：{len(res['rows'])} 行（新增 {c['added']}、改 {c['changed']}、不变 {c['same']}、"
               f"撤回 {c['reopened']}）" + ("，已写" if res["written"] else "，未写"))


# ---------------- revise ----------------

def cmd_revise(args) -> None:
    from .opinions import revise as V
    from .opinions.textsrc import default_book_text
    root = default_book_text(args.book_text)
    if not root:
        raise SystemExit("revise 要本地 book-text 检出（--book-text 或 GUJI_BOOK_TEXT）")
    st = _store(args, by="revise")
    todo, skipped = V.plan(st, args.vol)
    if args.only:
        want = set(args.only.split(","))
        todo = [(o, r) for o, r in todo if o.id in want]
    _print(f"第 {args.vol} 章：要套 {len(todo)} 条，跳过 {len(skipped)} 条")
    for op, rev in todo:
        _print(f"  {op.id} {rev.get('class')} {json.dumps(rev.get('cells'), ensure_ascii=False)}")
    for i, why in skipped:
        _print(f"  跳过 {i}：{why}")
    if not todo:
        return
    try:
        res = V.revise(root, args.book, args.vol, todo, dry_run=args.dry_run, pr=args.pr,
                       guess_style=args.guess_style, bump_script=args.bump_script, skipped=skipped)
    except V.ReviseError as e:
        raise SystemExit(f"✗ {e}")
    for line in res.bump_log:
        _print("  bump: " + line.replace("\n", "；"))
    _print(("[dry-run] " if args.dry_run else "") + f"文本线 {res.old_version} → {res.new_version or '（待升 patch）'}；"
           f"伴生层 标点 {res.companions['punct']} 处、实体 {res.companions['entity']} 处")
    _print("出口检查：" + ("通过" if not res.problems else "；".join(res.problems)))
    _print("\n---- PR 正文 ----\n" + V.pr_body(res, args.book))
    if res.problems and not args.dry_run:
        raise SystemExit(2)
    if args.log_applied and not args.dry_run:
        for op, _rev in todo:
            st.log(op.id, "applied", {"text_version": res.new_version, "pr": args.pr})
        st.save()
        _print(f"log 记 applied {len(todo)} 条（{st.backend.describe()}）")


# ---------------- auto（自动化调和器，设计见 book-text docs/design/2026-10-修订流程自动化设计.md）----------------

def _auto_rules(args) -> dict:
    from .opinions import rules as R
    return R.load_rules(getattr(args, "rules", None))


def _human_cells(args) -> set | None:
    return set(Path(args.human_cells).read_text(encoding="utf-8").split()) if getattr(args, "human_cells", None) else None


def cmd_auto(args) -> None:
    from .opinions import auto as A
    from .opinions import webstatus as W
    rules = _auto_rules(args)
    st = _store(args, by=args.by)
    sub = args.auto_cmd
    try:
        if sub == "decide":
            rows = A.decide_pending(st, rules)
            for r in rows:
                _print(f"{r['id']}\t{r['action']}\t{r['reason']}")
            _print(f"{'[dry-run] ' if args.dry_run else ''}自动结案 {sum(1 for r in rows if r['action'] != 'park')} 条，留着 {sum(1 for r in rows if r['action'] == 'park')} 条")
        elif sub == "prepare":
            from .opinions.textsrc import default_book_text
            root = default_book_text(args.book_text)
            if not root:
                raise SystemExit("prepare 要本地 book-text 检出（--book-text 或 GUJI_BOOK_TEXT）")
            plans = A.prepare(st, root, args.book, rules, vols=[v for v in args.vols.split(",") if v] or None,
                              human_cells=_human_cells(args), run_checks=not args.no_checks, trailers=args.trailer)
            _print(json.dumps(plans, ensure_ascii=False, indent=1))
        elif sub == "finish-pr":
            from .opinions.textsrc import default_book_text
            res = A.finish_pr(st, default_book_text(args.book_text), args.release, args.pr)
            _print(json.dumps(res, ensure_ascii=False))
        elif sub == "finish-merged":
            backend = W.status_backend(args.book, ws=args.ws, root=args.root, remote=args.remote,
                                       token_env=args.token_env, branch=args.branch)

            def pub():
                r = W.publish(st, backend, dry_run=args.dry_run)
                return {"rows": len(r["rows"]), "written": r["written"], "where": r["where"]}
            res = A.finish_merged(st, args.release, args.commit, publish_status=pub)
            _print(json.dumps(res, ensure_ascii=False))
        elif sub == "digest":
            _print(A.digest(st, rules, since=args.since))
            return
    except A.AutoError as e:
        raise SystemExit(f"✗ {e}")
    if args.dry_run:
        _print("[dry-run] 意见池不写")
        return
    st.save()
    _print(f"已写意见池（{st.backend.describe()}）")


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

    p = s.add_parser("normalize", help="会话把自由文字规整成一条或多条（原条 superseded）")
    p.add_argument("id")
    _common(p)
    p.add_argument("--into", required=True, help="JSON（或文件）：[{vol, target:{start,end,text_version}, category, proposal, note}]")
    p.add_argument("--by", required=True, help="规整者（会话名）")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_normalize)

    p = s.add_parser("triage", help="写判定（会话判、规则表定去向）")
    p.add_argument("id", nargs="?")
    _common(p)
    p.add_argument("--verdict", choices=("text_ok", "accept", "lacuna_guess", "seg_issue", "out_of_scope", "unclear"))
    p.add_argument("--confidence", type=float)
    p.add_argument("--public", default="", help="公开理由，一句话")
    p.add_argument("--internal", default="", help="内部理由")
    p.add_argument("--revision", default=None, help="修订 JSON（或 @文件）；不给就按意见和 book-text 推")
    p.add_argument("--guess", default=None, help="lacuna_guess 的推测字（不给取建议多出的那个字）")
    p.add_argument("--route", default=None, choices=("auto_accept", "auto_reject", "to_user", "discuss", "forward"),
                   help="只能要求比规则更保守的去向")
    p.add_argument("--evidence", default=None, help="证据包路径或摘要")
    p.add_argument("--evidence-agree", type=int, default=0, help="一致的证据路数（自动采纳门槛）")
    p.add_argument("--reply", default=None, help="公开回复草稿（不给按模板起）")
    p.add_argument("--profile", default="published", choices=("published", "proofing"))
    p.add_argument("--judge", required=True, help="判定者：会话名或模型名")
    p.add_argument("--engine", default="", help="引擎版本")
    p.add_argument("--rules", default=None, help="规则表（缺省 config/opinions/rules.json）")
    p.add_argument("--human-cells", default=None, help="用户亲裁过的格号清单文件（空白分隔）")
    p.add_argument("--book-text", default=None)
    p.add_argument("--github", action="store_true")
    p.add_argument("--from", dest="from_tsv", default=None, help="批量：TSV，表头含 id verdict confidence public …")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_triage)

    p = s.add_parser("to-user", help="交用户的意见出成审阅页数据")
    _common(p)
    p.add_argument("--out", required=True)
    p.add_argument("--pack", default=None, help="证据包目录（guji opinions pack 的 --out），带上裁图")
    p.set_defaults(func=cmd_to_user)

    p = s.add_parser("decide", help="收回的裁决记 decided；采纳的草稿事件进 cv_events_todo")
    _common(p)
    p.add_argument("--from", dest="from_file", required=True)
    p.add_argument("--by", default="user")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_decide)

    p = s.add_parser("revise", help="对已采纳意见改 book-text 冻结册 char／cord，升 patch，写 CHANGES，打印 PR 正文")
    _common(p)
    p.add_argument("--vol", required=True, help="章号 NNN")
    p.add_argument("--book-text", default=None, help="book-text 本地检出（要写）")
    p.add_argument("--dry-run", action="store_true", help="只算不写")
    p.add_argument("--pr", default=None, help="book-text 的 PR 号（写进 CHANGES；不 dry-run 时必填）")
    p.add_argument("--guess-style", default="guess-c", choices=("guess-c", "lacuna", "guess-char"),
                   help="阙文带推测字的写法：guess-c（缺省，char v0.2 guess_c，悬停出推测字）／lacuna（推测字只进 CHANGES）／guess-char（残字写法）")
    p.add_argument("--bump-script", default=None, help="缺省 <book-text>/scripts/book-text/bump_original.py")
    p.add_argument("--only", default="", help="只套这些意见（逗号分隔 id）")
    p.add_argument("--log-applied", action="store_true", help="改完在意见池 log 记 applied（PR 合了再用）")
    p.set_defaults(func=cmd_revise)

    p = s.add_parser("reply-drafts", help="列出已结案、待回复读者的意见和回复文字")
    _common(p)
    p.set_defaults(func=cmd_reply_drafts)

    p = s.add_parser("publish-status", help="网站来源意见的处理结论 → 中心库 feedback/lists/web/<书>/status.jsonl（网站 Action 回写 /api/fixes）")
    _common(p)
    p.add_argument("--dry-run", action="store_true", help="只打印，不写")
    p.set_defaults(func=cmd_publish_status)

    p = s.add_parser("auto", help="自动化调和器：decide 自动结案、prepare 聚批改文本、finish-pr／finish-merged 收尾、digest 汇总")
    p.add_argument("auto_cmd", choices=("decide", "prepare", "finish-pr", "finish-merged", "digest"))
    _common(p)
    p.add_argument("--by", default="auto", help="log 里记谁做的")
    p.add_argument("--rules", default=None, help="规则表路径（缺省 config/opinions/rules.json）")
    p.add_argument("--dry-run", action="store_true", help="意见池不写（prepare 仍会在 book-text 里建分支和提交）")
    p.add_argument("--book-text", default=None, help="book-text 本地检出（prepare／finish-pr 要）")
    p.add_argument("--vols", default="", help="prepare：只做这些章（逗号分隔，缺省全部）")
    p.add_argument("--human-cells", default=None, help="prepare：保护格清单（每行一个格号，人裁或手改过的），碰到的意见不自动改")
    p.add_argument("--no-checks", action="store_true", help="prepare：不跑 local_check（只给测试用）")
    p.add_argument("--trailer", action="append", default=[], help="prepare：提交信息末尾加的行，可重复")
    p.add_argument("--release", default=None, help="finish-pr／finish-merged：发布批 id")
    p.add_argument("--pr", default=None, help="finish-pr：PR 号")
    p.add_argument("--commit", default=None, help="finish-merged：合并后 main 上的提交")
    p.add_argument("--since", default=None, help="digest：只列这个时间（ISO）之后的自动结案")
    p.set_defaults(func=cmd_auto)

    p = s.add_parser("schema", help="打印 guji-opinion/0.1 的 JSON Schema")
    p.set_defaults(func=cmd_schema)


def cmd_opinions(args) -> None:
    f = getattr(args, "func", None)
    if f is None:
        raise SystemExit("guji opinions <子命令>；见 guji opinions -h")
    f(args)
