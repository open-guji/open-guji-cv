"""上下文表作否决：已放行字与表的高把握判定不同 → 列出（overview#428）。"""
import json, sys
from collections import Counter, defaultdict
sys.path.insert(0, "research/near_form")
from ctx_table import Table, GROUPS
DOM = ['/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本/corpus/zongmu_wenyuange_wikisource.txt']
EXT = ['corpus/external/daizhige_ru_yi.txt', 'corpus/external/daizhige_zhaoling.txt']
USE_DOM = len(sys.argv) > 4 and sys.argv[4] == 'dom'
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
PUR, MN = float(sys.argv[2]) if len(sys.argv) > 2 else 0.98, 5
out = []
for g in GROUPS:
    tab = Table(g, DOM if USE_DOM else [], EXT)
    stat = defaultdict(Counter)
    for r in rows:
        if r["group"] != g: continue
        cur = r["gold"] if (r["gold"] and r["gold_src"] != "witness_agree") else (r["char"] if r["admit"] and r["char"] in GROUPS[g] else None)
        if cur is None: continue
        src = "gold" if (r["gold"] and r["gold_src"] != "witness_agree") else "adm:" + str(r["channel"])
        ex = tab.block_of(r["left"], r["right"]) if USE_DOM else None
        ch, why = tab.decide(r["left"][-2:], r["right"][:2], PUR, MN, ex)
        key = (g, r["book"], src.split(":")[0])
        stat[key]["格"] += 1
        if ch:
            stat[key]["表定"] += 1
            if ch != cur:
                stat[key]["不同"] += 1
                out.append(dict(id=r["id"], g=g, book=r["book"], cur=cur, src=src, tab=ch, why=why, word=r["word"], ref=r["ref"], crop=r["crop"], gold=r["gold"], gold_src=r["gold_src"]))
for k in sorted(stat): print(*k, dict(stat[k]))
json.dump(out, open(sys.argv[3] if len(sys.argv) > 3 else "/dev/null", "w"), ensure_ascii=False, indent=1)
for o in out: print(o["id"], o["g"], "现", o["cur"], o["src"], "表", o["tab"], o["why"], o["word"], "ref", o["ref"])
