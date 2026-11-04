"""对一批格所在的页，用现行代码重跑 seed_admit（不调 API），和原产物逐格比。

    GUJI_WORKSPACE=… GUJI_PRODUCTS_DIR=… python replay_cmp.py <ids.txt> <备份目录> <diff.jsonl> [--why 理由]

先把原页产物备份到 <备份目录>/<vol>/pXXXX*.json（已有不覆盖），再跑 `guji step seed_admit <vol> --pages … --force`，
最后输出每个变了的格：{id, old:{char,admit,channel}, new:{…}, target: 是不是清单里的格}。"""
import glob, json, os, shutil, subprocess, sys
from collections import defaultdict
ids = [l.strip() for l in open(sys.argv[1]) if l.strip()]
bak, outp = sys.argv[2], sys.argv[3]
why = sys.argv[sys.argv.index("--why") + 1] if "--why" in sys.argv else "A24 r4 replay"
prod, ws = os.environ["GUJI_PRODUCTS_DIR"], os.environ["GUJI_WORKSPACE"]
env = {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")}
pages = defaultdict(set)
for i in ids:
    v, pg = i.split(":")[:2]; pages[v].add(int(pg))
tgt = set(ids)
res = []
for v, pgs in sorted(pages.items()):
    for pg in pgs:
        for f in glob.glob(f"{prod}/{v}/seed_admit/p{pg:04d}*.json"):
            d = f"{bak}/{v}"; os.makedirs(d, exist_ok=True)
            if not os.path.exists(f"{d}/{os.path.basename(f)}"):
                shutil.copy(f, d)
    pl = ",".join(str(p) for p in sorted(pgs))
    r = subprocess.run(["guji", "step", "seed_admit", v, "--pages", pl, "--force", "--allow-cv-mismatch", "--why", why, "-w", ws],
                       env=env, capture_output=True, text=True)
    if r.returncode:
        print(v, "FAIL", r.stdout[-300:], r.stderr[-300:], file=sys.stderr)
    for pg in pgs:
        for f in glob.glob(f"{bak}/{v}/p{pg:04d}*.json"):
            old = {c["id"]: c for col in json.load(open(f))["seed_admit"]["columns"] for c in col["chars"]}
            nf = f"{prod}/{v}/seed_admit/{os.path.basename(f)}"
            new = {c["id"]: c for col in json.load(open(nf))["seed_admit"]["columns"] for c in col["chars"]}
            for i, c in new.items():
                o = old.get(i)
                if o and (o["char"], o["admit"]) != (c["char"], c["admit"]):
                    res.append({"id": i, "target": i in tgt, "old": [o["char"], o["admit"], o.get("channel")], "new": [c["char"], c["admit"], c.get("channel")]})
    print(v, "done", file=sys.stderr)
with open(outp, "w") as fh:
    for x in res:
        fh.write(json.dumps(x, ensure_ascii=False) + "\n")
print(len(res), "changed;", sum(x["target"] for x in res), "targets")
