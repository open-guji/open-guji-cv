# -*- coding: utf-8 -*-
"""字形库与语料命令：store（推中心库）、recheck、glyphlib、rekey-cells、promote、corpus。

拆分 P1（`doc/design/拆分-pipeline与manager.md`）从 `cli_v2` 原样搬出；经 `cli_v2.MANAGER_CLI_MODULES` 登记。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cli_v2   # 共用辅助现取（测试 monkeypatch cli_v2 照样生效）


def cmd_store(args) -> None:
    """`guji store check|commit -w <工作区>`：glyph.db 导出成字形库账本、推进中心库（GUJI-608/611）。

    等同 `guji db push`（check = `--dry-run`）。字形库与人裁不再提交进工作区 git；没迁的工作区先
    `guji db migrate`。"""
    import os
    from .core.workspace import central_marker, workspace_root
    if not args.workspace:
        print("✗ 要 -w <工作区>", file=sys.stderr); sys.exit(2)
    os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())
    ws = workspace_root()
    if not central_marker(ws):
        print(f"✗ 工作区 {ws} 还没迁进中心库：字形库与人裁不再提交进工作区 git，"
              f"先 `guji db migrate -w {ws}`", file=sys.stderr)
        sys.exit(2)
    from .cli_db import push_workspace
    res = push_workspace(ws, dry_run=args.action != "commit", allow_delete=args.allow_deletions)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    n = sum(v.get("changes", 0) for v in (res.get("per_ws") or {}).values())
    if args.action == "commit":
        print(f"已推进中心库：{n} 处变更，rev {res.get('rev_from')} → {res.get('rev_to')}" if n else "没有改动")
    else:
        print(f"检查通过：推送会写 {n} 处变更（check 不写；要推用 `guji store commit` 或 `guji db push`）")


def cmd_recheck(args) -> None:
    """Step5-a 点名重算：按字 / 判档 / 命中条目已撤，把格写进 manifest 的格级失效。
    只标不跑——跑还是 `guji pipeline <p> <book> --from glyph_match`，只重算点名格。"""
    from .core.spec import page_key
    from .steps.glyph_match import live_exemplars, recheck_reasons
    eng = cli_v2._engine(args.book, args.pipeline, params=getattr(args, "params", None), quiet=True)
    step = eng.pipeline.producer_of("glyph_match")
    sid = step.spec.id
    p = eng.ctx.params_for(step)
    chars = set((args.chars or "").replace(",", "").replace("，", "").replace(" ", ""))
    verdicts = {v for v in (args.verdicts or "").split(",") if v}
    if not (chars or verdicts or args.dead or args.all or args.glyph_diff):
        raise SystemExit("至少给一个：--chars / --verdicts / --dead / --all / --glyph-diff")
    if args.glyph_diff:
        return _recheck_glyph_diff(args, eng, step, p)
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


def _old_glyph_db(spec: str) -> str:
    """`--glyph-diff` 的旧库：`g<N>`／`N`（钉版库，缺了就建）或库文件路径。"""
    from pathlib import Path
    from .core.glyph_pin import parse_pin, pinned_db_path
    n = parse_pin(spec) if not Path(spec).suffix else None
    if n is None:
        if not Path(spec).exists():
            raise SystemExit(f"--glyph-diff：库文件不存在：{spec}")
        return str(Path(spec))
    from .core.workspace import workspace_root
    from .ops.glyph_snapshot import build_pinned_db
    build_pinned_db(workspace_root(), n)
    return str(pinned_db_path(n))


def _recheck_glyph_diff(args, eng, step, p) -> None:
    """`guji recheck --glyph-diff <旧库>`：kNN 邻域差分（`ops/glyph_diff.py`），只点名换库后判决可能变的格。"""
    from .core.spec import page_key
    from .ops.glyph_diff import load_view, page_affected
    from .steps.glyph_match import _FontTier, db_fingerprint
    sid = step.spec.id
    old_db = _old_glyph_db(args.glyph_diff)
    if old_db == p.db_path:
        raise SystemExit(f"--glyph-diff 给的旧库就是本册现在读的库（{old_db}）：没有可比的")
    p_old = p.model_copy(update={"db_path": old_db, "db_fingerprint": db_fingerprint(old_db)})
    tier = _FontTier.rule(p.font_tier) is not None
    print(f"旧库 {old_db}\n新库 {p.db_path}", flush=True)
    old, new = load_view(p_old, font_tier=tier), load_view(p, font_tier=tier)
    manifest = eng.store.manifest(eng.book.id, sid)
    reason = f"recheck glyph-diff {args.glyph_diff}"
    n_pages = n_cells = n_total = 0
    by_why: dict[str, int] = {}
    for pg in eng.book.resolve_pages(args.pages):
        key = page_key(pg)
        if manifest.get(key) is None:
            continue
        pm = eng.store.read(eng.book.id, sid, key, "glyph_match")
        if pm is None:
            continue
        hit = page_affected(eng.ctx, pg, pm, p, old, new)
        n_total += sum(len(c.chars) for c in pm.columns if c.ok)
        for why in hit.values():
            for w in why:
                by_why[w] = by_why.get(w, 0) + 1
        if hit:
            n_pages += 1
            n_cells += len(hit)
            if not args.dry_run:
                manifest.invalidate(key, reason, cells=sorted(hit))
        if args.list:
            for cid, why in sorted(hit.items()):
                print(f"  {cid}\t{','.join(why)}")
    head = "[dry-run] " if args.dry_run else ""
    pct = f"{n_cells * 100 / n_total:.1f}%" if n_total else "-"
    print(f"{head}{sid}：{n_pages} 页 {n_cells}/{n_total} 格点名重算（{pct}）  "
          + "  ".join(f"{k} {v}" for k, v in sorted(by_why.items())))
    if n_pages and not args.dry_run:
        print(f"下一步：guji pipeline {eng.pipeline.id} {eng.book.id} --from {sid} "
              f"--pages {args.pages} -w <workspace>")


def cmd_corpus(args) -> None:
    """语料库（corpus-vN）清单：build 出新版、verify 对当前文件、list 列版本。P0 只登记，不改 Step／指纹。"""
    import os

    from .ops import corpus_pack as cp
    if args.action == "build-base":                   # 底库：不要 -w，写中心库的 corpus-base（共享方案 S2）
        from .cli_db import _pg_conn
        from .datastore.client import WorkerSource
        actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
        with _pg_conn() as conn:
            cli_v2._out(cp.publish_base(WorkerSource(), conn, note=args.note, actor=actor, dry_run=args.dry_run))
        return
    if not args.workspace:
        print("✗ 要给 -w 工作区", file=sys.stderr)
        sys.exit(2)
    ws = Path(args.workspace).expanduser().resolve()
    if not ws.is_dir():
        print(f"✗ 工作区 {ws} 不存在", file=sys.stderr)
        sys.exit(2)
    if args.action == "pin":                          # 册的钉子账：追加一行总号（分层版本）
        from .core.corpus_pin import append_pin
        if not args.vol:
            print("✗ pin 要给 --vol <册 id>", file=sys.stderr)
            sys.exit(2)
        kw = {k: v for k, v in (("global_ver", args.global_ver), ("book_ver", args.book_ver),
                                ("vol_ver", args.vol_ver)) if v is not None}
        try:
            row = append_pin(ws, args.vol, from_n=args.from_n, note=args.note, dev=args.dev, **kw)
        except (ValueError, FileNotFoundError) as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        cli_v2._out(row)
        tail = "，再加 corpus_dev: true（开发中，发版用 guji corpus release）" if args.dev else ""
        print(f"✓ 已追加钉子账；册 yaml 改成 corpus: {row['n']}{tail}（本命令不改册 yaml、不推中心库）")
        return
    if args.action in ("upload", "fetch"):            # 大文件（≥1MB）进／出 R2，清单只记哈希
        from .core.corpus_pin import load_pins
        v = args.version
        if not v and args.vol:
            rows = load_pins(ws, args.vol)
            v = rows[-1]["n"] if rows else None
        v = v or (cp.versions(ws) or [0])[-1]
        try:
            res = (cp.upload_blobs(ws, v, args.vol, execute=args.execute, all_items=args.all)
                   if args.action == "upload"
                   else cp.fetch_blobs(ws, v, args.vol))
        except (ValueError, FileNotFoundError) as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        cli_v2._out(res)
        return
    if args.action == "release":                      # 开发中的总号发版：三层清单齐了才放行
        from .core.corpus_pin import release_pin
        if not args.vol or not args.version:
            print("✗ release 要给 --vol <册 id> 和 --version <总号>", file=sys.stderr)
            sys.exit(2)
        try:
            row = release_pin(ws, args.vol, args.version)
        except (ValueError, FileNotFoundError) as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        cli_v2._out(row)
        print("✓ 已发版；册 yaml 去掉 corpus_dev: true，再 guji corpus verify --vol 确认干净")
        return
    if args.action == "build" and args.vol:           # 册层清单
        try:
            out = cp.build_vol(ws, args.vol, args.note)
        except (FileNotFoundError, ValueError) as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ 已写 {out}（接着 guji corpus pin --vol {args.vol} --vol-ver N 记进钉子账）")
        return
    if args.action in ("build", "init"):
        base = args.base
        if args.action == "init":                     # 新书：钉最新底库出 v1（两级清单）
            if cp.versions(ws):
                print(f"✗ {ws} 已有语料库版本 {cp.versions(ws)}；出新版用 guji corpus build --base latest",
                      file=sys.stderr)
                sys.exit(1)
            base = base or "latest"
        if base is not None:                          # 先把中心库的底库清单拉到本机
            from .datastore.client import BlobCache, WorkerSource
            from .datastore.workcopy import refresh_corpus_base
            refresh_corpus_base(WorkerSource(), ws, cache=BlobCache(), always=True)
        try:
            out = cp.build(ws, args.version, args.note, base=base)
        except (FileExistsError, FileNotFoundError, ValueError) as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ 已写 {out}（迁过的工作区接着 guji db push -w {ws}）")
    elif args.action == "verify":
        vs = cp.versions(ws)
        v = args.version
        if not v and args.vol:                        # 册：总号缺省取钉子账最新一行
            from .core.corpus_pin import load_pins
            rows = load_pins(ws, args.vol)
            v = rows[-1]["n"] if rows else None
        v = v or (vs[-1] if vs else 0)
        try:
            r = cp.verify(ws, v, args.vol)
        except FileNotFoundError as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        cli_v2._out(r)
        sys.exit(0 if r["clean"] else 1)
    else:
        cli_v2._out(cp.summary(ws))


def cmd_glyphlib(args) -> None:
    """共享刻例库（共享方案 S5）：build 从一本书精选刻例出 glyphlib-<族>-v<N>，加 --push 推进中心库。"""
    import os

    from .ops import glyphlib as gl
    actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
    if not args.workspace:
        print("✗ 要给 -w 来源书的工作区", file=sys.stderr)
        sys.exit(2)
    res = gl.build(Path(args.workspace).expanduser().resolve(), args.name, min_batches=args.min_confirm,
                   per_char=args.per_char, actor=actor, note=args.note)
    if args.push:
        from .cli_db import _pg_conn
        from .datastore.r2 import upload_files
        with _pg_conn() as conn:
            res["push"] = gl.publish(conn, args.name, actor=actor,
                                     uploader=lambda imgs, ext="png": upload_files(imgs, bucket="main", ext=ext))
    cli_v2._out(res)


def cmd_rekey_cells(args) -> None:
    """换图源后按格级对照表改键（GUJI-748）：glyph-db／json／jsonl／ids-bank 改，verify 核对。见 `ops/cell_rekey.py`。"""
    import os

    from .ops import cell_rekey as ck
    cm = ck.load_cell_map(args.map)
    if args.action in ("glyph-db", "verify"):
        if args.workspace:
            os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())
        from .core.workspace import glyph_db_path
        db = Path(args.db) if args.db else Path(glyph_db_path())
        if args.action == "verify":
            evs = None
            if args.events:
                evs = [json.loads(ln) for f in args.events for ln in open(f, encoding="utf-8") if ln.strip()]
            res = ck.verify_glyph_db(db, cm, evs)
            cli_v2._out({"db": str(db), "map": cm.source, **res})
            sys.exit(0 if res["ok"] else 1)
        if args.rev is None:
            print("✗ 要给 --rev 旧页表 rev（停放 id 用）", file=sys.stderr)
            sys.exit(2)
        res = ck.rekey_glyph_db(db, cm, args.rev, dry_run=args.dry_run)
        if args.table:
            ck.write_glyph_table(res["rows"], args.table)
        cli_v2._out({"db": str(db), "map": cm.source, "dry_run": args.dry_run, **cm.counts(), **res["summary"]})
        return
    if not args.files:
        print("✗ 要给要改的文件", file=sys.stderr)
        sys.exit(2)
    out = []
    for f in args.files:
        if args.action == "json":
            out.append(ck.rekey_json(f, cm))
        elif args.action == "jsonl":
            out.append(ck.rekey_jsonl(f, cm, fields=tuple(args.field or ("id", "key"))))
        else:
            if args.rev is None:
                print("✗ 要给 --rev 旧页表 rev（停放 id 用）", file=sys.stderr)
                sys.exit(2)
            out.append(ck.rekey_ids_bank(f, cm, args.rev))
    cli_v2._out({"map": cm.source, "files": out})


def cmd_promote(args) -> None:
    """升格候选（共享方案 S7，先做语料部分）：只读、只出清单。"""
    from .ops.promote import mine_corpus
    if not args.workspace:
        print("✗ 要给 -w 工作区", file=sys.stderr)
        sys.exit(2)
    res = mine_corpus(Path(args.workspace).expanduser().resolve(), min_confusable=args.min_confusable)
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"✓ 已写 {args.out}（形近新候选 {res['new']['confusable']}，异体新候选 {res['new']['variants']}）")
        return
    cli_v2._out(res)


def add_parser(sub) -> None:
    p = sub.add_parser("store", help="[v2] glyph.db 导出并推进中心库（= guji db push；check = 只看不写）")
    p.add_argument("action", choices=["check", "commit"])
    p.add_argument("-w", "--workspace", default=None, help="书的工作区目录")
    p.add_argument("--push", action="store_true", help=argparse.SUPPRESS)        # 旧参数，已无作用（总是推进中心库）
    p.add_argument("--allow-deletions", action="store_true", help="确认过删整个文件是对的，放行")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("recheck",
                       help="[v2] Step5-a 点名重算：库变了不自动重跑，要吃新库就在这里点名格")
    p.add_argument("book")
    p.add_argument("--pipeline", default=cli_v2.DEFAULT_PIPELINE)
    p.add_argument("--pages", default="all")
    p.add_argument("--chars", default=None, help="记录里出现这些字的格（判定字/候选），如 𠊓,虜")
    p.add_argument("--verdicts", default=None, help="这些判档的格，如 unsure,diff")
    p.add_argument("--dead", action="store_true",
                   help="same 档命中的库条目已撤或字头已改（撤库后建议跑一次）")
    p.add_argument("--all", action="store_true", help="整页失效（不复用任何格）")
    p.add_argument("--glyph-diff", default=None, metavar="旧库",
                   help="换了字形库版本后只点名受影响的格：旧库给 g<N> 或库文件路径，新库＝本册现在读的库"
                        "（kNN 邻域差分，见 ops/glyph_diff.py）；与其它点名条件互斥")
    p.add_argument("--list", action="store_true", help="--glyph-diff 时逐格列出点名理由")
    p.add_argument("--params", default=None,
                   help="参数覆盖 JSON（同 guji pipeline --params）；如新库不是册 yaml 指的那份："
                        '{"glyph_match": {"db_path": "…/new.db"}}，之后跑 pipeline 也要带同样的 --params')
    p.add_argument("--dry-run", action="store_true", help="只数不写")
    p = sub.add_parser("corpus", help="[v2] 语料库清单：build 出新版／verify 对当前文件／list／"
                                      "build-base 出底库／init 新书钉最新底库／pin 追加册的钉子账（分层版本）")
    p.add_argument("action", choices=["build", "verify", "list", "build-base", "init", "pin", "release", "upload", "fetch"])
    p.add_argument("--version", type=int, default=None, help="build：指定版本号（缺省最大号+1）；verify：缺省最新")
    p.add_argument("--note", default="", help="build／build-base：写进清单的备注")
    p.add_argument("--base", default=None,
                   help="build／init：两级清单，引擎仓文件归底库（latest 或底库号）；不给 build 出单级清单")
    p.add_argument("--dry-run", action="store_true", help="build-base：只算不推")
    p.add_argument("--vol", default=None, help="册 id：build 出册层清单／pin 追加这册的钉子账／verify 按这册的总号对")
    p.add_argument("--dev", action="store_true", help="pin：开发中的总号（各层版本可以指向还没出的清单；发版用 release）")
    p.add_argument("--execute", action="store_true", help="upload：真传 R2（缺省只演练；要 GUJI_DATA_TOKEN）")
    p.add_argument("--all", action="store_true",
                   help="upload：改传引擎仓（cv）的全部底库文件，不论大小（缺省只传 ≥1MB 的大文件）；后来改过的按底库 repo_commit 从 git 取当时那版；之后 cv 不带底库文件时 fetch 也能取回")
    p.add_argument("--from-n", type=int, default=None, help="pin：这册还没有钉子账时，册 yaml 现在的 corpus: 号")
    p.add_argument("--global-ver", type=int, default=None, help="pin：全局层（底库）版本；不给沿用最新一行")
    p.add_argument("--book-ver", type=int, default=None, help="pin：整套书层（书库）版本")
    p.add_argument("--vol-ver", type=int, default=None, help="pin：册层版本")
    p.add_argument("-w", "--workspace", default=None, help="工作区目录（清单落在 <工作区>/corpus-pack/vN/）")
    p = sub.add_parser("glyphlib", help="[v2] 共享刻例库：build 从一本书精选刻例出新版本（--push 推进中心库）")
    p.add_argument("action", choices=["build"])
    p.add_argument("--name", required=True, help="新版本的工作区名，如 glyphlib-qkp-v1（每版只能写一次）")
    p.add_argument("-w", "--workspace", default=None, help="来源书的工作区（已迁到中心库、已 db pull）")
    p.add_argument("--min-confirm", type=int, default=2, help="人裁至少在几个不同批次确认过（缺省 2）")
    p.add_argument("--per-char", type=int, default=3, help="每字最多几张（缺省 3）")
    p.add_argument("--note", default="", help="写进升格记录的备注")
    p.add_argument("--push", action="store_true", help="出完推进中心库（升级脚本身份，要写库权限）")
    p = sub.add_parser("rekey-cells", help="[v2] 换图源后按格级对照表改键：字形库、L2 表、金标/回放集、模板库出处（GUJI-748）")
    p.add_argument("action", choices=["glyph-db", "verify", "json", "jsonl", "ids-bank"],
                   help="glyph-db 改 glyph.db 实例 id；verify 核对改键后的库；json L2 表等按格当键的 JSON；"
                        "jsonl 金标/回放集；ids-bank IDS 模板库出处")
    p.add_argument("--map", required=True, help="格级对照表 old_new_cells/<册>.tsv[.gz]")
    p.add_argument("files", nargs="*", help="json／jsonl／ids-bank：要改的文件（原地改）")
    p.add_argument("-w", "--workspace", default=None, help="glyph-db／verify：工作区（取它的 glyph.db）")
    p.add_argument("--db", default=None, help="glyph-db／verify：直接给 glyph.db 路径")
    p.add_argument("--rev", default=None, help="旧页表 rev，停放 id 写成 <前缀>~r<rev>~册~页~列~格")
    p.add_argument("--dry-run", action="store_true", help="glyph-db：只推演不写")
    p.add_argument("--table", default=None, help="glyph-db：逐实例改键表写到这个 tsv")
    p.add_argument("--events", nargs="*", default=None, help="verify：迁移事件 jsonl，逐格核对字形")
    p.add_argument("--field", action="append", default=None, help="jsonl：格键所在字段（可多次，缺省 id、key）")
    p = sub.add_parser("promote", help="[v2] 升格候选：mine 从本书人裁挖形近对、异体对（只读，出清单待人审）")
    p.add_argument("action", choices=["mine"])
    p.add_argument("-w", "--workspace", default=None, help="书的工作区（已迁到中心库、已 db pull）")
    p.add_argument("--min-confusable", type=int, default=3, help="形近对在本书至少出现几次（缺省 3）")
    p.add_argument("--out", default=None, help="清单写到这个 JSON 文件；不给就打印")


#: 并进 `guji` 的子命令（同插件接口 `guji.commands`）
COMMANDS = {
    "store": (add_parser, cmd_store),
    "recheck": (add_parser, cmd_recheck),
    "glyphlib": (add_parser, cmd_glyphlib),
    "rekey-cells": (add_parser, cmd_rekey_cells),
    "promote": (add_parser, cmd_promote),
    "corpus": (add_parser, cmd_corpus),
}
