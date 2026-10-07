"""合并标签：用户裁决（harvest.py 出的 jsonl）优先于整理看图（labels_vol0X.jsonl）。
用法：python merge_labels.py <labels_vol0X.jsonl> <user.jsonl> <out.jsonl>"""
import json, sys
lab = {}
for l in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(l); d["src"] = "整理看图"; lab[d["cell"]] = d
n = 0
for l in open(sys.argv[2], encoding="utf-8"):
    d = json.loads(l); d["src"] = "用户"; lab[d["cell"]] = d; n += 1   # 用户裁决整条替换，不带整理看图的正字
# 口径 A（忠实原刻，异体码位放行算错）：标了 ok 却给出与放行字不同的正字，按 wrong 记（保留原 v 在 v_raw）。
for d in lab.values():
    if d.get("v") == "ok" and d.get("char") and d["char"] != d.get("shown"):
        d["v_raw"], d["v"] = "ok", "wrong"
open(sys.argv[3], "w", encoding="utf-8").write("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in lab.values()))
print(len(lab), "其中用户", n)
