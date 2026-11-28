"""decide-bench 一键跑分（CV4，2026-11-23）：冻结快照 → guji exp 只跑第四步（关人裁）→ score.py 按书报分＋翻转清单。

用法：
  python -m open_guji_cv.eval.decide_bench.run --shard <dataset>/decide-bench/small --ws 988g3f0wsu=<史記工作区> --ws 995ejelvk0=<…> --ws siku-zongmu=<…> \
      --work <工作目录> --name <这次的名字> [--params '{"seed_admit": {"xxx": 1}}'] [--against <上次 result.jsonl>] [--books 03,vol01]

- 不给 --params：只跑现行代码（变体 A），和 --against 比出翻转清单。
- 给 --params：A（现行）与 B（A＋这些参数）都跑，B 对 A 出翻转清单。
- 快照：<工作目录>/snap/<册> 没有就 `guji products pack fetch <册> --label <bench.yaml 的 pack> --to …`，取回后核 .pack.json 的 digest。
- 工作区要先备好（册配置、书仓 code/、模型、钉版字形库、原图）：见 dataset decide-bench/README.md「备工作区」。
- 跑时去掉 GUJI_ANTHROPIC_API_KEY／GUJI_LLM_ONLINE：文意 AI 只读裁定缓存，不在线问（结果才可复现）。
"""
import re
import argparse, json, os, subprocess, sys
from pathlib import Path
import yaml
_vn = lambda v: str(int(re.search(r"\d+", str(v)).group())) if re.search(r"\d+", str(v)) else str(v)   # 册号按数值比（11-27 册号位数统一）

ap = argparse.ArgumentParser()
ap.add_argument("--shard", required=True)
ap.add_argument("--ws", action="append", required=True, help="工作区id=工作区目录")
ap.add_argument("--work", required=True)
ap.add_argument("--name", required=True)
ap.add_argument("--params")
ap.add_argument("--params-a", help="变体 A 也加这些参数（对比「同一判法本地现算 vs 读 3b」这类，A 不能是现行空参数时用；要同时给 --params）")
ap.add_argument("--against")
ap.add_argument("--books")
ap.add_argument("--jobs", default="4")
ap.add_argument("--warm-cv", help="11-25 切字拆步前的 cv 检出（如 73133d89 的 worktree）：本工作目录缓存里没有某册字块图时，先用它跑一遍补字块")
ap.add_argument("--no-warm-check", action="store_true", help="cv≥#1952（dev 17888d4）后冻结包可直接跑，不再要求字块缓存/--warm-cv")
ap.add_argument("--guji", default=str(Path(sys.executable).with_name("guji")))
a = ap.parse_args()

shard, work = Path(a.shard), Path(a.work).resolve()
bench = yaml.safe_load(open(shard / "bench.yaml"))
wss = dict(s.split("=", 1) for s in a.ws)
want = {_vn(x) for x in a.books.split(",")} if a.books else None
here = Path(__file__).resolve().parent
env = {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "GUJI_LLM_ONLINE")}
# 冻结层自己的字块缓存 <工作目录>/cache/<工作区id>/<册>（键只按格号，和动态层／日常跑批或别的书同名册混用会互相覆盖）
env.setdefault("PYTHONIOENCODING", "utf-8"); env.setdefault("HF_HUB_OFFLINE", "1"); env.setdefault("GUJI_CORPUS_DRIFT", "warn")
runs = {"A": [], "B": []}
for b in bench["books"]:
    vol = b["vol"]
    if want and _vn(vol) not in want:
        continue
    if b["ws"] not in wss:   # 没给这本书的工作区就跳过（册号跨书重名时 --books 01 只跑给了 --ws 的那本）
        continue
    ws = Path(wss[b["ws"]]).resolve()
    snap = work / "snap" / b["ws"]          # 按工作区分开：史記 01 与脉经 01 同名
    env["GUJI_CACHE_DIR"] = str(work / "cache" / b["ws"])
    pj = snap / vol / ".pack.json"
    if not pj.exists():
        subprocess.run([a.guji, "products", "pack", "fetch", vol, "-w", str(ws), "--label", b["pack"], "--to", str(snap)],
                       check=True, env=env, cwd=ws)
    got = json.load(open(pj)).get("digest")
    if got != b["digest"]:
        raise SystemExit(f"{vol} 快照 digest 不符：{got} ≠ {b['digest']}")
    cfg = {"name": f"{a.name}-{b['ws']}-{vol}", "books": [vol], "snapshot": str(snap), "from": bench["from"], "to": bench["to"],
           "pages": "all", "book_params": "keep", "match": "exact", "eval": bench["eval"],
           "variants": ({"P": {"params": json.loads(a.params_a)}, "Q": {"params": json.loads(a.params)}} if a.params_a else {"B": {"params": json.loads(a.params) if a.params else {}}})}
    y = work / f"{a.name}-{b['ws']}-{vol}.yaml"
    y.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    cmd = [a.guji, "exp", "run", str(y), "-w", str(ws), "--root", str(work / "exp"), "--jobs", a.jobs, "--no-mlflow", "--no-report"]
    if not a.params:
        cmd += ["--only", "A"]
    elif a.params_a:
        cmd += ["--only", "P", "--only", "Q"]
    if not a.no_warm_check and not (Path(env["GUJI_CACHE_DIR"]) / vol / "char_patch" / "_stamps.json").exists():
        if not a.warm_cv and not a.no_warm_check:
            raise SystemExit(f"{vol}：缓存里没有字块图。冻结包早于 11-25 切字拆步、缺 column_bands，现行代码再生不出字块；"
                             f"加 --warm-cv <拆步前的 cv 检出> 先补一遍")
        wy = work / f"{a.name}-{b['ws']}-{vol}-warm.yaml"
        wy.write_text(yaml.safe_dump({**cfg, "name": f"{a.name}-{b['ws']}-{vol}-warm"}, allow_unicode=True))
        print("▶ 补字块（拆步前代码）", vol, flush=True)
        subprocess.run([a.guji, "exp", "run", str(wy), "-w", str(ws), "--root", str(work / "exp"), "--jobs", a.jobs,
                        "--no-mlflow", "--no-report", "--only", "A"], check=True,
                       env={**env, "GUJI_WORKSPACE": str(ws), "PYTHONPATH": a.warm_cv}, cwd=ws)
        import shutil; shutil.rmtree(work / "exp" / f"{a.name}-{b['ws']}-{vol}-warm", ignore_errors=True)
    print("▶", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env={**env, "GUJI_WORKSPACE": str(ws)}, cwd=ws)
    for v, k in ((("P", "A"), ("Q", "B")) if a.params_a else (("A", "A"), ("B", "B")) if a.params else (("A", "A"),)):
        runs[k].append(f"{b['ws']}/{vol}={work / 'exp' / cfg['name'] / v / vol}")

items = str(shard / "items.jsonl")
score = [sys.executable, str(here / "score.py"), "--items", items]
outA = work / f"{a.name}-A.jsonl"
subprocess.run(score + sum([["--run", r] for r in runs["A"]], []) + ["--out", str(outA)]
               + (["--against", a.against, "--flips", str(work / f"{a.name}-A-flips.tsv")] if a.against else []), check=True)
if a.params:
    print("\n== 变体 B（A＋参数）对 A")
    subprocess.run(score + sum([["--run", r] for r in runs["B"]], []) + ["--out", str(work / f"{a.name}-B.jsonl"),
                   "--against", str(outA), "--flips", str(work / f"{a.name}-B-flips.tsv")], check=True)
