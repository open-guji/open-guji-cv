"""形近字组普查：从已有人裁/校勘事件与整理本字频，统计各字对的出现情况（不重标、不跑模型）。
用法：python research/m7/census/group_census.py <工作区> <open-guji-dataset> [最小条数=3]
证据来源（都是已有数据）：
  collate    工作区 feedback/events 里 collate_verdict 的 pair（OCR 与整理本不一致、人裁过的）
  shape≠reading  confirm 事件里 刻形(shape) 与 读法(reading) 不同
  pairflag   confirm 事件带 pair 标记
  ref-mismatch   dataset ref-mismatch：人录刻本字 ≠ 整理本对位字
  confusable-ctx dataset confusable-context：设计题，不反映自然频率
字频：工作区 corpus/zongmu_wuyingdian_reference.txt（殿本整理本）。
⚠ 事件是「人看过的格」，偏向难例，不等于全书总数；只用来排序，不当绝对数。
"""
import collections, glob, json, sys

ws, ds = sys.argv[1], sys.argv[2]
minn = int(sys.argv[3]) if len(sys.argv) > 3 else 3
up = lambda a, b: "".join(sorted((a, b)))
ev = collections.defaultdict(collections.Counter)
for f in glob.glob(ws + "/feedback/events/*.jsonl"):
    for l in open(f, encoding="utf-8"):
        try:
            e = json.loads(l)
        except ValueError:
            continue
        p = e["payload"]
        pr = p.get("pair")
        if e["kind"] == "collate_verdict" and pr and len(pr) == 2 and pr[0] != pr[1]:
            ev[up(*pr)]["collate"] += 1
        elif e["kind"] == "confirm" and p.get("v") == "confirm" and len(p.get("shape") or "") == 1 \
                and len(p.get("reading") or "") == 1 and p["shape"] != p["reading"]:
            ev[up(p["shape"], p["reading"])]["shape≠reading"] += 1
        elif e["kind"] == "confirm" and pr and len(pr) == 2 and pr[0] != pr[1]:
            ev[up(*pr)]["pairflag"] += 1
for l in open(ds + "/ref-mismatch/items.jsonl", encoding="utf-8"):
    x = json.loads(l)["expected"]
    if x.get("char") and x.get("ref_char") and x["char"] != x["ref_char"]:
        ev[up(x["char"], x["ref_char"])]["ref-mismatch"] += 1
for l in open(ds + "/confusable-context/items.jsonl", encoding="utf-8"):
    p = json.loads(l)["input"]["case"].get("pair")
    if p and "/" in p:
        a, b = p.split("/")[:2]
        ev[up(a, b)]["confusable-ctx"] += 1
ref = open(glob.glob(ws + "/corpus/zongmu_wuyingdian_reference.txt")[0], encoding="utf-8").read()
cnt = collections.Counter(ref)
print(f"整理本 {len(ref)} 字；字对 {len(ev)} 个，下列为事件条数 ≥{minn}\n")
print("| 字对 | 事件合计 | 各字整理本字频 | 来源 |\n|---|---|---|---|")
for k, v in sorted(ev.items(), key=lambda kv: -sum(kv[1].values())):
    if sum(v.values()) >= minn:
        print(f"| {k} | {sum(v.values())} | {'/'.join(f'{c}:{cnt[c]}' for c in k)} | {dict(v)} |")
