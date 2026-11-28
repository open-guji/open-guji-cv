"""decide-bench 动态层（CV4，2026-11-26）：各册**现行 main 包**＋现行代码，关人裁重跑第四步，按金标原图框对格打分。

用法：python -m open_guji_cv.eval.decide_bench.dyn --shard <dataset>/decide-bench/small --shard <dataset>/decide-bench/large \
         --ws 988g3f0wsu=<史記工作区> --ws 995ejelvk0=<…> --ws siku-zongmu=<…> --work <目录> --name <名字> [--books 03,005] [--against <上次 dyn 结果.jsonl>]

和 run.py 的区别：不取 bench.yaml 钉的冻结包，而是取每册现在标 main 的包（`pack fetch` 不带 --label）；
切分可能已经变了，所以打分用 `score.py --rebind`，金标原图框按 IoU 对现行格（对不上记「缺格」）。
每册用了哪个包记在 <work>/<name>-packs.json，结果在 <work>/<name>.jsonl。
"""
import re
import argparse, json, os, subprocess, sys
from pathlib import Path
import yaml
_vn = lambda v: str(int(re.search(r"\d+", str(v)).group())) if re.search(r"\d+", str(v)) else str(v)   # 册号按数值比（11-27 册号位数统一）

ap = argparse.ArgumentParser()
ap.add_argument("--shard", action="append", required=True)
ap.add_argument("--ws", action="append", required=True)
ap.add_argument("--work", required=True)
ap.add_argument("--name", required=True)
ap.add_argument("--books")
ap.add_argument("--against")
ap.add_argument("--jobs", default="4")
ap.add_argument("--warm-cv", help="11-25 切字拆步前的 cv 检出：包里没有 column_bands（各书 main 包多是钉的 cv 0.7.x 线）时，先用它跑一遍补字块")
ap.add_argument("--guji", default=str(Path(sys.executable).with_name("guji")))
a = ap.parse_args()
work = Path(a.work).resolve(); work.mkdir(parents=True, exist_ok=True)
wss = dict(s.split("=", 1) for s in a.ws)
want = {_vn(x) for x in a.books.split(",")} if a.books else None
here = Path(__file__).resolve().parent
env = {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "GUJI_LLM_ONLINE")}
env.setdefault("PYTHONIOENCODING", "utf-8"); env.setdefault("HF_HUB_OFFLINE", "1"); env.setdefault("GUJI_CORPUS_DRIFT", "warn")
books, items = [], work / f"{a.name}-items.jsonl"
with open(items, "w") as out:
    for sh in a.shard:
        bench = yaml.safe_load(open(Path(sh) / "bench.yaml"))
        books += [b for b in bench["books"] if not want or _vn(b["vol"]) in want]
        out.write(open(Path(sh) / "items.jsonl").read())
packs, parts = {}, []
cache = work / "cache"                       # 动态层自己的字块缓存，不和冻结层（工作区 cache/）混用：键只按格号，混用会互相覆盖
env["GUJI_CACHE_DIR"] = str(cache)
done = work / f"{a.name}-done"; done.mkdir(exist_ok=True)
for b in books:
    vol, ws = b["vol"], Path(wss[b["ws"]]).resolve()
    part = done / f"{b['ws']}-{vol}.jsonl"
    if part.exists():                        # 断点续跑：跑完的册跳过
        parts.append(part); packs[f"{b['ws']}/{vol}"] = json.loads((done / f"{b['ws']}-{vol}.pack.json").read_text()); continue
    snap = work / "snap" / a.name
    subprocess.run([a.guji, "products", "pack", "fetch", vol, "-w", str(ws), "--to", str(snap), "--force"],
                   check=True, env={**env, "GUJI_WORKSPACE": str(ws)}, cwd=ws)
    pj = json.load(open(snap / vol / ".pack.json"))
    packs[f"{b['ws']}/{vol}"] = {"label": pj.get("label"), "digest": pj.get("digest")}
    cfg = {"name": f"{a.name}-{vol}", "books": [vol], "snapshot": str(snap), "from": "align_ref", "to": "seed_admit",
           "pages": "all", "book_params": "keep", "match": "exact", "eval": {"use_human_verdicts": False},
           "variants": {"B": {"params": {}}}}
    y = work / f"{a.name}-{vol}.yaml"
    y.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    cmd = [a.guji, "exp", "run", str(y), "-w", str(ws), "--root", str(work / "exp"), "--jobs", a.jobs,
           "--no-mlflow", "--no-report", "--only", "A"]
    print("▶", vol, packs[f"{b['ws']}/{vol}"]["label"], flush=True)
    if not (snap / vol / "column_band").exists() and not (snap / vol / "column_bands").exists():
        if not a.warm_cv:
            raise SystemExit(f"{vol}：包里没有 column_bands（早于 11-25 切字拆步），现行代码再生不出字块；加 --warm-cv")
        wy = work / f"{a.name}-{vol}-warm.yaml"
        wy.write_text(yaml.safe_dump({**cfg, "name": f"{a.name}-{vol}-warm"}, allow_unicode=True))
        print("▶ 补字块（拆步前代码）", vol, flush=True)
        subprocess.run([a.guji, "exp", "run", str(wy), "-w", str(ws), "--root", str(work / "exp"), "--jobs", a.jobs,
                        "--no-mlflow", "--no-report", "--only", "A"], check=True,
                       env={**env, "GUJI_WORKSPACE": str(ws), "PYTHONPATH": a.warm_cv}, cwd=ws)
        import shutil; shutil.rmtree(work / "exp" / f"{a.name}-{vol}-warm", ignore_errors=True)
    subprocess.run(cmd, check=True, env={**env, "GUJI_WORKSPACE": str(ws)}, cwd=ws)
    import shutil
    res = work / "exp" / cfg["name"] / "A" / vol
    keep = work / "keep" / f"{b['ws']}-{vol}"           # 只留打分要的两步，其余连同快照、缓存删掉（每册几百 MB）
    for st in ("seed_admit", "row_segment"):
        shutil.copytree(res / st, keep / st, dirs_exist_ok=True)
    subprocess.run([sys.executable, str(here / "score.py"), "--items", str(items), "--rebind", "--max-missing", "1.0", "--out", str(part),
                    "--run", f"{b['ws']}/{vol}={keep}"], check=True, env=env)
    (done / f"{b['ws']}-{vol}.pack.json").write_text(json.dumps(packs[f"{b['ws']}/{vol}"], ensure_ascii=False))
    for d in (work / "exp" / cfg["name"], snap / vol, cache / vol):
        shutil.rmtree(d, ignore_errors=True)
    parts.append(part)
(work / f"{a.name}-packs.json").write_text(json.dumps(packs, ensure_ascii=False, indent=1))
out = work / f"{a.name}.jsonl"
out.write_text("".join(p.read_text() for p in parts))
print("\n== 动态层合计")
subprocess.run([sys.executable, str(here / "score.py"), "--items", str(items), "--rebind", "--max-missing", "1.0", "--out", "/dev/null"]
               + sum([["--run", f"{p.stem.rsplit('-', 1)[0]}/{p.stem.rsplit('-', 1)[1]}={work / 'keep' / p.stem}"] for p in parts], [])
               + (["--against", a.against, "--flips", str(work / f"{a.name}-flips.tsv")] if a.against else []), check=True)
