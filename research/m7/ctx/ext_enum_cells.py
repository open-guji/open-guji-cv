"""扩展字组（戊戌戍/未末/土士）：从整理本 siku_daizhige.txt 枚举候选格，按册量格数。
  python ext_enum_cells.py <工作区目录> <输出 jsonl> [--vols vol02,...,vol10]
id＝vol:page:col:slot[a/b]（col＝整理本行序 + 1，与产物格键一致，经 21 条人裁事件核对；slot＝列首留白 + 列内字序，夹注右行先于左行逐字计 1 格；与刻本格位只是近似，
最终定位以管线产物为准）。窗口前后各 20 字、不分段、跨列连读，夹注按读序（先右行后左行）。
"""
import argparse, json, re, collections
from pathlib import Path
GROUPS = {"wxs": "戊戌戍", "wm": "未末", "ts": "土士"}
ap = argparse.ArgumentParser(); ap.add_argument("--groups", default="", help="id=字,id=字；缺省＝戊戌戍/未末/土士"); ap.add_argument("ws"); ap.add_argument("out"); ap.add_argument("--vols", default="vol02,vol03,vol04,vol05,vol06,vol07,vol08,vol09,vol10")
a = ap.parse_args()
if a.groups: GROUPS = dict(x.split("=") for x in a.groups.split(","))
ws = Path(a.ws); vols = set(a.vols.split(","))
m = {}
for l in open(ws / "corpus/daizhige/page_map.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("dzg_id"): m[(r["dzg_id"], r["dzg_page"], "h%d" % r["side"])] = (r["vol"], r["page"])
pages = collections.defaultdict(list)   # (vol,page) -> [(col, start, text)]
cur = None
for line in open(ws / "corpus/siku_daizhige.txt", encoding="utf-8").read().split("\n"):
    if line.startswith("#@"):
        p = line.split(); cur = m.get((p[1], p[2], p[3])); continue
    if line.startswith("#") or cur is None or not line: continue
    start = len(line) - len(line.lstrip("　")); pages[cur].append((start, line.lstrip("　")))
cells = []
for (vol, page), cols in sorted(pages.items()):
    if vol not in vols: continue
    seq = []   # (col, slot, char)
    for ci, (start, text) in enumerate(cols):
        slot = start + 1; pos = 0
        while pos < len(text):
            if text[pos] == "<":
                e = text.find(">", pos); r_, _, l_ = text[pos + 1:e].partition("|")
                for sub, part in (("a", r_), ("b", l_)):
                    s = slot
                    for ch in part: seq.append((ci, s, ch, sub)); s += 1
                slot += max(len(r_), len(l_)); pos = e + 1
            else:
                seq.append((ci, slot, text[pos], "")); slot += 1; pos += 1
    pages_seq = seq
    for i, (ci, slot, ch, jz) in enumerate(pages_seq):
        for g, mem in GROUPS.items():
            if ch in mem:
                cells.append(dict(id=f"{vol}:{page}:{ci + 1}:{slot}{jz}", vol=vol, page=page, col=ci + 1, slot=slot, jz=jz, group=g, ref=ch,
                                  left="".join(c[2] for c in pages_seq[max(0, i - 20):i]), right="".join(c[2] for c in pages_seq[i + 1:i + 21])))
Path(a.out).write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cells), encoding="utf-8")
t = collections.defaultdict(lambda: collections.Counter())
for c in cells: t[c["group"]][(c["vol"], c["ref"])] += 1
for g in GROUPS:
    print(g, GROUPS[g], sum(t[g].values()), dict(collections.Counter(c["ref"] for c in cells if c["group"] == g)))
    print("  by vol", {v: sum(n for (vv, _), n in t[g].items() if vv == v) for v in sorted(vols)})
