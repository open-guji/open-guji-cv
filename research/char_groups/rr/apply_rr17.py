"""把 17 格审查页的裁决（dataset review/rr17_verdicts.jsonl）并进 rr/items.jsonl：人裁入 A 档（src user_review_rr17，排最前），看不清记 X_unclear。
建集脚本 build.py 需要工作区/快照，这里只就地打补丁（幂等）。"""
import json, os, sys
DS = os.environ.get("GUJI_DATASET", "/home/user/open-guji-dataset") + "/char-groups"
V = {}
for l in open(f"{DS}/review/rr17_verdicts.jsonl", encoding="utf-8"):
    x = json.loads(l); V[x["id"]] = x
rows = [json.loads(l) for l in open(f"{DS}/rr/items.jsonl", encoding="utf-8")]
n = 0
for r in rows:
    v = V.get(r["id"])
    if not v: continue
    r["golds"] = [g for g in r["golds"] if g["src"] != "user_review_rr17"]
    if v["verdict"] == "unclear":
        r["golds"].append({"char": None, "tier": "X_unclear", "src": "user_review_rr17", "note": "看不清"}); n += 1; continue
    r["golds"].insert(0, {"char": v["verdict"].replace("other:", ""), "tier": "A_human", "src": "user_review_rr17", "note": "rr17 第二轮"})
    old = r.get("gold")
    r["gold"], r["gold_tier"], r["label_origin"], r["gold_src"] = r["golds"][0]["char"], "A_human", "human", "user_review_rr17"
    strong = {g["char"] for g in r["golds"] if g["tier"] in ("A_human", "B_vision")}
    r["gold_conflict"] = len(strong) > 1
    n += 1
with open(f"{DS}/rr/items.jsonl", "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("patched", n)
