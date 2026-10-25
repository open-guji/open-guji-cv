"""任务看板：把任务库里在跑、排队、最近结束的任务整理成一张表，写进中心库 `progress.metric`（栏目 jobs）。

网站后台「文本整理 → 重跑任务」读的就是这一条（`detail.table` 画成可排序的表，见 kaiyuanguji-web
`docs/text-progress.md` 2.2）；网站同步任务把 `progress` 搬进后台，所以这里只管写，不碰网站。
执行方领单、收尾、每隔几分钟心跳时顺手写一次（`publish(db, force=False)` 带节流）；`guji job board` 手动写或只看。

预计完成＝这一条的本次开跑时间＋「同类已成功任务（同种类、同起止步、同页范围类别）最近 30 条的耗时中位数」；
没有同类样本就不估（显示 —），超出中位数的显示「已超预估」。排队的显示前面还有几条。
"""
from __future__ import annotations

import json
import statistics
import time
from zoneinfo import ZoneInfo

from . import spec as SP

SECTION, KEY, WRITER = "jobs", "board", "任务库"
RECENT = 40                 # 表里留最近结束的几条
_MIN_GAP_S = 120            # 节流：本进程两次写之间至少隔这么久（force 不受限）
_last = 0.0

_STATUS = {"running": "在跑", "queued": "排队", "succeeded": "完成", "failed": "失败", "blocked": "拦下",
           "cancelled": "已取消"}


def _la(t) -> str:
    return t.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%m-%d %H:%M") if t else "—"


def _mins(sec: float) -> str:
    m = int(sec // 60)
    return f"{m // 60}小时{m % 60:02d}分" if m >= 60 else f"{m}分"


def _kind(j: dict) -> tuple:
    """同类任务的键：种类、起止步、全册还是部分页。"""
    sp = j["spec"]
    st = sp.get("steps") or {}
    return (j["kind"], st.get("from"), st.get("to"), sp.get("pages") == "all")


def _config(j: dict) -> str:
    sp = j["spec"]
    if j["kind"] in ("command", "eval"):
        return SP.summary(sp)
    st = sp["steps"]
    bits = [f"cv {sp['cv_ref']}", f"{st['from'] or '头'}→{st['to'] or '尾'}",
            "全册" if sp["pages"] == "all" else f"页 {sp['pages']}"]
    bits += [f"{k}={v}" for k, v in (sp.get("book_overrides") or {}).items()]
    if sp.get("force"):
        bits.append("force")
    c = sp.get("compare_to")
    if c:
        bits.append(f"比 {'#' + str(c['job']) if isinstance(c, dict) else c}")
    return " ".join(bits)


def build(conn) -> dict:
    """读任务库，整理成 `detail.table`（列定义＋行）。"""
    from . import store as S
    now = conn.execute("SELECT now()").fetchone()[0]
    jobs = S._rows(conn.execute(
        "SELECT j.*, a.worker AS a_worker, a.started_at AS a_start, a.heartbeat_at AS a_beat, a.finished_at AS a_end"
        " FROM jobs.job j LEFT JOIN LATERAL (SELECT * FROM jobs.attempt a WHERE a.job_id = j.id"
        "  ORDER BY a.n DESC LIMIT 1) a ON true"
        " WHERE j.status IN ('running', 'queued')"
        "    OR (j.status IN ('succeeded', 'failed', 'blocked', 'cancelled') AND j.id IN"
        "        (SELECT id FROM jobs.job WHERE status IN ('succeeded', 'failed', 'blocked', 'cancelled')"
        "         ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT %s))"
        " ORDER BY CASE j.status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,"
        "          CASE WHEN j.status = 'queued' THEN j.priority END, CASE WHEN j.status = 'queued' THEN j.created_at END,"
        "          j.finished_at DESC NULLS LAST, j.id DESC", (RECENT,)))
    # 同类已成功任务的耗时（该任务成功那次领单的起止）
    done = S._rows(conn.execute(
        "SELECT j.kind, j.spec, extract(epoch FROM a.finished_at - a.started_at) AS secs FROM jobs.job j"
        " JOIN jobs.attempt a ON a.job_id = j.id AND a.outcome = 'succeeded'"
        " WHERE j.status = 'succeeded' ORDER BY a.finished_at DESC LIMIT 200"))
    hist: dict[tuple, list[float]] = {}
    for d in done:
        k = _kind(d)
        if len(hist.setdefault(k, [])) < 30 and d["secs"] and float(d["secs"]) > 30:
            hist[k].append(float(d["secs"]))
    results = {}
    for r in S._rows(conn.execute("SELECT job_id, name, location FROM jobs.result WHERE kind = 'pack'")):
        results.setdefault(r["job_id"], r["name"])
    ahead = 0
    rows = []
    for j in jobs:
        st = j["status"]
        row = {"id": j["id"], "book": j["book"] or "—", "kind": j["kind"], "status": _STATUS.get(st, st),
               "config": _config(j), "who": j["submitted_by"], "worker": "—", "stage": "—",
               "submitted": _la(j["created_at"]), "started": "—", "elapsed": "—", "eta": "—",
               "result": results.get(j["id"]) or "—", "note": (j["why"] or "")[:80]}
        if st == "running":
            row["worker"] = j["a_worker"] or "—"
            row["stage"] = (j["stage"] or "—") + (f"（{j['progress']}）" if j.get("progress") else "")
            row["started"] = _la(j["a_start"])
            el = (now - j["a_start"]).total_seconds() if j["a_start"] else None
            row["elapsed"] = _mins(el) if el is not None else "—"
            h = hist.get(_kind(j))
            if h and j["a_start"] is not None:
                med = statistics.median(h)
                from datetime import timedelta
                row["eta"] = _la(j["a_start"] + timedelta(seconds=med)) if el <= med else "已超预估"
        elif st == "queued":
            ahead += 1
            row["stage"] = f"前面还有 {ahead - 1} 条排队"
            if j.get("run_after") and j["run_after"] > now:
                row["stage"] += f"，冷却到 {_la(j['run_after'])}"
            h = hist.get(_kind(j))
            if h:
                row["eta"] = f"约 {_mins(statistics.median(h))}"
        else:
            row["worker"] = j["a_worker"] or "—"
            row["started"] = _la(j["a_start"])
            if j["a_start"] and j["a_end"]:
                row["elapsed"] = _mins((j["a_end"] - j["a_start"]).total_seconds())
            row["eta"] = _la(j["finished_at"])
            if st in ("failed", "blocked") and j.get("error"):
                row["note"] = j["error"].splitlines()[0][:120]
        rows.append(row)
    cols = [("id", "号"), ("book", "册"), ("kind", "种类"), ("status", "状态"), ("config", "配置"),
            ("stage", "阶段／排队"), ("worker", "执行方"), ("started", "开始（洛杉矶）"), ("elapsed", "已跑"),
            ("eta", "预计完成／结束"), ("result", "结果包"), ("who", "提交人"), ("submitted", "提交时间"),
            ("note", "原因／说明")]
    return {"columns": [{"key": k, "label": lb} for k, lb in cols], "rows": rows,
            "note": "任务库（guji_jobs ls）的快照：在跑、排队、最近结束的 %d 条。预计完成按同类已成功任务的耗时中位数估，没有同类记录就不估；"
                    "已结束的任务这一列显示结束时间。每次领单、收尾和执行方心跳时更新，网站再按同步节奏搬过来。" % RECENT}


def publish(db, *, force: bool = False, dry: bool = False) -> dict | None:
    """整理并写进 progress.metric。`db` 是 `store.DB`；失败只返回 None，不影响跑单。"""
    global _last
    if not force and time.time() - _last < _MIN_GAP_S:
        return None
    _last = time.time()
    try:
        table = db(build)
        running = sum(1 for r in table["rows"] if r["status"] == "在跑")
        queued = sum(1 for r in table["rows"] if r["status"] == "排队")
        if dry:
            return table
        db(_put, table, f"在跑 {running}、排队 {queued}")
        return table
    except Exception:       # noqa: BLE001 —— 看板写不上不能拖垮执行方；进展以任务库为准
        return None


def _put(conn, table: dict, text: str) -> None:
    import psycopg
    try:
        with conn.transaction():
            conn.execute("INSERT INTO progress.section (section, title, owner, description, sort) VALUES"
                         " (%s, '重跑任务', 'A30', '重跑、A/B、评测任务：配置、状态、已跑多久、预计完成（任务库 guji_jobs 的快照）', 40)"
                         " ON CONFLICT (section) DO NOTHING", (SECTION,))
            conn.execute("SELECT progress.put_metric('', '', %s, %s, %s, NULL, NULL, %s, %s, %s::jsonb, 10)",
                         (SECTION, KEY, "重跑任务", WRITER, text, json.dumps({"table": table}, ensure_ascii=False)))
    except psycopg.errors.UndefinedFunction:
        raise RuntimeError("中心库还没有 progress schema（网站 ops/text-progress/schema.sql）") from None
