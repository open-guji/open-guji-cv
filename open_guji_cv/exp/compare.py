# -*- coding: utf-8 -*-
"""统一比较：读各变体的 `seed_admit` 产物 + 标签 → `report.json`。

每格在每个变体里落成一个**状态**：

| 状态 | 判据 |
|---|---|
| `admit` | `admit=True`，非人裁通道 |
| `human` | `provenance=human` 或 `channel=human`（Step7 抄人裁；**不进任何错率**——循环）|
| `excluded` | 排除名单格（`doubts` 含 excluded、没有拟定字）|
| `review` | 其余：送人审 |

放行率 = (admit+human)/格数；送审率 = review/格数。**放行错**：放行了、且标签说字不对（异体
等价算对）或标签说是切坏/非字。放行错误率只在 `random` 标签上算，分母是「放行且有标签」的格；
分母为 0 时报 `None`（报告写「无检验力」），不输出 0%。

逐格翻转（每个变体对基线，只看两边都有的格）：

| 键 | 含义 |
|---|---|
| `admit_to_review` | 基线放行、变体送审（含排除）；有标签的再分「拦对」（基线那格是错的）／「误拦」 |
| `review_to_admit` | 基线送审、变体放行；有标签的分「放对」／「放错」 |
| `char_changed` | 两边都放行但字不同 |
| `right_to_wrong` | 有标签、基线不是放行错、变体是（**A 对 B 错**）|
| `wrong_to_right` | 有标签、基线是放行错、变体不是（**A 错 B 对**，含变体把它拦回送审）|
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from .labels import PICKED, RANDOM, Label
from .stats import mcnemar_exact, paired_bootstrap, wilson

ADMITTED = ("admit", "human")
SCOPES = ("body", "nonbody", "all")
METRICS = ("admit_rate", "review_rate", "excluded_rate", "admit_err_rate")
FLIP_KEYS = ("admit_to_review", "review_to_admit", "char_changed", "right_to_wrong", "wrong_to_right")


# ── 读产物 ───────────────────────────────────────────────────────────────
def cell_state(r: dict) -> str:
    if r.get("provenance") == "human" or r.get("channel") == "human":
        return "human"
    if r.get("admit"):
        return "admit"
    if "excluded" in (r.get("doubts") or []) and not r.get("char"):
        return "excluded"
    return "review"


def load_cells(vroot: Path, book: str, step: str = "seed_admit") -> dict[str, dict]:
    """变体根下一册的全部格：{格 id: {page, state, char, channel, doubts}}。"""
    out: dict[str, dict] = {}
    d = Path(vroot) / book / step
    for f in sorted(d.glob("p*.json")) if d.is_dir() else []:
        page = int(f.stem[1:])
        sa = json.loads(f.read_text(encoding="utf-8")).get(step) or {}
        for col in sa.get("columns") or []:
            for r in col.get("chars") or []:
                out[r["id"]] = {"page": page, "book": book, "state": cell_state(r), "char": r.get("char") or "",
                                "channel": r.get("channel") or "", "doubts": list(r.get("doubts") or []),
                                "alts": _alts(r)}
    return out


def _alts(r: dict) -> list[str]:
    """证据里别的通道「认为该是」的字（如 `evidence.shadow_veto.pick`）——翻转审查页拿来当候选。"""
    out = []
    for v in (r.get("evidence") or {}).values():
        pick = v.get("pick") if isinstance(v, dict) else None
        if isinstance(pick, str) and pick and pick != r.get("char") and pick not in out:
            out.append(pick)
    return out


def scope_of(page_type: str | None) -> str:
    if page_type is None or page_type == "unknown":
        return "unknown"
    return "body" if page_type == "body" else "nonbody"


# ── 判对错 ───────────────────────────────────────────────────────────────
def default_same() -> Callable[[str, str], bool]:
    """放行字与标签字语义同（异体等价）算对；异体表读不到就退回逐字相等。"""
    try:
        from ..clustering.variants import VariantMap
        vm = VariantMap.load(None)
    except Exception:  # noqa: BLE001 —— 评测降级，不该因异体表缺失整份报告失败
        return lambda a, b: bool(a) and a == b
    return lambda a, b: bool(a) and bool(b) and (a == b or vm.semantic(a) == vm.semantic(b))


def correct(rec: dict, lab: Label | None, same) -> bool | None:
    """放行格的字对不对；没放行、没标签、或标签说不清 → None。"""
    if lab is None or rec["state"] not in ADMITTED:
        return None
    if lab.defect:
        return False
    if lab.truth:
        return bool(same(rec["char"], lab.truth))
    if lab.wrong and any(same(rec["char"], w) for w in lab.wrong):
        return False
    return None


def admit_err(rec: dict, lab: Label | None, same) -> int | None:
    """「放行错」指示：1 放行且错；0 没放行，或放行且对；None 说不清（含人裁通道：循环，不算）。"""
    if lab is None or rec["state"] == "human":
        return None
    if rec["state"] not in ADMITTED:
        return 0
    c = correct(rec, lab, same)
    return None if c is None else int(not c)


# ── 指标 ─────────────────────────────────────────────────────────────────
def _page_rows(cells_a: dict, cells_b: dict, keys: list[str], labels: dict[str, Label], same) -> dict:
    """每页的分子分母，供点估计与自助法。"""
    rows: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0] * 4))
    for k in keys:
        a, b = cells_a[k], cells_b[k]
        pg = rows[(a["book"], a["page"])]
        for i, rec in ((0, a), (2, b)):
            pg["admit_rate"][i] += rec["state"] in ADMITTED
            pg["admit_rate"][i + 1] += 1
            pg["review_rate"][i] += rec["state"] == "review"
            pg["review_rate"][i + 1] += 1
            pg["excluded_rate"][i] += rec["state"] == "excluded"
            pg["excluded_rate"][i + 1] += 1
            lab = labels.get(k)
            if lab is not None and lab.selection == RANDOM and rec["state"] == "admit":
                e = admit_err(rec, lab, same)
                if e is not None:
                    pg["admit_err_rate"][i] += e
                    pg["admit_err_rate"][i + 1] += 1
    return rows


def _metric_block(rows: dict, metric: str, n_boot: int, seed: int) -> dict:
    tup = [tuple(r[metric]) for r in rows.values()]
    an = sum(t[0] for t in tup)
    ad = sum(t[1] for t in tup)
    bn = sum(t[2] for t in tup)
    bd = sum(t[3] for t in tup)
    out = {"A": an / ad if ad else None, "B": bn / bd if bd else None,
           "A_k": int(an), "A_n": int(ad), "B_k": int(bn), "B_n": int(bd)}
    out["diff"] = (out["B"] - out["A"]) if ad and bd else None
    out["no_power"] = not (ad and bd)
    if metric == "admit_err_rate":
        out["A_ci"] = wilson(int(an), int(ad))
        out["B_ci"] = wilson(int(bn), int(bd))
    ci = paired_bootstrap([t for t in tup if t[1] or t[3]], n_boot=n_boot, seed=seed) if ad and bd else None
    out["ci"] = ci
    out["noise"] = None if ci is None else (ci[0] <= 0 <= ci[1])
    return out


def overall(cells_a: dict, cells_b: dict, keys: list[str], labels: dict[str, Label], same,
            n_boot: int, seed: int) -> dict:
    rows = _page_rows(cells_a, cells_b, keys, labels, same)
    out = {m: _metric_block(rows, m, n_boot, seed) for m in METRICS}
    out["cells"] = len(keys)
    out["pages"] = len(rows)
    return out


def _scoped(keys: list[str], cells: dict, scope: str, page_type: Callable) -> list[str]:
    if scope == "all":
        return keys
    return [k for k in keys if scope_of(page_type(cells[k]["book"], cells[k]["page"])) == scope]


# ── 翻转 ─────────────────────────────────────────────────────────────────
def flips(cells_a: dict, cells_b: dict, keys: list[str], labels: dict[str, Label], same) -> dict:
    out = {k: {"n": 0, "labeled": 0, "cells": []} for k in FLIP_KEYS}
    out["admit_to_review"].update(caught=0, wrongly_blocked=0)
    out["review_to_admit"].update(admit_ok=0, admit_err=0)
    out["char_changed"].update(a_ok_b_err=0, a_err_b_ok=0, both_err=0)
    for k in keys:
        a, b = cells_a[k], cells_b[k]
        lab = labels.get(k)
        aa, ba = a["state"] in ADMITTED, b["state"] in ADMITTED
        row = {"cell": k, "A": a["char"], "B": b["char"],
               "alts": sorted(set(a.get("alts") or []) | set(b.get("alts") or [])), "A_state": a["state"], "B_state": b["state"],
               "A_channel": a["channel"], "B_channel": b["channel"], "doubts": b["doubts"] if aa else a["doubts"],
               "label": None if lab is None else ("∅" if lab.defect else lab.truth or f"≠{''.join(sorted(lab.wrong))}"),
               "label_source": None if lab is None else f"{lab.source}/{lab.selection}"}
        if aa and not ba:
            f = out["admit_to_review"]
            f["n"] += 1
            f["cells"].append(row)
            c = correct(a, lab, same)
            if c is not None:
                f["labeled"] += 1
                f["caught" if not c else "wrongly_blocked"] += 1
        elif ba and not aa:
            f = out["review_to_admit"]
            f["n"] += 1
            f["cells"].append(row)
            c = correct(b, lab, same)
            if c is not None:
                f["labeled"] += 1
                f["admit_ok" if c else "admit_err"] += 1
        elif aa and ba and not same(a["char"], b["char"]) and a["char"] != b["char"]:
            f = out["char_changed"]
            f["n"] += 1
            f["cells"].append(row)
            ca, cb = correct(a, lab, same), correct(b, lab, same)
            if ca is not None and cb is not None:
                f["labeled"] += 1
                if ca and not cb:
                    f["a_ok_b_err"] += 1
                elif cb and not ca:
                    f["a_err_b_ok"] += 1
                elif not ca and not cb:
                    f["both_err"] += 1
        ea, eb = admit_err(a, lab, same), admit_err(b, lab, same)
        if ea is not None and eb is not None and ea != eb:
            f = out["right_to_wrong" if eb else "wrong_to_right"]
            f["n"] += 1
            f["labeled"] += 1
            f["cells"].append(row)
    return out


def mcnemar(cells_a: dict, cells_b: dict, keys: list[str], labels: dict[str, Label], same) -> dict:
    """「放行错」指示的逐格配对检验，分 random 与全部标签两档。"""
    out = {}
    for name, sels in (("random", {RANDOM}), ("all", {RANDOM, PICKED})):
        b = c = n = 0
        for k in keys:
            lab = labels.get(k)
            if lab is None or lab.selection not in sels:
                continue
            ea, eb = admit_err(cells_a[k], lab, same), admit_err(cells_b[k], lab, same)
            if ea is None or eb is None:
                continue
            n += 1
            b += (ea == 0 and eb == 1)
            c += (ea == 1 and eb == 0)
        out[name] = {"n": n, "a_ok_b_err": b, "a_err_b_ok": c, "p": mcnemar_exact(b, c)}
    return out


# ── 分层 ─────────────────────────────────────────────────────────────────
def by_channel(cells_a: dict, cells_b: dict, keys: list[str], labels: dict[str, Label], same) -> list[dict]:
    acc: dict[str, dict] = defaultdict(lambda: {"A": 0, "B": 0, "A_err": 0, "A_judged": 0, "B_err": 0,
                                                "B_judged": 0, "A_picked_err": 0, "B_picked_err": 0})
    for k in keys:
        lab = labels.get(k)
        for side, rec in (("A", cells_a[k]), ("B", cells_b[k])):
            if rec["state"] not in ADMITTED:
                continue
            ch = rec["channel"] or "?"
            acc[ch][side] += 1
            e = admit_err(rec, lab, same)
            if e is None:
                continue
            if lab.selection == RANDOM:
                acc[ch][f"{side}_judged"] += 1
                acc[ch][f"{side}_err"] += e
            else:
                acc[ch][f"{side}_picked_err"] += e
    return [{"channel": ch, **v} for ch, v in sorted(acc.items(), key=lambda x: -(x[1]["A"] + x[1]["B"]))]


_PAREN = re.compile(r"\s*[(（][^()（）]*[)）]")


def doubt_code(d: str) -> str:
    """成因码去掉括号里的数值（`库 unsure(cov=0.979)` → `库 unsure`），否则分层碎成几十行。"""
    return _PAREN.sub("", d).strip() or d


def by_doubt(cells_a: dict, cells_b: dict, keys: list[str]) -> list[dict]:
    """送审格的成因（doubts 码去掉括号里的数值；一格多码各计一次）。"""
    acc: dict[str, Counter] = defaultdict(Counter)
    for k in keys:
        for side, rec in (("A", cells_a[k]), ("B", cells_b[k])):
            if rec["state"] != "review":
                continue
            for d in {doubt_code(x) for x in rec["doubts"]} or {"(无)"}:
                acc[d][side] += 1
    return [{"doubt": d, "A": c["A"], "B": c["B"], "diff": c["B"] - c["A"]}
            for d, c in sorted(acc.items(), key=lambda x: -abs(x[1]["B"] - x[1]["A"]) * 1e6 - x[1]["A"])]


# ── 判准 ─────────────────────────────────────────────────────────────────
_OPS = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b,
        ">": lambda a, b: a > b, "==": lambda a, b: a == b}


def _lookup(comp: dict, metric: str, scope: str, side: str):
    if metric.startswith("flips."):
        parts = metric.split(".")
        f = comp["flips"].get(parts[1])
        if f is None:
            raise KeyError(metric)
        return f.get(parts[2] if len(parts) > 2 else "n")
    blk = comp["overall"][scope].get(metric)
    if blk is None:
        raise KeyError(metric)
    return blk[side]


def eval_guardrails(comp: dict, rules: list[dict]) -> list[dict]:
    out = []
    for r in rules:
        metric = r.get("metric", "")
        scope = r.get("scope", "body")
        op = r.get("op", "<=")
        res = {"rule": r, "metric": metric, "scope": scope, "op": op}
        try:
            val = _lookup(comp, metric, scope, "B")
            if "value" in r:
                target = float(r["value"])
                what = f"{r['value']}"
            else:
                base = _lookup(comp, metric, scope, "A")
                slack = float(r.get("delta", r.get("tol", 0)) or 0)
                target = None if base is None else base + slack
                what = "基线" + (f"{slack:+g}" if slack else "")
        except KeyError:
            res.update(verdict="error", msg=f"不认识的指标 {metric}")
            out.append(res)
            continue
        if op not in _OPS:
            res.update(verdict="error", msg=f"不认识的比较 {op}")
        elif val is None or target is None:
            res.update(verdict="unknown", value=val, target=target, msg="无检验力（分母为 0），判不了")
        else:
            ok = _OPS[op](val, target)
            rate = not metric.startswith("flips.")
            where = f"[{scope}]" if rate else ""
            res.update(verdict="pass" if ok else "fail", value=val, target=target,
                       msg=f"{metric}{where} = {_fmt(val, rate)} {op} {what} = {_fmt(target, rate)}")
        out.append(res)
    return out


def _fmt(x, rate: bool = True) -> str:
    if rate and isinstance(x, float):
        return f"{x:.4%}"
    return f"{x:g}" if isinstance(x, float) else str(x)


# ── 汇总 ─────────────────────────────────────────────────────────────────
def compare(cells: dict[str, dict[str, dict]], base: str, labels: dict[str, Label], page_type: Callable,
            *, same=None, guardrails: list[dict] | None = None, n_boot: int = 2000, seed: int = 0,
            books: list[str] | None = None) -> dict:
    """`cells` = {变体: {格: 记录}}。返回每个非基线变体对基线的比较块。"""
    same = same or default_same()
    out = {}
    ca = cells[base]
    for vn, cb in cells.items():
        if vn == base:
            continue
        keys = sorted(set(ca) & set(cb))
        comp: dict = {"only_in_base": len(set(ca) - set(cb)), "only_in_variant": len(set(cb) - set(ca))}
        comp["overall"] = {}
        for sc in (*SCOPES, "unknown"):
            ks = _scoped(keys, ca, sc, page_type)
            if sc == "unknown" and not ks:
                continue
            comp["overall"][sc] = overall(ca, cb, ks, labels, same, n_boot, seed)
        comp["by_book"] = {}
        for bk in books or sorted({ca[k]["book"] for k in keys}):
            bkeys = [k for k in keys if ca[k]["book"] == bk]
            comp["by_book"][bk] = {sc: overall(ca, cb, _scoped(bkeys, ca, sc, page_type), labels, same,
                                               n_boot, seed) for sc in ("body", "nonbody")}
        comp["by_channel"] = by_channel(ca, cb, keys, labels, same)
        comp["by_doubt"] = by_doubt(ca, cb, keys)
        comp["flips"] = flips(ca, cb, keys, labels, same)
        comp["mcnemar"] = mcnemar(ca, cb, keys, labels, same)
        comp["guardrails"] = eval_guardrails(comp, guardrails or [])
        out[vn] = comp
    return out


def label_summary(labels: dict[str, Label], cells: dict[str, dict[str, dict]], conflicts: list[dict],
                  sources: list[dict]) -> dict:
    known = set().union(*(set(c) for c in cells.values())) if cells else set()
    c = Counter((x.source, x.selection) for x in labels.values())
    return {"sources": sources, "n": len(labels),
            "by_source": {f"{s}/{sel}": n for (s, sel), n in sorted(c.items())},
            "random": sum(1 for x in labels.values() if x.selection == RANDOM),
            "picked": sum(1 for x in labels.values() if x.selection == PICKED),
            "nocell": sum(1 for k in labels if k not in known),
            "conflicts": len(conflicts), "conflict_cells": conflicts[:50]}
