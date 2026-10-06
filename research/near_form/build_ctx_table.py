"""从外部语料（daizhige，与四庫总目无重叠）建己已巳上下文决策表 → config/near_form_ctx_jys.json。
只存 n≥3 的键（运行时 min_n 不得小于 3）。用法：python research/near_form/build_ctx_table.py"""
import json, sys, hashlib
sys.path.insert(0, "research/near_form")
from ctx_table import Table
EXT = ["corpus/external/daizhige_ru_yi.txt", "corpus/external/daizhige_zhaoling.txt"]
t = Table("jys", [], EXT)
keys = {}
for (ab, l, r), c in t.ext.items():
    if sum(c.values()) >= 3:
        keys[f"{ab[0]}{ab[1]}|{l}|{r}"] = [c["己"], c["已"], c["巳"]]
out = {"_doc": "己已巳上下文决策表：键 'ab|前a字|后b字'，值 [己,已,巳] 计数。由 research/near_form/build_ctx_table.py 从 corpus/external 建（overview#428）。",
       "order": "己已巳", "min_count": 3, "corpus": {p: hashlib.sha256(open(p, 'rb').read()).hexdigest()[:12] for p in EXT},
       "keys": dict(sorted(keys.items()))}
json.dump(out, open("config/near_form_ctx_jys.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(len(keys))
