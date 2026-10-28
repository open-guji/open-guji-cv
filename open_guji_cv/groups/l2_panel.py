"""文意 L2 表的强模型复核（2026-10-24，A24「优化己已巳判别」）：离线把 Opus／Sonnet 的批跑结果合进已有的 `group_clf/1` 表。

为什么：己已巳 vol11–20 的表只有 haiku 一遍，haiku 不是 high 的 90 格全部送审；而表里 haiku high 的格也有错
（vol15:123:7:18「附入【己】見」haiku 判已）。规则（`panel_merge`）：

- **否决**：表里已给字的格（`agree`、`agree:review`），强模型以 high 给了别的答案（组内另一字或「其他」）→ 弃权
  （`why=abstain:panel_veto`）。
- **补字**：表里弃权的格、或表里没有的新格，强模型 high 给组内字，且第二模型给了同一个字（置信不限），且主模型没有以 high
  给过别的字 → 用这个字（`why=agree:panel`）。新格主模型 high、强模型没有以 high 反对 → `agree`。
- 其余照旧；每格记下各模型的票（`votes`），补字和否决的格另记强模型的理由（`note`，文意判断的备注）。

金标（vol01–05 强真值，215 格）上：L1 → haiku high → 本规则，给字 209，错 1（vol03:109:6:5，金标与维基文库本不一，待 sheldon 定）。
本模块不被任何 Step 引用，不改产物指纹；管线照旧只查表（`ctx_l3.CtxL3Backend`）。
"""
from __future__ import annotations

from collections import Counter

from .context import WIDTH, ctx_key
from .ctx_l3 import OTHER

GIVE_WHY = ("agree", "agree:review", "agree:panel")


def _vote(v: dict | None):
    return [v.get("char"), v.get("conf")] if v else None


def panel_merge(table: dict, runs: dict[str, dict], members: str, ctxs: dict[str, tuple[str, str]] | None = None,
                main: str = "haiku", strong: str = "opus", second: str = "sonnet") -> Counter:
    """就地改 `table`。`runs`＝{模型名: {格: {char, conf, why}}}（`ctx_l3.parse_output` 的输出）；`ctxs`＝表里没有的新格的
    窗口 {格: (left, right)}（与管线同一取法，见 `research/m7/ctx/l2_make_book.py`）。→ 各结局的格数。"""
    cells = table.setdefault("cells", {})
    ctxs = ctxs or {}
    n = Counter()
    ids = set(cells) | set(ctxs)
    for cid in sorted(ids):
        e = cells.get(cid)
        if e is None:
            left, right = ctxs[cid]
            e = {"ctx": ctx_key(left[-WIDTH:], right[:WIDTH]), "char": None, "why": "abstain:new", "votes": {}}
        votes = e.setdefault("votes", {})
        for m, r in runs.items():
            if r.get(cid):
                votes[m] = _vote(r[cid])
        s = (runs.get(strong) or {}).get(cid)
        t = (runs.get(second) or {}).get(cid)
        h = votes.get(main)
        s_high = bool(s and s.get("conf") == "high")
        if e.get("char") is not None:
            if s_high and s.get("char") != e["char"]:
                e["char"], e["why"], e["note"] = None, "abstain:panel_veto", f"{strong}: {s.get('char')} {s.get('why', '')}"
                n["veto"] += 1
            else:
                n["keep"] += 1
        elif cid not in cells and h and h[1] == "high" and h[0] in members and not (s_high and s.get("char") != h[0]):
            e["char"], e["why"] = h[0], "agree"
            n["new_main"] += 1
        elif (s_high and s.get("char") in members and t and t.get("char") == s.get("char")
              and not (h and h[1] == "high" and h[0] != s.get("char"))):
            e["char"], e["why"], e["note"] = s["char"], "agree:panel", f"{strong}: {s.get('why', '')}"
            n["panel"] += 1
        else:
            n["abstain"] += 1
        cells[cid] = e
    table["models"] = sorted({*table.get("models", []), *runs})
    return n


__all__ = ["panel_merge", "GIVE_WHY", "OTHER"]
