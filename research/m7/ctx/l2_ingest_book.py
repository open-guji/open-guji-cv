"""把 haiku 的批输出合成整册 group_clf/1 表（ctx_ver 3），只收 conf=high。
  python l2_ingest_book.py <批目录> <模型子目录名，如 haiku> <输出表目录> [--min-conf high]
批目录里要有 l2_make_book.py 出的 <组>_manifest.json／<组>_cells.json；模型输出放 <批目录>/<模型>/<批名>.json。
"""
import argparse, json
from pathlib import Path

from open_guji_cv.groups.ctx_l3 import load_prompt, merge_runs, parse_output
from open_guji_cv.groups.registry import GROUPS

ap = argparse.ArgumentParser(); ap.add_argument("dir"); ap.add_argument("model"); ap.add_argument("out")
ap.add_argument("--min-conf", default="high"); ap.add_argument("--groups", default="jys,ry,rr")
a = ap.parse_args(); D = Path(a.dir); O = Path(a.out); O.mkdir(parents=True, exist_ok=True)
for g in a.groups.split(","):
    spec = GROUPS[g]; meta, _ = load_prompt(Path("/home/user/open-guji-cv") / spec.config_dir / "prompt.md")
    man = json.loads((D / f"{g}_manifest.json").read_text(encoding="utf-8"))
    cells = json.loads((D / f"{g}_cells.json").read_text(encoding="utf-8"))
    run, miss = {}, []
    for name in man:
        f = D / a.model / f"{name}.json"
        if f.exists():
            run.update(parse_output(f.read_text(encoding="utf-8")))
        else:
            miss.append(name)
    ctxs = {i: tuple(cells[i]) for ids in man.values() for i in ids}
    t = merge_runs(g, "".join(sorted(spec.members)), meta["ver"], {a.model: run}, ctxs, tuple(a.min_conf.split(",")))
    (O / f"{g}_table.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    import collections
    print(g, "模型答了", len(run), "/", len(ctxs), "缺批", miss, dict(collections.Counter(c["why"] for c in t["cells"].values())))
