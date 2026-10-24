"""网站精校页投票 → 人裁事件草稿（`guji cellvotes`，M10 精校，2026-10-21）。

精校页六档按钮（`/api/cellreview`）的票，从前要会话一步步摸清数据在哪、手搓草稿（ai-team
`team/CV/公众意见导入/web_opinions.py` 那套要 rev 快照工作区，中心库迁移后云端没有）。这里把**确定的那部分**
写死成一条流水：

    取票 → 去测试票、同格同来源留最新 → 按格归并 → 映射成事件 payload
         → 对正式库最新人裁（数据目录 feedback/events）→ 对格位（现行产物 vs 出单那一版的 book-text cord）
         → 分成「可写」与「挂起」两堆，各带理由

映射（与 web_opinions.py、`格级审阅页-数据流程.md` §五 同口径）：

    char   → confirm v=confirm shape=<字>
    cut    → confirm v=seg_defect quality=truncated（给了字就带 shape）
    jiazhu → confirm v=seg_defect reason=jiazhu_as_main（给了字就带 shape）
    main   → confirm v=seg_defect reason=main_as_jiazhu（给了字就带 shape）
    none   → confirm v=not_a_char —— **缺省挂起**：排除名单只增不删、不带锚（M10 调研 B 的 P6），要落加 include_none
    unsure → 不写

网站 10-21 起四档都能同时带一个字（用户：切分错了也先把字给上，格子先过、切分另修）。cut／jiazhu／main 带字照上
带 shape；**none、unsure 带字自相矛盾（说没字／看不清又给了字），挂起交人看**。

挂起（不写，交人看）的情形：同格意见不一致；要推翻已有人裁；格位对不上（现行 cv 重切过这一列，旧格号已不是那个字）；
无字（缺省）。和已有人裁一致的直接跳过，不重写。

**在网站上推翻旧人裁（M10 复盘第 5 项，10-23）**：复审单（`republish.py prep --recheck`）上的格带 `prior`
（{c, id}），网站卡片写明「已有判断：判为 X。这次提交的选择会替代它」。票投在这样的格上、且 `prior.id` 就是该格
现在最新的那条人裁，就是投票人看过旧裁、有意推翻：照写，payload 记 `overrides: <旧人裁 id>`（最新的人裁按时间生效）。
出单之后该格又来了新人裁（`prior.id` 不是最新那条）照旧挂起。`triage(sheet_prior=…)` 传 {格位: prior.id}。

挂起里能回网站让人再看的几类（`Draft.kind`：overturn 推翻旧裁、disagree 意见不一致、guess 说无字又给字、moved 格位变了）
由 `recheck_rows` 写成复审清单（`cellvotes draft` 的 `recheck.tsv`），直接交 `republish.py prep --recheck`。

**为什么要对格位**：票上的格号是出单那一版产物的格号。云端／别的机器上能拿到的是**现行**产物，现行 cv 可能把那一列
重切过——格号还在，字已经不是那个字。出单那一版的格框留在 book-text 的 `<册>.cord.json` 里，拿它和现行
`cell_shrink` 的框逐格比（目标格与同列各格框差都 ≤ tol，且同列格位集合相同）才放行。

本模块只读，不写事件；写入在 `cli_cellvotes.py`（走控制台同一条写入路径，锚按现行产物算）。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

CHOICES = ("char", "none", "unsure", "cut", "jiazhu", "main")
A_RE = re.compile(r"^(\d+):(\d+):(-?\d+)([ab]?)$")
#: 人裁里算「定了这一格」的 payload.v
HUMAN_VS = ("confirm", "seg_defect", "not_a_char", "damaged")
BOX_TOL = 8.0


def is_test(v: dict) -> bool:
    """验收测试票：note 以【测试】开头，或来源含 eden-test（与 web_opinions.py 同口径）。"""
    return str(v.get("note") or "").startswith("【测试】") or any(
        "eden-test" in str(v.get(k) or "") for k in ("aid", "src", "voter"))


def load_votes(path: Path) -> list[dict]:
    """jsonl（中心库快照，一行一票），或管理读接口原样存下的 ``{items: [...]}``。"""
    txt = Path(path).read_text(encoding="utf-8").strip()
    if not txt:
        return []
    if txt.startswith("{") and '"items"' in txt[:4000]:
        try:
            return list(json.loads(txt)["items"])
        except (json.JSONDecodeError, KeyError):
            pass
    return [json.loads(line) for line in txt.splitlines() if line.strip()]


def cell_order(a: str) -> tuple:
    m = A_RE.match(a)
    return (int(m[1]), int(m[2]), int(m[3]), m[4]) if m else (10**9, 0, 0, a)


def latest_votes(votes: list[dict], site_book: str, rev: str) -> tuple[list[dict], dict[str, int]]:
    """只留本书本 rev 的合法票，去测试票，同格同来源留最新一条。返回 (票, 丢弃计数)。"""
    dropped: dict[str, int] = defaultdict(int)
    best: dict[tuple, dict] = {}
    for v in votes:
        if v.get("book") != site_book or v.get("rev") != rev:
            dropped["别的书或别的 rev"] += 1
            continue
        if is_test(v):
            dropped["测试票"] += 1
            continue
        if not A_RE.match(str(v.get("a") or "")) or v.get("choice") not in CHOICES or not v.get("voter"):
            dropped["字段不合法"] += 1
            continue
        if v["choice"] == "char" and len(v.get("char") or "") != 1:
            dropped["选字档没给单字"] += 1
            continue
        k = (v["a"], v["voter"])
        if k not in best or (v.get("ts") or 0) >= (best[k].get("ts") or 0):
            best[k] = v
    return sorted(best.values(), key=lambda v: (cell_order(v["a"]), v.get("ts") or 0)), dict(dropped)


def payload_of(choice: str, char: str = "") -> dict | None:
    if choice == "char":
        return {"v": "confirm", "shape": char} if char else None
    if choice == "cut":
        return {"v": "seg_defect", "quality": "truncated", **({"shape": char} if char else {})}
    if choice == "jiazhu":
        return {"v": "seg_defect", "reason": "jiazhu_as_main", **({"shape": char} if char else {})}
    if choice == "main":
        return {"v": "seg_defect", "reason": "main_as_jiazhu", **({"shape": char} if char else {})}
    if choice == "none":
        return {"v": "not_a_char"}
    return None


def latest_human(events) -> dict[str, object]:
    """每格最后一条算人裁的 confirm（`counts_as_human`），key → Event。``events`` 是 Event 的可迭代。"""
    from .events import counts_as_human
    last: dict[str, object] = {}
    for e in events:
        t = e.target
        if e.kind != "confirm" or t.unit != "cell" or (e.payload or {}).get("v") not in HUMAN_VS:
            continue
        if not counts_as_human(e):
            continue
        if t.key not in last or e.ts >= last[t.key].ts:
            last[t.key] = e
    return last


def same_verdict(p: dict, q: dict) -> bool:
    keys = ("v", "shape", "quality", "reason")
    return all((p.get(k) or "") == (q.get(k) or "") for k in keys)


# ───────────────────────── 格位核对 ─────────────────────────

def cord_boxes(cord: dict) -> dict[int, tuple[int, dict[str, list]]]:
    """book-text ``<册>.cord.json`` → {页: (页宽, {格位 a: [x, y, w, h]（左上原点）})}。"""
    out = {}
    for p in cord.get("pages") or []:
        out[int(p["page"])] = (int((p.get("image") or {}).get("width") or 0),
                               {c["a"]: c["box"] for c in p.get("cells") or []})
    return out


def shrink_boxes(char_index: dict, page_width: int) -> dict[str, list]:
    """现行 cell_shrink 产物（``char_index``）→ {格位 a: [x, y, w, h]}；``bbox_page`` 是右上原点，换成左上。"""
    out = {}
    for col in char_index.get("columns") or []:
        for c in col.get("chars") or []:
            b = c.get("bbox_page")
            if not b or ":" not in str(c.get("id")):
                continue
            x0, y0, x1, y1 = b
            out[c["id"].split(":", 1)[1]] = [page_width - x1, y0, x1 - x0, y1 - y0]
    return out


def check_cell(a: str, old: dict[str, list], new: dict[str, list], tol: float = BOX_TOL) -> str | None:
    """同一格在出单版（old）与现行（new）里是不是同一个框。对得上返回 None，否则返回理由。"""
    pg, col = a.split(":")[:2]
    pre = f"{pg}:{col}:"
    so = {k for k in old if k.startswith(pre)}
    sn = {k for k in new if k.startswith(pre)}
    if a not in old:
        return "出单版 cord 里没有这一格"
    if a not in new:
        return "现行产物里没有这一格（本列重切过）"
    if so != sn:
        return f"本列格位变了（出单版 {len(so)} 格，现行 {len(sn)} 格）"
    worst = max(max(abs(u - w) for u, w in zip(old[k], new[k])) for k in so)
    if worst > tol:
        return f"本列格框变了（最大差 {worst:.0f}px）"
    return None


# ───────────────────────── 分流 ─────────────────────────

@dataclass
class Draft:
    key: str                     # 事件 target.key，如 vol04:15:8:20
    a: str
    payload: dict
    votes: list[dict]
    held: str = ""               # 非空＝挂起理由
    kind: str = ""               # 挂起的类别：overturn／disagree／guess／moved／none（无字缺省挂起）
    prior: object = None         # 要推翻的旧人裁 Event（overturn 才有）

    def row(self, source: str) -> dict:
        """控制台 ``/api/events`` 一行。"""
        ids = "、".join(f"{v['voter'][:16]}" for v in self.votes)
        note = "；".join(v["note"] for v in self.votes if v.get("note"))
        return {"id": self.key, **self.payload, "note": note, "source": f"{source}；意见来源 {ids}"}


@dataclass
class Triage:
    drafts: list[Draft] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (格位, 理由)

    @property
    def ready(self) -> list[Draft]:
        return [d for d in self.drafts if not d.held]

    @property
    def held(self) -> list[Draft]:
        return [d for d in self.drafts if d.held]


def triage(votes: list[dict], cv_book: str, human: dict, *, include_none: bool = False,
           check: Callable[[str], str | None] | None = None, sheet_prior: dict[str, str] | None = None) -> Triage:
    """``votes`` 已经过 latest_votes；``human`` 是 latest_human 的结果；
    ``check(a)`` 核格位（对得上返回 None，否则理由；只对要写的格调用），给 None 表示不核（调用方要自己担保）；
    ``sheet_prior`` {格位: 单上 prior.id}：投票人看过的旧人裁，票就是有意推翻它（见模块说明）。"""
    sheet_prior = sheet_prior or {}
    out = Triage()
    groups: dict[str, list[dict]] = defaultdict(list)
    for v in votes:
        groups[v["a"]].append(v)
    for a in sorted(groups, key=cell_order):
        vs = groups[a]
        guess = [v for v in vs if v["choice"] in ("none", "unsure") and v.get("char")]
        if guess:
            out.drafts.append(Draft(f"{cv_book}:{a}", a, {}, vs, held="说无字／看不清又给了字：" + "、".join(
                sorted({f"{v['choice']}={v['char']}" for v in guess})), kind="guess"))
            continue
        real = [v for v in vs if v["choice"] != "unsure"]
        if not real:
            out.skipped.append((a, f"只有「看不出」×{len(vs)}"))
            continue
        kinds = {(v["choice"], v.get("char") or "") for v in real}
        key = f"{cv_book}:{a}"
        if len(kinds) > 1:
            out.drafts.append(Draft(key, a, {}, real, held="意见不一致：" + "、".join(
                sorted(f"{c}{'=' + ch if ch else ''}" for c, ch in kinds)), kind="disagree"))
            continue
        choice, char = next(iter(kinds))
        p = payload_of(choice, char)
        if p is None:
            out.skipped.append((a, f"{choice} 档不写"))
            continue
        h = human.get(key)
        if h is not None:
            if same_verdict(h.payload, p):
                out.skipped.append((a, f"与已有人裁 {h.id} 一致"))
                continue
            if sheet_prior.get(a) != h.id:
                out.drafts.append(Draft(key, a, p, real, held=f"要推翻已有人裁 {h.id}（{h.payload.get('v')} "
                                                              f"{h.payload.get('shape') or ''}）", kind="overturn", prior=h))
                continue
            p = {**p, "overrides": h.id}         # 单上写明了旧裁、投票人有意推翻
        d = Draft(key, a, p, real)
        if p["v"] == "not_a_char" and not include_none:
            d.held, d.kind = "无字：排除名单只增不删、不带锚，缺省不落（要落加 --include-none）", "none"
        elif check is not None:
            why = check(a)
            if why:
                d.held, d.kind = f"格位对不上：{why}", "moved"
        out.drafts.append(d)
    return out


# ───────────────────────── 复审清单 ─────────────────────────

RECHECK_KINDS = ("overturn", "disagree", "guess", "moved")


def vote_label(v: dict) -> str:
    """一票的大白话：选字「X」／没有字／看不清／切分错了「X」……"""
    ch = f"「{v['char']}」" if v.get("char") else ""
    return {"char": ch, "none": "没有字" + ch, "unsure": "看不清" + ch, "cut": "切分错了" + ch,
            "jiazhu": "小注当正文" + ch, "main": "正文当小注" + ch}.get(v["choice"], v["choice"] + ch)


def recheck_rows(t: Triage) -> list[tuple[str, str, str, str, str]]:
    """挂起里能回网站再看的格 → (格位, 说明, 旧人裁 id, 旧人裁的字, 旧人裁时间)，交 `republish.py prep --recheck`。"""
    rows = []
    for d in t.held:
        if d.kind not in RECHECK_KINDS:
            continue
        got = "、".join(sorted({vote_label(v) for v in d.votes}))
        pid = pc = pts = ""
        if d.kind == "overturn":
            pl = d.prior.payload or {}
            pid, pc, pts = d.prior.id, pl.get("shape") or {"not_a_char": "无字"}.get(pl.get("v"), pl.get("v") or ""), str(d.prior.ts)
            note = f"上次投了{got}，和已有判断不同：要改就再选一次，不改就选「{pc}」"
        elif d.kind == "disagree":
            note = f"几票不一致（{got}），请定"
        elif d.kind == "guess":
            note = f"上次投的是{got}，既说看不出又给了字，请再定"
        else:
            note = f"切字改过，上次在旧框上投了{got}，请按现在的框再看"
        rows.append((d.a, note, pid, pc, pts))
    return rows
