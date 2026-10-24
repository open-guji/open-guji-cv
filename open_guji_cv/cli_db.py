"""`guji db`：中心库客户端（GUJI-606/608）。代码在 `open_guji_cv/datastore/`，不进任何 Step 的 code_deps。

写入切换（GUJI-608）后中心库是这些数据唯一的家：册 yaml、人裁事件、台账、批次、人工配置、字形库。
工作区里只留 workspace.yaml（身份）与 `.central.json` 标记；数据在工作区外的数据目录
（`$GUJI_DATA_HOME`，缺省 `~/.guji-data`，下面按 <分支>/<工作区 id>/）。

    guji db migrate -w <工作区> [--keep-local] [--dry-run]   # 一次性：工作区里的数据挪进数据目录
    guji db pull    -w <工作区> [--force]                     # 中心库 → 数据目录（有新字形库才重建 glyph.db）
    guji db push    -w <工作区> [--dry-run] [--allow-delete]  # 数据目录 → 中心库，先比版本号
    guji db sync    -w <工作区> [--dry-run] [--watch 秒] [--no-admit]  # 拉＋合并＋顺带落库＋推；--watch 定时反复做
    guji db status  [-w <工作区>]                             # rev、令牌角色、本地落后几条、没推的文件
    guji db branch  list | create <exp/GUJI-号-说明> [--from-rev N] | delete <名>
    guji db import  --from exp/<名> -w <工作区> [--events ids.txt] [--to main] [--dry-run]
    guji db diff    -w <工作区> --branch exp/<名> [--against main]   # 实验分支与正式库逐文件比

连接：`GUJI_DATA_URL`（缺省 https://data.open-guji.com）、`GUJI_DATA_TOKEN`、`GUJI_DATA_BRANCH`（缺省 main）。
push 直连 Postgres：`GUJI_DATA_PG_DSN`，没有就用 `NEON_DATABASE_URL` 在本进程起 443 桥；新图经 Worker 传正式桶。

实验分支（`--branch exp/GUJI-号-说明` 或 `GUJI_DATA_BRANCH`）：数据目录换成 `$GUJI_DATA_HOME/exp__GUJI-…/<工作区>/`，
glyph.db 与 products 也放进去；pull／push／sync 都对那个分支，push 经 Neon API（`NEON_API_KEY`）找到该分支的端点，
新图传实验桶。只许 main 与 `exp/*`；ci 只给测试。
"""
from __future__ import annotations

import json
import os
import sys
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


def _branch() -> str:
    return os.environ.get("GUJI_DATA_BRANCH") or "main"


def _check_write_branch(branch: str) -> None:
    from .datastore.client import is_exp_branch
    if branch != "main" and not is_exp_branch(branch):
        raise SystemExit(f"只能写 main 或实验分支 exp/GUJI-<号>[-说明]，不能写 {branch}")


def _pg_conn(branch: str | None = None):
    """连 ``branch``（缺省 ``GUJI_DATA_BRANCH`` 或 main）的 Postgres。实验分支经 Neon API 找端点。"""
    from .datastore.connect import connect
    branch = branch or _branch()
    if branch == "main":
        return connect()
    _check_write_branch(branch)
    from .datastore.neonapi import branch_endpoint
    return connect(endpoint=branch_endpoint(branch))


def _bucket(branch: str) -> str:
    return "main" if branch == "main" else "exp"


def push_workspace(ws_dir: Path, *, dry_run: bool = False, allow_delete: bool = False) -> dict:
    """``guji db push`` 的实现（``guji store commit`` 在已迁移的工作区上也走这里）。"""
    from .datastore.r2 import upload_files
    from .datastore.workcopy import push
    actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
    branch = _branch()
    _check_write_branch(branch)
    with _pg_conn(branch) as conn:
        return push(conn, ws_dir, actor=actor, dry_run=dry_run, allow_delete=allow_delete,
                    uploader=lambda imgs, ext="png": upload_files(imgs, bucket=_bucket(branch), ext=ext),
                    glyph=glyph_hooks(ws_dir))


def _ensure_glyph_pins(ws_dir: Path, res: dict) -> None:
    """拉完以后，各册钉的字形库版本（有快照的）本机没建库就建（GUJI-727）。建不成只记一行，不让拉取失败。"""
    from .ops.glyph_snapshot import ensure_pins
    try:
        built = [r for r in ensure_pins(ws_dir, log=lambda s: print(s, file=sys.stderr)) if not r.get("reused")]
    except SystemExit as e:
        res["glyph_pins_error"] = str(e)
        return
    if built:
        res["glyph_pins_built"] = [r["pin"] for r in built]


def sync_workspace(ws_dir: Path, *, dry_run: bool = False, src=None, admit: bool = True) -> dict:
    """``guji db sync`` 一轮：库里有新改动先合进来（只追加台账两边的新行都留），再推本地的。

    合完之后把还没落库的人裁落进字形库（``feedback/auto_admit.py``，``admit=False`` 或 ``GUJI_AUTO_ADMIT=0`` 关），
    落了就再推一次，结果记在 ``glyph_admit``／``after_admit``。"""
    from .datastore.client import BlobCache, WorkerSource
    from .datastore.r2 import upload_files
    from .datastore.workcopy import sync
    from .feedback import auto_admit
    actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
    branch = _branch()
    _check_write_branch(branch)
    src = src or WorkerSource(branch=branch)

    def once() -> dict:
        with _pg_conn(branch) as conn:
            return sync(src, conn, ws_dir, actor=actor, cache=BlobCache(), dry_run=dry_run,
                        uploader=lambda imgs, ext="png": upload_files(imgs, bucket=_bucket(branch), ext=ext),
                        glyph=glyph_hooks(ws_dir), replay=lambda ids: _reconsume(ws_dir, ids))

    res = once()
    if admit and auto_admit.enabled():
        res["glyph_admit"] = _admit_pending(ws_dir, dry_run)
        if not dry_run and auto_admit.touched(res["glyph_admit"]):
            res["after_admit"] = once()
    return res


def _admit_pending(ws_dir: Path, dry_run: bool) -> dict:
    """本工作区待落库的人裁跑一遍字形库两个消费者（消费者按 ``GUJI_WORKSPACE`` 找 glyph.db、产物与字块缓存）。"""
    from .core.workspace import feedback_root
    from .feedback.auto_admit import admit_pending
    from .feedback.events import EventLog
    os.environ["GUJI_WORKSPACE"] = str(ws_dir)
    try:
        return admit_pending(EventLog(feedback_root()), dry_run=dry_run)
    except Exception as e:                  # noqa: BLE001 —— 落库失败不挡同步本身，报出来、下一轮再试
        return {"error": f"{type(e).__name__}: {e}"}


def _reconsume(ws_dir: Path, ids: set[str]) -> dict:
    """sync 取了库里的字形库后，本地新人裁事件在它上面重新过一遍消费者（只有字形库消费者的记账被删了，别的跳过）。"""
    from .core.workspace import feedback_root, verdicts_root
    from .feedback.consumers import route_and_consume
    from .feedback.events import EventLog
    from .feedback.routes import RouteTable
    from .gold.store import GoldStore
    os.environ["GUJI_WORKSPACE"] = str(ws_dir)          # 消费者（glyph.db、排除名单）都按工作区找路径
    log = EventLog(feedback_root())
    out = route_and_consume(log, table=RouteTable.load(log.root / "routes.yaml"), store=GoldStore(verdicts_root()),
                            event_ids=ids)
    return {"events": len(ids), "results": [str(r) for r in out["results"]], "unrouted": len(out["unrouted"])}


def route_imported(ws_dir: Path, ids: set[str], *, branch: str) -> dict:
    """导回的事件经 Worker 直写进库，没走控制台「写完就 route」（规范 §9 F-7）：拉下来、只对这几条跑消费者、再推。

    本机副本不是 ``branch`` 那个分支的就不跑（消费者要写的是那个分支的工作区），返回里说明，留给那边补跑。"""
    from .core.workspace import feedback_root, verdicts_root
    from .feedback.consumers import route_and_consume
    from .feedback.events import EventLog
    from .feedback.routes import RouteTable
    from .gold.store import GoldStore
    if _branch() != branch:
        return {"skipped": f"本机副本在分支 {_branch()}，事件导进了 {branch}；到 {branch} 的副本上 guji db sync 后 "
                           f"guji events route"}
    pulled = sync_workspace(ws_dir, admit=False)     # 这几条下面连同别的消费者一起跑
    os.environ["GUJI_WORKSPACE"] = str(ws_dir)          # 消费者（glyph.db、排除名单）都按工作区找路径
    log = EventLog(feedback_root())
    out = route_and_consume(log, table=RouteTable.load(log.root / "routes.yaml"), store=GoldStore(verdicts_root()),
                            event_ids=ids)
    pushed = sync_workspace(ws_dir)
    return {"pulled": pulled.get("action"), "results": out["results"], "unrouted": len(out["unrouted"]),
            "pushed": pushed.get("action")}


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
            admitted = {c: r.get("marked", r.get("events")) for c, r in (res.get("glyph_admit") or {}).items()
                        if isinstance(r, dict)}
            print(json.dumps({"at": at, "action": res["action"], "local": len(res["local_changes"]),
                              "merged": res.get("merged", []), "rev": res.get("rev_remote"),
                              **({"glyph_admit": admitted} if admitted else {})},
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
    if args.action in need_ws | {"diff"} and ws_dir is None:
        raise SystemExit(f"db {args.action} 要 -w <工作区>（或 GUJI_WORKSPACE）")
    if args.branch and args.action not in ("branch", "import"):
        # --branch 等于设 GUJI_DATA_BRANCH：数据目录、glyph.db、products、连库都跟着换（core.workspace.central_marker）
        os.environ["GUJI_DATA_BRANCH"] = args.branch

    if args.action == "push":
        _print(push_workspace(ws_dir, dry_run=args.dry_run, allow_delete=args.allow_delete))
        return

    if args.action == "sync":
        if args.watch:
            _watch(ws_dir, args.watch, args.dry_run)
        res = sync_workspace(ws_dir, dry_run=args.dry_run, admit=not args.no_admit)
        if not args.dry_run:
            _ensure_glyph_pins(ws_dir, res)
        _print(res)
        left = {c: r.get("left") for c, r in (res.get("glyph_admit") or {}).items() if isinstance(r, dict) and r.get("left")}
        if left:
            print(f"⚠️  还有人裁没落进字形库（多为本机没有那一页的产物和字块缓存）：{json.dumps(left, ensure_ascii=False)}"
                  "——到有产物的机器上 guji db sync，或交 A23 扫尾", file=sys.stderr)
        return

    src = WorkerSource(branch=args.branch)

    if args.action == "diff":
        from .datastore.pull import diff_branches, workspace_id
        if src.branch == args.against:
            raise SystemExit("db diff 要 --branch exp/<名>（与 --against 不同的分支）")
        other = WorkerSource(token=src.token, branch=args.against)
        _print(diff_branches(src, other, workspace_id(ws_dir), show=args.show))
        return

    if args.action == "status":
        from .datastore.pull import status
        _print(status(src, ws_dir))
        return

    if args.action == "pull":
        from .datastore.workcopy import pull
        res = pull(src, ws_dir, cache=BlobCache(), bucket=args.bucket, force=args.force,
                   glyph=None if args.no_rebuild else glyph_hooks(ws_dir))
        res["worker_requests"] = src.requests
        if not args.no_rebuild:
            _ensure_glyph_pins(ws_dir, res)
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
        res = import_events(src_from, src, workspace_id(ws_dir), ids, dst_branch=args.to, dry_run=args.dry_run)
        if not args.dry_run and res["ids"] and not args.no_route:
            res["route"] = route_imported(ws_dir, set(res["ids"]), branch=args.to)
        res.pop("ids")
        _print(res)
        return


def add_parser(sub) -> None:
    p = sub.add_parser("db", help="中心库：migrate / pull / push / status / branch / import（GUJI-606/608）")
    p.add_argument("action", choices=["status", "migrate", "pull", "push", "sync", "branch", "import", "diff"])
    p.add_argument("args", nargs="*", help="branch 的子命令与分支名")
    p.add_argument("-w", "--workspace", default=None, help="工作区仓根（含 workspace.yaml）；不给读 GUJI_WORKSPACE")
    p.add_argument("--branch", default=None,
                   help="读写哪个分支（缺省 GUJI_DATA_BRANCH 或 main）；exp/* 时数据目录、glyph.db、products 换到该分支自己的")
    p.add_argument("--against", default="main", help="diff：和哪个分支比（缺省 main）")
    p.add_argument("--show", type=int, default=20, help="diff：每类最多列几个路径")
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
    p.add_argument("--no-route", action="store_true",
                   help="import：导完不在本机副本上跑消费者（缺省会拉下来、只对导入的事件 route、再推）")
    p.add_argument("--dry-run", action="store_true", help="migrate/push/sync/import：只列计划不写")
    p.add_argument("--watch", type=int, default=None, metavar="秒", help="sync：每隔这么多秒做一轮，不退出")
    p.add_argument("--no-admit", action="store_true",
                   help="sync：不顺带把待落库的人裁落进字形库（缺省落；也可设 GUJI_AUTO_ADMIT=0）")
