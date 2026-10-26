"""象彖𧰼（xz）离线回放（2026-10-26，A24 全册任务 08；照 `replay_family.py` 改）：用现有产物，不重跑管线，补放（lift）与复核
（review）都回放；字块用线上同款 char_patch（工作区 GUJI_WORKSPACE 要有产物、原图、新 L2 表）。

用法：GUJI_WORKSPACE=<工作区> python replay_xz.py <产物根> <输出 jsonl> [--vols vol50,vol51]
每行一格：id 原状态 现结局 字 整理本字 坐标对位字 判法留痕。别的组本遍已处理过的格（疑问里有 group_flow_*）不算。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from build_shape_pair import char_patch_fn
from open_guji_cv.core.book import load_book
from open_guji_cv.core.workspace import data_root
from open_guji_cv.groups.context import WIDTH
from open_guji_cv.groups.flow import FlowConfig, entry, group_flow_pass
from open_guji_cv.groups.freq import load as _load_freq, load_vols as _load_vols
from open_guji_cv.steps.seed_admit import _clf_ctx
from open_guji_cv.utils.jiazhu_order import sort_by_reading
from open_guji_cv.steps.seed_admit import _GROUP_FLOW_HARD, _GROUP_FLOW_OWN_DOUBTS, _GROUP_FLOW_OWN_GUARDS, _hard_blocked


@dataclass
class Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def blocked(r, guard) -> bool:
    if guard in _GROUP_FLOW_OWN_GUARDS:
        guard = None
    ds = [d for d in (r.doubts or []) if isinstance(d, str) and d not in _GROUP_FLOW_OWN_DOUBTS]
    return _hard_blocked(ds, guard) or any(d in _GROUP_FLOW_HARD for d in ds) or any(d.startswith("group_flow_") for d in ds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prod", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--vols", default="")
    a = ap.parse_args()
    vols = set(filter(None, a.vols.split(",")))
    mine = ("xz",)
    cfg_e = FlowConfig(groups=mine)
    gdir = data_root() / "config" / "groups"
    cfg = FlowConfig(groups=mine, freq_table=_load_freq(str(gdir / "freq.json")), freq_vols=_load_vols(str(gdir / "freq.json")),
                     l2_tables={"xz": str(gdir / "l2" / "xz.json")})
    print("L2 表", cfg.l2_tables["xz"])
    pfn = char_patch_fn()
    out = open(a.out, "w", encoding="utf-8")
    tally = Counter()
    for vd in sorted(a.prod.glob("vol*")):
        b = vd.name
        if (vols and b not in vols) or b == "vol06":            # vol06 是 A32 精校测试册，不碰
            continue
        bk = load_book(b)
        canon = bk.canonical_char if bk.codepoints else (lambda c: c)
        cfg.canon = canon if bk.codepoints else None
        for f in sorted((vd / "seed_admit").glob("p*.json")):
            s = f.read_text(encoding="utf-8")
            if not any(ch in s for ch in "象彖𧰼"):
                continue
            gm = json.load(open(vd / "glyph_match" / f.name))["glyph_match"]
            cand = {c["id"]: ([tuple(x) for x in c.get("candidates") or []], c.get("guard")) for col in gm["columns"] for c in col["chars"]}
            amap, coord = {}, {}
            ar = vd / "align_ref" / f.name
            if ar.exists():
                al = json.load(open(ar))["align_ref"]
                amap = {c["id"]: (c.get("align_char"), c.get("align_op")) for c in al.get("chars") or [] if c.get("align_char")}
                coord = {c["id"]: c.get("ref_char") for c in al.get("coord") or []}
            seq, guards, old = [], {}, {}
            for col in sorted(json.loads(s)["seed_admit"]["columns"], key=lambda c: c["col"]):
                rs = []
                for r in col["chars"]:
                    ds = [d for d in (r.get("doubts") or []) if not (isinstance(d, str) and d.startswith("group_flow"))]
                    x = Rec(r["id"], r["char"], r["admit"], r.get("channel"), r.get("provenance") or "", ds)
                    x.col, x.slot, x.sub = col["col"], r["slot"], r.get("sub")
                    old[r["id"]] = (r["char"], r["admit"], r.get("channel"), ((r.get("evidence") or {}).get("group") or {}).get("id"))
                    if old[r["id"]][2] == "group_flow" and old[r["id"]][3] == "xz":   # 原来就是本组补放的：按未放行回放
                        x.admit, x.channel = False, None
                    guards[r["id"]] = cand.get(r["id"], ([], None))[1]
                    rs.append(x)
                seq += [x for x in sort_by_reading(rs) if not (x.doubts and "excluded" in x.doubts)]
            todo = [r for r in seq if old[r.id][3] in (None, "xz") and not blocked(r, guards[r.id])
                    and (e := entry(r, cand.get(r.id, ([], None))[0], (amap.get(r.id) or (None, None))[0], cfg_e)) and e[0] in mine]
            if not todo:
                continue
            ids = {r.id for r in todo}
            group_flow_pass(seq, amap, lambda cid: cand.get(cid, ([], None))[0], lambda r: r.id not in ids, cfg,
                            ctx_fn=lambda q, i, step: _clf_ctx(q, amap, i, step, WIDTH),
                            patch_fn=lambda cid: pfn(b, cid), canon=canon, veto_refs=coord)
            for r in todo:
                gv = r.evidence.get("group", {})
                was = "放行" if old[r.id][1] else "送审"
                now = "放行" if r.admit else "送审"
                row = dict(id=r.id, was=was, was_char=old[r.id][0], now=now, char=r.char if r.admit else None, decision=gv.get("decision"),
                           why=gv.get("why"), doubts=[d for d in r.doubts if d.startswith("group_flow")],
                           ref=(amap.get(r.id) or (None,))[0], coord=coord.get(r.id), cands=cand[r.id][0][:3], solvers=gv.get("solvers"))
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                tally[(was, now, row["decision"], row["why"])] += 1
    for k, v in sorted(tally.items(), key=str):
        print(k, v)


if __name__ == "__main__":
    main()
