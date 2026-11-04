"""r3「乱码闸／影子闸拦下」格：新图源文本层与整理本同字（锚点≥1、页匹配≥0.85）→ 按整理本放行；整理本无字、文本层有真字且锚点≥3 → 按文本层放行。
出 src-1、subclass=GB 的 ctx_ruling 事件（A24 2026-11-04）。r3 95 格里 62 格同字（拼图目检整理本全对：图上是边缘残字，机器读错），2 格整理本无字取文本层（載、△）。
输入：extract_cells.py（CELLS=这 95 格）的输出目录＋分类v2-明细.tsv；输出 events.jsonl、report.tsv。"""
import json, glob, sys, os, re, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.feedback.events import make_event, EventTarget

def main(indir, detail_tsv, outdir):
    R = {r["格号"]: r for r in csv.DictReader(open(detail_tsv), delimiter="\t")}
    st, evs, rep = RulingStore(persist=False), [], []
    for f in sorted(glob.glob(indir + "/*.jsonl")):
        for l in open(f):
            x = json.loads(l)
            if "err" in x or not x.get("src"):
                rep.append((x["id"], "skip", x.get("err", "无文本层对位")[:30])); continue
            ref = re.match(r"整理本(\S+)", R[x["id"]]["事实"]).group(1)
            s = x["src"]; o = ord(s)
            if 0xE000 <= o <= 0xF8FF or o >= 0xF0000 or s in "〓□？?" or x["pagematch"] < 0.85:
                rep.append((x["id"], "skip", "源文本非真字或页匹配低")); continue
            if s == ref and x["anch"] >= 1: route, why = "text_ref", "新图源文本层与整理本同为 %s（锚点 %d/4），机器读 %s 为边缘残字" % (s, x["anch"], x["cur"])
            elif ref == "∅" and x["anch"] >= 3: route, why = "text_layer", "整理本无字，新图源文本层为 %s（锚点 %d/4）" % (s, x["anch"])
            else: rep.append((x["id"], "skip", "文本层 %s≠整理本 %s" % (s, ref))); continue
            p = st.put("O", "src-1", x["left"], x["right"], char=s, conf="high", why=why, model="src-text-" + route, cell=x["id"], pending_reason="garble_gate")
            p.update({"admit_ok": True, "subclass": "GB", "ref": x["ref"], "route": route, "src": s, "machine": x["cur"], "pending_reason": "garble_gate"})
            evs.append(make_event("src-1-20261104-gb", len(evs) + 1, "ctx_ruling", EventTarget(step="seed_admit", unit="cell", key=x["id"], book=x["id"].split(":")[0]), p, actor="model"))
            rep.append((x["id"], route, s))
    os.makedirs(outdir, exist_ok=True)
    with open(outdir + "/events.jsonl", "w") as f:
        for e in evs: f.write(json.dumps(e.model_dump(mode="json"), ensure_ascii=False) + "\n")
    with open(outdir + "/report.tsv", "w") as f:
        f.write("格号\t结果\t字\n")
        for r in rep: f.write("\t".join(map(str, r)) + "\n")
    print(len(evs), "events")

if __name__ == "__main__":
    main(*sys.argv[1:4])
