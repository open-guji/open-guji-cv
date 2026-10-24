"""修订流程的自动化调和器（M11；设计 book-text ``docs/design/2026-10-修订流程自动化设计.md``）。

每个函数只做一段、幂等、不自己碰 GitHub（推送、开 PR、合并由调用的会话或 Action 做）：

| 函数 | 阶段 | 输入状态 | 输出 |
|---|---|---|---|
| ``decide_pending`` | S3 | ``to_user`` | log ``decided``（``by`` 是策略名），命中 ``park_reasons`` 或 C 类、看不清的留着 |
| ``prepare`` | S4–S6 | ``accepted``／``auto_accepted`` 且还没进批 | book-text 里一个分支、一次提交、一行发布批（``releases.jsonl``）、log ``batched`` |
| ``finish_pr`` | S6 | 已 push、已开 PR | 把 CHANGES 里的 ``#TBD`` 换成 PR 号，再提交一次；log ``pr_opened`` |
| ``finish_merged`` | S8 | PR 已合并 | log ``applied``、格谱系（``lineage.jsonl``）、度量（``metrics.jsonl``）、网站状态；log ``published`` |
| ``digest`` | — | 全池 | 给人看的汇总（Markdown） |

策略在 ``config/opinions/rules.json`` 的 ``auto`` 段；``auto.enabled=false`` 全停。合并进 book-text main 默认不自动
（``auto.merge.enabled=false``）：覆盖线上文本要用户点头。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from . import revise as V
from .schema import cell_key, norm_class, now_iso
from .textsrc import BookText, vol_key

RELEASE_SCHEMA = "guji-release/0.1"
OPEN_RELEASE = ("checked", "pr_open", "merged")      # 还没结案的发布批：里面的意见不再进新批


class AutoError(RuntimeError):
    pass


def policy(rules: dict) -> dict:
    p = rules.get("auto") or {}
    if not p:
        raise AutoError("rules.json 没有 auto 段（要 version 2）")
    return p


# ---------------- S3：自动结案 ----------------

def decide_pending(st, rules: dict) -> list[dict]:
    """``to_user`` 的意见按策略自动结案。返回每条的去向行（action: accept／reject／park）。"""
    pol = policy(rules)
    if not pol.get("enabled"):
        return []
    dec = pol["decide"]
    by = dec.get("by", "policy:auto")
    rows = []
    for op in list(st.opinions.values()):
        if st.status(op.id) != "to_user":
            continue
        tri = st.last(op.id, "triaged")
        d = tri.data if tri else {}
        verdict, conf = d.get("verdict"), float(d.get("confidence") or 0)
        rev = d.get("revision")
        klass = norm_class((rev or {}).get("class"))
        why_user = "；".join(d.get("rule") or [])
        row = {"id": op.id, "vol": op.vol, "verdict": verdict, "confidence": conf, "class": klass, "why_user": why_user}
        hit = [r for r in pol.get("park_reasons", []) if r in why_user]
        if hit:
            row.update(action="park", reason=f"需要人看：{why_user}")
        elif verdict in ("accept", "lacuna_guess") and rev and klass in dec["classes"] and conf >= dec["min_confidence"]:
            row.update(action="accept", reason=f"{verdict} 置信 {conf}，修订 {klass} 类")
        elif verdict == "text_ok" and conf >= dec["reject_min_confidence"] and (d.get("rationale_public") or "").strip():
            row.update(action="reject", reason=f"原文对，置信 {conf}，有公开理由")
        else:
            why = []
            if verdict in ("seg_issue", "unclear") or klass == "C":
                why.append("切分或看不清，不能自动改")
            if conf < dec["min_confidence"]:
                why.append(f"置信 {conf} 低于 {dec['min_confidence']}")
            if verdict in ("accept", "lacuna_guess") and not rev:
                why.append("没有修订草案")
            row.update(action="park", reason="；".join(why) or f"结论 {verdict} 没有自动规则")
        if row["action"] in ("accept", "reject"):
            st.log(op.id, "decided", {"decision": row["action"], "by": by, "auto": True, "note": row["reason"],
                                      "confidence": conf}, by=by)
        rows.append(row)
    return rows


# ---------------- S4–S6：聚批、改文本、检查、提交 ----------------

def _git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AutoError(f"git {' '.join(args)} 失败：{(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def in_flight(st) -> set[str]:
    """已在某个没结案的发布批里的意见 id。"""
    busy: set[str] = set()
    for r in st.release_latest().values():
        if r.get("status") in OPEN_RELEASE:
            busy.update(r.get("opinions") or [])
    return busy


def select(st, vol: str, rules: dict, human_cells: set | None = None) -> tuple[list, list[dict]]:
    """这一章能进批的 (op, revision)，和被挡下的 [{id, reason}]。同一格只留最早的一条；超 ``batch.max_cells`` 的留给下一批。"""
    pol = policy(rules)
    cap = int(pol["batch"]["max_cells"])
    todo, _skipped = V.plan(st, vol)
    busy = in_flight(st)
    take, held, seen, n = [], [], set(), 0
    for op, rev in todo:
        if op.id in busy:
            continue
        cells = [c["a"] for c in rev.get("cells") or []]
        prot = sorted(set(cells) & (human_cells or set()), key=cell_key)
        if prot:
            held.append({"id": op.id, "reason": f"碰到保护格 {','.join(prot)}（人裁或手改），不自动改"})
            continue
        if set(cells) & seen:
            held.append({"id": op.id, "reason": "同一格已有更早的修订在这一批，下一批再看"})
            continue
        if n + len(cells) > cap and take:
            held.append({"id": op.id, "reason": f"超过一批 {cap} 格，留给下一批"})
            continue
        take.append((op, rev))
        seen.update(cells)
        n += len(cells)
    return take, held


def _run_checks(bt_root: Path) -> dict:
    script = bt_root / "scripts" / "local_check.py"
    if not script.is_file():
        return {"local_check": "skipped", "tail": "没有 scripts/local_check.py"}
    r = subprocess.run([sys.executable, str(script)], cwd=bt_root, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip().splitlines()
    return {"local_check": "pass" if r.returncode == 0 else "fail", "tail": "\n".join(out[-12:])}


def _cell_rows(applied: list, st) -> list[dict]:
    rows = []
    for ap in applied:
        tri = st.last(ap.opinion, "triaged")
        why = ((tri.data if tri else {}) or {}).get("rationale_public") or ""
        for c in ap.cells:
            if ap.cls == "B′":
                rows.append({"a": c["a"], "before": None, "after": c["new"], "opinion": ap.opinion, "class": ap.cls,
                             "inserted_after": c["after_cell"], "mark": c["mark"].get("id"), "why": why})
            else:
                rows.append({"a": c["a"], "before": c["before"], "after": c["after"], "opinion": ap.opinion,
                             "class": ap.cls, "why": why})
    return rows


def prepare(st, bt_root: str | Path, book: str, rules: dict, *, vols: list[str] | None = None,
            human_cells: set | None = None, run_checks: bool = True, base: str = "origin/main",
            trailers: list[str] | None = None, today: str | None = None) -> list[dict]:
    """每章一批：book-text 里 ``auto/<书>-<章>-<日期>`` 分支上套修订、升版本、跑检查、提交一次。返回每批一份计划。

    book-text 工作树要干净。失败（修订对不上现文、检查不过）不留半成品：分支删掉、写一行 status=failed 的发布批。"""
    pol = policy(rules)
    if not pol.get("enabled"):
        return []
    root = Path(bt_root)
    if _git(root, "status", "--porcelain"):
        raise AutoError(f"{root} 工作树不干净，先处理")
    today = today or now_iso()[:10]
    orig = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    out = []
    for vol in sorted({o.vol for o in st.opinions.values()}):
        if vols and vol_key(vol) not in {vol_key(v) for v in vols}:
            continue
        take, held = select(st, vol, rules, human_cells)
        if not take:
            if held:
                out.append({"vol": vol, "status": "none", "held": held})
            continue
        _git(root, "fetch", "-q", "origin", "main", check=False)
        base_sha = _git(root, "rev-parse", base)
        branch = f"auto/{book}-{vol_key(vol)}-{today}"
        _git(root, "checkout", "-q", "-B", branch, base)
        plan = {"vol": vol_key(vol), "branch": branch, "base": base_sha, "held": held,
                "opinions": [op.id for op, _ in take]}
        try:
            res = V.revise(root, book, vol, take, dry_run=False, pr="TBD")
            if res.problems:
                raise AutoError("出口检查：" + "；".join(res.problems))
            checks = _run_checks(root) if run_checks else {"local_check": "skipped", "tail": ""}
            if checks["local_check"] == "fail":
                raise AutoError("local_check 不过：\n" + checks["tail"])
        except (V.ReviseError, AutoError) as e:
            _git(root, "checkout", "-q", "--", ".", check=False)
            _git(root, "clean", "-fdq", check=False)
            _git(root, "checkout", "-q", orig, check=False)
            _git(root, "branch", "-D", branch, check=False)
            rel_id = f"rel_{book}_{vol_key(vol)}_failed_{today}"
            row = {"schema": RELEASE_SCHEMA, "id": rel_id, "book": book, "vol": vol_key(vol), "opinions": plan["opinions"],
                   "status": "failed", "error": str(e)[:800], "ts": now_iso()}
            st.add_row("releases", row)
            plan.update(status="failed", release=rel_id, error=str(e))
            out.append(plan)
            continue
        new_v = res.new_version
        vdir = BookText(book, root).path("")
        comp = {}
        for line in ("punct", "entity"):
            f = vdir / f"{vol_key(vol)}.{line}.json"
            comp[line] = json.loads(f.read_text(encoding="utf-8")).get("version") if f.is_file() else None
        rel_id = f"rel_{book}_{vol_key(vol)}_{new_v}"
        cells = _cell_rows(res.applied, st)
        title = f"四庫總目 {vol_key(vol)} 读者意见修订：文本 {res.old_version}→{new_v}（{len(cells)} 格）"
        _git(root, "add", "-A", "Book")
        body = title + "\n\n" + res.note + ("\n\n" + "\n".join(trailers) if trailers else "")
        _git(root, "commit", "-q", "-m", body)
        commit = _git(root, "rev-parse", "HEAD")
        pr_body = V.pr_body(res, book) + "\n\n本批由 `guji opinions auto prepare` 生成。本地检查：\n```\n" + checks["tail"] + "\n```"
        row = {"schema": RELEASE_SCHEMA, "id": rel_id, "book": book, "vol": vol_key(vol),
               "from": {"text": res.old_version}, "to": {"text": new_v, **{k: v for k, v in comp.items() if v}},
               "opinions": plan["opinions"], "cells": cells, "branch": branch, "base": base_sha, "commit": commit,
               "pr": None, "checks": {"local_check": checks["local_check"]},
               "diff": {"cells": len(cells), "companions_shifted": {k: res.companions.get(k, 0) for k in ("punct", "entity")}},
               "protected_conflicts": 0, "status": "checked", "title": title, "ts": now_iso()}
        st.add_row("releases", row)
        for oid in plan["opinions"]:
            st.log(oid, "batched", {"release": rel_id})
        plan.update(status="checked", release=rel_id, title=title, pr_body=pr_body, commit=commit,
                    merge_ok=merge_ok(row, rules))
        out.append(plan)
        _git(root, "checkout", "-q", orig, check=False)
    return out


def merge_ok(rel: dict, rules: dict) -> tuple[bool, str]:
    """策略允许自动合并吗。默认 ``merge.enabled=false``：永远 (False, 理由)。"""
    m = policy(rules).get("merge") or {}
    if not m.get("enabled"):
        return False, "策略未开自动合并（覆盖线上文本要用户点头）"
    if m.get("require_checks", True) and (rel.get("checks") or {}).get("local_check") != "pass":
        return False, "本地检查未通过"
    if (rel.get("diff") or {}).get("cells", 0) > int(m.get("max_cells", 50)):
        return False, "超过自动合并的格数上限"
    if (rel.get("protected_conflicts") or 0) > int(m.get("max_protected_conflicts", 0)):
        return False, "有保护格冲突"
    return True, "满足策略"


# ---------------- S6/S8：开 PR 之后、合并之后 ----------------

def _release(st, rel_id: str) -> dict:
    r = st.release_latest().get(rel_id)
    if r is None:
        raise AutoError(f"没有发布批 {rel_id}")
    return r


def finish_pr(st, bt_root: str | Path, rel_id: str, pr: int | str) -> dict:
    """PR 开好后：CHANGES 里这一批加的 ``#TBD`` 换成 PR 号，提交一次，记 ``pr_opened``。要在 push 之前的分支上做完再 push。"""
    rel = _release(st, rel_id)
    root = Path(bt_root)
    pr_n = str(pr).lstrip("#")
    _git(root, "checkout", "-q", rel["branch"])
    changes = BookText(rel["book"], root).path("CHANGES.md")
    base_lines = set(_git(root, "show", f"{rel['base']}:{changes.relative_to(root).as_posix()}").splitlines())
    lines = changes.read_text(encoding="utf-8").splitlines()
    n = 0
    for i, ln in enumerate(lines):
        if ln not in base_lines and ln.rstrip().endswith("| #TBD |"):
            lines[i] = ln.rstrip()[: -len("#TBD |")] + f"#{pr_n} |"
            n += 1
    if n:
        changes.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        _git(root, "add", changes.relative_to(root).as_posix())
        _git(root, "commit", "-q", "-m", f"CHANGES 补 PR 号 #{pr_n}")
    commit = _git(root, "rev-parse", "HEAD")
    for oid in rel["opinions"]:
        st.log(oid, "pr_opened", {"release": rel_id, "pr": pr_n})
    st.add_row("releases", {**rel, "pr": pr_n, "commit": commit, "status": "pr_open", "ts": now_iso()})
    return {"release": rel_id, "pr": pr_n, "changes_lines_fixed": n, "commit": commit}


def finish_merged(st, rel_id: str, commit: str, *, publish_status=None) -> dict:
    """PR 合并后：记 ``applied``、格谱系、度量、网站状态、``published``。``publish_status`` 是个无参函数（调 ``webstatus.publish``）。"""
    rel = _release(st, rel_id)
    if rel.get("status") == "published":
        return {"release": rel_id, "note": "已结案，不重做"}
    ver = rel["to"]["text"]
    for oid in rel["opinions"]:
        st.log(oid, "applied", {"text_version": ver, "release": rel_id, "pr": rel.get("pr"), "commit": commit})
    for c in rel.get("cells") or []:
        st.add_row("lineage", {"cell": c["a"], "vol": rel["vol"], "release": rel_id, "from_version": rel["from"]["text"],
                               "to_version": ver, "before": c.get("before"), "after": c.get("after"),
                               "opinion": c["opinion"], "class": c.get("class"), "why": c.get("why", ""),
                               **({"inserted_after": c["inserted_after"]} if c.get("inserted_after") else {}),
                               "ts": now_iso()})
    decided = [st.last(o, "decided") for o in rel["opinions"]]
    auto = sum(1 for d in decided if d and (d.data or {}).get("auto"))
    st.add_row("metrics", {"ts": now_iso(), "release": rel_id, "book": rel["book"], "vol": rel["vol"],
                           "from": rel["from"]["text"], "to": ver, "opinions": len(rel["opinions"]),
                           "cells": len(rel.get("cells") or []), "auto_decided": auto,
                           "human_decided": len(rel["opinions"]) - auto})
    st.add_row("releases", {**rel, "status": "merged", "commit": commit, "ts": now_iso()})
    out = {"release": rel_id, "applied": len(rel["opinions"])}
    if publish_status is not None:
        out["status"] = publish_status()
        for oid in rel["opinions"]:
            st.log(oid, "published", {"release": rel_id})
        st.add_row("releases", {**rel, "status": "published", "commit": commit, "ts": now_iso()})
    return out


# ---------------- 汇总 ----------------

def _short(op_id: str) -> str:
    return op_id.replace("op_", "")[:22]


def digest(st, rules: dict, *, since: str | None = None) -> str:
    """给人看的汇总（Markdown）：不要求任何人裁，只报告发生了什么、哪些留着。"""
    stat = st.statuses()
    pol = policy(rules)
    cnt = Counter(stat.values())
    cnt.pop("superseded", None)
    L = [f"# 意见修订汇总（{st.book}）", f"生成于 {now_iso()}，策略 rules.json v{rules.get('version')}（自动结案{'开' if pol.get('enabled') else '关'}，自动合并{'开' if (pol.get('merge') or {}).get('enabled') else '关'}）", ""]
    L.append("## 总览")
    L.append("，".join(f"{k} {v}" for k, v in sorted(cnt.items())) or "池里没有意见")
    todo_triage = [o for o in st.opinions.values() if stat[o.id] == "new"]
    if todo_triage:
        L.append(f"待初判 {len(todo_triage)} 条。")
    auto_rows = []
    for op in st.opinions.values():
        d = st.last(op.id, "decided")
        if d and (d.data or {}).get("auto") and (since is None or d.ts >= since):
            auto_rows.append((d.ts, op, d))
    L += ["", f"## 自动结案（{len(auto_rows)} 条）"]
    if not auto_rows:
        L.append("本期没有。")
    for ts, op, d in sorted(auto_rows, key=lambda x: x[0]):
        tri = st.last(op.id, "triaged")
        t = tri.data if tri else {}
        tg = (op.target or {})
        prop = (op.proposal or {}).get("text")
        L.append(f"- {_short(op.id)}｜{op.vol} {tg.get('start')}｜{tg.get('check') or ''}→{prop or ''}｜"
                 f"{(d.data or {}).get('decision')}（置信 {(d.data or {}).get('confidence')}）｜{t.get('rationale_public', '')}")
    parked = [o for o in st.opinions.values() if stat[o.id] in ("to_user", "discussing")]
    L += ["", f"## 留着的（{len(parked)} 条，系统不会替你裁，也不阻塞别的）"]
    if not parked:
        L.append("没有。")
    for op in parked:
        tri = st.last(op.id, "triaged")
        t = tri.data if tri else {}
        L.append(f"- {_short(op.id)}｜{op.vol} {(op.target or {}).get('start')}｜{stat[op.id]}｜{'；'.join(t.get('rule') or [])}")
    rels = sorted(st.release_latest().values(), key=lambda r: r.get("ts", ""))
    L += ["", f"## 发布批（{len(rels)} 个）"]
    for r in rels[-15:]:
        extra = f" PR {r['pr']}" if r.get("pr") else ""
        err = f" 失败：{r['error'][:120]}" if r.get("error") else ""
        L.append(f"- {r['id']}｜{r['status']}{extra}｜{len(r.get('opinions') or [])} 条{err}")
    ms = st.metrics
    if ms:
        tot = sum(m.get("opinions", 0) for m in ms)
        au = sum(m.get("auto_decided", 0) for m in ms)
        L += ["", "## 度量", f"累计发布 {len(ms)} 批、{tot} 条意见、{sum(m.get('cells', 0) for m in ms)} 格；自动结案占 {au}/{tot}。"]
    return "\n".join(L) + "\n"
