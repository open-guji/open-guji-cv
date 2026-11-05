"""用真实产物页回放 `_vis_ruling_pass`：看 src-1 裁定的窗口键能否在产物上命中（A24 2026-11-03）。
用法：python replay_pass.py <feedback目录(含 rulings/)> <工作区> <out.tsv>   需要 GUJI_DATA_TOKEN_READ。"""
import csv, json, os, shutil, subprocess, sys, collections
from concurrent.futures import ThreadPoolExecutor
from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.products.kinds.recog import PageAdmit, PageAlignRef
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _vis_ruling_pass

fb, ws, out = sys.argv[1:4]
GUJI = os.environ.get("GUJI", "guji")
env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}   # guji 子进程用已装的版本（PYTHONPATH 指向 dev 工作树时列包输出格式可能不同）
env.update(GUJI_DATA_TOKEN=os.environ["GUJI_DATA_TOKEN_READ"], GUJI_CORPUS_DRIFT="warn")
store = RulingStore(fb)
want = {}
for e in store.log.iter_all(raw=True):
    want[e.payload["cell"]] = e.payload["char"]
byvol = collections.defaultdict(set)
for c in want: byvol[c.split(":")[0]].add(int(c.split(":")[1]))

def run(v):
    import time
    for _ in range(6):                     # 列包偶尔空（限流），重试
        L = [x for x in subprocess.run([GUJI, "products", "pack", "list", v, "-w", ws], capture_output=True, text=True, env=env).stdout.splitlines() if x.startswith("★")]
        if L: break
        time.sleep(5)
    lab = L[0].split("\t")[0].split("/")[-1]
    tmp = f"/home/user/prod2/r_{v}"
    subprocess.run([GUJI, "products", "pack", "fetch", v, "-w", ws, "--label", lab, "--to", tmp], capture_output=True, env=env)
    P = f"{tmp}/{v}" if os.path.isdir(f"{tmp}/{v}") else tmp
    res = []
    for p in sorted(byvol[v]):
        pa = PageAdmit.model_validate(json.load(open(f"{P}/seed_admit/p{p:04d}.json"))["seed_admit"])
        try:
            al = PageAlignRef.model_validate(json.load(open(f"{P}/align_ref/p{p:04d}.json"))["align_ref"])
            amap = {c.id: (c.align_char, c.align_op) for c in al.chars} if al.anchored else {}
        except FileNotFoundError:
            amap = {}
        before = {r.id: (r.admit, r.char) for c in pa.columns for r in c.chars}
        _vis_ruling_pass(SeedAdmitParams(db_path="x"), pa.columns, amap, store)
        for c in pa.columns:
            for r in c.chars:
                if r.id in want:
                    res.append((r.id, before[r.id][0], r.channel == "vis_ruling", r.char if r.channel == "vis_ruling" else "", want[r.id], (not r.admit) and "src_code_conflict" in (r.doubts or [])))
    shutil.rmtree(tmp, ignore_errors=True)
    return res
with ThreadPoolExecutor(5) as ex: R = [x for L in ex.map(run, sorted(byvol)) for x in L]
with open(out, "w") as f:
    f.write("格号\t回放前已放行\t本通道放行\t放出的字\t裁定字\t被降审\n")
    for r in R: f.write("\t".join(map(str, r)) + "\n")
print(len(R), "cells; lifted", sum(1 for r in R if r[2]), "; wrong char", sum(1 for r in R if r[2] and r[3] != r[4]), "; already admitted", sum(1 for r in R if r[1]))

print("demoted", sum(1 for r in R if r[5]))
