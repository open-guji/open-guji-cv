"""`guji db`：中心库客户端（GUJI-606/608）。代码在 `open_guji_cv/datastore/`，不进任何 Step 的 code_deps。

写入切换（GUJI-608）后中心库是这些数据唯一的家：册 yaml、人裁事件、台账、批次、人工配置、字形库。
工作区里只留 workspace.yaml（身份）与 `.central.json` 标记；数据在工作区外的数据目录
（`$GUJI_DATA_HOME`，缺省 `~/.guji-data`，下面按 <分支>/<工作区 id>/）。

    guji db migrate -w <工作区> [--keep-local] [--dry-run]   # 一次性：工作区里的数据挪进数据目录
    guji db pull    -w <工作区> [--force]                     # 中心库 → 数据目录（有新字形库才重建 glyph.db）
    guji db push    -w <工作区> [--dry-run] [--allow-delete]  # 数据目录 → 中心库，先比版本号
    guji db sync    -w <工作区> [--dry-run] [--watch 秒]      # 拉＋合并＋推一步做完；--watch 定时反复做
    guji db status  [-w <工作区>]                             # rev、令牌角色、本地落后几条、没推的文件
    guji db branch  list | create <exp/GUJI-号-说明> [--from-rev N] | delete <名>
    guji db import  --from exp/<名> -w <工作区> [--events ids.txt] [--to main] [--dry-run]

连接：`GUJI_DATA_URL`（缺省 https://data.open-guji.com）、`GUJI_DATA_TOKEN`、`GUJI_DATA_BRANCH`（缺省 main）。
push 直连 Postgres：`GUJI_DATA_PG_DSN`，没有就用 `NEON_DATABASE_URL` 在本进程起 443 桥；新图经 Worker 传正式桶。
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


from .ops.central_glyph import export_db, glyph_hooks, rebuild_db  # noqa: E402,F401  （旧入口）


def _pg_conn():
    from .datastore.connect import connect
    return connect()


def push_workspace(ws_dir: Path, *, dry_run: bool = False, allow_delete: bool = False) -> dict:
    """``guji db push`` 的实现（``guji store commit`` 在已迁移的工作区上也走这里）。"""
    from .datastore.r2 import upload_files
    from .datastore.workcopy import push
    actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
    with _pg_conn() as conn:
        return push(conn, ws_dir, actor=actor, dry_run=dry_run, allow_delete=allow_delete,
                    uploader=lambda imgs: upload_files(imgs, bucket="main"), glyph=glyph_hooks(ws_dir))


def sync_workspace(ws_dir: Path, *, dry_run: bool = False, src=None) -> dict:
    """``guji db sync`` 一轮：库里有新改动先合进来（只追加台账两边的新行都留），再推本地的。"""
    from .datastore.client import BlobCache, WorkerSource
    from .datastore.r2 import upload_files
    from .datastore.workcopy import sync
    actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
    src = src or WorkerSource()
    with _pg_conn() as conn:
        return sync(src, conn, ws_dir, actor=actor, cache=BlobCache(), dry_run=dry_run,
                    uploader=lambda imgs: upload_files(imgs, bucket="main"), glyph=glyph_hooks(ws_dir))


def _watch(ws_dir: Path, interval: int, dry_run: bool) -> None:
    """定时 sync（替代旧的 guji-glyph-store-sync.timer）。冲突、网络错都只记一行，下一轮再试。"""
    import sys
    import time
    from datetime import datetime

    from .datastore.workcopy import SyncConflict
    while True:
        at = datetime.now().isoformat(timespec="seconds")
        try:
            res = sync_workspace(ws_dir, dry_run=dry_run)
            print(json.dumps({"at": at, "action": res["action"], "local": len(res["local_changes"]),
                              "merged": res.get("merged", []), "rev": res.get("rev_remote")},
                             ensure_ascii=False), flush=True)
        except SyncConflict as e:
            print(json.dumps({"at": at, "conflict": str(e)}, ensure_ascii=False), file=sys.stderr, flush=True)
        except (Exception, SystemExit) as e:  # noqa: BLE001  断网、连库失败、读到一半有人写都下一轮再试
            print(json.dumps({"at": at, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False),
                  file=sys.stderr, flush=True)
        time.sleep(interval)


def cmd_db(args) -> None:
    from .datastore.client import BlobCache, WorkerSource
    ws_dir = _ws_dir(args)
    need_ws = {"pull", "push", "sync", "migrate", "import"}
    if args.action in need_ws and ws_dir is None:
        raise SystemExit(f"db {args.action} 要 -w <工作区>（或 GUJI_WORKSPACE）")

    if args.action == "push":
        if (args.branch or os.environ.get("GUJI_DATA_BRANCH") or "main") != "main":
            raise SystemExit("db push 只写 main；实验照旧用 guji exp 和实验分支")
        _print(push_workspace(ws_dir, dry_run=args.dry_run, allow_delete=args.allow_delete))
        return

    if args.action == "sync":
        if (args.branch or os.environ.get("GUJI_DATA_BRANCH") or "main") != "main":
            raise SystemExit("db sync 只写 main")
        if args.watch:
            _watch(ws_dir, args.watch, args.dry_run)
        _print(sync_workspace(ws_dir, dry_run=args.dry_run))
        return

    src = WorkerSource(branch=args.branch)

    if args.action == "status":
        from .datastore.pull import status
        _print(status(src, ws_dir))
        return

    if args.action == "pull":
        from .datastore.workcopy import pull
        res = pull(src, ws_dir, cache=BlobCache(), bucket=args.bucket, force=args.force,
                   glyph=None if args.no_rebuild else glyph_hooks(ws_dir))
        res["worker_requests"] = src.requests
        _print(res)
        return

    if args.action == "migrate":
        from .datastore.workcopy import migrate
        res = migrate(src, ws_dir, cache=BlobCache(), bucket=args.bucket, keep_local=args.keep_local,
                      dry_run=args.dry_run, glyph=glyph_hooks(ws_dir))
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
        if not args.from_branch:
            raise SystemExit("db import 要 --from exp/<名>")
        from .datastore.pull import import_events, workspace_id
        ids = None
        if args.events:
            ids = {x.strip() for x in Path(args.events).read_text(encoding="utf-8").splitlines()
                   if x.strip() and not x.startswith("#")}
        src_from = WorkerSource(token=src.token, branch=args.from_branch)
        _print(import_events(src_from, src, workspace_id(ws_dir), ids, dst_branch=args.to, dry_run=args.dry_run))
        return


def add_parser(sub) -> None:
    p = sub.add_parser("db", help="中心库：migrate / pull / push / status / branch / import（GUJI-606/608）")
    p.add_argument("action", choices=["status", "migrate", "pull", "push", "sync", "branch", "import"])
    p.add_argument("args", nargs="*", help="branch 的子命令与分支名")
    p.add_argument("-w", "--workspace", default=None, help="工作区仓根（含 workspace.yaml）；不给读 GUJI_WORKSPACE")
    p.add_argument("--branch", default=None, help="读哪个分支（缺省 GUJI_DATA_BRANCH 或 main）")
    p.add_argument("--no-rebuild", action="store_true", help="pull：不重建 glyph.db")
    p.add_argument("--force", action="store_true", help="pull：丢掉本地没推的改动")
    p.add_argument("--bucket", choices=["main", "exp"], default="main", help="pull/migrate：图从哪个桶拉")
    p.add_argument("--keep-local", action="store_true",
                   help="migrate：工作区里与库不一致的文件以本地为准，迁完成为待推改动")
    p.add_argument("--allow-delete", action="store_true",
                   help="push：允许删库里的文件、只追加台账里的行（确认是真删）")
    p.add_argument("--from-rev", type=int, default=None, help="branch create：从哪个 rev 开")
    p.add_argument("--from", dest="from_branch", default=None, help="import：实验分支名")
    p.add_argument("--to", default="main", help="import：导入到哪个分支（缺省 main）")
    p.add_argument("--events", default=None, help="import：事件 id 清单文件（一行一个）；不给就导入目标没有的全部")
    p.add_argument("--dry-run", action="store_true", help="migrate/push/sync/import：只列计划不写")
    p.add_argument("--watch", type=int, default=None, metavar="秒", help="sync：每隔这么多秒做一轮，不退出")
