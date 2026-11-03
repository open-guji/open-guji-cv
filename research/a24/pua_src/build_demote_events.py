"""25 格「已放行但与码表不一致」→ src-1 code_conflict 裁定（admit_ok=False），seed_admit 的 vis_rulings 遍把非人裁的已放行格降回待审（A31 11-03 定）。
输入：extract_cells.py（CELLS=不一致清单）的输出目录；码表同 build_events.py。输出 events.jsonl（batch src-1-20261103-conflict）。"""
import json, glob, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.feedback.events import make_event, EventTarget

def main(indir, out):
    tab = json.load(open(os.path.join(os.path.dirname(__file__), "code_table.json")))
    st, evs = RulingStore(persist=False), []
    for f in sorted(glob.glob(indir + "/*.jsonl")):
        for l in open(f):
            x = json.loads(l)
            if "err" in x or x["anch"] < 3 or not x.get("src"): continue
            c = "%X" % ord(x["src"])
            if c not in tab or tab[c] == x["cur"]: continue
            p = st.put("O", "src-1", x["left"], x["right"], char=tab[c], conf="high", why="码 U+%s 表定 %s，现放行 %s" % (c, tab[c], x["cur"]), model="src-text-code_conflict", cell=x["id"])
            p.update({"admit_ok": False, "subclass": "PUA", "ref": x["ref"], "route": "code_conflict", "src": x["src"], "machine": x["cur"]})
            evs.append(make_event("src-1-20261103-conflict", len(evs) + 1, "ctx_ruling", EventTarget(step="seed_admit", unit="cell", key=x["id"], book=x["id"].split(":")[0]), p, actor="model"))
    with open(out, "w") as f:
        for e in evs: f.write(json.dumps(e.model_dump(mode="json"), ensure_ascii=False) + "\n")
    print(len(evs), "events")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
