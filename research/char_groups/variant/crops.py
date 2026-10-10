"""取异体组字块图：python crops.py <items.jsonl> <crops_dir> <prod_snapshot_root>  （读工作区 cache 的 char_patch，只读）"""
import json, os, subprocess, sys, glob
items, out, snap = sys.argv[1:4]
WS = os.environ.get("GUJI_WORKSPACE", "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本")
os.makedirs(out, exist_ok=True)
keys = {}
for l in open(items, encoding="utf-8"):
    it = json.loads(l); b, p = it["book"], it["page"]
    if (b, p) not in keys:
        f = f"{snap}/{b}/cell_shrink/p{p:04d}.json"
        keys[(b, p)] = {x["id"]: x["patch_key"] for c in json.load(open(f))["char_index"]["columns"] for x in c["chars"]} if os.path.exists(f) else {}
n = 0
for l in open(items, encoding="utf-8"):
    it = json.loads(l); k = keys[(it["book"], it["page"])].get(it["id"])
    if not k: continue
    dst = f"{out}/{it['id'].replace(':', '_')}.png"
    if os.path.exists(dst): continue
    r = subprocess.run([sys.executable, "-m", "open_guji_cv", "cache", "get", "--book", it["book"], "--kind", "char_patch", "--key", k, "--out", dst, "-w", WS], capture_output=True, text=True)
    n += os.path.exists(dst)
print("crops", n)
