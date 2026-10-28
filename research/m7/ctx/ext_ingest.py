"""扩展字组：合并 L1 + haiku(high)，与整理本字、人裁对账，列出需复审的格。
  python ext_ingest.py <cells.jsonl> <批目录> <人裁 ids.json→字 json> <输出 decisions.jsonl>"""
import json, sys, collections
from pathlib import Path
sys.path.insert(0, "/home/user/open-guji-cv")
from open_guji_cv.groups.ctx_l3 import parse_output
cells_f, D, human_f, out = sys.argv[1:5]; D = Path(D)
human = json.load(open(human_f)); cells = {}
for l in open(cells_f, encoding="utf-8"):
    c = json.loads(l); cells[c["id"]] = c
rows = []
for g in ("wxs", "wm", "ts"):
    l1 = json.load(open(D / f"{g}_l1.json")); man = json.load(open(D / f"{g}_manifest.json")); run = {}
    for n in man:
        f = D / "haiku" / f"{n}.json"
        if f.exists(): run.update(parse_output(f.read_text(encoding="utf-8")))
    mem = set({"wxs": "戊戌戍", "wm": "未末", "ts": "土士"}[g])
    for cid, c in ((i, c) for i, c in cells.items() if c["group"] == g):
        h = run.get(cid); hv = h["char"] if h and h["char"] in mem and h.get("conf") == "high" else None
        final = l1[cid] or hv
        via = "l1" if l1[cid] else ("haiku" if hv else None)
        rows.append(dict(id=cid, group=g, ref=c["ref"], l1=l1[cid], haiku=(h or {}).get("char"), conf=(h or {}).get("conf"), why=(h or {}).get("why"),
                         final=final, via=via, human=human.get(cid), left=c["left"], right=c["right"]))
Path(out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
for g in ("wxs", "wm", "ts"):
    R = [r for r in rows if r["group"] == g]; gv = [r for r in R if r["final"]]
    print(g, "格", len(R), "给字", len(gv), f"(L1 {sum(r['via']=='l1' for r in R)}, haiku {sum(r['via']=='haiku' for r in R)})",
          "给字≠整理本", sum(r["final"] != r["ref"] for r in gv), "弃权", len(R) - len(gv))
    hh = [r for r in R if r["human"]]
    print("   人裁格", len(hh), "给字", sum(1 for r in hh if r["final"]), "给字对", sum(1 for r in hh if r["final"] == r["human"]), "给字错", [(r["id"], r["human"], r["final"]) for r in hh if r["final"] and r["final"] != r["human"]])
    print("   haiku 非high/其他/未答:", collections.Counter((r["conf"] if r["l1"] is None else None) for r in R if r["l1"] is None))
