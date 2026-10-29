# -*- coding: utf-8 -*-
"""生成 `align_ref` 的页钉位表 `page_pins.jsonl`（史记文渊阁，GUJI-750）。

输入：拆页表（`sp_0243.json`/`sp_0244.json`，每行 `{ia_leaf, canvas_seq}`）、册划分
`vols_plan.json`（`[[册号, djvu, 起叶, 止叶], …]`）、殆知阁整理本（含 `#@ <djvu>-<id> <叶> h0|h1` 半叶头）。

对应规则（2026-10-28 实证：整理本 2859 个半叶头与拆页表的 2859 个上/下开一一对上，无多无少）：
- 册内第 k 页（1 起）＝该册叶范围内拆页表的第 k 行（叶升序、同叶 a b c d）；
- 一张图（djvu 一叶 L）分上开（a 右半、b 左半）、下开（c 右、d 左）；整理本一个开 ＝ id `4·(L−5)+下开(0|1)`，
  `h0` ＝ 右半（a/c），`h1` ＝ 左半（b/d）；
- 拆页表里没有对应整理本开的页（书名签、衔名、上开无版框的单页等）不钉。

用法：make_page_pins.py <整理本> <vols_plan.json> <sp_0243.json> <sp_0244.json> <out.jsonl>"""
import json
import sys

corpus, plan, sp43, sp44, out = sys.argv[1:6]
heads = set()
for ln in open(corpus, encoding="utf-8"):
    if ln.startswith("#@"):
        heads.add(ln[2:].strip())
by_key = {}                       # (djvu, id, h) → 半叶头全文
for h in heads:
    did, _leaf, hh = h.split()[0], h.split()[1], h.split()[-1]
    by_key[(did, hh)] = h
sp = {"0243": json.load(open(sp43, encoding="utf-8")), "0244": json.load(open(sp44, encoding="utf-8"))}
n_pin = n_all = 0
with open(out, "w", encoding="utf-8") as f:
    for vol, dj, a, b in json.load(open(plan, encoding="utf-8")):
        rows = [r for r in sp[dj] if a <= r["ia_leaf"] <= b]
        for k, r in enumerate(rows, 1):
            n_all += 1
            part = r["canvas_seq"][-1]
            leaf = r["ia_leaf"]
            idn = 4 * (leaf - 5) + (1 if part in "cd" else 0)
            key = (f"{dj}-{idn:04d}", "h0" if part in "ac" else "h1")
            head = by_key.get(key)
            if head:
                f.write(json.dumps({"book": f"{int(vol):02d}", "page": k, "head": head}, ensure_ascii=False) + "\n")
                n_pin += 1
print(f"钉 {n_pin}/{n_all} 页 → {out}")
