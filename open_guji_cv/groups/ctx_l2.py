"""M7 上下文路 L2（GUJI-563 块 E）：大模型离线批跑 → 答案表 → 管线只查表。

流程（模型不在管线里调用）：
  1. `build_batch(group, cells)`：把格（id＋前后各 20 字）排成给模型的消息（提示词＝`config/groups/<组>/prompt.md`）；
  2. 各家模型各跑一遍，输出 JSON 数组（`parse_output`）；
  3. `merge_runs`：**所有遍一致才给字**（且没有一遍说「其他」、置信都不是 low），否则弃权并写明原因，出 `group_clf/1` 表
     （`ctx_ver` 跟随 `context.CTX_VER`，键＝`context.ctx_key`，与旧版本的表不混）；
  4. `CtxL2Backend`：查表，ctx 对不上／版本对不上一律弃权。
本模块不被任何 Step 引用，不改产物指纹。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .context import CTX_VER, WIDTH, ctx_key
from .protocol import GroupVerdict, JudgeInput

OTHER = "其他"
CONFS = ("high", "mid", "low")


def load_prompt(path: str | Path) -> tuple[dict, str]:
    """→ (frontmatter, 正文)。frontmatter 只认简单的 `key: value` 行（ver、group、members）。"""
    t = Path(path).read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", t, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        t = t[m.end():]
    return meta, t.strip()


def render_cell(cell_id: str, left: str, right: str) -> str:
    return f"{cell_id}\t{left[-WIDTH:]}【?】{right[:WIDTH]}"


def build_batch(prompt_path: str | Path, cells: list[dict]) -> str:
    """cells: [{id, left, right}]。→ 整条消息文本（提示词＋逐条输入）。"""
    _, body = load_prompt(prompt_path)
    lines = [render_cell(c["id"], c.get("left") or "", c.get("right") or "") for c in cells]
    return body + "\n\n**本批输入**（每行：id、制表符、前文【?】后文）：\n" + "\n".join(lines) + "\n"


def parse_output(text: str) -> dict[str, dict]:
    """从模型输出里取 JSON 数组（容忍前后夹文字、代码围栏）。→ {id: {char, conf, why}}。"""
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {}
    for e in arr:
        if isinstance(e, dict) and e.get("id"):
            out[str(e["id"])] = {"char": e.get("char"), "conf": e.get("conf"), "why": e.get("why", "")}
    return out


def merge_runs(group: str, members: str, ver: str, runs: dict[str, dict], ctxs: dict[str, tuple[str, str]],
               min_conf: tuple = ("high", "mid")) -> dict:
    """runs: {模型名: {id: {char, conf, why}}}；ctxs: {id: (left, right)}（建表时用的窗口，写进键）。
    规则：每个模型都有答案、都在组内、都不是「其他」、置信 ∈ min_conf、且字相同 → 给字；否则 char=None 并写原因。"""
    cells = {}
    for cid, (left, right) in ctxs.items():
        votes = {m: r.get(cid) for m, r in runs.items()}
        ans = [v for v in votes.values() if v]
        if len(ans) < len(runs):
            ch, why = None, "abstain:missing_run"
        elif any(v.get("char") == OTHER for v in ans):
            ch, why = None, "abstain:other"
        elif any(v.get("char") not in members for v in ans):
            ch, why = None, "abstain:non_member"
        elif len({v["char"] for v in ans}) > 1:
            ch, why = None, "disagree"
        elif any(v.get("conf") not in min_conf for v in ans):
            ch, why = None, "abstain:low_conf"
        else:
            ch, why = ans[0]["char"], "agree"
        left, right = left[-WIDTH:], right[:WIDTH]
        cells[cid] = {"ctx": ctx_key(left, right), "char": ch, "why": why,
                      "votes": {m: ([v["char"], v.get("conf")] if v else None) for m, v in votes.items()}}
    return {"schema": "group_clf/1", "group": group, "ctx_ver": CTX_VER, "ver": ver, "models": sorted(runs), "cells": cells}


class CtxL2Backend:
    name = "ctx_l2"

    def __init__(self, table: dict | str | Path):
        if isinstance(table, dict):
            self._t, self.fingerprint = table, ""
        else:
            raw = Path(table).read_bytes()
            self._t, self.fingerprint = json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()[:16]

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        t = self._t
        if t.get("schema") != "group_clf/1" or t.get("group") != spec.id or t.get("ctx_ver") != CTX_VER:
            return GroupVerdict(None, why="ver_mismatch", via="ctx_l2")
        e = (t.get("cells") or {}).get(cell.id)
        if not e:
            return GroupVerdict(None, why="cache_miss", via="ctx_l2")
        left, right = cell.window(WIDTH)
        if e.get("ctx") != ctx_key(left, right):
            return GroupVerdict(None, why="ctx_mismatch", via="ctx_l2")
        ch = e.get("char")
        if ch is not None and ch not in spec.members:
            ch = None
        return GroupVerdict(ch, why=str(e.get("why") or ""), via="ctx_l2", extra={"votes": e.get("votes")})
