"""`guji db`：中心库客户端（GUJI-606，设计第五节）。代码在 `open_guji_cv/datastore/`，不进任何 Step 的 code_deps。

    guji db status  [-w <工作区>]                       # 分支、rev、令牌角色、本地快照落后几条
    guji db pull    -w <工作区> [--rev N] [--with-feedback] [--no-rebuild]
    guji db branch  list | create <exp/GUJI-号-说明> [--from-rev N] | delete <名>
    guji db import  --from exp/<名> -w <工作区> [--events ids.txt] [--to main] [--dry-run]
    guji db pull    -w <工作区> --full [--force]         # 写入切换后（GUJI-608）：中心库 → 工作区本身
    guji db push    -w <工作区> [--dry-run] [--allow-delete]   # 工作区改动 → 中心库，先比版本号

连接：`GUJI_DATA_URL`（缺省 https://data.open-guji.com）、`GUJI_DATA_TOKEN`、`GUJI_DATA_BRANCH`
（缺省 main；也可 `--branch`）。读令牌够 status/pull；开删实验分支要实验令牌；导入正式库要正式令牌，
且写入切换（GUJI-608）之前 Worker 不接受写 main。

push 直连 Postgres：``GUJI_DATA_PG_DSN``；没有就用 ``NEON_DATABASE_URL`` 自动在本进程起
WebSocket 桥（云会话只通 443）。新图经 Worker 传 R2，要正式令牌（``GUJI_DATA_TOKEN``）。
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


def rebuild_db(ws_dir: Path, store: Path, db_path: Path) -> dict:
    """同 ``guji glyph-db rebuild --no-replay --no-borrow --store <store>``。"""
    import yaml
    from .clustering.glyph_db import assert_db_not_silently_empty, rebuild_from_store
    wcfg = yaml.safe_load((Path(ws_dir) / "workspace.yaml").read_text(encoding="utf-8")) or {}
    if ((wcfg.get("glyph_lib") or {}).get("borrow")):
        raise SystemExit("workspace.yaml 配了 glyph_lib.borrow（借库）：db pull 暂不支持借库，"
                         "请先用 guji glyph-db rebuild")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    summary = rebuild_from_store(store, db_path)
    assert_db_not_silently_empty(db_path, store)
    return summary



def _pg_conn():
    import psycopg
    dsn = os.environ.get("GUJI_DATA_PG_DSN")
    if not dsn:
        url = os.environ.get("NEON_DATABASE_URL")
        if not url:
            raise SystemExit("db push 要连库：设 GUJI_DATA_PG_DSN，或 NEON_DATABASE_URL（自动经 443 桥）")
        from .datastore.wsbridge import neon_dsn_via_bridge
        dsn = neon_dsn_via_bridge(url)
    return psycopg.connect(dsn)


def cmd_db(args) -> None:
    from .datastore.client import WorkerSource
    ws_dir = _ws_dir(args)

    if args.action == "push":
        if ws_dir is None:
            raise SystemExit("db push 要 -w <工作区>（或 GUJI_WORKSPACE）")
        from .datastore.push import push_dir
        from .datastore.r2 import upload_files
        if (args.branch or os.environ.get("GUJI_DATA_BRANCH") or "main") != "main":
            raise SystemExit("db push 只写 main；实验分支请用 guji exp")
        actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
        with _pg_conn() as conn:
            res = push_dir(conn, ws_dir, actor=actor, dry_run=args.dry_run,
                           allow_delete=args.allow_delete,
                           uploader=lambda imgs: upload_files(imgs, bucket="main"))
        _print(res)
        return

    src = WorkerSource(branch=args.branch)

    if args.action == "status":
        from .datastore.pull import status
        _print(status(src, ws_dir, _db_path(ws_dir)))
        return

    if args.action == "pull":
        if ws_dir is None:
            raise SystemExit("db pull 要 -w <工作区>（或 GUJI_WORKSPACE）")
        if args.full:
            from .datastore.client import BlobCache
            from .datastore.push import pull_full
            res = pull_full(src, ws_dir, cache=BlobCache(), bucket=args.bucket, force=args.force)
            if not args.no_rebuild:
                res["glyph_db"] = rebuild_db(ws_dir, ws_dir / "output" / "glyph_store", _db_path(ws_dir))
            res["worker_requests"] = src.requests
            _print(res)
            return
        from .datastore.pull import pull
        res = pull(src, ws_dir, _db_path(ws_dir), rev=args.rev, with_feedback=args.with_feedback,
                   rebuild=None if args.no_rebuild else rebuild_db, bucket=args.bucket)
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
    p = sub.add_parser("db", help="中心库：status / pull / push / branch / import（GUJI-606/608）")
    p.add_argument("action", choices=["status", "pull", "push", "branch", "import"])
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
    p.add_argument("--dry-run", action="store_true", help="import/push：只列计划不写")
    p.add_argument("--full", action="store_true",
                   help="pull：还原进工作区本身（workspace.yaml、books/、feedback/、review/、config/、字形库），写 .central.json")
    p.add_argument("--force", action="store_true", help="pull --full：丢掉本地没 push 的改动")
    p.add_argument("--allow-delete", action="store_true",
                   help="push：允许删库里的文件、只追加台账里的行（确认是真删）")
