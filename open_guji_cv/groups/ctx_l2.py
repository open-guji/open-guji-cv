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


def add_review(table: dict, model: str, run: dict, members: str, need: tuple = ("high",)) -> int:
    """第二个模型复核（sheldon 10-22 定，同日放宽）：主表里主模型没给出把握的格（`abstain:low_conf`、`abstain:other`），
    复核模型给组内字且置信 ∈ `need`、主模型又没有哪一遍以 high 给过别的字 → 用复核模型的字（why=`agree:review`）；
    其余格不动，只记票。就地改 `table`，返回改了几格。
    己已巳 179 格人工标注上：haiku 非 high、Sonnet high 的 9 格全对（8 格同字、1 格异字）。"""
    n = 0
    for cid, e in (table.get("cells") or {}).items():
        v = run.get(cid)
        if not v:
            continue
        e.setdefault("votes", {})[model] = [v.get("char"), v.get("conf")]
        if e.get("why") not in ("abstain:low_conf", "abstain:other"):
            continue
        main = [x for m, x in e["votes"].items() if m != model and x]
        if any(x[1] == "high" and x[0] != v.get("char") for x in main):
            continue
        if v.get("char") in members and v.get("conf") in need:
            e["char"], e["why"] = v["char"], "agree:review"
            n += 1
    if model not in table.get("models", []):
        table["models"] = sorted([*table.get("models", []), model])
    return n


def add_confirm(table: dict, runs: dict, need: tuple = ("high",)) -> int:
    """再跑几遍确认（日曰，sheldon 10-22「文意置信度特别高可以改掉整理本」）：`runs`＝{模型名: {格: 答案}}。主表已给字的格，
    每一遍都给同一个字且置信 ∈ `need` → 记 `strong: true`。只有 strong 的答案能在复核时改掉别的通道放行的字
    （`FlowSpec.review_fix_strong`）；不 strong 的答案照旧（照常补放、照常降审）。就地改 `table`，返回 strong 格数。
    日曰 98 格人工标注上：haiku 与 Sonnet 都 high 且同字 66 格，错 1 格（vol02:183:8:7，sheldon 两轮复审为日）。"""
    n = 0
    for cid, e in (table.get("cells") or {}).items():
        vs = [r.get(cid) for r in runs.values()]
        for m, v in zip(runs, vs):
            if v:
                e.setdefault("votes", {})[m] = [v.get("char"), v.get("conf")]
        if e.get("char") is not None and all(v and v.get("char") == e["char"] and v.get("conf") in need for v in vs):
            e["strong"] = True
            n += 1
        else:
            e.pop("strong", None)
    table["models"] = sorted({*table.get("models", []), *runs})
    return n


def add_verify(table: dict, model: str, run: dict, members: str, ctxs: dict | None = None,
               need: tuple = ("high",)) -> dict:
    """逐格细读复核（日曰，A24 10-24）：一家逐格读文意（每格写依据）补进表。单遍 haiku 在 vol11–20 的日曰表里
    176 格错 6 格，其中 3 格与坐标对位字相反、会被补放成错字；细读与之不同就弃权。就地改 `table`，规则：
    - 记票；表里没有这一格、`ctxs` 里有 → 新建（键按 `ctxs[格]` 取）；
    - 细读给组内字、置信 ∈ `need`，其余各遍没有以 high 给过别的字 → 用细读的字（原来就是这个字时 why 不变，
      否则 why=`agree:verify`）；
    - 细读说「其他」、置信 ∈ `need`，其余各遍没有以 high 给组内字 → 弃权 `abstain:other`；
    - 以上都不成立、细读给了与表里不同的字（置信 high／mid）→ 弃权 `disagree:verify`；
    - 细读过的格按全部票重算 strong：至少两遍、都 high、同一个字且就是表里的字。
    → 各类计数 {verify, other, veto, new, strong}。"""
    cells = table.setdefault("cells", {})
    n = dict(verify=0, other=0, veto=0, new=0, strong=0)
    for cid, v in run.items():
        ch, conf = v.get("char"), v.get("conf")
        e = cells.get(cid)
        if e is None:
            if not ctxs or cid not in ctxs:
                continue
            left, right = ctxs[cid]
            e = cells[cid] = {"ctx": ctx_key(left[-WIDTH:], right[:WIDTH]), "char": None, "why": "abstain:missing_run",
                              "votes": {}}
            n["new"] += 1
        others = [x for m, x in (e.get("votes") or {}).items() if m != model and x]
        e.setdefault("votes", {})[model] = [ch, conf]
        if ch in members and conf in need and not any(x[1] == "high" and x[0] != ch for x in others):
            if e.get("char") != ch:
                e["char"], e["why"] = ch, "agree:verify"
                n["verify"] += 1
        elif ch == OTHER and conf in need and not any(x[1] == "high" and x[0] in members for x in others):
            if e.get("char") is not None or e.get("why") != "abstain:other":
                e["char"], e["why"] = None, "abstain:other"
                n["other"] += 1
        elif e.get("char") is not None and ch != e["char"] and conf in ("high", "mid"):
            e["char"], e["why"] = None, "disagree:verify"
            n["veto"] += 1
        vs = [x for x in e["votes"].values() if x]
        if (e.get("char") is not None and len(vs) >= 2
                and all(x[0] == e["char"] and x[1] == "high" for x in vs)):
            e["strong"] = True
            n["strong"] += 1
        else:
            e.pop("strong", None)
    if model not in table.get("models", []):
        table["models"] = sorted([*table.get("models", []), model])
    return n


def _canon_str(s, canon) -> str:
    return "".join(canon(c) for c in s) if isinstance(s, str) else ""


#: 窗口漂移（`drift`）时目标字两侧各这么多字内必须逐字相同（干支、搭配都在这里）
DRIFT_CORE = 3


def _split_key(k) -> tuple[str, str] | None:
    if not isinstance(k, str) or ":" not in k or "|" not in k:
        return None
    body = k.split(":", 1)[1]
    left, _, right = body.partition("|")
    return left, right


def ctx_drift(stored, now, canon=None, core: int = DRIFT_CORE) -> int | None:
    """表键 `stored` 与本格窗口键 `now` 差几个字位（按离目标字的距离逐位比，左文从右往左、右文从左往右；
    长度不同时多出的位也算差）；目标字两侧各 `core` 字内有差 → None（不算同一上下文）。
    建表后重跑，邻格的放行字会变（□→曰、徵→徴、远处一字改放），表就整条对不上（vol04–10 重跑后 己已巳／日曰 约 40 格）。
    本格窗口是「□」（组流时还没放行）而表键有字的位不算差：坐标兜底等组流之后的补放遍会把邻格放进来，
    按成品建表时这些位有字、组流时却是 □（vol09:251「祭統曰春祭曰礿」6 格因此整条对不上）。"""
    a, b = _split_key(stored), _split_key(now)
    if a is None or b is None:
        return None
    c = canon or (lambda x: x)
    n = 0
    for sa, sb in ((a[0][::-1], b[0][::-1]), (a[1], b[1])):
        for i in range(max(len(sa), len(sb))):
            x = c(sa[i]) if i < len(sa) else None
            y = c(sb[i]) if i < len(sb) else None
            if x != y and not (y == "□" and x is not None):
                if i < core:
                    return None
                n += 1
    return n


class CtxL2Backend:
    name = "ctx_l2"

    def __init__(self, table: dict | str | Path):
        if isinstance(table, dict):
            self._t, self.fingerprint = table, ""
        else:
            raw = Path(table).read_bytes()
            self._t, self.fingerprint = json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()[:16]

    def judge(self, spec, cell: JudgeInput, canon=None, drift: int = 0) -> GroupVerdict:
        """`drift`＞0：窗口对不上时，若只差远处（目标字两侧 `DRIFT_CORE` 字外）至多 `drift` 个字位，仍用表里的答案
        （证据 `ctx_drift` 记差几位）；0＝逐字相同才用。"""
        t = self._t
        if t.get("schema") != "group_clf/1" or t.get("group") != spec.id or t.get("ctx_ver") != CTX_VER:
            return GroupVerdict(None, why="ver_mismatch", via="ctx_l2")
        e = (t.get("cells") or {}).get(cell.id)
        if not e:
            return GroupVerdict(None, why="cache_miss", via="ctx_l2")
        left, right = cell.window(WIDTH)
        if canon is not None:
            # 书级码位归一：表键与本格窗口各自归一再比（别/別、巻/卷 不算上下文变了）
            same = _canon_str(e.get("ctx"), canon) == _canon_str(ctx_key(left, right), canon)
        else:
            same = e.get("ctx") == ctx_key(left, right)
        extra = {"votes": e.get("votes")}
        if not same:
            n = ctx_drift(e.get("ctx"), ctx_key(left, right), canon) if drift > 0 else None
            if n is None or n > drift:
                return GroupVerdict(None, why="ctx_mismatch", via="ctx_l2")
            extra["ctx_drift"] = n
        ch = e.get("char")
        if ch is not None and ch not in spec.members:
            ch = None
        why = str(e.get("why") or "")
        if why == "abstain:other":
            # 「组内字都不通」有多把握（共字组联合判 `flow.decide_joint` 只认 high）
            vs = [v for v in (e.get("votes") or {}).values() if v]
            extra["other_conf"] = "high" if vs and all(v[1] == "high" for v in vs) else "low"
        if ch is not None and e.get("strong"):
            extra["strong"] = True
        if ch is not None:
            # 几遍给了这个字（单遍答案拗整理本时不补放，`flow.group_flow_pass` 的 coord_dissent）
            extra["runs"] = sum(1 for v in (e.get("votes") or {}).values() if v and v[0] == ch)
        return GroupVerdict(ch, why=why, via="ctx_l2", extra=extra)
