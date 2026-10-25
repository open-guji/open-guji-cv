"""确定性规则（设计第三节 ``rules.py``、C2）：分流去向、修订分类、起草事件与回复。

「判」（verdict、confidence、理由）第一阶段由会话做；这里只管判完之后**不靠判断**的部分：

去向（按顺序，先中先定）：
1. 已是 dup／superseded／forwarded 的不判；
2. 标点、专名类别，或判「超出范围」→ ``forward``；
3. 校验字与现文对不上（版本漂移）→ ``to_user``；现文已是建议字 → ``auto_accept``（已改，只回复不改文本）；
4. 判「图无字录阙文带推测字」「切分问题」「看不清」→ ``to_user``（Q7 新原则、C 类修订都要人定）；
5. 这一格用户亲裁过（``human_cells``，或池里同格意见有用户的 ``decided``）→ ``to_user``；
6. 疑似刷票（同一来源当天意见过多且大多与原文不同；同格 1 小时内多来源集中）→ ``to_user``；
7. 判「建议对」：置信度、证据一致路数够档、修订类在许可内 → ``auto_accept``，否则 ``to_user``；
8. 判「原文对」：置信度够档且有公开理由 → ``auto_reject``，否则 ``to_user``。
会话可以要更保守的去向（``to_user``／``discuss``），不能比规则更激进。

门槛在 ``config/opinions/rules.json``（``published``＝冻结册、``proofing``＝0.x），初值待评测集标定。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .schema import Opinion, cell_key, norm_class

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "opinions" / "rules.json"
DEFAULT_RULES = {
    "version": 1,
    "profiles": {
        "published": {"auto_accept": {"min_confidence": 0.95, "min_evidence_agree": 2, "classes": ["A", "B"]},
                      "auto_reject": {"min_confidence": 0.9},
                      "to_user_verdicts": ["lacuna_guess", "seg_issue", "unclear"], "reply_required": True},
        "proofing": {"auto_accept": {"min_confidence": 0.8, "min_evidence_agree": 1, "classes": ["A", "B"]},
                     "auto_reject": {"min_confidence": 0.9},
                     "to_user_verdicts": ["lacuna_guess", "seg_issue", "unclear"], "reply_required": False},
    },
    "forward": {"punct": "punct", "entity": "entity"},
    "flood": {"per_source_per_day": 60, "disagree_ratio": 0.8, "burst_sources": 5, "burst_seconds": 3600},
}
CONSERVATIVE = ("to_user", "discuss")
LACUNA = "□"


class RuleError(ValueError):
    pass


def load_rules(path: str | Path | None = None) -> dict:
    p = Path(path) if path else RULES_PATH
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return DEFAULT_RULES


# ---- 修订 ----

def _grid(a: str) -> tuple[str, int, str]:
    """``3:1:9`` → ("3:1", 9, "")；``3:4:6a`` → ("3:4", 6, "a")。"""
    p, c, s = a.split(":")
    sub = s[-1] if s[-1:] in ("a", "b") else ""
    return f"{p}:{c}", int(s[:-1] if sub else s), sub


def next_key(after: str) -> str:
    """紧接 ``after`` 的新格号：同列、同子列，格号加一（-1 的下一格是 1）。"""
    pc, g, sub = _grid(after)
    g = 1 if g == -1 else g + 1
    return f"{pc}:{g}{sub}"


def derive_revision(op: Opinion, verdict: str, char_cells: list[dict] | None, cord_pg: dict | None,
                    guess: str | None = None) -> dict | None:
    """由意见＋结论推修订（会话没给 ``--revision`` 时用）。推不出返回 None。

    - A：同格改字（``c`` 换成建议字）；
    - B：□↔字（原是阙文，补字；或建议改成 □）；
    - B′：意见格之后紧挨的是 cord 里的 mark（排除名单／留白），图上无字、文意应有 → 把 mark 变成 lacuna 格，带推测字；
    - C：多字、漏字要插格（mark 不在旁边）、拆并格——切分变了，第一阶段不做，只标类。"""
    t = op.target or {}
    s, e = t.get("start"), t.get("end")
    if not s or not char_cells:
        return None
    by = {c["a"]: c for c in char_cells}
    prop = (op.proposal or {}).get("text")
    if verdict == "accept" and s == e and s in by and prop and len(prop) == 1 and op.category in ("wrong", "lacuna", "unclear"):
        cur = by[s]
        if cur["c"] == LACUNA and cur.get("lacuna"):
            return {"class": "B", "cells": [{"a": s, "from": LACUNA, "to": prop}]}
        if prop == LACUNA:
            return {"class": "B", "cells": [{"a": s, "from": cur["c"], "to": LACUNA, "lacuna": True}]}
        return {"class": "A", "cells": [{"a": s, "from": cur["c"], "to": prop}]}
    if verdict in ("accept", "lacuna_guess") and op.category == "missing" and e in by:
        check = t.get("check") or ""
        added = prop[len(check):] if prop and check and prop.startswith(check) else None
        if added and len(added) == 1 and cord_pg is not None:
            from .evidence import column_units
            seq = [c["a"] for c in char_cells]
            col = int(e.split(":")[1])
            units = column_units(cord_pg, by, col, seq)
            i = next((k for k, u in enumerate(units) if u.a == e), None)
            nxt = units[i + 1] if i is not None and i + 1 < len(units) else None
            if nxt is not None and nxt.kind in ("excluded", "blank"):
                a = next_key(e)
                if a in by:
                    raise RuleError(f"新格号 {a} 已有字，B′ 要改格号，属 C 类")
                g = guess or added
                cell = {"a": a, "after": e, "mark": nxt.mark_id, "from": nxt.kind, "to": LACUNA, "lacuna": True}
                if verdict == "lacuna_guess":
                    cell["guess"] = g
                else:
                    cell["to"] = g
                    cell.pop("lacuna")
                return {"class": "B′", "cells": [cell]}
        return {"class": "C", "cells": [{"a": e, "after": e, "to": added or prop or ""}],
                "note": "漏字要插格且旁边没有可用的 mark：切分变了（C 类，依赖 GUJI-579）"}
    if verdict == "seg_issue":
        return {"class": "C", "cells": [{"a": s, "to": prop or ""}]}
    return None


def draft_event(rev: dict | None) -> dict | None:
    """起草 CV 人裁事件（第二阶段在恢复的工作区补写，GUJI-718）。"""
    if not rev:
        return None
    c = (rev.get("cells") or [{}])[0]
    k = norm_class(rev.get("class"))
    if k == "A" or (k == "B" and c.get("to") != LACUNA):
        return {"v": "confirm", "shape": c.get("to"), "cell": c.get("a")}
    if k == "B":
        return {"v": "damaged", "cell": c.get("a")}
    if k == "B′":
        ev = {"v": "damaged" if c.get("lacuna") else "confirm", "cell": c.get("a"),
              "note": f"先移出排除名单（mark {c.get('mark')}），再写事件"}
        if c.get("guess"):
            ev["guess"] = c["guess"]
        if not c.get("lacuna"):
            ev["shape"] = c.get("to")
        return ev
    return {"v": "seg_defect", "cell": c.get("a"), "note": "C 类，切分变了"}


def template_core(verdict: str, rev: dict | None, op: Opinion) -> str:
    """没有公开理由时的模板回复（只说结论，不带理由）。"""
    t = (op.target or {})
    if verdict == "text_ok":
        return f"感谢指正。经核对原书图，此处原文作「{t.get('check') or ''}」，暂不改。"
    if verdict == "accept":
        return "感谢指正，已采纳，下一版文本改正。"
    if verdict == "lacuna_guess":
        g = ((rev or {}).get("cells") or [{}])[0].get("guess") or (op.proposal or {}).get("text") or ""
        return f"感谢指正。原书此处图上无字，按文意当有「{g}」：将录为阙文 □，并注推测字「{g}」（按磨损缺字处理）。"
    if verdict == "out_of_scope":
        return "感谢指正，已转给标点／专名整理。"
    return "感谢指正，这一处还要再看，结果会在这里更新。"


def _sentence(s: str) -> str:
    s = (s or "").strip()
    return s if not s or s[-1] in "。！？.!?" else s + "。"


def reply_template(verdict: str, rev: dict | None, op: Opinion, public: str) -> str:
    """公开回复草稿。有公开理由时只用「感谢指正。」＋公开理由：结论（采纳／未采纳、版本）由网站状态显示，
    模板句再说一遍就与理由重复（GUJI-713：原来是模板句＋公开理由叠在一起）。没有公开理由才用模板句。"""
    public = (public or "").strip()
    if public:
        return "感谢指正。" + _sentence(public)
    return template_core(verdict, rev, op)


THANKS = re.compile(r"^感谢指正[。，,.！!]?\s*")


def reply_body(tri: dict, op: Opinion) -> str:
    """判定记录里的回复草稿 → 去掉致谢与模板句后的正文（给网站回写用）。

    - 草稿是模板生成的（新写法「感谢指正。＋理由」、旧写法「模板句＋理由」、或只有模板句）→ 正文就是公开理由；
    - 会话手写的草稿 → 原样，只去掉开头的「感谢指正」。"""
    draft = (tri.get("reply_draft") or "").strip()
    public = (tri.get("rationale_public") or "").strip()
    core = template_core(tri.get("verdict") or "", tri.get("revision"), op)
    generated = {core, (core + public).strip(), reply_template(tri.get("verdict") or "", tri.get("revision"), op, public)}
    if not draft or draft in generated:
        return _sentence(public)
    return THANKS.sub("", draft).strip()


# ---- 刷票 ----

def flood_flags(op: Opinion, pool: list[Opinion], rules: dict) -> list[str]:
    f = rules.get("flood") or {}
    out = []
    w = (op.voter or "")[:6]
    if w:
        day = op.ts[:10]
        same = [o for o in pool if (o.voter or "")[:6] == w and o.ts[:10] == day]
        if len(same) >= f.get("per_source_per_day", 60):
            dis = [o for o in same if (o.proposal or {}).get("text") not in (None, (o.target or {}).get("check"))]
            if len(dis) / len(same) >= f.get("disagree_ratio", 0.8):
                out.append(f"疑似刷票：同一来源 {day} 提了 {len(same)} 条，大多与原文不同")
    t = op.target or {}
    if t.get("start"):
        near = [o for o in pool if o.vol == op.vol and (o.target or {}).get("start") == t["start"]]
        ws = {(o.voter or "")[:6] for o in near}
        if len(ws) >= f.get("burst_sources", 5):
            ts = sorted(dt.datetime.fromisoformat(o.ts.replace("Z", "+00:00")) for o in near if o.ts)
            if ts and (ts[-1] - ts[0]).total_seconds() < f.get("burst_seconds", 3600):
                out.append(f"疑似刷票：同格 {len(ws)} 个来源在 1 小时内集中")
    return out


def human_decided(op: Opinion, store) -> list[str]:
    """池里同章同格（区间相交）的其他意见有用户 ``decided`` 的。"""
    t = op.target or {}
    if not t.get("start"):
        return []
    lo, hi = cell_key(t["start"]), cell_key(t["end"])
    out = []
    for o in store.opinions.values():
        tt = o.target or {}
        if o.id == op.id or o.vol != op.vol or not tt.get("start"):
            continue
        if cell_key(tt["start"]) <= hi and cell_key(tt["end"]) >= lo:
            d = store.last(o.id, "decided")
            if d is not None:
                out.append(f"同格意见 {o.id} 用户已裁 {d.data.get('decision')}")
    return out


# ---- 去向 ----

def route(op: Opinion, *, verdict: str, confidence: float, public: str, profile: str, revision: dict | None,
          status: str, located: dict | None = None, evidence_agree: int = 0, human_cells: set | None = None,
          store=None, rules: dict | None = None, requested: str | None = None) -> tuple[str, list[str]]:
    """返回 (route, 理由列表)。不合规则的请求抛 ``RuleError``。"""
    rules = rules or load_rules()
    prof = (rules.get("profiles") or {}).get(profile)
    if prof is None:
        raise RuleError(f"rules.json 里没有 profile {profile}")
    if status in ("dup", "superseded"):
        raise RuleError(f"{op.id} 状态是 {status}，不判（判它的本条）")
    why: list[str] = []
    fwd = (rules.get("forward") or {}).get(op.category)
    r = None
    if status == "forwarded" or fwd:
        r, why = "forward", [f"类别 {op.category}，转给{fwd or '别的线'}"]
    elif verdict == "out_of_scope":
        r, why = "forward", ["超出文本线范围"]
    elif located and located.get("already"):
        r, why = "auto_accept", ["现文已是建议字（已改），只回复"]
    elif located and located.get("drift"):
        r, why = "to_user", [f"版本漂移：{located['drift']}"]
    elif op.category == "figure":
        r, why = "to_user", ["读者说这格是图形、不是字，交用户定（定了按人裁 figure 写）"]
    elif verdict in prof.get("to_user_verdicts", []):
        r = "to_user"
        why = {"lacuna_guess": ["图上无字、按文意补（Q7 以图为准的新原则），交用户确认"],
               "seg_issue": ["切分问题（C 类），交用户"], "unclear": ["看不清，交用户"]}.get(verdict, [verdict])
    if r is None:
        hc = []
        t = op.target or {}
        if human_cells and t.get("start") and (t["start"] in human_cells or t["end"] in human_cells):
            hc.append("这一格用户亲裁过")
        if store is not None:
            hc += human_decided(op, store)
            hc += flood_flags(op, list(store.opinions.values()), rules)
        if hc:
            r, why = "to_user", hc
    if r is None:
        conf = float(confidence)
        if verdict == "accept":
            aa = prof["auto_accept"]
            k = norm_class((revision or {}).get("class"))
            miss = []
            if conf < aa["min_confidence"]:
                miss.append(f"置信度 {conf} < {aa['min_confidence']}")
            if evidence_agree < aa["min_evidence_agree"]:
                miss.append(f"一致证据 {evidence_agree} 路 < {aa['min_evidence_agree']}")
            if k not in aa["classes"]:
                miss.append(f"修订类 {k or '无'} 不在自动采纳许可 {aa['classes']}")
            r, why = ("to_user", miss) if miss else ("auto_accept", ["置信度与一致证据够档"])
        elif verdict == "text_ok":
            ar = prof["auto_reject"]
            if conf >= ar["min_confidence"] and (public or "").strip():
                r, why = "auto_reject", ["原文对，证据充分"]
            else:
                r, why = "to_user", [f"置信度 {conf} < {ar['min_confidence']} 或缺公开理由"]
        else:
            r, why = "to_user", [f"结论 {verdict} 没有自动规则"]
    if requested and requested != r:
        if requested in CONSERVATIVE and r in ("auto_accept", "auto_reject"):
            why = why + [f"判定者要求 {requested}（比规则保守）"]
            r = requested
        elif requested in CONSERVATIVE and r in CONSERVATIVE:
            r = requested
        else:
            raise RuleError(f"规则给的去向是 {r}（{'；'.join(why)}），不能改成 {requested}")
    return r, why


def parse_revision(s: str | None) -> dict | None:
    """``--revision`` 的 JSON（或 @文件）。"""
    if not s or s == "auto":
        return None
    if s.startswith("@"):
        s = Path(s[1:]).read_text(encoding="utf-8")
    d = json.loads(s)
    d["class"] = norm_class(d.get("class"))
    for c in d.get("cells") or []:
        if not re.match(r"^\d+:\d+:-?[1-9]\d*[ab]?$", str(c.get("a", ""))):
            raise RuleError(f"revision 格号不对：{c.get('a')!r}")
    return d
