"""`guji db`：中心库客户端（GUJI-606，设计第五节）。代码在 `open_guji_cv/datastore/`，不进任何 Step 的 code_deps。

    guji db status  [-w <工作区>]                       # 分支、rev、令牌角色、本地快照落后几条
    guji db pull    -w <工作区> [--rev N] [--with-feedback] [--no-rebuild]
    guji db branch  list | create <exp/GUJI-号-说明> [--from-rev N] | delete <名>
    guji db import  --from exp/<名> -w <工作区> [--events ids.txt] [--to main] [--dry-run]

连接：`GUJI_DATA_URL`（缺省 https://data.open-guji.com）、`GUJI_DATA_TOKEN`、`GUJI_DATA_BRANCH`
（缺省 main；也可 `--branch`）。读令牌够 status/pull；开删实验分支要实验令牌；导入正式库要正式令牌，
且写入切换（GUJI-608）之前 Worker 不接受写 main。
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _ws_dir(args) -> Path | None:
    w = getattr(args, "workspace", None) or os.environ.get("GUJI_WORKSPACE")
    return Path(w).expanduser().resolve() if w else None


def _db_path(ws_dir: Path | None) -> Path | None:
    if ws_dir is None:
        return None
    os.environ["GUJI_WORKSPACE"] = str(ws_dir)
    from .core.workspace import glyph_db_path
    return Path(glyph_db_path())


def cmd_db(args) -> None:
    from .datastore.client import WorkerSource
    src = WorkerSource(branch=args.branch)
    ws_dir = _ws_dir(args)

    if args.action == "status":
        from .datastore.pull import status
        _print(status(src, ws_dir, _db_path(ws_dir)))
        return

    if args.action == "pull":
        if ws_dir is None:
            raise SystemExit("db pull 要 -w <工作区>（或 GUJI_WORKSPACE）")
        from .datastore.pull import pull
        res = pull(src, ws_dir, _db_path(ws_dir), rev=args.rev, with_feedback=args.with_feedback,
                   rebuild=not args.no_rebuild, bucket=args.bucket)
        res["worker_requests"] = src.requests
        _print(res)
        return

    if args.action == "branch":
        op = args.args[0] if args.args else "list"
        if op == "list":
            _print(src.branches())
        elif op == "create" and len(args.args) == 2:
            _print(src.create_branch(args.args[1], from_rev=args.from_rev))
        elif op == "delete" and len(args.args) == 2:
            _print(src.delete_branch(args.args[1]))
        else:
            raise SystemExit("用法：guji db branch list | create <exp/GUJI-号-说明> [--from-rev N] | delete <名>")
        return

    if args.action == "import":
        if not args.from_branch or ws_dir is None:
            raise SystemExit("db import 要 --from exp/<名> 和 -w <工作区>")
        from .datastore.pull import import_events, workspace_id
        ids = None
        if args.events:
            ids = {x.strip() for x in Path(args.events).read_text(encoding="utf-8").splitlines()
                   if x.strip() and not x.startswith("#")}
        src_from = WorkerSource(token=src.token, branch=args.from_branch)
        res = import_events(src_from, src, workspace_id(ws_dir), ids, dst_branch=args.to,
                            dry_run=args.dry_run)
        _print(res)
        return


def add_parser(sub) -> None:
    p = sub.add_parser("db", help="中心库：status / pull / branch / import（GUJI-606）")
    p.add_argument("action", choices=["status", "pull", "branch", "import"])
    p.add_argument("args", nargs="*", help="branch 的子命令与分支名")
    p.add_argument("-w", "--workspace", default=None, help="工作区仓根（含 workspace.yaml）；不给读 GUJI_WORKSPACE")
    p.add_argument("--branch", default=None, help="读哪个分支（缺省 GUJI_DATA_BRANCH 或 main）")
    p.add_argument("--rev", type=int, default=None,
                   help="pull：钉版本。工作区在该 rev 之后有变更就报错（中心库不存旧内容）")
    p.add_argument("--with-feedback", action="store_true", help="pull：连 feedback/ 一起还原（人裁事件、台账）")
    p.add_argument("--no-rebuild", action="store_true", help="pull：只还原文件，不重建 glyph.db")
    p.add_argument("--bucket", choices=["main", "exp"], default="main", help="pull：图从哪个桶拉")
    p.add_argument("--from-rev", type=int, default=None, help="branch create：从哪个 rev 开")
    p.add_argument("--from", dest="from_branch", default=None, help="import：实验分支名")
    p.add_argument("--to", default="main", help="import：导入到哪个分支（缺省 main）")
    p.add_argument("--events", default=None, help="import：事件 id 清单文件（一行一个）；不给就导入目标没有的全部")
    p.add_argument("--dry-run", action="store_true", help="import：只列计划不写")
