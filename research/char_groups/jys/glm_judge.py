# -*- coding: utf-8 -*-
"""GLM 独立判官（overview#443 段 3）：盲判前后各 30 字，与 Claude 子代理两遍判断相互独立。
云端代理已接 open.bigmodel.cn（不用 key）。用法：glm_judge.py <model> <ids.txt|labels.json> <out.json> [--max N]
输出 {id: {"char":..,"raw":..}}；断点续跑（已有的 id 跳过）；并发 3。"""
import json, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common

URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
PROMPT = ("下面是《四庫全書總目》刻本里一处文字，目标位用【？】表示，它是「己」「已」「巳」三个字之一（刻本三字刻得几乎一样，只能按文意判）。\n"
          "判法：干支（X己丑、癸巳）天干用己、地支用巳；虚词「而已、已經、已久、業已、不得已」是已；表示自己（自己、克己、以己意、參以己見）是己。\n"
          "只回答一个字：己、已 或 巳。\n\n前文：{l}\n【？】\n后文：{r}")


def ask(model, left, right):
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT.format(l=left, r=right)}],
            "max_tokens": 2000, "temperature": 0.01}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    for k in range(5):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=120))
            m = d["choices"][0]["message"]
            txt = (m.get("content") or "").strip()
            c = [ch for ch in txt if ch in "己已巳"]
            return (c[-1] if c and len(txt) < 40 else (c[0] if c else None)), txt[:80]
        except Exception as e:
            err = str(e)[:80]; time.sleep(4 + 6 * k)
    return None, "ERR " + err


if __name__ == "__main__":
    model, src, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    ids = list(json.load(open(src))) if src.endswith(".json") else Path(src).read_text().split()
    if mx: ids = ids[:mx]
    items = {x["id"]: x for x in common.load_items()}
    res = json.load(open(out)) if out.exists() else {}
    todo = [i for i in ids if i not in res]

    def one(i):
        l, r = common.ctx(items[i])
        c, raw = ask(model, l.replace("□", "？"), r.replace("□", "？"))
        return i, {"char": c, "raw": raw}
    with ThreadPoolExecutor(1) as ex:
        for k, (i, v) in enumerate(ex.map(one, todo), 1):
            res[i] = v
            if k % 10 == 0: out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(len(res), "done")
