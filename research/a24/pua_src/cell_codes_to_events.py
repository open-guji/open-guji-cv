"""build_cell_codes.py 的输出（cell_codes-<册>.jsonl）→ `src-2` 裁定事件（落 <feedback>/rulings/，由 A31 推库）。
用法：python cell_codes_to_events.py <build_cell_codes 输出目录> <feedback 目录> [--only-table]
 `--only-table`：只收码在仓内码表里的（其余私用码不进库，减小体量）。"""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import time
from open_guji_cv.feedback.events import make_event, EventTarget
from open_guji_cv.feedback.rulings import KIND, RulingStore
from open_guji_cv.utils.pua_v2_codes import load_table

ap = argparse.ArgumentParser()
ap.add_argument("indir"); ap.add_argument("feedback"); ap.add_argument("--only-table", action="store_true")
a = ap.parse_args()
codes, _ = load_table(None)
st = RulingStore(a.feedback, persist=False)
n = 0
evs = []
for f in sorted(glob.glob(a.indir + "/cell_codes-*.jsonl")):
    for l in open(f):
        r = json.loads(l)
        if a.only_table and r["code"] not in codes:
            continue
        p = st.put_cell_code(r["cell"], r["code"], ref=r.get("ref", ""), anch=r["anch"], page_match=r["page_match"], src=r.get("src", ""))
        evs.append(make_event("src-2-" + time.strftime("%Y%m%d", time.gmtime()), len(evs) + 1, KIND,
                              EventTarget(step="seed_admit", unit="cell", key=r["cell"], book=r["cell"].split(":")[0]), p, actor="model"))
        n += 1
st.log.append(evs)
print(n, "src-2 events →", a.feedback)
