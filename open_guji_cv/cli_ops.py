# -*- coding: utf-8 -*-
"""运维命令：snap（快照导入）、archive（归档包）、release／deploy（发版与部署检查）。

拆分 P1（`doc/design/拆分-pipeline与manager.md`）从 `cli_v2` 原样搬出；经 `cli_v2.MANAGER_CLI_MODULES` 登记。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def cmd_release(args) -> None:
    """`guji release check`：候选提交跟上一个 `cv-*` tag 比（K 道，2026-09-26）。
    见 `open_guji_cv/ops/release_check.py` 模块头。"""
    from .ops import release_check as rc
    if args.action != "check":
        print(f"未知 action: {args.action}", file=sys.stderr)
        sys.exit(1)
    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent
    res = rc.release_check(repo, args.candidate, against=args.against, version=args.version,
                           run_tests=not args.no_tests)
    if args.json:
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(res.draft)
    if args.write_baseline:
        import json as _json
        baseline_path = repo / rc.BASELINE_REL
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(_json.dumps({"failed": res.test_result["failed"],
                                              "skipped": res.test_result["skipped"],
                                              "version": res.version},
                                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写基线：{baseline_path}", file=sys.stderr)
    if res.test_diff["regressed"]:
        print("✗ 全量测试比上一版多了失败/跳过——这是发布前唯一的硬门槛，见上面「全量测试」一节",
              file=sys.stderr)
        sys.exit(1)


def cmd_deploy(args) -> None:
    """`guji deploy check`：服务器定时器跑，拉模式部署 `production` 分支（K 道，2026-09-26）。
    见 `open_guji_cv/ops/deploy_check.py` 模块头。"""
    from .ops import deploy_check as dc
    if args.action != "check":
        print(f"未知 action: {args.action}", file=sys.stderr)
        sys.exit(1)
    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent
    products_root = Path(args.products).resolve() if args.products else None
    result = dc.deploy_check(repo, branch=args.branch, service=args.service, base_url=args.base_url,
                             products_root=products_root, dry_run=args.dry_run,
                             state_path=repo / "runs" / "deploy_state.json")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    stale = None
    if result.status == dc.DEPLOYED and args.workspace:
        stale = dc.collect_stale_summary(Path(args.workspace).resolve())
        if stale:
            print("过期步（排进夜间重算队列，只写清单不自动起跑批）：", file=sys.stderr)
            for book, steps in sorted(stale.items()):
                print(f"  {book}: {', '.join(steps)}", file=sys.stderr)
    if args.overview and not args.dry_run and result.status != dc.NO_UPDATE:
        path = dc.write_deploy_record(Path(args.overview).resolve(), result, stale_summary=stale)
        print(f"部署记录：{path}", file=sys.stderr)
    if result.status in (dc.FETCH_FAILED, dc.RESOLVE_FAILED, dc.MERGE_FAILED, dc.ROLLED_BACK):
        sys.exit(1)


def cmd_archive(args) -> None:
    """`guji archive fetch <tag> --out <空目录>`：取回 dataset Release 的归档包、核 sha256、解包（GUJI-601）。"""
    from .ops.archive_fetch import ArchiveError, DEFAULT_REPO, fetch
    try:
        res = fetch(args.tag, Path(args.out), repo=args.repo or DEFAULT_REPO, sha256=args.sha256,
                    asset=args.asset, keep_tar=args.keep_tar, no_verify=args.no_verify)
    except ArchiveError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"下一步：guji glyph-db rebuild -w {res['out']} --no-replay"
              "（完整恢复步骤见 ai-team team/整理/GUJI-562/恢复演练步骤.md）")


def cmd_snap(args) -> None:
    """`guji snap pack|import|watch|list`：快照自动导入（K 道，2026-09-27）。
    见 `open_guji_cv/snap/__init__.py` 模块头与 overview 任务书-K-快照自动导入。"""
    from .snap import gitio
    from .snap import importer as imp
    from .snap import watch as sw
    state = Path(args.state).expanduser() if args.state else sw.DEFAULT_STATE
    ws_repo = Path(args.ws_repo).expanduser().resolve() if args.ws_repo else None
    cv_repo = Path(args.cv_repo).expanduser().resolve() if args.cv_repo else Path(__file__).resolve().parent.parent
    ws_roots = [Path(r).expanduser().resolve() for r in (args.ws_root or [])]
    if args.action == "pack":
        from .snap import pack as sp
        if not args.target:
            print("pack 要给书 id", file=sys.stderr)
            sys.exit(2)
        import os
        from .core.workspace import products_root, workspace_root
        ws_dir = Path(args.workspace).expanduser().resolve() if args.workspace else workspace_root()
        if ws_dir is None:
            print("✗ 不知道是哪个工作区：设 GUJI_WORKSPACE 或给 --workspace", file=sys.stderr)
            sys.exit(2)
        # 产物根：--from-products > GUJI_PRODUCTS_DIR（沙箱）> 这个工作区的 products/。
        # 原来直接用 products_root()，给了 -w 但没设 GUJI_WORKSPACE 时会去读仓内 products/（09-27 实测）
        if args.from_products:
            prod = Path(args.from_products).expanduser().resolve()
        elif os.environ.get("GUJI_PRODUCTS_DIR"):
            prod = products_root()
        else:
            prod = ws_dir / "products"
        pages = args.pages
        if pages and pages != "all" and not pages[:1].isdigit():
            from .core.book import load_book
            from .core.workspace import books_dir
            pages = ",".join(str(p) for p in load_book(args.target, books_dir(ws_dir)).resolve_pages(pages))
        overrides: dict[str, dict] = {}
        for kv in args.param or []:
            key, _, val = kv.partition("=")
            step, _, field = key.partition(".")
            try:
                val = json.loads(val)
            except ValueError:
                pass
            overrides.setdefault(step, {})[field] = val
        atts = []
        for a in args.attach or []:
            src, _, dst = a.partition("=")
            root, _, dest = dst.partition(":")
            atts.append(sp.Attachment(root=root, dest=dest, src=Path(src).expanduser().resolve()))
        for a in args.attach_url or []:
            dst, _, rest = a.partition("=")
            root, _, dest = dst.partition(":")
            url, _, sha = rest.rpartition("#")
            atts.append(sp.Attachment(root=root, dest=dest, url=url, sha256=sha))
        idx_files = _snap_index_files(args, ws_dir, cv_repo, ws_repo)
        spec = sp.PackSpec(book=args.target, products_root=prod, ws_dir=ws_dir,
                           steps=[s for s in (args.steps or "").split(",") if s] or None,
                           pages=sp.parse_pages(pages), mode=args.mode,
                           supersedes=[s for s in (args.supersedes or "").split(",") if s],
                           cv_commit=args.cv_commit,
                           compatible_with=[s for s in (args.compatible_with or "").split(",") if s],
                           param_overrides=overrides, attachments=atts, note=args.note or "",
                           stamp=args.stamp, create_workspace=args.create_workspace,
                           allow_downgrade=args.allow_downgrade)
        import tempfile
        with tempfile.TemporaryDirectory(prefix="guji-snap-") as td:
            tree = Path(td) / "tree"
            repo = ws_repo or ws_dir
            top = gitio.default_git(repo, ["rev-parse", "--show-toplevel"])
            if top.returncode != 0:
                print(f"✗ {repo} 不在 git 仓里；给 --ws-repo", file=sys.stderr)
                sys.exit(2)
            if idx_files:
                # 模板索引先上 idx/<kind>/<key>（远端已有同 key 的直接引用、不重推），包里只写引用
                from .snap import indexes as sidx
                host_repo = cv_repo if args.index_repo == "cv" else Path(top.stdout.strip())
                spec.indexes = sidx.publish(host_repo, idx_files, host=args.index_repo,
                                            cv_commit=args.cv_commit or sp._cv_head(cv_repo),
                                            push=not args.no_push, dry_run=args.dry_run)
            m = sp.build_tree(spec, tree, cv_repo=cv_repo)
            # --dry-run：只打印计划，不建提交、不建本地分支、不推（原来 pack 根本不看 --dry-run，
            # 照样真推——整理 Z21/Z22/Z23 三道都踩过，#174）
            if args.dry_run:
                commit = None
                size = sum(f.stat().st_size for f in tree.rglob("*") if f.is_file())
            else:
                commit = sp.commit_and_push(Path(top.stdout.strip()), tree, m, push=not args.no_push)
        out = {"branch": m["branch"], "commit": commit, "book": m["book"], "mode": m["mode"],
               "steps": m["steps"], "pages": len(m["pages"]), "files": len(m["files"]),
               "attachments": len(m["attachments"]),
               "indexes": [{k: e.get(k) for k in ("kind", "key", "dest", "branch", "size", "reused", "label")}
                           for e in m.get("indexes", [])],
               "cv": m["cv"]["commit"],
               "pushed": not args.no_push and not args.dry_run}
        if args.dry_run:
            out.update(dry_run=True, bytes=size, supersedes=m.get("supersedes", []),
                       plan=f"演练：会推 {m['branch']}（未建提交、未推）")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if args.action == "import-index":
        # 值守手动：不经 snap 包，按 idx 分支名直接落一张模板索引（已在就跳过）
        from .snap import indexes as sidx
        if not args.target:
            print("import-index 要给分支名（idx/<kind>/<key>）", file=sys.stderr)
            sys.exit(2)
        ws_dir = Path(args.workspace).expanduser().resolve() if args.workspace else None
        try:
            row = sidx.import_branch(args.target, host=args.index_repo, ws_repo=ws_repo, cv_repo=cv_repo,
                                     ws_dir=ws_dir, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001
            print(f"✗ {type(e).__name__}: {e}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(row, ensure_ascii=False))
        return
    if ws_repo is None:
        print("✗ 要给 --ws-repo（服务器上 guji-workspace 的 clone）", file=sys.stderr)
        sys.exit(2)
    if not ws_roots:
        ws_roots = [ws_repo]
    if args.action == "list":
        for row in sw.list_packs(ws_repo, state):
            print(f"{row['status']:<13} {row['branch']}  {row['commit'][:10]}  {row['at'] or ''}")
        return
    if args.action == "import":
        if not args.target:
            print("import 要给分支名（snap/…）", file=sys.stderr)
            sys.exit(2)
        r = imp.import_pack(args.target, ws_repo=ws_repo, ws_roots=ws_roots, cv_repo=cv_repo,
                            dry_run=args.dry_run, force=args.force)
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2, default=str))
        if not args.dry_run:
            sw.remember(state, r)   # 定时器据此不再重导同一提交
        if args.overview and not args.dry_run:
            path = sw.write_import_record(Path(args.overview).expanduser().resolve(), [r],
                                          push=not args.no_push)
            print(f"导入记录：{path}", file=sys.stderr)
        sys.exit(0 if r.status in (imp.IMPORTED, imp.WOULD_IMPORT) else 1)
    if args.action == "watch":
        out = sw.watch(ws_repo=ws_repo, ws_roots=ws_roots, cv_repo=cv_repo, state_path=state,
                       overview=Path(args.overview).expanduser().resolve() if args.overview else None,
                       dry_run=args.dry_run, push=not args.no_push)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        if out.get("status") in ("ls_remote_failed", "fetch_failed"):
            sys.exit(1)
        return


def _snap_index_files(args, ws_dir: Path, cv_repo: Path, ws_repo: Path | None) -> list:
    """`snap pack --rare-index/--font-index` → 要带的表（`snap.indexes.IndexFile`）。
    key 要按这本书的字表算，字表叠加了工作区里的整理本语料，所以临时把 GUJI_WORKSPACE 指过来。
    本地没建、但索引仓远端已有同 key 的 idx 分支也行（只引用），所以先 ls-remote 一次。"""
    if not (args.rare_index or args.font_index):
        return []
    import os
    from .snap import gitio
    from .snap import indexes as sidx
    try:
        have = set(sidx.remote_index_branches(cv_repo if args.index_repo == "cv" else (ws_repo or ws_dir)))
    except gitio.GitError as e:
        print(f"  ⚠️ 查不了远端 idx 分支（{e}），只认本地已建的表", file=sys.stderr)
        have = set()
    saved = os.environ.get("GUJI_WORKSPACE")
    os.environ["GUJI_WORKSPACE"] = str(ws_dir)
    try:
        out = []
        if args.rare_index:
            out += sidx.rare_index_files(args.target, args.rare_index, cv_repo, have)
        if args.font_index:
            out += sidx.font_index_files(args.target if args.font_index == "book" else None, have)
        return out
    except FileNotFoundError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(2)
    finally:
        if saved is None:
            os.environ.pop("GUJI_WORKSPACE", None)
        else:
            os.environ["GUJI_WORKSPACE"] = saved


def add_parser(sub) -> None:
    p = sub.add_parser("release", help="[v2] 发版前检查：release check <commit>（K 道，2026-09-26）")
    p.add_argument("action", choices=["check"])
    p.add_argument("candidate", nargs="?", default="HEAD", help="候选提交，默认当前 HEAD")
    p.add_argument("--against", default=None, help="对比的旧提交/tag，默认上一个 cv-* tag")
    p.add_argument("--version", default=None, help="版本号，默认 cv-YYYY.MM.DD（当天已有就加 -2/-3）")
    p.add_argument("--repo", default=None, help="cv 仓根，默认本模块所在的仓")
    p.add_argument("--no-tests", action="store_true", help="跳过全量测试（只看指纹影响清单，调试用）")
    p.add_argument("--write-baseline", action="store_true",
                   help="把这次的失败/跳过写成新基线（ops/baseline_tests.json），发布通过后再加")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("deploy", help="[v2] 服务器部署检查：deploy check（K 道，2026-09-26）")
    p.add_argument("action", choices=["check"])
    p.add_argument("--repo", default=None, help="cv 仓（服务器上跟 production 分支的那个 checkout），默认本模块所在的仓")
    p.add_argument("--branch", default="production")
    p.add_argument("--service", default="guji-cv-console", help="systemd --user 服务名")
    p.add_argument("--base-url", default="http://127.0.0.1:8640", help="健康检查打的地址")
    p.add_argument("--products", default=None, help="products 根目录，探测跑批锁用；不给就不查锁")
    p.add_argument("--workspace", default=None, help="部署成功后 guji status 各书要用的工作区")
    p.add_argument("--overview", default=None, help="overview 仓路径，成功/失败都写一张部署记录并推")
    p.add_argument("--dry-run", action="store_true", help="只打印会做什么，不改任何东西")
    p = sub.add_parser("archive", help="[v2] 归档包：fetch 取回 open-guji-dataset Release 上的归档 tar，核 sha256 后解到空目录")
    p.add_argument("action", choices=["fetch"])
    p.add_argument("tag", help="Release tag，如 archive-96mid1ogzk-vol03-0.1.0-1")
    p.add_argument("--out", required=True, help="解到哪个目录（必须不存在或为空）")
    p.add_argument("--repo", default=None, help="默认 open-guji/open-guji-dataset")
    p.add_argument("--sha256", default=None, help="应有的 sha256；不给就用 Release 资产自带的 digest")
    p.add_argument("--asset", default=None, help="Release 里有多个 .tar 时指定文件名")
    p.add_argument("--keep-tar", action="store_true", help="解完把 tar 留在 --out 旁边")
    p.add_argument("--no-verify", action="store_true", help="没有 sha256 可核时仍然解（不建议）")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("snap", help="[v2] 快照自动导入：pack（云端打包推分支）/ import / watch（服务器定时器）/ list")
    p.add_argument("action", choices=["pack", "import", "watch", "list", "import-index"])
    # dest 不叫 book：不走「带 book 的命令必填 -w」那层包装（import 的位置参数是分支名）
    p.add_argument("target", nargs="?", default=None,
                   help="pack：书 id；import：分支名 snap/…；import-index：分支名 idx/<kind>/<key>")
    p.add_argument("-w", "--workspace", default=None, help="pack：书的工作区目录，默认 GUJI_WORKSPACE；import-index：font_hog 落哪个工作区")
    p.add_argument("--from-products", default=None,
                   help="pack：从这个 products 根读（如旧快照目录），默认当前 products 根")
    p.add_argument("--pages", default=None, help="pack：页集（1-5,9 / all / 命名页集），默认 all")
    p.add_argument("--steps", default=None, help="pack：逗号分隔的步，默认这本书现有的全部步")
    p.add_argument("--mode", default="replace-steps", choices=["replace-steps", "display-only", "attach-only"],
                   help="attach-only：纯附件包（如 rare 预建索引），本地不需要 products，target 当标签用")
    p.add_argument("--supersedes", default=None, help="pack：作废哪些旧包（逗号分隔的分支名）")
    p.add_argument("--cv-commit", default=None, help="pack：产物是哪个 cv 提交算的，默认 cv 仓 HEAD")
    p.add_argument("--compatible-with", default=None, help="pack：另声明与这些 cv 提交兼容（逗号分隔）")
    p.add_argument("--param", action="append", help="pack：记一条参数覆盖 step.key=value，可重复")
    p.add_argument("--attach", action="append", help="pack：附件 SRC=cv:相对路径 或 SRC=ws:相对路径")
    p.add_argument("--attach-url", action="append", help="pack：外链附件 cv:相对路径=URL#sha256")
    p.add_argument("--rare-index", nargs="?", const="all", default=None, choices=["all", "base", "escalate"],
                   help="pack：带上这本书的 Step5-b embedding 索引（先 `guji cache build-rare-index`）。"
                        "大文件进 idx/rare_emb/<key> 分支、按 key 去重，包里只写引用")
    p.add_argument("--font-index", nargs="?", const="book", default=None, choices=["book", "default"],
                   help="pack：带上控制台 HOG 字体索引（先 `guji cache build-font-index`）；"
                        "book=按这本书的语料，default=控制台启动预热用的默认语料")
    p.add_argument("--index-repo", default="ws", choices=["ws", "cv"],
                   help="pack / import-index：idx 分支挂在哪个仓的 origin（缺省 ws=guji-workspace；cv=open-guji-cv）")
    p.add_argument("--note", default=None)
    p.add_argument("--stamp", default=None, help="pack：分支时戳，默认当前 UTC yyyymmddThhmm")
    p.add_argument("--create-workspace", action="store_true",
                   help="pack：允许服务器上还没有这个工作区时新建（新书第一包）")
    p.add_argument("--allow-downgrade", action="store_true",
                   help="pack：导入后新鲜度变差也照换（缺省会整包换回、报 downgrade）")
    p.add_argument("--ws-repo", default=None, help="guji-workspace 的 git clone（pack 默认工作区所在仓）")
    p.add_argument("--ws-root", action="append", help="import/watch：到哪找书的工作区目录，可重复；默认 --ws-repo")
    p.add_argument("--cv-repo", default=None, help="import/watch：判 cv 兼容用的 cv 仓，默认本模块所在的仓")
    p.add_argument("--overview", default=None, help="import/watch：写导入记录并推的 overview 仓")
    p.add_argument("--state", default=None, help="watch/list：状态文件，默认 ~/.local/state/guji_snap/state.json")
    p.add_argument("--dry-run", action="store_true",
                   help="pack：只打印计划（分支名、页数、文件数），不建提交、不推；import/watch：只校验不替换")
    p.add_argument("--force", action="store_true", help="import：被作废的包、会降级的包也照导")
    p.add_argument("--no-push", action="store_true", help="pack：只建本地分支；import/watch：记录只提交不推")


#: 并进 `guji` 的子命令（同插件接口 `guji.commands`）
COMMANDS = {
    "snap": (add_parser, cmd_snap),
    "archive": (add_parser, cmd_archive),
    "release": (add_parser, cmd_release),
    "deploy": (add_parser, cmd_deploy),
}
