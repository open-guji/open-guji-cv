"""L2 批跑工具。
  make   <组> <目录> [--set strong|all] [--size 40] [--seed 1]  → 写 <目录>/<组>_NN.txt（整条消息）+ manifest.json
  ingest <组> <目录> [--models a,b] [--min-conf high,mid]        → 读 <目录>/<模型>/<组>_NN.json，合并成 group_clf/1 表、按强真值评测
模型输出文件：每批一个，内容是 JSON 数组（可带围栏）。模型不是本脚本调用的——批跑由人／会话做。
"""
import argparse, json, random, sys
from pathlib import Path
sys.path.insert(0, "/home/user/open-guji-cv")
from common import *
from open_guji_cv.groups.ctx_l3 import parse_output, merge_runs
from open_guji_cv.groups.prompt_template import book_prompt_vars, build_batch_rendered as build_batch
from open_guji_cv.groups.registry import GROUPS

ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("group"); ap.add_argument("dir")
ap.add_argument("--set", default="strong"); ap.add_argument("--size", type=int, default=40); ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--models", default=""); ap.add_argument("--min-conf", default="high,mid")
a = ap.parse_args(); g = a.group; D = Path(a.dir); D.mkdir(parents=True, exist_ok=True)
spec = GROUPS[g]; prompt = Path("/home/user/open-guji-cv") / spec.config_dir / "prompt.md"

if a.cmd == "make":
    rows = [r for r in load(g) if a.set == "all" or r["gold_tier"] in STRONG]
    random.Random(a.seed).shuffle(rows)
    man = {}
    for i in range(0, len(rows), a.size):
        chunk = rows[i:i + a.size]; name = f"{g}_{i // a.size:02d}"
        cells = [dict(id=r["id"], left=window(r)[0], right=window(r)[1]) for r in chunk]
        (D / f"{name}.txt").write_text(build_batch(prompt, cells, book_prompt_vars()), encoding="utf-8")
        man[name] = [c["id"] for c in cells]
    (D / f"{g}_manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    print(g, len(rows), "格", len(man), "批")
elif a.cmd == "ingest":
    from open_guji_cv.groups.ctx_l3 import load_prompt
    meta, _ = load_prompt(prompt)
    man = json.loads((D / f"{g}_manifest.json").read_text(encoding="utf-8"))
    models = a.models.split(",") if a.models else sorted(p.name for p in D.iterdir() if p.is_dir())
    runs = {m: {} for m in models}
    for m in models:
        for name in man:
            f = D / m / f"{name}.json"
            if f.exists(): runs[m].update(parse_output(f.read_text(encoding="utf-8")))
    byid = {r["id"]: r for r in load(g)}
    ctxs = {i: window(byid[i]) for ids in man.values() for i in ids}
    mc = tuple(a.min_conf.split(","))
    t = merge_runs(g, spec.members and "".join(sorted(spec.members)), meta["ver"], runs, ctxs, mc)
    (D / f"{g}_table.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    pick = lambda r: ((t["cells"][r["id"]]["char"], t["cells"][r["id"]]["why"]) if r["id"] in t["cells"] else (None, "n/a"))
    fam = set(spec.members)
    print("模型", models, "各自完成", {m: len(runs[m]) for m in models}, "/", len(ctxs))
    for m in models:   # 单遍成绩
        s, e = score(list(byid.values()), lambda r, m=m: ((runs[m].get(r["id"], {}).get("char") if runs[m].get(r["id"], {}).get("char") in fam else None), "single"), g)
        print(" 单遍", m, {k: s[k] for k in ("n", "give", "ok", "err", "cover", "acc", "wilson_lo", "leak")})
    s, e = score([r for r in byid.values() if r["id"] in t["cells"]], pick, g)
    print("合并(全部一致才给字)", s)
    for x in e: print("  ERR", x, "票", t["cells"][x[0]]["votes"])
    import collections
    print(collections.Counter(c["why"] for c in t["cells"].values()))
