"""字形库刻例按异体组重判（GUJI-719 第 1 项并入 A24，2026-10-25）：库里每个刻例，若库标在某个同义组（`kind=variant`）里，
就用该组在线判法（`ids_online.judge`，模板库冻结的那一套）判它的字块，与库标比；殿本只一种刻法的对（`ONE_FORM`）直接按刻形改。

用法：python libcheck.py <glyph.db> <输出 tsv> [--groups g1,g2]
输出一行一个「库标与判法／刻形不一致」的刻例：instance_id 库标 来路 组 判 margin 依据。只列，不改库；
看图确认后由 `relabel.py` 写成 glyph_audit relabel 事件（推中心库要 sheldon 说「推」）。

口径：
- 字块用库里存的 patch（vol01 的刻例来自 v1 管线，库 bbox 与现页图对不上，裁不回去；v2 刻例与产物同格号，实测与按页图重裁 margin 差 ≤0.4）。
- 判法给字即算（门槛用各组 `SPECS.min_margin`）；与库标不同的才列。人裁入库（provenance=human）的只列不改——判法在库字块上
  与 sheldon 719 裁决有冲突（yi_560 3 格、zheng 1 格，见 README），人裁以人为准。
"""
from __future__ import annotations

import io
import sqlite3
import sys
from collections import Counter

import numpy as np
from PIL import Image

from open_guji_cv.groups import ids_online as O, registry as R

#: 殿本只一种刻法、码位跟刻形走的对：库标 → 刻形（看图 vol01–20：字形库刻例与 vol04–20 已放行格全是后一形，人裁也全录后一形）。
ONE_FORM = {"既": "旣", "清": "淸", "青": "靑"}


def main(db: str, out: str, only: set | None = None) -> Counter:
    c = sqlite3.connect(db)
    groups = {g: s for g, s in R.FLOW_GROUPS.items() if s.kind == "variant" and g in O.SPECS and O.has_bank(g)
              and (not only or g in only)}
    ch2g: dict = {}
    for g, s in sorted(groups.items()):
        for ch in s.members:
            ch2g.setdefault(ch, g)
    st: Counter = Counter()
    rows = []
    q = "select i.instance_id, i.label, a.provenance, i.patch_png from instances i join admissions a using(instance_id)"
    for iid, lab, prov, png in c.execute(q):
        if lab in ONE_FORM:
            rows.append((iid, lab, prov, "one_form", ONE_FORM[lab], "", "殿本只一种刻法"))
            st[("one_form", prov)] += 1
            continue
        g = ch2g.get(lab)
        if not g:
            continue
        v = O.judge(g, np.array(Image.open(io.BytesIO(png)).convert("L")))
        k = "abstain" if not v.char else ("same" if v.char == lab else "diff")
        st[(g, k)] += 1
        if k == "diff":
            rows.append((iid, lab, prov, g, v.char, f"{v.conf:.2f}" if v.conf is not None else "", v.why))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("instance_id\t库标\t来路\t组\t判\tmargin\t依据\n")
        for r in sorted(rows, key=lambda r: (r[3], r[0])):
            fh.write("\t".join(map(str, r)) + "\n")
    return st


if __name__ == "__main__":
    only = next((set(a.split("=", 1)[1].split(",")) for a in sys.argv if a.startswith("--groups=")), None)
    for k, n in sorted(main(sys.argv[1], sys.argv[2], only).items()):
        print(k, n)
