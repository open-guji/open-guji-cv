"""文意路与量横路合并：文意有字用文意；文意弃权时按量横取字（弃权带内仍弃权）；两路不一致打 conflict 旗。
用法：python research/m7/bars/merge_ctx_bars.py <m7-ext 目录> <输出 json> [弃权带半宽，缺省 0.1]
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import bars

R = Path(sys.argv[1]); out = sys.argv[2]; h = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1
res = []
for c in json.load(open(R / "cells_with_crops.json")):
    r = bars.ratio(str(R / c["crop"]))
    a, b = ("土", "士") if c["group"] == "ts" else ("未", "末")
    g = None if r is None or abs(r - 1) < h else (a if r > 1 else b)
    ctx = c["final"]
    if ctx and g and ctx != g: via, f = "ctx", "conflict"
    elif ctx: via, f = "ctx", None
    elif g: via, f = "bars", "bars_only"
    else: via, f = None, None
    res.append(dict(id=c["id"], group=c["group"], ctx=ctx, bars=g, ratio=r, final=ctx or g, via=via, flag=f))
json.dump(res, open(out, "w"), ensure_ascii=False, indent=0)
import collections
print(collections.Counter((x["group"], x["via"], x["flag"]) for x in res))
