"""扩展字组 L2 批：L1 弃权的格（＋可选的点名格）出 haiku 批，每批 40 格。
  python ext_make_batches.py <cells.jsonl> <输出目录> [--extra ids.json] [--size 40]
输出：<目录>/<组>_NN.txt、<组>_manifest.json（批→ids）、<组>_cells.json（id→[left,right]）、<组>_l1.json（id→L1 字）"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, "/home/user/open-guji-cv")
from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.ctx_l2 import build_batch
ap = argparse.ArgumentParser(); ap.add_argument("cells"); ap.add_argument("out"); ap.add_argument("--extra", default=""); ap.add_argument("--size", type=int, default=40)
a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
extra = set(json.load(open(a.extra)) if a.extra else [])
cells = [json.loads(l) for l in open(a.cells, encoding="utf-8")]
for g in ("wxs", "wm", "ts"):
    b = CtxL1Backend(f"/home/user/open-guji-cv/config/groups/{g}/rules.yaml")
    sel, l1 = [], {}
    for c in cells:
        if c["group"] != g: continue
        ch, _, _ = b.decide(c["left"], c["right"]); l1[c["id"]] = ch
        if ch is None or c["id"] in extra: sel.append(c)
    man = {}; cm = {c["id"]: [c["left"], c["right"]] for c in sel}
    for i in range(0, len(sel), a.size):
        ch_ = sel[i:i + a.size]; name = f"{g}_{i // a.size:02d}"
        (out / f"{name}.txt").write_text(build_batch(f"/home/user/open-guji-cv/config/groups/{g}/prompt.md", ch_), encoding="utf-8")
        man[name] = [c["id"] for c in ch_]
    (out / f"{g}_manifest.json").write_text(json.dumps(man, ensure_ascii=False)); (out / f"{g}_cells.json").write_text(json.dumps(cm, ensure_ascii=False)); (out / f"{g}_l1.json").write_text(json.dumps(l1, ensure_ascii=False))
    print(g, "共", sum(1 for c in cells if c["group"] == g), "L1给字", sum(1 for v in l1.values() if v), "送模型", len(sel), "批", len(man))
