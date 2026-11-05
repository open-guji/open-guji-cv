"""把 r2「整理本缺字」格变成 ctx_ruling 事件（group=O、prompt_ver=src-1、subclass=PUA），供 seed_admit 的 vis_rulings 通道放行（A24 2026-11-03）。

两条路：
  text_layer  新图源（siku-qiefen-v2）text.jsonl.gz 在缺字位有真 Unicode 字；对齐锚点≥3（左右各两字里至少 3 个同字）才取；
              源文本字是私用码、〓、□、？、缅甸字母的不取。
  code_table  源文本字是私用码 U+F1xxx：按 code_table.json「一码一字」取字（表里的码只定一次：人裁一致的码＋人定的冲突码；不在表里的码留空）。
输入：extract_cells.py 的输出目录（每册一个 jsonl）。输出：events.jsonl、report.tsv。
"""
import json, glob, sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.feedback.events import make_event, EventTarget  # noqa

def kind(s):
    if not s: return "none"
    o = ord(s)
    if 0xE000 <= o <= 0xF8FF or o >= 0xF0000: return "pua"
    if s in "〓□?？" or 0x1000 <= o <= 0x109F: return "blank"
    # 文本层取字必须是汉字区的字（含 Ext J U+323B0–3347F，Unicode 17 真汉字，py3.12 的 unicodedata 不认，不能用字名判）
    if not (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3347F or 0x2F800 <= o <= 0x2FA1F): return "nonhan"
    return "real"

def main(indir, outdir, table="code_table.json"):
    tab = json.load(open(os.path.join(os.path.dirname(__file__), table)))
    st = RulingStore(persist=False)
    rows = [json.loads(l) for f in sorted(glob.glob(indir + "/*.jsonl")) for l in open(f)]
    evs, rep = [], []
    for x in rows:
        if "err" in x:
            rep.append((x["id"], "-", "", "err:" + x["err"])); continue
        s = x.get("src"); k = kind(s); route = ch = None; why = ""
        if k == "real" and x["anch"] >= 3 and x["pagematch"] >= 0.85:
            route, ch, why = "text_layer", s, "新图源文本层此位为 %s（锚点 %d/4）" % (s, x["anch"])
        elif k == "pua" and x["anch"] >= 3:
            c = "%X" % ord(s)
            if c in tab:
                route, ch, why = "code_table", tab[c], "码 U+%s 表定 %s" % (c, tab[c])
        if not ch:
            rep.append((x["id"], k, s or "", "skip:anch=%s" % x.get("anch"))); continue
        p = st.put("O", "src-1", x["left"], x["right"], char=ch, conf="high", why=why, model="src-text-" + route, cell=x["id"], pending_reason="ref_lacuna")
        p.update({"admit_ok": True, "subclass": "PUA", "ref": x["ref"], "route": route, "src": s, "machine": x.get("cur"), "pending_reason": "ref_lacuna"})
        ev = make_event("src-1-20261103", len(evs) + 1, "ctx_ruling", EventTarget(step="seed_admit", unit="cell", key=x["id"], book=x["id"].split(":")[0]), p, actor="model")
        evs.append(ev); rep.append((x["id"], k, s, route + ":" + ch))
    os.makedirs(outdir, exist_ok=True)
    with open(outdir + "/events.jsonl", "w") as f:
        for e in evs: f.write(json.dumps(e.model_dump(mode="json"), ensure_ascii=False) + "\n")
    with open(outdir + "/report.tsv", "w") as f:
        f.write("格号\t源文本类\t源文本字\t结果\n")
        for r in rep: f.write("\t".join(map(str, r)) + "\n")
    print(len(rows), "cells;", len(evs), "events;", collections.Counter(e.payload["route"] for e in evs))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
