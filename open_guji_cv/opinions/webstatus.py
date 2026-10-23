"""意见池处理结论 → 网站状态清单（M11 B2 第一步，GUJI-714）。

把池里**网站来源**的意见（改字 ``charfix``、一段有问题／专名 ``span``）按网站的「一处意见」``target`` 聚合，
算出网站状态，写进中心库 ``feedback/lists/web/<书>/status.jsonl``。网站每日 Action（kaiyuanguji-web
``proofing-sync``）读它，与 KV 现状比，不同的才 ``POST /api/fixes`` 回写（``fs:`` 状态＋整理组回复），
并把状态合进 COS 公开清单。精校票（``cellreview``）不发：精校页不显示结果；通用反馈 ``fb_`` 没有格位，也不发。

状态映射（意见状态由 log 推，``store.statuses()``）：

| 意见状态 | 网站 state | 带什么 |
|---|---|---|
| ``applied`` | ``adopted`` | ``version``＝log ``applied`` 的 ``text_version``；回复「已进文本 vX」＋公开理由 |
| ``accepted``／``auto_accepted`` | ``adopted`` | 不带 version；回复「已采纳，待随下一版文本更新」＋公开理由 |
| ``rejected``／``auto_rejected`` | ``rejected`` | ``reason``＝判定的 ``rationale_public``；回复只在比理由多出内容时才带 |
| ``to_user``／``discussing`` | ``discussing`` | 回复「还要再看」 |
| ``dup`` | 随它指向的那条 | — |
| 其余（``new``、``forwarded``、``superseded``…） | 不写（网站保持 open） | — |

同一 target 有多条意见时取最靠前的一档：已进文本 > 已采纳 > 讨论中 > 未采纳。
log 里有 ``replied``（已回复读者的定稿文字）的，回复用它，不再拼。

``status.jsonl`` 一行：``{v:1, book, volume, target, state, version?, reason?, reply?, opinions:[id…], ts}``，
按章、格位、target 排序；内容（除 ``ts``）没变的行保留旧 ``ts``，整份没变就不重写（幂等）。
上次发过、这次没有状态的 target 留一行 ``state: "open"``（撤回网站上的旧状态）。
"""
from __future__ import annotations

import json
import re

from .rules import reply_body, template_core
from .schema import Opinion, cell_key, now_iso
from .store import LocalBackend, RemoteBackend

WEB_DIR = "feedback/lists/web/{book}"
STATUS_FILE = "status.jsonl"
WEB_CHANNELS = ("charfix", "span")
#: 网站 /api/fixes 的限制（edge-functions/api/fixes.js validateTeamWrite）
REASON_MAX = 200
REPLY_MAX = 500
RE_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,16}$")

STATE_OF = {"applied": "adopted", "accepted": "adopted", "auto_accepted": "adopted",
            "rejected": "rejected", "auto_rejected": "rejected",
            "to_user": "discussing", "discussing": "discussing",
            "reverted": "discussing"}      # 撤销后回到「还要再看」，网站不再显示已改
#: 同一 target 多条意见时谁说了算（大的优先）
RANK = {("adopted", True): 4, ("adopted", False): 3, ("discussing", False): 2, ("rejected", False): 1}

REPLY_PENDING = "感谢指正，已采纳，待随下一版文本更新。"
REPLY_APPLIED = "感谢指正，已采纳，已进文本 {v}。"
REPLY_DISCUSS = "感谢指正，这一处还要再看，结果会在这里更新。"
REPLY_REJECTED = "感谢指正。"


def web_volume(op: Opinion) -> str:
    """网站 KV 里的册号：中心库快照来的 raw_id 是 ``cf:<书>:<册>:…``，照原样取；公开读来的用意见的三位章号。"""
    rid = op.raw_id or ""
    if rid[:3] in ("cf:", "cs:", "ce:"):
        parts = rid.split(":")
        if len(parts) > 2 and parts[2]:
            return parts[2]
    return op.vol


def web_target(op: Opinion) -> str | None:
    """网站「一处意见」的 target：``<kind>~<首格>~<末格>~<类别>``（与 thread.js、fixes.js targetOf 同口径）。
    非网站来源、或缺格位的返回 None。"""
    if op.channel not in WEB_CHANNELS:
        return None
    rid = op.raw_id or ""
    # 公开实时读入池的，raw_id 就是 ``<target>~<who>``
    m = re.match(r"^((?:char|span|entity)~[^~]*~[^~]*~[^~]*)~[^~]*$", rid)
    if m:
        return m.group(1)
    t = op.target or {}
    s, e = t.get("start"), t.get("end")
    if not s:
        return None
    if op.channel == "charfix":
        return f"char~{s}~~"
    if rid.startswith("ce:") or op.category == "entity" and (op.extra or {}).get("entity_id"):
        return f"entity~{s}~{e or ''}~"
    sub = (op.extra or {}).get("sub") or ""
    return f"span~{s}~{e or ''}~{sub}"


def _vkey(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.]", v or ""))


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _target_key(row: dict) -> tuple:
    parts = row["target"].split("~")
    try:
        ck = cell_key(parts[1])
    except (IndexError, ValueError):
        ck = (0, 0, 0, "")
    return (row["volume"], ck, row["target"])


def _reply_for(store, op: Opinion, state: str, version: str | None, reason: str) -> str:
    """一条意见给网站的整理组回复；空串表示不回。"""
    rep = store.last(op.id, "replied")
    if rep is not None and (rep.data or {}).get("text"):
        return rep.data["text"].strip()
    if state == "discussing":
        return REPLY_DISCUSS
    tri = store.last(op.id, "triaged")
    body = reply_body(tri.data, op) if tri is not None else ""
    if state == "adopted":
        return (REPLY_APPLIED.format(v=version) if version else REPLY_PENDING) + body
    if state == "rejected":
        if not body and not (reason or "").strip():
            # 人裁驳回又没写公开理由：判定是「原文不误」且知道原字的，回复用模板句（「此处原文作「甲」，暂不改」），
            # 不然读者只看到「未采纳」
            if tri is not None and tri.data.get("verdict") == "text_ok" and (op.target or {}).get("check"):
                return template_core("text_ok", tri.data.get("revision"), op)
            return ""
        # 理由已在状态里显示；回复只在比理由多出内容时才带
        if not body or body.strip("。 ") == (reason or "").strip("。 "):
            return ""
        return REPLY_REJECTED + body
    return ""


def compute(store) -> tuple[list[dict], list[str]]:
    """意见池 → 网站状态行（不带 ts）与说明。只看网站来源；精校票、通用反馈、机器意见不发。"""
    stat = store.statuses()
    notes: list[str] = []
    # 每条意见的 (state, version)
    per: dict[str, tuple[str, str | None]] = {}
    for op in store.opinions.values():
        s = stat.get(op.id)
        if s == "dup":
            continue
        st = STATE_OF.get(s)
        if not st:
            continue
        ver = None
        if s == "applied":
            ev = store.last(op.id, "applied")
            ver = str((ev.data or {}).get("text_version") or "") or None
            if ver and not RE_VERSION.match(ver):
                notes.append(f"{op.id}：text_version {ver!r} 网站不收，状态不带版本")
                ver = None
        per[op.id] = (st, ver)
    for op in store.opinions.values():  # dup 随它指向的那条
        if stat.get(op.id) == "dup":
            ev = store.last(op.id, "dup")
            root = (ev.data or {}).get("of") if ev else None
            if root in per:
                per[op.id] = per[root]
    groups: dict[tuple[str, str], list[Opinion]] = {}
    for op in store.opinions.values():
        if op.id not in per:
            continue
        tgt = web_target(op)
        if tgt is None:
            if op.channel in WEB_CHANNELS:
                notes.append(f"{op.id}：算不出网站 target，跳过")
            continue
        groups.setdefault((web_volume(op), tgt), []).append(op)
    rows = []
    for (vol, tgt), ops in groups.items():
        best = max(RANK[(per[o.id][0], bool(per[o.id][1]))] for o in ops)
        lead = sorted((o for o in ops if RANK[(per[o.id][0], bool(per[o.id][1]))] == best), key=lambda o: (o.ts, o.id))
        state = per[lead[0].id][0]
        versions = sorted({per[o.id][1] for o in lead if per[o.id][1]}, key=_vkey)
        version = versions[-1] if versions else None
        reason = ""
        if state == "rejected":
            rs = []
            for o in lead:
                tri = store.last(o.id, "triaged")
                r = ((tri.data if tri else {}) or {}).get("rationale_public") or ""
                if r.strip() and r.strip() not in rs:
                    rs.append(r.strip())
            reason = _clip("；".join(rs), REASON_MAX)
        replies = []
        for o in lead:
            if stat.get(o.id) == "dup":
                continue  # 重复票的回复归本条（看当前状态：撤销过 dup 的意见照常回复）
            r = _reply_for(store, o, state, version, reason)
            if r and r not in replies:
                replies.append(r)
        row = {"v": 1, "book": store.book, "volume": vol, "target": tgt, "state": state}
        if version:
            row["version"] = version
        if reason:
            row["reason"] = reason
        if replies:
            row["reply"] = _clip("\n".join(replies), REPLY_MAX)
        row["opinions"] = sorted(o.id for o in ops)
        rows.append(row)
    rows.sort(key=_target_key)
    return rows, notes


def _line(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def _strip_ts(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "ts"}


def render(rows: list[dict], old_text: str | None, ts: str | None = None) -> tuple[str, dict]:
    """新行 → 文件全文。与旧文件同 (章, target) 且内容相同的行保留旧 ts。返回 (全文, 计数)。

    旧文件有、这次算不出状态的 target（意见重开、改判成不写的状态……）写一行 ``state: "open"``，
    网站据此把 KV 里的旧状态撤回；已经是 open 的旧行原样保留（幂等，日后有了新状态再被顶掉）。"""
    old = {}
    for ln in (old_text or "").splitlines():
        if ln.strip():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            old[(d.get("volume"), d.get("target"))] = d
    ts = ts or now_iso()
    out, n = [], {"same": 0, "changed": 0, "added": 0}
    for r in rows:
        prev = old.pop((r["volume"], r["target"]), None)
        if prev is not None and _strip_ts(prev) == r and prev.get("ts"):
            out.append({**r, "ts": prev["ts"]})
            n["same"] += 1
        else:
            out.append({**r, "ts": ts})
            n["changed" if prev is not None else "added"] += 1
    n["reopened"] = 0
    for prev in old.values():
        if not prev.get("volume") or not prev.get("target"):
            continue
        if prev.get("state") == "open" and prev.get("ts"):
            out.append(prev)
            continue
        out.append({"v": 1, "book": prev.get("book"), "volume": prev["volume"], "target": prev["target"],
                    "state": "open", "opinions": prev.get("opinions") or [], "ts": ts})
        n["reopened"] += 1
    out.sort(key=_target_key)
    return "".join(_line(r) + "\n" for r in out), n


def status_backend(book: str, *, ws: str | None = None, root=None, remote: bool = False,
                   token_env: str = "GUJI_DATA_TOKEN", branch: str = "main"):
    """``status.jsonl`` 写在哪：``--remote`` 是中心库 ``feedback/lists/web/<书>/``；本地缺省是数据目录同一路径；
    ``root`` 给了是 ``<root>/_web/<书>/``（试跑，不进中心库）。"""
    import os
    from pathlib import Path
    if remote:
        from ..datastore.client import WorkerSource
        tok = os.environ.get(token_env)
        if not tok:
            raise SystemExit(f"缺环境变量 {token_env}（中心库令牌）")
        if not ws:
            raise SystemExit("--remote 要给工作区 id（--ws）")
        b = RemoteBackend(WorkerSource(token=tok, branch=branch), ws, book, branch)
        b.dir = WEB_DIR.format(book=book)
        return b
    if root is not None:
        return LocalBackend(Path(root) / "_web" / book)
    if not ws:
        raise SystemExit("本地要给 --root，或给 --ws 用数据目录")
    from ..core.workspace import central_data_dir
    return LocalBackend(central_data_dir(ws, branch) / "feedback" / "lists" / "web" / book)


def publish(store, backend, *, dry_run: bool = False, ts: str | None = None) -> dict:
    """算状态、与现有 ``status.jsonl`` 比，变了才写。返回 {rows, text, counts, notes, written, where}。"""
    rows, notes = compute(store)
    old_text, old_sha = backend.read(STATUS_FILE)
    text, counts = render(rows, old_text, ts)
    changed = text != (old_text or "")
    written = False
    if changed and not dry_run:
        backend.write(STATUS_FILE, text, old_sha)
        written = True
    return {"rows": [json.loads(x) for x in text.splitlines()], "text": text, "counts": counts, "notes": notes,
            "changed": changed, "written": written, "where": f"{backend.describe().rstrip('/')}/{STATUS_FILE}"}
