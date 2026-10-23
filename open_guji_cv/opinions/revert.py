"""撤销一个已发布的修订批（M11 GUJI-734；设计 book-text ``docs/design/2026-10-已发1x文本修订流程.md``）。

不 ``git revert``：撤销也是一次正式修订——book-text 里一个 ``auto/revert-…`` 分支、文本线再升一个 patch、
CHANGES 写明撤销了哪个发布批、哪些意见、为什么；意见池里补 ``reverted`` 事件，原批标 ``reverted``。

| 函数 | 输入 | 输出 |
|---|---|---|
| ``prepare_revert`` | 状态 ``published``／``merged`` 的发布批 | 分支＋一次提交＋一行 ``kind=revert`` 的发布批（``checked``） |
| ``finish_revert_merged`` | 撤销批的 PR 已合并 | 各意见 ``reverted``、格谱系、原批 ``reverted``、网站状态 |

撤销批的 ``finish_pr`` 与普通批共用 ``auto.finish_pr``。现文与原批的 ``after`` 对不上（之后又被改过）就拒绝，不覆盖后来的改动。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from . import revise as V
from .auto import AutoError, _git, _release, _run_checks, RELEASE_SCHEMA
from .schema import now_iso
from .textsrc import BookText, vol_key


def _base_text(root: Path, rel: dict, path: Path) -> str | None:
    r = _git(root, "show", f"{rel['base']}:{path.relative_to(root).as_posix()}", check=False)
    return r or None


def _unapply(char: dict, cord: dict, base_cord: dict | None, cells: list[dict]) -> tuple[dict, list[str]]:
    """把原批的格逐个退回。返回 (B′ 退回的 {新格: 前一格}, 说明)。对不上就 AutoError。"""
    moves, notes = {}, []
    for c in cells:
        a = c["a"]
        col, i, cur = V._find_cell(char, a)
        if cur is None:
            raise AutoError(f"现文没有 {a}，之后被动过，不能自动撤销")
        if c.get("inserted_after"):                     # B′：删掉新格，cord 框放回去
            if cur != c["after"]:
                raise AutoError(f"{a} 现为 {cur}，原批写入的是 {c['after']}，之后被改过，不能自动撤销")
            page = int(a.split(":")[0])
            pg = next((p for p in cord.get("pages") or [] if p.get("page") == page), None)
            bpg = next((p for p in (base_cord or {}).get("pages") or [] if p.get("page") == page), None)
            mk = next((m for m in (bpg or {}).get("marks") or [] if m.get("id") == c.get("mark")), None)
            if pg is None or mk is None:
                raise AutoError(f"找不到 {a} 原来的 cord 框 {c.get('mark')}（基线 cord 第 {page} 页）")
            del col["cells"][i]
            pg["cells"] = [x for x in pg.get("cells") or [] if x.get("a") != a]
            idx = next((n for n, m in enumerate(bpg["marks"]) if m.get("id") == mk["id"]), len(pg.setdefault("marks", [])))
            pg.setdefault("marks", []).insert(min(idx, len(pg["marks"])), copy.deepcopy(mk))
            moves[a] = c["inserted_after"]
        else:                                           # A／B：整格退回
            if cur != c["after"]:
                raise AutoError(f"{a} 现为 {cur}，原批写入的是 {c['after']}，之后被改过，不能自动撤销")
            col["cells"][i] = copy.deepcopy(c["before"])
        notes.append(a)
    return moves, notes


def prepare_revert(st, bt_root: str | Path, rel_id: str, reason: str, *, run_checks: bool = True,
                   base: str = "origin/main", trailers: list[str] | None = None, today: str | None = None) -> dict:
    """为已发布的批 ``rel_id`` 在 book-text 里准备撤销分支。工作树要干净；失败不留半成品。"""
    if not reason.strip():
        raise AutoError("撤销要写理由（--reason）")
    rel = _release(st, rel_id)
    if rel.get("kind") == "revert":
        raise AutoError("撤销批本身不能再撤销，要恢复就重新走意见→修订")
    if rel.get("status") not in ("published", "merged"):
        raise AutoError(f"{rel_id} 状态是 {rel.get('status')}，只有已合并／已发布的批才撤销")
    if any(r.get("reverts") == rel_id and r.get("status") in ("checked", "pr_open", "merged", "published")
           for r in st.release_latest().values()):
        raise AutoError(f"{rel_id} 已有进行中或已完成的撤销批")
    root, book, vol = Path(bt_root), rel["book"], rel["vol"]
    if _git(root, "status", "--porcelain"):
        raise AutoError(f"{root} 工作树不干净，先处理")
    today = today or now_iso()[:10]
    orig = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    _git(root, "fetch", "-q", "origin", "main", check=False)
    base_sha = _git(root, "rev-parse", base)
    branch = f"auto/revert-{book}-{vol_key(vol)}-{today}"
    _git(root, "checkout", "-q", "-B", branch, base)
    bt = BookText(book, root)
    v3 = vol_key(vol)
    vdir = bt.path("")
    names = {k: f"{v3}.{k}.json" for k in ("char", "cord", "punct", "entity")}
    try:
        texts = {k: bt.text(n) for k, n in names.items()}
        old_char = json.loads(texts["char"])
        char = copy.deepcopy(old_char)
        cord = json.loads(texts["cord"]) if texts["cord"] else {"pages": []}
        bc = _base_text(root, rel, vdir / names["cord"])
        moves, cells_done = _unapply(char, cord, json.loads(bc) if bc else None, rel.get("cells") or [])
        punct = json.loads(texts["punct"]) if texts["punct"] else None
        entity = json.loads(texts["entity"]) if texts["entity"] else None
        V.follow_companions(old_char, char, punct, entity, moves)
        ops = rel["opinions"]
        note = (f"撤销发布批 {rel_id}（文本 {rel['from']['text']}→{rel['to']['text']}）{len(cells_done)} 格："
                f"{'、'.join(cells_done)}；理由：{reason.strip()}［意见 {' '.join(ops)}］")
        script = root / "scripts" / "book-text" / "bump_original.py"
        (vdir / names["char"]).write_text(V.dump_like(texts["char"], char), encoding="utf-8", newline="\n")
        (vdir / names["cord"]).write_text(V.dump_like(texts["cord"], cord), encoding="utf-8", newline="\n")
        V.bump(script, vdir, "text", v3, note, "TBD")
        char_now = json.loads((vdir / names["char"]).read_text(encoding="utf-8"))
        new_v = char_now.get("version")
        for line in ("punct", "entity"):
            p = vdir / names[line]
            if not p.is_file():
                continue
            t = p.read_text(encoding="utf-8")
            d = json.loads(t)
            r = V.follow_companions(old_char, char_now, d if line == "punct" else None, d if line == "entity" else None, moves)
            if r[line]:
                p.write_text(V.dump_like(t, d, default="indent"), encoding="utf-8", newline="\n")
                V.bump(script, vdir, line, v3, f"跟随文本 {new_v}（撤销 {rel_id}）：{r[line]} 处锚点校验字／偏移更新", "TBD")
        final = {k: (json.loads((vdir / n).read_text(encoding="utf-8")) if (vdir / n).is_file() else None) for k, n in names.items()}
        index = json.loads((vdir / "index.json").read_text(encoding="utf-8"))
        ich = next((c for c in index.get("chapters") or [] if str(c.get("file")) == v3), None)
        problems = V.check_chapter(final["char"], final["cord"], final["punct"], final["entity"], ich)
        if problems:
            raise AutoError("出口检查：" + "；".join(problems))
        checks = _run_checks(root) if run_checks else {"local_check": "skipped", "tail": ""}
        if checks["local_check"] == "fail":
            raise AutoError("local_check 不过：\n" + checks["tail"])
    except (V.ReviseError, AutoError) as e:
        _git(root, "checkout", "-q", "--", ".", check=False)
        _git(root, "clean", "-fdq", check=False)
        _git(root, "checkout", "-q", orig, check=False)
        _git(root, "branch", "-D", branch, check=False)
        raise AutoError(str(e)) from e
    title = f"撤销发布批 {rel_id}：文本 {old_char.get('version')}→{new_v}"
    _git(root, "add", "-A", "Book")
    _git(root, "commit", "-q", "-m", title + "\n\n" + note + ("\n\n" + "\n".join(trailers) if trailers else ""))
    commit = _git(root, "rev-parse", "HEAD")
    new_id = f"rel_{book}_{v3}_{new_v}"
    row = {"schema": RELEASE_SCHEMA, "id": new_id, "kind": "revert", "reverts": rel_id, "reason": reason.strip(),
           "book": book, "vol": v3, "from": {"text": old_char.get("version")}, "to": {"text": new_v},
           "opinions": ops, "cells": [{"a": c["a"], "before": c.get("after"), "after": c.get("before"),
                                       "opinion": c["opinion"], "class": c.get("class")} for c in rel["cells"]],
           "branch": branch, "base": base_sha, "commit": commit, "pr": None,
           "checks": {"local_check": checks["local_check"]}, "diff": {"cells": len(cells_done)},
           "protected_conflicts": 0, "status": "checked", "title": title, "ts": now_iso()}
    st.add_row("releases", row)
    _git(root, "checkout", "-q", orig, check=False)
    return {"release": new_id, "reverts": rel_id, "branch": branch, "title": title, "commit": commit,
            "pr_body": note + "\n\n本批由 `guji opinions auto revert` 生成。本地检查：\n```\n" + checks["tail"] + "\n```"}


def finish_revert_merged(st, rel_id: str, commit: str, *, publish_status=None) -> dict:
    """撤销批合并后：各意见记 ``reverted``，格谱系补撤销行，原批标 ``reverted``，更新网站状态。"""
    rel = _release(st, rel_id)
    if rel.get("kind") != "revert":
        raise AutoError(f"{rel_id} 不是撤销批")
    if rel.get("status") == "published":
        return {"release": rel_id, "note": "已结案，不重做"}
    orig = rel["reverts"]
    for oid in rel["opinions"]:
        st.log(oid, "reverted", {"release": orig, "revert_release": rel_id, "reason": rel["reason"],
                                 "text_version": rel["to"]["text"], "pr": rel.get("pr"), "commit": commit})
    for c in rel.get("cells") or []:
        st.add_row("lineage", {"cell": c["a"], "vol": rel["vol"], "release": rel_id, "revert_of": orig,
                               "from_version": rel["from"]["text"], "to_version": rel["to"]["text"],
                               "before": c.get("before"), "after": c.get("after"), "opinion": c["opinion"],
                               "why": rel["reason"], "ts": now_iso()})
    o = st.release_latest().get(orig)
    if o:
        st.add_row("releases", {**o, "status": "reverted", "reverted_by": rel_id, "ts": now_iso()})
    out = {"release": rel_id, "reverted": len(rel["opinions"])}
    st.add_row("releases", {**rel, "status": "merged", "commit": commit, "ts": now_iso()})
    if publish_status is not None:
        out["status"] = publish_status()
        st.add_row("releases", {**rel, "status": "published", "commit": commit, "ts": now_iso()})
    return out
