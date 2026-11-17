#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""码位归一表入表审（A24，2026-11-10，「字的等价与归一」全流程审视第三节 3：入表前要有一道审）。

`config/codepoints.yaml` 的 `另一码位: 本书指定码位` 一旦进表，比较、写文本、出单门处处视为同字。
所以**只收异体（同一个字的不同写法）**；形近不同义的字（日／曰、撰／𢰅 一类）、通假字绝不进表。

对每条 `k: v` 给判决（证据都来自仓内已有数据，不联网）：
  REJECT  永不并组名单有这一对；或 k、v 同属某个形近不同义（near_form）字组且不是同义组；或关系层只有 NEVER 来源
  REVIEW  关系层没有异体边／只有 T3（通假、形近、简繁）／只有 yitizi 一家；要人看图或查字书后再收
  ACCEPT  关系层 T1 且 ≥2 个异体来源，或有本书刻例手工边（local:keben）；且不在 edge_pair_exclude.tsv
  （T2「互通／只在某些义项同」不自动收：撰／𢰅、晝／畫、遍／徧、概／槪 都是 T2，字典说互通，但本书是否同词要人定）
另报：链（v 本身也是别条的键）、环、同一目标过多、键不是单个汉字。

用法：
  python scripts/codepoints_audit.py <codepoints.yaml> [--tsv 输出.tsv] [--new k:v ...]
  --new 只审给定的新条目（入表前的闸门；有 REJECT 退出码 2，有 REVIEW 退出码 1）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from open_guji_cv.variants import VariantGraph  # noqa: E402
from open_guji_cv.clustering.variants import never_group_pairs  # noqa: E402
from open_guji_cv.groups.registry import GROUPS, PROVISIONAL  # noqa: E402

EXCLUDE_TSV = ROOT / "config" / "variants" / "edge_pair_exclude.tsv"


def exclude_pairs(path: Path = EXCLUDE_TSV) -> dict[frozenset, str]:
    out: dict[frozenset, str] = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        f = ln.split("\t")
        if len(f) >= 2 and len(f[0]) == 1 and len(f[1]) == 1:
            out[frozenset((f[0], f[1]))] = f[2] if len(f) > 2 else ""
    return out


def load_entries(path: Path) -> dict[str, str]:
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (d.get("codepoints") or {}).items()}


def audit_one(k: str, v: str, vg: VariantGraph, never: frozenset, table: dict[str, str]) -> tuple[str, str, str]:
    """返回 (判决, 档位/来源摘要, 理由)。"""
    notes: list[str] = []
    e = vg.variant_edge(k, v)
    src = f"{e.tier or '无边'}:{'+'.join(e.sources)}" if e.tier else "无边"
    if frozenset((k, v)) in never:
        return "REJECT", src, "永不并组名单（人审定的不同字）"
    nf = [g.id for g in GROUPS.values() if k in g.members and v in g.members and g.kind == "near_form"]
    if nf:
        return "REJECT", src, "同属形近不同义组 " + "/".join(nf)
    ex = exclude_pairs().get(frozenset((k, v)))
    if ex is not None:
        return "REJECT", src, "边表暂归一排除对：" + ex
    if e.never_only:
        return "REJECT", src, "关系层只有「形近易混／通假」来源"
    # 形近组里 k、v 分属不同组也要看一眼（如 k 在 near_form 组、v 是它的陪衬）
    kn = [g.id for g in GROUPS.values() if g.kind == "near_form" and (k in g.members) != (v in g.members) and (k in g.members or v in g.members)]
    if kn:
        notes.append("一头在形近组 " + "/".join(kn[:3]) + "（核对 v 不是该组的陪衬字）")
    if v in table:
        notes.append(f"链：{v}→{table[v]}（目标本身又被归一，须压平）")
    if table.get(v) == k:
        notes.append("环")
    if not e.tier:
        return "REVIEW", src, "关系层无异体边；" + ("；".join(notes) if notes else "要看图或查字书")
    if e.tier == "T3":
        return "REVIEW", src, "T3（通假／形近／仅简繁）；" + "；".join(notes)
    if e.tier == "T2" and "local:keben" not in e.sources:
        return "REVIEW", src, "T2（互通／只在某些义项同／一形多正），要人确认本书同词异形；" + "；".join(notes)
    if e.tier == "T1" and "local:keben" not in e.sources and e.n_bridge < 2:
        return "REVIEW", src, "T1 但只有 1 家异体来源（单一来源，yitizi 一家最可疑）；" + "；".join(notes)
    return ("REVIEW" if any(n.startswith(("链", "环")) for n in notes) else "ACCEPT"), src, "；".join(notes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("yaml", type=Path)
    ap.add_argument("--tsv", type=Path)
    ap.add_argument("--new", nargs="*", help="只审这些新条目，形如 釆:采")
    a = ap.parse_args()
    table = load_entries(a.yaml) if a.yaml.exists() else {}
    items = dict(table)
    if a.new is not None:
        items = {}
        for s in a.new:
            k, v = s.split(":")
            items[k] = v
            table.setdefault(k, v)
    vg = VariantGraph.load()
    never = never_group_pairs()
    prov_forms = {frozenset(p.forms) for p in PROVISIONAL.values()}
    rows = []
    for k, v in items.items():
        ver, src, why = audit_one(k, v, vg, never, table)
        if len(k) != 1 or len(v) != 1:
            ver, why = "REVIEW", "键或值不是单个字；" + why
        in_prov = any(k in f and v in f for f in prov_forms)
        rows.append((k, v, ver, src, "是" if in_prov else "否", why))
    out = ["键\t值\t判决\t关系层\t在暂归一兜底表\t理由"] + ["\t".join(r) for r in rows]
    text = "\n".join(out) + "\n"
    if a.tsv:
        a.tsv.write_text(text, encoding="utf-8")
    cnt = {x: sum(r[2] == x for r in rows) for x in ("ACCEPT", "REVIEW", "REJECT")}
    print(text if len(rows) <= 40 else "\n".join(out[:1] + [r for r in out[1:] if "\tACCEPT\t" not in r]))
    print("合计", len(rows), cnt, file=sys.stderr)
    return 2 if cnt["REJECT"] else (1 if cnt["REVIEW"] else 0)


if __name__ == "__main__":
    sys.exit(main())
