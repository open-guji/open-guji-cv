"""本书字形库刻例数，按来源分列（参校本属性 C 块 C1，A23 2026-11-08；设计见 ai-team
`domain/CV/设计/参校本属性/C-字形库侧.md`）。

无参照页（`reference_profile` 里 `kind: none`）放行几乎只靠「库首位 cov＋刻例数」。刻例数若把借来的库、
只靠库形状放行再自动入库的刻例也算进去，门槛就会自己抬高自己（放错的格入库后让错字刻例越来越多）。
这里把每个字的刻例按来源分开数：

- `human`：本书人裁（`label_status=human`）；
- `ref`：有参照互证进库的——旧管线 `align`／`match`，以及 `auto`（`scripts/book_lib_auto.py` 进库、
  `admissions.evidence.channel` 不是 solo 系）；
- `solo`：`auto` 里 channel 是 solo 系（`match_solo`／`match_solo_ocr`／`match_solo_5b`，只靠库形状放行）；
- `borrow`：借库人裁（`borrowed_human`）；
- `other`：其余（`context`、`human_stale_*`、`auto` 没记通道……）；
- `unknown`：库里有刻例、`instances` 表里没这一行（11-08 实测全唐文 5707、史記 5334 条，多为早期 v2 号），
  来源查不到，不算可信。

`trusted`＝`human`＋`ref`，是无参照通道该读的刻例数。`font:` 字体域实例不数。只读库，不改任何东西；
本模块不被 Step 引用时不影响产物指纹。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SOLO_CHANNELS = frozenset({"match_solo", "match_solo_ocr", "match_solo_5b"})
REF_STATUS = frozenset({"align", "match"})
KINDS = ("human", "ref", "solo", "borrow", "other", "unknown")


def classify(label_status: str | None, provenance: str | None, evidence: str | dict | None,
             *, has_instance: bool = True) -> str:
    """一条刻例归哪一类（见模块头）。纯函数。"""
    if not has_instance:
        return "unknown"
    st = (label_status or "").strip()
    if st == "human":
        return "human"
    if st == "borrowed_human":
        return "borrow"
    if st in REF_STATUS:
        return "ref"
    if st == "auto" or provenance == "auto":
        ev = evidence
        if isinstance(ev, str):
            try:
                ev = json.loads(ev or "{}")
            except ValueError:
                ev = {}
        ch = (ev or {}).get("channel")
        if not ch:
            return "other"
        return "solo" if ch in SOLO_CHANNELS else "ref"
    return "other"


def keben_breakdown(db_path: str | Path) -> dict[str, dict[str, int]]:
    """字 → {human, ref, solo, borrow, other, trusted}。读不了库＝空表。"""
    out: dict[str, dict[str, int]] = {}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
            rows = c.execute(
                "SELECT g.char, e.instance_id, i.instance_id IS NOT NULL, i.label_status, a.provenance, a.evidence "
                "FROM exemplars e JOIN glyphs g USING(glyph_id) "
                "LEFT JOIN instances i ON i.instance_id = e.instance_id "
                "LEFT JOIN admissions a ON a.instance_id = e.instance_id").fetchall()
    except sqlite3.Error:
        return {}
    for ch, iid, has, st, prov, ev in rows:
        if str(iid or "").startswith("font:"):
            continue
        d = out.setdefault(str(ch), dict.fromkeys(KINDS, 0))
        d[classify(st, prov, ev, has_instance=bool(has))] += 1
    for d in out.values():
        d["trusted"] = d["human"] + d["ref"]
    return out


def trusted_keben_counts(db_path: str | Path) -> dict[str, int]:
    """字 → 可信刻例数（人裁＋有参照互证），无参照放行通道的刻例门槛读这个。"""
    return {ch: d["trusted"] for ch, d in keben_breakdown(db_path).items()}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="字形库刻例按来源分列（参校本属性 C1）")
    ap.add_argument("db")
    ap.add_argument("--tsv", default=None, help="逐字明细写到这里")
    a = ap.parse_args(argv)
    bd = keben_breakdown(a.db)
    tot = {k: sum(d[k] for d in bd.values()) for k in (*KINDS, "trusted")}
    print(f"{len(bd)} 字；" + "，".join(f"{k} {v}" for k, v in tot.items()))
    gap = sum(1 for d in bd.values() if d["trusted"] < 3 <= sum(d[k] for k in KINDS))
    print(f"全表刻例≥3 但可信刻例<3 的字：{gap}")
    if a.tsv:
        with open(a.tsv, "w", encoding="utf-8") as f:
            f.write("char\t" + "\t".join((*KINDS, "trusted")) + "\n")
            for ch, d in sorted(bd.items()):
                f.write(ch + "\t" + "\t".join(str(d[k]) for k in (*KINDS, "trusted")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
