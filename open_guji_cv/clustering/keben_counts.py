"""本书字形库刻例数，按来源分列（参校本属性 C 块 C1，A23 2026-11-08；设计见 ai-team
`domain/CV/设计/参校本属性/C-字形库侧.md`）。

无参照页（`reference_profile` 里 `kind: none`）放行几乎只靠「库首位 cov＋刻例数」。刻例数若把借来的库、
只靠库形状放行再自动入库的刻例也算进去，门槛就会自己抬高自己（放错的格入库后让错字刻例越来越多）。
这里把每个字的刻例按来源分开数：

- `human`：本书人裁（`label_status=human`）；
- `ref`：有参照互证进库的——旧管线 `align`／`match`，以及 `auto`（`scripts/book_lib_auto.py` 进库、
  `admissions.evidence.channel` 不是 solo 系）；
- `solo`：`auto` 里 channel 是 solo 系（`match_solo`／`match_solo_ocr`／`match_solo_5b`，只靠库形状放行）；
- `borrow`：借来的库（`borrowed` 表里有这一例，或 `borrowed_human`）——借库带进来的 auto 也归这里，
  不按它在原书的通道算 ref（11-08 史記实测：借全唐文 human+auto 两万多例，原先被算成 other）；
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
             *, has_instance: bool = True, borrowed: bool = False) -> str:
    """一条刻例归哪一类（见模块头）。纯函数。"""
    if borrowed:
        return "borrow"
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
            has_b = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='borrowed'").fetchone()
            bsel, bjoin = (("b.instance_id IS NOT NULL", "LEFT JOIN borrowed b ON b.instance_id = e.instance_id ")
                           if has_b else ("0", ""))
            rows = c.execute(
                f"SELECT g.char, e.instance_id, i.instance_id IS NOT NULL, {bsel}, i.label_status, a.provenance, a.evidence "
                "FROM exemplars e JOIN glyphs g USING(glyph_id) "
                "LEFT JOIN instances i ON i.instance_id = e.instance_id "
                "LEFT JOIN admissions a ON a.instance_id = e.instance_id " + bjoin).fetchall()
    except sqlite3.Error:
        return {}
    for ch, iid, has, bor, st, prov, ev in rows:
        if str(iid or "").startswith("font:"):
            continue
        d = out.setdefault(str(ch), dict.fromkeys(KINDS, 0))
        d[classify(st, prov, ev, has_instance=bool(has), borrowed=bool(bor))] += 1
    for d in out.values():
        d["trusted"] = d["human"] + d["ref"]
    return out


def trusted_keben_counts(db_path: str | Path, borrow_db: str | Path | None = None,
                         *, min_own: int = 1) -> dict[str, int]:
    """字 → 可信刻例数（人裁＋有参照互证），无参照放行通道的刻例门槛读这个。

    `borrow_db`（A24 11-08 收窄版借库）：同族书的库（如史記借全唐文），按**那本书自己的库**再分一次来源，
    只把它的可信刻例（它的 human＋ref）加进来；本库的借库副本没带准入证据，分不出通道，所以不从本库数。
    只有本书自己已有 ≥`min_own` 条可信刻例的字才加借库数（免得一个本书没见过的字全靠别书刻例放行）。
    缺省不借，结果与不传一样。字体族是否同族由调用方（册配置）负责。"""
    own = {ch: d["trusted"] for ch, d in keben_breakdown(db_path).items()}
    if borrow_db is None:
        return own
    other = {ch: d["trusted"] for ch, d in keben_breakdown(borrow_db).items()}
    return {ch: n + (other.get(ch, 0) if n >= min_own else 0) for ch, n in own.items()}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="字形库刻例按来源分列（参校本属性 C1）")
    ap.add_argument("db")
    ap.add_argument("--tsv", default=None, help="逐字明细写到这里")
    ap.add_argument("--borrow-db", default=None, help="同族借库书的 glyph.db（只数它的可信刻例）")
    a = ap.parse_args(argv)
    bd = keben_breakdown(a.db)
    tot = {k: sum(d[k] for d in bd.values()) for k in (*KINDS, "trusted")}
    print(f"{len(bd)} 字；" + "，".join(f"{k} {v}" for k, v in tot.items()))
    if a.borrow_db:
        own = trusted_keben_counts(a.db)
        withb = trusted_keben_counts(a.db, a.borrow_db)
        print(f"可信≥3 的字：本书 {sum(v >= 3 for v in own.values())}，加同族借库 {sum(v >= 3 for v in withb.values())}")
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
