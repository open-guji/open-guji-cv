"""`glyph-db` 子命令：跨书字形数据库（SQLite）的导入、重建、导出、自检。

2026-10-06 cv 大清理（overview#413）从退役的 v1 入口 `__main__.py` 搬来，挂在 `guji` 与 `guji-cv` 两个入口下。
函数体原样照搬，只把 `_book_out_dir` 一并带过来。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def cmd_glyph_db(args):
    """M8 跨书字形数据库：stats / export / rebuild / import-font / 自检。

    索引库（SQLite）的落盘位置统一交给 `core.workspace.glyph_db_path()` 解析
    （`GUJI_GLYPH_DB` → `GUJI_WORKSPACE/output/glyph.db` → 仓内默认），不再由
    `--store` 推出——`--store` 只表示「真源（JSONL+PNG）在哪」，是 rebuild 的
    读入口、export 的写出口。库路径只有这一处说了算，`glyph_match` /
    `seed_admit` 读的是同一个 `glyph_db_path()`，rebuild 之后不必手工搬库。
    （库路径 P0：以前这里写的是 `<store>/glyphdb.sqlite`，与真正被读取的
    `glyph_db_path()` 不是同一个文件——干净环境上 rebuild 看着成功，
    `glyph_match` 却读到空库，静默出错、exit 0。）

    （库路径 P0 另一半：`--store` 同样不能就地当裸路径用——它以前是相对 CWD
    的字面量，即使 `GUJI_WORKSPACE` 设对了也不会跟着走，在仓根跑会读到仓根
    遗留的 `glyph_store/`（94 条）而不是工作区里的 `output/glyph_store/`
    （16,557 条），且不报错、只让下游数字全线变小。现在统一过
    `core.workspace.glyph_store_path()`：不传按工作区解析，传相对路径按工作区
    解释，传绝对路径当覆盖。）
    """
    import os
    from .clustering.glyph_db import GlyphDB
    from .core.workspace import assert_workspace_declared, glyph_db_path, glyph_store_path

    if getattr(args, "workspace", None):
        os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())
    if getattr(args, "allow_sample_db", False):
        os.environ["GUJI_ALLOW_SAMPLE_DB"] = "1"
    assert_workspace_declared()

    if args.action in PIN_ACTIONS:
        _pin_action(args)
        return
    db_path = glyph_db_path()
    store_dir = glyph_store_path(args.store)
    db = GlyphDB(db_path)
    try:
        if args.action == "export":
            from .clustering.glyph_db import export_store
            summary = export_store(db, store_dir)
        elif args.action == "rebuild":
            from .clustering.glyph_db import (assert_db_not_silently_empty,
                                              rebuild_from_store)
            db.close()
            # 借库（2026-09-27，全唐文）：别的工作区的库一起装进本库，只为匹配、导出时跳过。
            # **只用于新书冷启动**（用户 09-27 定：两套书字形不一样，有人裁之后只用本书
            # 自己的字形）。来源：命令行 --extra-store，或工作区 workspace.yaml 的
            # `glyph_lib.borrow`（有人裁后把它清空、再 rebuild 一次就切到只用自有库）。
            # 不走 glyph_store_path()：它先看 GUJI_GLYPH_STORE，会把每个借库都解析成本书的库
            from .core.workspace import REPO_ROOT, workspace_root
            base = workspace_root() or REPO_ROOT
            no_borrow = getattr(args, "no_borrow", False)
            borrow = list(getattr(args, "extra_store", None) or [])
            if not borrow and not no_borrow and (base / "workspace.yaml").exists():
                import yaml
                wcfg = yaml.safe_load((base / "workspace.yaml").read_text(encoding="utf-8")) or {}
                borrow = list(((wcfg.get("glyph_lib") or {}).get("borrow")) or [])
            # 迁到中心库的工作区可写被借工作区的名字，解析到 db pull 拉好的只读副本（共享方案 S4）
            from .core.workspace import resolve_borrow
            extras = [resolve_borrow(str(x), base) for x in ([] if no_borrow else borrow)]
            missing = [str(p) for p in extras if ".borrowed" in p.parts and not p.is_dir()]
            if missing:
                print(f"借库不存在：{missing}（写中心库工作区名的，先 guji db pull 拉一次）"); sys.exit(1)
            import os
            jobs = getattr(args, "jobs", None) or (os.cpu_count() or 1)
            if extras:
                print(f"借库（冷启动）：{', '.join(map(str, extras))}")
                summary = rebuild_from_store(store_dir, db_path, extra_stores=extras, jobs=jobs)
            else:
                summary = rebuild_from_store(store_dir, db_path, jobs=jobs)
            db = None
            assert_db_not_silently_empty(db_path, store_dir)
            # 补放两次导出之间审进库、真源还没跟上的人裁（值守 #115，2026-09-27）；--no-replay 跳过
            if not getattr(args, "no_replay", False):
                from .core.workspace import feedback_root
                from .feedback.replay import replay_after_rebuild
                summary = {**summary, "replay": replay_after_rebuild(db_path, store_dir, feedback_root())}
        elif args.action == "drop-edition":
            if not args.edition:
                print("drop-edition 需要 --edition"); sys.exit(1)
            summary = db.drop_edition(args.edition)
        elif args.action == "import-font":
            from .clustering.font_glyphs import import_fonts_from_manifest
            summary = import_fonts_from_manifest(
                db, args.manifest, only=args.edition,
                charset=args.charset, limit=args.limit,
                jobs=getattr(args, "jobs", None) or 1, vertical=args.vertical,
                use_pack=not getattr(args, "no_pack", False))
        elif args.action == "font-pack-push":
            summary = _font_pack_push(db, args)
        elif args.action == "set-edition":
            # 一本书一个 edition：把库里全部刻本字形并到 --edition（字形库 06）
            if not args.edition:
                print("set-edition 需要 --edition"); sys.exit(1)
            summary = db.set_book_edition(args.edition, title=args.title,
                                          dry_run=not args.apply)
        elif args.action == "selfcheck":
            # 字形库自检（字形库 03）：本书内 / 对兄弟工作区的库 / 对字体
            from .clustering import glyph_selfcheck as G
            db.close()
            db = None
            others = [] if args.no_others else G.sibling_libraries()
            font_db = G.pick_font_db(db_path, *[p for _, p in others])
            res = G.run_selfcheck(db_path, others, font_db, progress=True)
            out = G.save(res)
            summary = {k: v for k, v in res.items() if k not in ("findings", "all", "inst_sha")}
            summary["out"] = str(out)
        elif args.action == "repair":
            # 字头脏数据 + 同一格的机器副本；默认只报，--apply 才写
            from .clustering.glyph_ledger import (evict_shadow_duplicates,
                                                  label_mismatches,
                                                  repair_glyph_heads,
                                                  semantic_disagreements)
            db.close()
            db = None
            summary = {
                "heads": repair_glyph_heads(db_path, dry_run=not args.apply),
                "shadow": evict_shadow_duplicates(db_path, dry_run=not args.apply),
                "labels": label_mismatches(db_path, apply=args.apply),
                "semantic_disagreements（只报不改，交人裁）":
                    semantic_disagreements(db_path),
            }
        else:
            # 本书套总账（并套口径，见 glyph_ledger 模块头）＋ 原来的表行数
            from .clustering.glyph_ledger import library_summary
            summary = library_summary(db_path, store_dir)
            summary["tables"] = db.stats()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        if db is not None:
            db.close()


def _font_pack_push(db, args) -> dict:
    """`glyph-db font-pack-push`：把库里已导好的字体域导成预建件、存进 R2（`clustering/font_pack.py`）。

    手动跑，要正式令牌（同 `products pack push-index`）。只推与清单、字表、竖排开关对得上的那几套：
    库里记的字体文件与字表 sha（`font_manifests`）和现在算的不一样就不推——包的键按现在的输入算，
    拿旧库的行配新键会让别的机器拷到不对的字形。"""
    from .clustering import font_pack as FP
    from .clustering.font_glyphs import load_charset, load_manifest
    from .clustering.glyph_fp import font_domain_manifest
    import hashlib
    specs, data = load_manifest(args.manifest)
    if args.edition:
        specs = [x for x in specs if x.edition_tag == args.edition]
    chars = load_charset(args.charset or data["charset"])
    have = font_domain_manifest(db.db_path)
    saved, skipped = [], []
    for spec in specs:
        man = have.get(spec.edition_tag) or {}
        want_fonts = {p.name: FP._sha_file(p) for p in spec.font_paths if p.exists()}
        if (man.get("fonts") != want_fonts or bool(man.get("vertical")) != bool(args.vertical)
                or man.get("chars_sha256") != hashlib.sha256("".join(chars).encode("utf-8")).hexdigest()):
            skipped.append({"edition": spec.edition_tag, "why": "库里这套字体域与清单／字表／--vertical 对不上，先重导"})
            continue
        saved.append(FP.save_pack(db, spec, chars, args.vertical))
    from .ops.derived_push import push_packs
    pushed = push_packs()
    if not getattr(args, "keep_pack", False):
        for f in saved:
            f.unlink(missing_ok=True)
    return {"saved": [f.name for f in saved], "pushed": pushed, "skipped": skipped}


#: 字形库按版本钉（GUJI-727，`ops/glyph_snapshot.py`）
PIN_ACTIONS = ("snapshot", "pin-build", "pin-list", "pin-verify", "snapshot-upload")


def _pin_action(args) -> None:
    """`glyph-db snapshot | pin-build | pin-list | pin-verify | snapshot-upload`。只写本机；
    清单推中心库走 `guji db push`（新清单登记的文本随 push 传 R2），`snapshot-upload --execute` 单独补传。"""
    from .core.workspace import workspace_root
    from .ops import glyph_snapshot as G
    ws = workspace_root()
    if ws is None:
        print("要 -w <工作区>"); sys.exit(1)
    need_pin = args.action in ("pin-verify", "snapshot-upload")
    if need_pin and not args.pin:
        print(f"{args.action} 要 --pin N"); sys.exit(1)
    if args.action == "snapshot":
        out = G.snapshot(ws, note=args.note or "", require_clean=not args.allow_dirty)
    elif args.action == "pin-build":
        out = ([G.build_pinned_db(ws, args.pin, force=args.force)] if args.pin
               else G.ensure_pins(ws) if not args.force
               else [G.build_pinned_db(ws, n, force=True) for n in sorted(G.pins_in_use(ws))])
    elif args.action == "pin-list":
        out = G.list_pins(ws)
    elif args.action == "pin-verify":
        out = G.verify_remote(ws, args.pin, full=args.full)
    else:
        out = G.upload_blobs(ws, args.pin, execute=args.execute, full=args.full)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def add_parser(sub) -> None:
    """在 `sub`（argparse 子命令表）上注册 `glyph-db`。"""
    p = sub.add_parser("glyph-db", help="跨书字形数据库（SQLite）")
    p.add_argument("action",
                   choices=["stats", "export", "rebuild",
                            "import-font", "drop-edition", "repair", "selfcheck",
                            "set-edition", "font-pack-push", *PIN_ACTIONS])
    p.add_argument("-w", "--workspace", default=None,
                   help="工作区仓根（含 books/、output/glyph.db）。同 v2 命令那个 -w：给了就覆盖"
                        "本次调用的 GUJI_WORKSPACE，不给就退回读环境变量。任务卡 #54 第13条：这个"
                        "命令以前只认 GUJI_WORKSPACE、没设也不报错，会静默去改 cv 仓自己的 output/。")
    p.add_argument("--allow-sample-db", action="store_true",
                   help="没有工作区时，显式声明就用仓内小样本库（本地试跑/装台子/跑单测才该用；"
                        "同控制台『允许用本地示例库』勾选框）。不加就直接报错退出。")
    p.add_argument("--no-others", action="store_true",
                   help="selfcheck 用：只在本书内比，不拿兄弟工作区的库当参照")
    p.add_argument("--apply", action="store_true",
                   help="repair / set-edition 用：真写库（不加只报告）")
    p.add_argument("--store", default=None,
                   help="字形库目录（真源）。不传按 core.workspace 解析"
                        "（GUJI_WORKSPACE 设了就是 <工作区>/output/glyph_store，"
                        "没设就是仓内样本库）；传相对路径按工作区解释，"
                        "传绝对路径当覆盖")
    p.add_argument("--extra-store", action="append", default=None,
                   help="rebuild 用，可重复：再借一个别的工作区的字形库真源进本库"
                        "（按原 edition 装，只为匹配；export 时跳过，不进本书真源）。"
                        "只用于新书冷启动；不给时读 workspace.yaml 的 glyph_lib.borrow")
    p.add_argument("--no-replay", action="store_true",
                   help="rebuild 用：不补放人裁事件（缺省会把真源水位线之后的人裁 confirm 重新进库）")
    p.add_argument("--no-borrow", action="store_true",
                   help="rebuild 用：不借任何库（无视 workspace.yaml 的 glyph_lib.borrow），只用本书自有库")
    p.add_argument("--edition", default=None,
                   help="版本 edition_tag（import-font 用于只导 manifest 里的某一套字体；"
                        "drop-edition / set-edition 用）")
    p.add_argument("--manifest", default="config/fonts/manifest.json",
                   help="字体清单（import-font 用）")
    p.add_argument("--vertical", action="store_true",
                   help="竖排本：括号类标点（「」《》…）渲染后转 90° 再入库——"
                        "竖排里它们是横放的，不转的话库里的模板跟书上对不上"
                        "（见 font_glyphs.VERTICAL_ROTATED_PUNCT）")
    p.add_argument("--charset", default=None,
                   help="字表文件（import-font 用，默认取 manifest 里的）")
    p.add_argument("--limit", type=int, default=None,
                   help="只导前 N 个字（import-font 冒烟测试用）")
    p.add_argument("--jobs", type=int, default=None,
                   help="并行进程数：import-font 渲染（缺省 1）；rebuild 算派生表示（缺省 CPU 数）。"
                        "渲染、归一、骨架、HOG 是纯 CPU，写库仍单线程，结果与单进程逐位相同")
    p.add_argument("--no-pack", action="store_true",
                   help="import-font 用：不找字体域预建件（本机或 R2），一律逐字渲染")
    p.add_argument("--keep-pack", action="store_true",
                   help="font-pack-push 用：推完把本机导出的包留在 cache/fontdb/（缺省删掉，省盘）")
    p.add_argument("--title", default=None, help="书名")
    p.add_argument("--pin", type=int, default=None,
                   help="pin-build / pin-verify / snapshot-upload 用：字形库版本号 N（g<N>）")
    p.add_argument("--note", default=None, help="snapshot 用：这一版的说明（记进清单）")
    p.add_argument("--force", action="store_true", help="pin-build 用：库在且对得上也重建")
    p.add_argument("--execute", action="store_true",
                   help="snapshot-upload 用：真传 R2（要正式令牌 GUJI_DATA_TOKEN；不加只演练）")
    p.add_argument("--full", action="store_true",
                   help="pin-verify / snapshot-upload 用：全量核对（缺省只核相对上一版新增或改动的条目）")
    p.add_argument("--allow-dirty", action="store_true",
                   help="snapshot 用：数据目录有没推的改动也出（快照就对不上中心库的 rev，只供试验）")

