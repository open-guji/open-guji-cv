# -*- coding: utf-8 -*-
"""Step8 复核的**状态**：每个字位现在归哪一类、最终落哪个字。

## 两层分类（用户 2026-09-24 定）

```
第一层：待审 · 我方对 · 校对本对 · 都不对
第二层（只挂在「我方对」下）：异体字 · 通假字 · 避讳字 · 其他
```

此前的五层（避諱改字 / 异体字 / 通假字 / 本书特有转换 / 零星分歧）是**自动判据**
的分档，被当成了人裁的分类摆在页签上——两件事混在一起：「本书特有转换」「零星分歧」
不是结论，只是「机器还没法归」的两种原因。现在自动判据退成**预标注**：

| 自动档 | 没人裁时放哪 |
|---|---|
| 避諱改字 / 异体字 / 通假字 | 直接进「我方对」对应小类，标「自动」，可随时挪走 |
| 本书特有 / 零星分歧 | 「待审」，默认选中「我方对 · 其他」（本书通例按其 kind 预选） |

卡片上选哪一类，那几个字位就**挪进哪一类**——各类之间随时可以再挪，也可以退回待审。

## 状态是按**字位**记的，不是按字对

「N 处一起裁」不勾时，同一字对的几处可以落进不同类（𠊓→傍 24 处里有一处是真认错）。
所以状态的单位是字位，页面上的卡片是「同一字对 × 同一状态」的一组字位。

## 真源是事件日志

`<book>-collate` 批次里每个字位**后到覆盖**。新事件是 `collate_verdict`
（payload 自带 pair/who/cat/fix/final 与上下文快照）；2026-09-22～24 的旧事件
（`collate_ok` / 无 `via` 的 `confirm` / `mark_jiajie` / `char_convention`）照旧
能读出来，不必改写日志——那 173 条是用户亲手裁的。

## 最终落哪个字（`final`）

| 裁决 | 这一格的字 |
|---|---|
| 我方对 | 我方转写（字对左边） |
| 校对本对 | 校对本的字（字对右边） |
| 都不对 | 人输入的字 |
| 待审 | 我方转写（不动） |

`final` 变了才写 `confirm`（走 Step7 现成的改字／入库／失效通道），
`feedback/lookup.human_chars` 读回来进 Step7 文本层。**挪回「我方对」也要写**：
否则先点「校对本对」再挪回来，那一格会一直是校对本的字。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

WHO = ("ours", "theirs", "neither")
CATS = ("variant", "jiajie", "taboo", "other")
BUCKETS = ("pending",) + WHO

WHO_LABEL = {"pending": "待审", "ours": "我方对", "theirs": "校对本对", "neither": "都不对"}
CAT_LABEL = {"variant": "异体字", "jiajie": "通假字", "taboo": "避讳字", "other": "其他"}

#: 自动档 → 没人裁时直接落进「我方对」的哪一小类。不在表里的档（book / dispute）进待审。
AUTO_CAT = {"taboo": "taboo", "variant": "variant", "jiajie": "jiajie"}

#: 旧 `char_convention` 的 kind → 小类。人名/物品 是「不同字，本书这么用」→ 其他。
CONV_KIND_CAT = {"通假": "jiajie", "避諱": "taboo", "异体": "variant", "正俗": "variant",
                 "人名": "other", "物品": "other"}

#: 新事件写 confirm / mark_jiajie 时带的标记：读状态时跳过它们，状态以 collate_verdict 为准。
VIA = "collate_verdict"


_CTX_KEYS = ("page", "col", "slot", "sub", "hyp_ctx", "ref_ctx")


def _coords(key: str) -> dict:
    """`bxgb:25:3:2` / `bxgb:25:3:2a` → page/col/slot/sub。解析不了返回空。"""
    parts = key.split(":")
    if len(parts) != 4:
        return {}
    slot, sub = parts[3], None
    if slot and slot[-1] in "ab":
        slot, sub = slot[:-1], slot[-1]
    try:
        return {"page": int(parts[1]), "col": int(parts[2]), "slot": int(slot), "sub": sub}
    except ValueError:
        return {}


def final_char(pair, who: str, fix: str = "") -> str:
    """这一格最后是哪个字。待审与我方对都是我方转写。"""
    if who == "theirs":
        return pair[1]
    if who == "neither" and fix:
        return fix
    return pair[0]


@dataclass
class Verdict:
    """一个字位的人裁结论。"""

    id: str
    pair: tuple[str, str]
    who: str                    # ours | theirs | neither
    cat: str | None = None      # who=ours 时的小类；旧事件读不出来时为 None，由调用方按预标注补
    fix: str = ""
    ts: str = ""
    event: str = ""
    ctx: dict = field(default_factory=dict)   # page/col/slot/sub/hyp_ctx/ref_ctx 快照

    @property
    def final(self) -> str:
        return final_char(self.pair, self.who, self.fix)


def human_verdicts(events: Iterable, book: str,
                   row_of: Callable[[str], dict | None] = lambda _k: None
                   ) -> dict[str, Verdict]:
    """事件 → `{字位 id: Verdict}`。只看 `<book>-collate` 批次，按 seq 后到覆盖。

    `row_of(id)`：这个字位在（任一份）对勘报告里的那条差异。旧事件既不带字对（confirm）
    也不带上下文快照，靠它查回来；字对查不到的跳过（不知道我方原来是什么字，就说不清
    这一格是「校对本对」还是「都不对」）。上下文查不到，卡片上就没有图和上下文——
    「校对本对」改字重跑后差异从最新报告里消失，只有旧报告还记得它。
    """
    batch = f"{book}-collate"
    labels: dict[tuple[str, str], str] = {}     # 旧的字对级标签 → 小类
    out: dict[str, Verdict] = {}
    for e in sorted((e for e in events if e.batch == batch), key=lambda e: e.seq):
        p = e.payload or {}
        key = e.target.key
        if e.kind == "collate_verdict":
            pair = tuple(p.get("pair") or ())
            if p.get("who") in WHO and len(pair) == 2:
                out[key] = Verdict(key, pair, p["who"],
                                   p.get("cat") if p["who"] == "ours" else None,
                                   p.get("fix") or "", e.ts, e.id, dict(p.get("ctx") or {}))
            else:                                   # who 空 = 退回待审
                out.pop(key, None)
        elif p.get("via") == VIA:
            continue
        elif e.kind == "collate_ok":
            pair = tuple(p.get("pair") or ())
            row = row_of(key) or {}
            # 旧台子（2026-09-24 03:57 之前）有过把字对落到**别的字位**上的事件：壘→墨 记在了
            # bxgb:3:1:1（那一格是卷端「北」），那一格不在任何对勘报告里。报告里查不到这个字对
            # 的旧事件一律不认——新事件 `collate_verdict` 由接口校验过字位，不受此限。
            if len(pair) == 2 and (row.get("char"), row.get("ref")) == pair:
                out[key] = Verdict(key, pair, "ours", None, "", e.ts, e.id)
        elif e.kind == "confirm" and (p.get("v") or "confirm") == "confirm":
            row = row_of(key) or {}
            pair = tuple(p.get("pair") or ()) or (
                (row["char"], row["ref"]) if row.get("char") and row.get("ref") else None)
            shape = p.get("shape") or ""
            if not pair or len(pair) != 2 or not shape or not row:
                continue
            who = ("theirs" if shape == pair[1] else
                   "ours" if shape == pair[0] else "neither")
            out[key] = Verdict(key, tuple(pair), who, None,
                               shape if who == "neither" else "", e.ts, e.id)
        elif e.kind == "mark_jiajie":
            pair = tuple(p.get("pair") or ())
            if len(pair) == 2:
                labels[pair] = "jiajie"
        elif e.kind == "char_convention":
            pair = tuple(p.get("pair") or ())
            if len(pair) == 2:
                labels[pair] = CONV_KIND_CAT.get(p.get("kind") or "", "other")
    for v in out.values():
        if v.who == "ours" and v.cat is None:
            v.cat = labels.get(v.pair)
        if not v.ctx.get("hyp_ctx"):
            row = row_of(v.id) or {}
            if (row.get("char"), row.get("ref")) == v.pair:
                v.ctx = {**{k: row.get(k) for k in _CTX_KEYS}, **{k: x for k, x in v.ctx.items() if x}}
    return out




def build_items(diffs: list[dict], verdicts: dict[str, Verdict],
                tier_fn: Callable[[str, str, int], str],
                convention_cat: dict | None = None,
                kinds: tuple = ("sub.", "variant.")) -> list[dict]:
    """对勘差异 ＋ 人裁 → 逐字位的状态行。

    - 报告里有、人裁过且字对一致 → 按人裁；
    - 报告里有、人裁的字对**不一致** → 人裁作废（重切/重识别后这一格已不是那个字），回待审；
    - 报告里**没有**、人裁过 → 照样列出（用裁决时的快照）。「校对本对」改字后重跑，
      差异本来就会消失——不列出来就没法再挪回去了。
    """
    convention_cat = convention_cat or {}
    rows: dict[str, dict] = {}
    for d in diffs:
        if not str(d.get("kind", "")).startswith(kinds):
            continue
        a, b = d.get("char"), d.get("ref")
        if not a or not b or a == b or not d.get("id"):
            continue
        rows[d["id"]] = {"id": d["id"], "pair": (a, b),
                         **{k: d.get(k) for k in _CTX_KEYS}}
    for vid, v in verdicts.items():
        r = rows.get(vid)
        if r is None:
            if v.pair[0] != v.pair[1]:
                rows[vid] = {"id": vid, "pair": v.pair,
                             **{k: v.ctx.get(k) for k in _CTX_KEYS}}
                if rows[vid]["page"] is None:
                    # 连旧报告都查不到：至少从字位 id（书:页:列:格）拿回坐标，图还能出
                    rows[vid].update(_coords(vid))
        elif r["pair"] != v.pair and r["pair"][0] == v.final:
            # 「都不对」改成 丙 之后重跑：这一格变成 丙→乙 的差异，仍是那条裁决的结果，
            # 按裁决时的字对归位，别当成新差异再问一遍
            r["pair"] = v.pair

    n_of: dict[tuple, int] = {}
    for r in rows.values():
        n_of[r["pair"]] = n_of.get(r["pair"], 0) + 1

    out = []
    for r in rows.values():
        pair = r["pair"]
        tier = tier_fn(pair[0], pair[1], n_of[pair])
        v = verdicts.get(r["id"])
        if v is not None and v.pair != pair:
            v = None
        default_cat = AUTO_CAT.get(tier) or convention_cat.get(pair) or "other"
        if v is not None:
            who, cat, fix, basis = v.who, (v.cat or default_cat) if v.who == "ours" else None, \
                v.fix, "human"
        elif tier in AUTO_CAT:
            who, cat, fix, basis = "ours", AUTO_CAT[tier], "", "auto"
        elif pair in convention_cat:
            # 旧 ② 本书通例：人在字对级裁过（没落到字位），当作已归类
            who, cat, fix, basis = "ours", convention_cat[pair], "", "convention"
        else:
            who, cat, fix, basis = "pending", None, "", ""
        out.append({**r, "tier": tier, "who": who, "cat": cat, "fix": fix,
                    "basis": basis, "default_cat": default_cat,
                    "final": final_char(pair, who, fix),
                    "decided_at": v.ts if v else ""})
    return out


def group_items(items: list[dict]) -> list[dict]:
    """逐字位 → 卡片：同一字对 × 同一状态（who/cat/fix/basis）一张。"""
    groups: dict[tuple, dict] = {}
    for it in items:
        k = (it["pair"], it["who"], it["cat"], it["fix"], it["basis"])
        g = groups.get(k)
        if g is None:
            g = groups[k] = {"pair": list(it["pair"]), "who": it["who"], "cat": it["cat"],
                             "fix": it["fix"], "basis": it["basis"], "tier": it["tier"],
                             "default_cat": it["default_cat"], "final": it["final"],
                             "ids": [], "pages": set(), "samples": [], "decided_at": ""}
        g["ids"].append(it["id"])
        if it.get("page") is not None:
            g["pages"].add(it["page"])
        g["samples"].append({k: it.get(k) for k in ("id",) + _CTX_KEYS})
        g["decided_at"] = max(g["decided_at"], it["decided_at"])
    order = {"dispute": 0, "book": 1, "variant": 2, "jiajie": 3, "taboo": 4}
    out = []
    for g in groups.values():
        g["n"] = len(g["ids"])
        g["pages"] = sorted(g["pages"])
        g["samples"].sort(key=lambda s: (s.get("page") or 0, s.get("col") or 0,
                                         s.get("slot") or 0))
        g["ids"] = [s["id"] for s in g["samples"]]
        out.append(g)
    out.sort(key=lambda g: (order.get(g["tier"], 9), -g["n"], g["pair"]))
    return out


def counts(items: list[dict]) -> dict:
    """→ 两层页签上的数：`{bucket: {pairs, items}}` ＋ `cats: {cat: {pairs, items, auto}}`。

    **对数与处数都给**：人按对判，报告讲处。`auto` 是其中尚未人裁、按预标注放进来的对数。
    """
    def blank():
        return {"pairs": set(), "items": 0, "auto": set()}
    b = {k: blank() for k in BUCKETS}
    c = {k: blank() for k in CATS}
    for it in items:
        key = (it["pair"], it["who"], it["cat"], it["fix"])
        b[it["who"]]["pairs"].add(key)
        b[it["who"]]["items"] += 1
        if it["who"] == "ours" and it["cat"] in c:
            c[it["cat"]]["pairs"].add(key)
            c[it["cat"]]["items"] += 1
            if it["basis"] == "auto":
                c[it["cat"]]["auto"].add(key)
                b["ours"]["auto"].add(key)

    def fin(d):
        return {"pairs": len(d["pairs"]), "items": d["items"], "auto": len(d["auto"])}
    return {**{k: fin(v) for k, v in b.items()}, "cats": {k: fin(v) for k, v in c.items()}}


#: 切分反馈（2026-09-24）：卡片上每张图右边两个复选框。与「谁对 / 哪一类」**独立**——
#: 图切坏了不妨碍判断谁对，只是留一笔给 Step3 的打回台账。
SEG_FLAGS = ("truncated", "contaminated")      # 字形不完整 / 有噪声
SEG_VIA = "seg_flag"


def seg_payload(flags: list[str], note: str = "") -> dict:
    """勾选状态 → 一条 `confirm(v=seg_defect)` 的 payload，走现成的切分缺陷通道
    （`gold_add` → `char-segmentation/instances` 金标）。

    - `quality` 取一档（instances 金标是单值四分类）：不完整优先，全不勾 = `clean`
      （人先勾后取消，得有一条把旧的盖掉）；
    - 两个都勾时 `defect` 记全，读回靠它；
    - **不带 shape**：带了 `human_chars` 会把它当定字、`decided_cells` 会当已裁——
      这一维不该碰定字。
    """
    fl = [f for f in SEG_FLAGS if f in flags]
    return {"v": "seg_defect", "quality": fl[0] if fl else "clean",
            # 全不勾写 "none" 而不是空串：金标按键合并，空串不落键，旧的 defect 会留下来
            "defect": ",".join(fl) or "none", "via": SEG_VIA,
            "note": note or ("Step8 复核：" + ("、".join(
                {"truncated": "字形不完整", "contaminated": "有噪声"}[f] for f in fl) or "取消切分标记"))}


def seg_flags(events: Iterable, book: str) -> dict[str, list[str]]:
    """这本书**所有批次**里人标过的切分缺陷 → `{字位: [truncated/contaminated…]}`，按时间后到覆盖。

    跨批次：Step7 定字台上标过的「有噪声 / 字形不完整」这里也显示出来，同一格不必再标。
    """
    pre = f"{book}:"
    out: dict[str, list[str]] = {}
    evs = [e for e in events if e.kind == "confirm" and e.target.key.startswith(pre)
           and (e.payload or {}).get("v") == "seg_defect"]
    for e in sorted(evs, key=lambda e: (e.ts, e.batch, e.seq)):
        p = e.payload or {}
        toks = set(str(p.get("defect") or "").split(",")) | {p.get("quality")}
        fl = [f for f in SEG_FLAGS if f in toks]
        if fl:
            out[e.target.key] = fl
        else:
            out.pop(e.target.key, None)
    return out
