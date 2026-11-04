"""R「整理本这位没字」格按新图源文本层取字（A24 2026-11-04，A31 派）。出 src-1、subclass=GB、route=text_blank 的 ctx_ruling 事件。
文本层有真字、锚点≥3、页匹配≥0.85：
  strict  文本层字＝字形库首位（机器字）→ 放行（独立来源互证）
  ext     文本层字≠库首位 → 单独出，是否放行等 sheldon 定（拼图目检：库对这些字没样本，文本层读字全对）
符号 〇 ○ ● 丶 不取。输出 events_strict.jsonl、events_ext.jsonl、report.tsv。"""
import json, glob, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.feedback.events import make_event, EventTarget

def main(indir, outdir):
    st = RulingStore(persist=False); evs = {"strict": [], "ext": []}; rep = []
    for f in sorted(glob.glob(indir + "/*.jsonl")):
        for l in open(f):
            x = json.loads(l); s = x.get("src")
            if "err" in x or not s: rep.append((x["id"], "skip", "无文本层对位")); continue
            o = ord(s)
            if 0xE000 <= o <= 0xF8FF or o >= 0xF0000 or s in "〓□？?〇○●丶" or x["pagematch"] < 0.85 or x["anch"] < 3:
                rep.append((x["id"], "skip", "非真字／页匹配低／锚点弱")); continue
            lib = x["cands"][0][0] if x["cands"] else None
            kind = "strict" if s == lib else "ext"
            why = "新图源文本层此位为 %s（锚点 %d/4），%s" % (s, x["anch"], "与库首位一致" if kind == "strict" else "库首位 %s 不同" % lib)
            p = st.put("O", "src-1", x["left"], x["right"], char=s, conf="high", why=why, model="src-text-text_blank", cell=x["id"])
            p.update({"admit_ok": True, "subclass": "GB", "ref": x["ref"], "route": "text_blank", "src": s, "machine": x["cur"], "pending_reason": "ref_gap"})
            evs[kind].append(make_event("src-1-20261104-blank-" + kind, len(evs[kind]) + 1, "ctx_ruling", EventTarget(step="seed_admit", unit="cell", key=x["id"], book=x["id"].split(":")[0]), p, actor="model"))
            rep.append((x["id"], kind, s))
    os.makedirs(outdir, exist_ok=True)
    for k, v in evs.items():
        with open(f"{outdir}/events_{k}.jsonl", "w") as f:
            for e in v: f.write(json.dumps(e.model_dump(mode="json"), ensure_ascii=False) + "\n")
    with open(outdir + "/report.tsv", "w") as f:
        f.write("格号\t结果\t字\n")
        for r in rep: f.write("\t".join(map(str, r)) + "\n")
    print({k: len(v) for k, v in evs.items()})

if __name__ == "__main__":
    main(*sys.argv[1:3])
