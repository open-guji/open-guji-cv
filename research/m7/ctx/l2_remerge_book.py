"""窗口取法改了（夹注读序）之后补表：旧批输出里窗口没变的格沿用，变了的格用新批输出，合成新表。
  python l2_remerge_book.py <旧批目录> <新批目录> <模型子目录名> <输出表目录>
新批目录由 l2_make_book.py 出（<组>_cells.json），其中变了的格另存 <组>_changed.json、补批为 <组>c_NN。"""
import argparse, json, glob
from pathlib import Path

from open_guji_cv.groups.ctx_l3 import load_prompt, merge_runs, parse_output
from open_guji_cv.groups.registry import GROUPS

ap = argparse.ArgumentParser(); ap.add_argument("old"); ap.add_argument("new"); ap.add_argument("model"); ap.add_argument("out")
ap.add_argument("--groups", default="jys,ry,rr"); a = ap.parse_args()
Old, New, O = Path(a.old), Path(a.new), Path(a.out); O.mkdir(parents=True, exist_ok=True)
for g in a.groups.split(","):
    spec = GROUPS[g]; meta, _ = load_prompt(Path("/home/user/open-guji-cv") / spec.config_dir / "prompt.md")
    cells = json.loads((New / f"{g}_cells.json").read_text(encoding="utf-8"))
    changed = set(json.loads((New / f"{g}_changed.json").read_text(encoding="utf-8")))
    run = {}
    for f in sorted(glob.glob(str(Old / a.model / f"{g}_*.json"))):
        run.update({k: v for k, v in parse_output(Path(f).read_text(encoding="utf-8")).items() if k not in changed})
    miss = []
    for f in sorted(glob.glob(str(New / a.model / f"{g}c_*.json"))):
        run.update(parse_output(Path(f).read_text(encoding="utf-8")))
    miss = [i for i in changed if i not in run]
    ctxs = {i: tuple(v) for i, v in cells.items()}
    t = merge_runs(g, "".join(sorted(spec.members)), meta["ver"], {a.model: run}, ctxs, ("high",))
    (O / f"{g}_table.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    print(g, "格", len(ctxs), "模型答", len(run), "补批缺", len(miss), "表项", len(t["cells"]))
