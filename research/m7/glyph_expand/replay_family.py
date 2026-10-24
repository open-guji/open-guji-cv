"""部首族（門族 men、辶族 chuo）离线回放：用现有产物（seed_admit／glyph_match／align_ref／cell_shrink＋原图），
不重跑管线，只看进本组的格：入口照 `flow.entry`（点名 wj yh 在前，与上线顺序一致），判法照 `flow.group_flow_pass`。

用法：python replay_family.py <原图根> <产物根> <输出 jsonl> [--groups men,chuo]
每行一格：id 组 原状态 补放字/送审原因 整理本字 坐标对位字 判法留痕。别的组本遍已处理过的格（疑问里有 group_flow_*）不算。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.groups.flow import FlowConfig, entry, group_flow_pass
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
    ap.add_argument("imgs", type=Path)
    ap.add_argument("prod", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--groups", default="men,chuo")
    a = ap.parse_args()
    mine = tuple(a.groups.split(","))
    named = ("wj", "yh", *mine)
    cfg_e = FlowConfig(groups=named)
    out = open(a.out, "w", encoding="utf-8")
    tally = Counter()
    for vd in sorted(a.prod.glob("vol*")):
        b = vd.name
        for f in sorted((vd / "seed_admit").glob("p*.json")):
            page = int(f.stem[1:])
            gm = json.load(open(vd / "glyph_match" / f.name))["glyph_match"]
            cand = {c["id"]: ([tuple(x) for x in c.get("candidates") or []], c.get("guard")) for col in gm["columns"] for c in col["chars"]}
            amap, coord = {}, {}
            ar = vd / "align_ref" / f.name
            if ar.exists():
                al = json.load(open(ar))["align_ref"]
                amap = {c["id"]: (c.get("align_char"), c.get("align_op")) for c in al.get("chars") or [] if c.get("align_char")}
                coord = {c["id"]: c.get("ref_char") for c in al.get("coord") or []}
            seq, guards = [], {}
            for col in json.load(open(f))["seed_admit"]["columns"]:
                for r in col["chars"]:
                    seq.append(Rec(r["id"], r["char"], r["admit"], r.get("channel"), r.get("provenance") or "", list(r.get("doubts") or [])))
                    guards[r["id"]] = cand.get(r["id"], ([], None))[1]
            todo = []
            for r in seq:
                if blocked(r, guards[r.id]):
                    continue
                e = entry(r, cand.get(r.id, ([], None))[0], (amap.get(r.id) or (None, None))[0], cfg_e)
                if e and e[0] in mine and e[1] == "lift":
                    todo.append(r)
            if not todo:
                continue
            sh = json.load(open(vd / "cell_shrink" / f.name))["char_index"]["columns"]
            box = {c["id"]: c["bbox_page"] for col in sh for c in col["chars"]}
            img = cv2.imread(str(a.imgs / b / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
            before = {r.id: (r.char, r.admit, list(r.doubts)) for r in todo}
            group_flow_pass(todo, amap, lambda cid: cand.get(cid, ([], None))[0], lambda r: False, FlowConfig(groups=mine),
                            patch_fn=lambda cid: crop_patch(img, tuple(box[cid])) if box.get(cid) else None,
                            veto_refs=coord)
            for r in todo:
                gv = r.evidence.get("group", {})
                row = dict(id=r.id, group=gv.get("id"), was=before[r.id][0], decision=gv.get("decision"), char=r.char if r.admit else None,
                           why=gv.get("why"), doubts=[d for d in r.doubts if d.startswith("group_flow")],
                           ref=(amap.get(r.id) or (None,))[0], coord=coord.get(r.id), cands=cand[r.id][0][:4], solvers=gv.get("solvers"))
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                tally[(row["group"], row["decision"], row["why"])] += 1
    for k, v in sorted(tally.items()):
        print(k, v)


if __name__ == "__main__":
    main()
