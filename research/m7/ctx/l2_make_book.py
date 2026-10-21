"""整册 L2 批：从 A 臂 seed_admit 产物里取 M7 候选格，L1 先判，**L1 弃权的**格出 haiku 批（每批 40 格）。
窗口与运行时同一个函数（seed_admit._clf_ctx，宽 20），所以表的键能对上。
  python l2_make_book.py <A 臂 seed_admit 目录> <align_ref 目录> <输出目录> [--size 40]
输出：<输出目录>/<组>_NN.txt、<组>_manifest.json（id→批）、<组>_cells.json（id→[left,right]，建表用）、stats.json
"""
import argparse, glob, json, sys
from pathlib import Path
from types import SimpleNamespace

from open_guji_cv.groups.context import WIDTH
from open_guji_cv.groups.prompt_template import book_prompt_vars, build_batch_rendered as build_batch
from open_guji_cv.groups.flow import ctx_judge as judge
from open_guji_cv.groups.registry import GROUPS
from open_guji_cv.steps.seed_admit import _clf_ctx
from open_guji_cv.utils.jiazhu_order import sort_by_reading

ap = argparse.ArgumentParser()
ap.add_argument("seed_dir"); ap.add_argument("align_dir"); ap.add_argument("out")
ap.add_argument("--size", type=int, default=40); ap.add_argument("--groups", default="jys,ry,rr")
a = ap.parse_args()
groups = a.groups.split(","); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
cells = {g: {} for g in groups}; l1 = {g: {} for g in groups}
for f in sorted(glob.glob(str(Path(a.seed_dir) / "*.json"))):
    d = json.load(open(f, encoding="utf-8"))["seed_admit"]
    af = Path(a.align_dir) / Path(f).name
    amap = {c["id"]: (c["align_char"], c.get("align_op")) for c in json.load(open(af, encoding="utf-8"))["align_ref"]["chars"]}
    seq = [SimpleNamespace(**{k: getattr(c, k, None) for k in ("id", "char", "admit", "doubts")})
           for col in sorted(d["columns"], key=lambda c: c["col"])
           for c in sort_by_reading([SimpleNamespace(**c) for c in col["chars"]])
           if not (c.doubts and "excluded" in c.doubts)]      # 夹注读序，与 seed_admit._group_flow_pass 一致
    for i, r in enumerate(seq):
        ref = (amap.get(r.id) or (None, None))[0]
        left = right = None
        for g in groups:
            mem = GROUPS[g].members
            if ref not in mem and r.char not in mem:
                continue
            if left is None:
                left, right = _clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH)
            v = judge(g, r.id, ref, left, right, None)
            l1[g][r.id] = v.char
            if v.char is None:
                cells[g][r.id] = [left, right]
stats = {}
for g in groups:
    prompt = Path("/home/user/open-guji-cv") / GROUPS[g].config_dir / "prompt.md"
    ids = sorted(cells[g]); man = {}
    for i in range(0, len(ids), a.size):
        chunk = ids[i:i + a.size]; name = f"{g}_{i // a.size:02d}"
        (out / f"{name}.txt").write_text(build_batch(prompt, [dict(id=c, left=cells[g][c][0], right=cells[g][c][1]) for c in chunk], book_prompt_vars()), encoding="utf-8")
        man[name] = chunk
    (out / f"{g}_manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    (out / f"{g}_cells.json").write_text(json.dumps(cells[g], ensure_ascii=False), encoding="utf-8")
    (out / f"{g}_l1.json").write_text(json.dumps(l1[g], ensure_ascii=False), encoding="utf-8")
    stats[g] = dict(candidates=len(l1[g]), l1_give=sum(1 for v in l1[g].values() if v), to_model=len(ids), batches=len(man))
(out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
print(stats)
