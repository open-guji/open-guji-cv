"""`guji job`：任务库命令行（也可 `python -m open_guji_cv.jobs …`，云端用 `guji_jobs …`）。

    guji job submit <spec.json|->            # 交一条任务（JSON，字段见 jobs/spec.py 模块头）
    guji job submit --book vol10 --cv v0.5.16 --from seed_admit --corpus 16 --change seed-c16 --why "…"
    guji job ls [--book vol10] [--status queued,running] [--all]   # 谁在跑什么、排了什么
    guji job show <号> [--json] [--log]      # 定义、每次领单、进展流水、结果（包在哪）
    guji job wait <号>                       # 等到它结束（成功退出码 0）
    guji job cancel <号> | bump <号> [--priority 10] | retry <号>
    guji job work [--once] [--idle 分钟]     # 执行方：领单跑单（只在云端执行会话里用）
    guji job init                            # 建表（幂等）

连库：缺省正式库（NEON_DATABASE_URL）；GUJI_JOBS_BRANCH=ci 连测试分支。提交人名字取 GUJI_JOBS_WHO（如 A24）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import spec as SP
from . import store as S

_ICON = {"queued": "…", "running": "▶", "succeeded": "✓", "failed": "✗", "blocked": "■", "cancelled": "–",
         "duplicate": "="}


def add_parser(sub) -> argparse.ArgumentParser:
    p = sub.add_parser("job", help="任务库：交重跑／评测任务、看谁在跑什么、结果在哪（Neon jobs schema）")
    fill(p)
    return p


def fill(p: argparse.ArgumentParser) -> None:
    js = p.add_subparsers(dest="job_action", required=True)
    s = js.add_parser("submit", help="交一条任务")
    s.add_argument("file", nargs="?", help="spec JSON 文件，- 为标准输入；不给就用下面的参数拼")
    s.add_argument("--kind", default=None, choices=SP.KINDS)
    s.add_argument("--book", default=None)
    s.add_argument("--cv", default=None, help="tag／分支／提交（必填）")
    s.add_argument("--pipeline", default=None)
    s.add_argument("--from", dest="from_step", default=None)
    s.add_argument("--to", dest="to_step", default=None)
    s.add_argument("--pages", default=None)
    s.add_argument("--no-force", action="store_true", help="不加 --force（按指纹能跳就跳）")
    s.add_argument("--corpus", type=int, default=None)
    s.add_argument("--glyph-pin", type=int, default=None)
    s.add_argument("--base", default=None, help="铺底包：main｜标签；从中间某步起跑缺省 main")
    s.add_argument("--human-chars", type=int, default=None, help="开跑前人裁格数必须等于它")
    s.add_argument("--env", action="append", default=[], help="K=V，只收 GUJI_ 开头")
    s.add_argument("--params", default=None, help="guji pipeline --params 的 JSON")
    s.add_argument("--override", default=None, help='册配置片段 JSON（写进 book_overrides，运行时叠在册 yaml 上，不改文件不推库），如 \'{"cv_version":"0.5.21","corpus":23}\'')
    s.add_argument("--compare-to", default=None, help="main｜包标签｜job:<号>")
    s.add_argument("--change", default=None, help="存包改动名（缺省 job<号>）")
    s.add_argument("--note", default=None)
    s.add_argument("--no-pack", action="store_true", help="跑完不存包")
    s.add_argument("--run", action="append", default=[], help="command／eval：一条 guji 命令（引号括起，可多次）")
    s.add_argument("--why", default=None, help="为什么跑（谁要、要回答什么问题）")
    s.add_argument("--priority", type=int, default=100, help="越小越先，缺省 100；插队给 10")
    s.add_argument("--after", type=int, action="append", default=[], help="等这条任务成功后再跑（可多次）")
    s.add_argument("--again", action="store_true", help="同配置已跑过也再跑一次")
    s.add_argument("--dry-run", action="store_true", help="只打印规整后的定义和指纹，不交")

    s = js.add_parser("ls", help="列任务")
    s.add_argument("--book", default=None)
    s.add_argument("--status", default=None, help="逗号分隔，缺省 排队+在跑+最近结束的")
    s.add_argument("--mine", action="store_true")
    s.add_argument("--all", action="store_true")
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--json", action="store_true")

    s = js.add_parser("show", help="看一条任务")
    s.add_argument("id", type=int)
    s.add_argument("--json", action="store_true")
    s.add_argument("--log", action="store_true", help="带最后一次的日志尾巴")

    s = js.add_parser("wait", help="等一条任务结束")
    s.add_argument("id", type=int)
    s.add_argument("--timeout", type=int, default=0, help="最多等几秒，0 不限")

    for name, h in (("cancel", "取消／停下"), ("retry", "失败、拦下、取消的重新排队")):
        s = js.add_parser(name, help=h)
        s.add_argument("id", type=int)
    s = js.add_parser("bump", help="改优先级（插队）")
    s.add_argument("id", type=int)
    s.add_argument("--priority", type=int, default=10)

    s = js.add_parser("work", help="执行方：领单跑单，缺省跑到队列空；常驻用 --idle")
    s.add_argument("--once", action="store_true", help="只跑一条")
    s.add_argument("--id", type=int, default=None, help="只跑这一条")
    s.add_argument("--idle", type=float, default=0, help="队列空了再等几分钟有没有新单")
    s.add_argument("--kinds", default=None, help="只接这些 kind，逗号分隔")
    s.add_argument("--dry-run", action="store_true", help="只打印要跑的命令（仍会领单、记库，测试分支上用）")

    s = js.add_parser("board", help="把任务整理成表写进后台「重跑任务」栏（progress.metric）；--dry-run 只打印")
    s.add_argument("--dry-run", action="store_true")
    s = js.add_parser("workers", help="列执行方：谁在线、空闲还是在跑哪条")
    s.add_argument("--all", action="store_true", help="连已离线的也列")

    js.add_parser("init", help="建表（幂等）")


def _spec_from_args(a) -> dict:
    if a.file:
        raw = json.load(sys.stdin) if a.file == "-" else json.loads(Path(a.file).read_text(encoding="utf-8"))
    else:
        raw = {}
    put = lambda k, v: raw.__setitem__(k, v) if v is not None else None  # noqa: E731
    put("kind", a.kind)
    put("book", a.book)
    put("cv", a.cv)
    put("pipeline", a.pipeline)
    put("pages", a.pages)
    put("base", a.base)
    put("why", a.why)
    if a.from_step or a.to_step:
        raw["steps"] = {**raw.get("steps", {}), **{k: v for k, v in (("from", a.from_step), ("to", a.to_step)) if v}}
    if a.no_force:
        raw["force"] = False
    ov = {k: v for k, v in (("corpus", a.corpus), ("glyph_pin", a.glyph_pin)) if v is not None}
    if ov:
        raw["book_overrides"] = {**raw.get("book_overrides", {}), **ov}
    if getattr(a, "override", None):
        raw["book_overrides"] = {**raw.get("book_overrides", {}), **json.loads(a.override)}
    if a.human_chars is not None:
        raw["checks"] = {**raw.get("checks", {}), "human_chars": a.human_chars}
    if a.env:
        raw["env"] = {**raw.get("env", {}), **dict(e.split("=", 1) for e in a.env)}
    if a.params:
        raw["params"] = json.loads(a.params)
    if a.compare_to:
        raw["compare_to"] = {"job": int(a.compare_to[4:])} if a.compare_to.startswith("job:") else a.compare_to
    out = dict(raw.get("output") or {})
    if a.change:
        out["change"] = a.change
    if a.note:
        out["note"] = a.note
    if a.no_pack:
        out["pack"] = False
    if out:
        raw["output"] = out
    if a.run:
        import shlex
        raw["run"] = [shlex.split(r) for r in a.run]
        raw.setdefault("kind", "command")
    return raw


def _fmt_time(t) -> str:
    """洛杉矶时间（团队规矩）。"""
    from zoneinfo import ZoneInfo
    return t.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%m-%d %H:%M") if t else "-"


_FAILED = ("failed", "blocked", "cancelled")
_REASON_MAX = 160
_TAG = {"failed": "失败原因", "blocked": "拦下原因", "cancelled": "取消", "queued": "上次失败"}


def _reason(j: dict) -> str | None:
    """失败／拦下的一行原因（库里 error 列，执行方收尾时写的）。排队中的单是上次失败留下的原因。"""
    err = " ".join((j.get("error") or "").split())
    if not err or j["status"] not in _FAILED + ("queued",):
        return None
    return err if len(err) <= _REASON_MAX else err[:_REASON_MAX - 1] + "…"


def _line(j: dict) -> str:
    sp = j["spec"]
    st = j["status"] + (f"→#{j['duplicate_of']}" if j.get("duplicate_of") else "")
    where = f" @{j.get('worker')}" if j["status"] == "running" and j.get("worker") else ""
    stage = f" [{j['stage']}]" if j["status"] == "running" and j.get("stage") else ""
    pri = f" p{j['priority']}" if j["status"] == "queued" and j["priority"] != 100 else ""
    if j["status"] == "queued" and j.get("run_after"):
        pri += f" 冷却到 {_fmt_time(j['run_after'])}（第 {j['attempts']} 次环境失败后）"
    head = (f"{_ICON.get(j['status'], '?')} #{j['id']:<4} {st:<10} {j['kind']:<7} {(j['book'] or '-'):<6} "
            f"{SP.summary(sp)}{pri}{stage}{where}  {j['submitted_by']} {_fmt_time(j['created_at'])}")
    why = _reason(j)
    return head if why is None else f"{head}\n      ↳ {_TAG[j['status']]}：{why}"


def cmd_job(a) -> None:
    act = a.job_action
    if act == "submit":
        try:
            spec = SP.normalize(_spec_from_args(a))
        except SP.SpecError as e:
            sys.exit(f"✗ {e}")
        h = SP.spec_hash(spec)
        if a.dry_run:
            print(json.dumps(spec, ensure_ascii=False, indent=1))
            print("指纹", h)
            return
        db = S.DB()
        row = db(S.submit, spec, h, by=S.who(), why=spec.get("why"), priority=a.priority,
                 depends_on=a.after, again=a.again)
        if row["status"] == "duplicate":
            print(f"= #{row['id']} 与 #{row['duplicate_of']}（{row['dup_status']}）同一配置，不另跑；"
                  f"看结果：guji job show {row['duplicate_of']}（确要再跑加 --again）")
        else:
            print(f"已排队 #{row['id']}：{SP.summary(spec)}；看进展：guji job show {row['id']}")
        return
    db = S.DB()
    if act == "init":
        db(S.init)
        print("jobs schema 已就绪")
    elif act == "ls":
        status = a.status.split(",") if a.status else (None if a.all else None)
        rows = db(S.list_jobs, status=status, book=a.book, limit=a.limit, mine=S.who() if a.mine else None)
        if not a.all and not a.status:
            rows = [r for r in rows if r["status"] in SP.ACTIVE] + \
                   [r for r in rows if r["status"] not in SP.ACTIVE][:10]
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, default=str, indent=1))
            return
        live = db(S.live_workers)
        ws = [w for w in db(S.workers) if w["online"]]
        idle = sum(1 for w in ws if w["state"] == "idle")
        print(f"排队 {db(S.queue_depth)} 条，在跑 {len(live)} 条" +
              (f"（{'、'.join(sorted({w['worker'] for w in live}))}）" if live else "") +
              f"；执行方在线 {len(ws)} 个（空闲 {idle}）")
        for r in rows:
            print(_line(r))
    elif act == "show":
        j = db(S.detail, a.id)
        if j is None:
            sys.exit(f"✗ 没有 #{a.id}")
        if a.json:
            print(json.dumps(j, ensure_ascii=False, default=str, indent=1))
            return
        print(_line(j))
        if j.get("why"):
            print("为什么：", j["why"])
        if j.get("progress") and j["status"] == "running":
            print("进展：", j["progress"])
        if j.get("error"):
            print("错误：", j["error"])
        if j["status"] in _FAILED and j["attempts_rows"]:
            last = j["attempts_rows"][-1]
            print(f"看日志：guji_jobs show {j['id']} --log（第 {last['n']} 次领单的尾巴，执行方 {last['worker']}；"
                  f"完整日志只在执行方机器上）")
        print("定义：", json.dumps(j["spec"], ensure_ascii=False))
        for t in j["attempts_rows"]:
            print(f"  第{t['n']}次 {t['worker']} {t.get('session') or ''} {_fmt_time(t['started_at'])}"
                  f"→{_fmt_time(t['finished_at'])} {t['outcome'] or '在跑'} 心跳 {_fmt_time(t['heartbeat_at'])}")
        for e in j["events"]:
            secs = f" {e['secs']:.0f}s" if e.get("secs") else ""
            print(f"  {_fmt_time(e['at'])} {e['level']:<5} {e['stage'] or '':<8} {e['msg']}{secs}")
        for r in j["results"]:
            d = r.get("data") or {}
            extra = d.get("report_head", "")[:600] or d.get("tail", "")[-600:] or json.dumps(d, ensure_ascii=False)
            print(f"  结果 {r['kind']} {r['name']} {r.get('location') or ''}\n    " + extra.replace("\n", "\n    "))
        if a.log and j["attempts_rows"]:
            print("── 日志尾巴 ──\n" + (j["attempts_rows"][-1].get("log_tail") or ""))
    elif act == "wait":
        t0 = time.time()
        while True:
            j = db(S.get, a.id)
            if j is None:
                sys.exit(f"✗ 没有 #{a.id}")
            if j["status"] == "duplicate":
                a.id = j["duplicate_of"]
                continue
            if j["status"] not in SP.ACTIVE:
                print(_line(j))
                sys.exit(0 if j["status"] == "succeeded" else 1)
            if a.timeout and time.time() - t0 > a.timeout:
                print(_line(j))
                sys.exit(2)
            time.sleep(60)
    elif act == "board":
        from . import board
        t = board.publish(db, force=True, dry=a.dry_run)
        if t is None:
            sys.exit("✗ 看板没写成（连库失败或中心库还没有 progress schema）")
        if a.dry_run:
            for r in t["rows"]:
                print(f"#{r['id']:<4} {r['status']:<4} {r['book']:<6} {r['elapsed']:<8} {r['eta']:<14} {r['config']}")
        print(f"{'（只看，没写）' if a.dry_run else '已写入 progress.metric jobs/board'}：共 {len(t['rows'])} 行")
    elif act == "workers":
        rows = db(S.workers)
        for w in rows:
            if not (w["online"] or a.all):
                continue
            st = {"idle": "空闲", "busy": f"在跑 #{w['job_id']}", "stopped": "已停"}[w["state"]] if w["online"] or \
                w["state"] == "stopped" else "离线"
            print(f"{'●' if w['online'] else '○'} {w['name']:<14} {st:<10} 领过 {w['done']} 条  "
                  f"上线 {_fmt_time(w['started_at'])}  最近 {_fmt_time(w['seen_at'])}  runner {w.get('runner') or '?'}"
                  f"  {w.get('session') or ''}" + (f"\n    ⚠ {w['note']}" if w["online"] and w.get("note") else ""))
        if not any(w["online"] for w in rows):
            print("（没有在线的执行方）")
    elif act == "cancel":
        print(db(S.cancel, a.id, S.who()))
    elif act == "bump":
        print("已改" if db(S.bump, a.id, a.priority, S.who()) else "✗ 只有排队中的能改优先级")
    elif act == "retry":
        print("已重新排队" if db(S.retry, a.id, S.who()) else "✗ 只有失败、拦下、取消的能重排")
    elif act == "work":
        from .runner import work
        work(once=a.once, only=a.id, idle_minutes=a.idle, kinds=a.kinds.split(",") if a.kinds else None,
             dry=a.dry_run, say=lambda m: print(m, flush=True))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="guji_jobs", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    fill(p)
    cmd_job(p.parse_args(argv))
