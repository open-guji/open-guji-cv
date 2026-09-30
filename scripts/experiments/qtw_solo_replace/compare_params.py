"""几套 seed_admit 书级参数跑出来的产物对比（overview#155）。

  python compare_params.py <products 根>:<名> [<products 根>:<名> ...] --truth v006_truth.jsonl --book v006

每套报：放行 / 待审率、match_solo 与 match_replace 放行数，以及按 `v006_truth.jsonl`
（目检＋列级放宽锚定出的真形）量的错数——**原来两通道的格不论改后走哪条通道都算**，
关掉一条通道后这些格可能被 ref_lib 等别的通道接住，错不错要跟着格走。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json


def load(root: str, book: str) -> dict:
    out = {}
    for f in glob.glob(f"{root}/{book}/seed_admit/p*.json"):
        x = json.load(open(f, encoding="utf-8"))
        x = x[next(iter(x))]
        for c in x["columns"]:
            for r in c["chars"]:
                out[r["id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--truth", required=True)
    ap.add_argument("--book", default="v006")
    a = ap.parse_args()
    T = [json.loads(l) for l in open(a.truth, encoding="utf-8")]
    for spec in a.runs:
        root, name = spec.rsplit(":", 1)
        S = load(root, a.book)
        n = len(S)
        adm = sum(r["admit"] for r in S.values())
        ch = collections.Counter(r["channel"] for r in S.values() if r["admit"])
        res = {"放行": adm, "放行率%": round(adm / n * 100, 2),
               "待审": n - adm, "待审率%": round((n - adm) / n * 100, 2),
               "match_solo": ch["match_solo"], "match_replace": ch["match_replace"]}
        for chan in ("match_solo", "match_replace"):
            c = collections.Counter()
            for t in T:
                if t["channel"] != chan:
                    continue
                r = S[t["id"]]
                if not r["admit"]:
                    c["落审"] += 1
                elif t["ok"] is None and t["truth"] is None and chan == "match_replace":
                    c["放行·存疑"] += 1
                elif r["char"] != t["truth"]:
                    c["放行·错"] += 1
                else:
                    c["放行·对"] += 1
                if r["admit"]:
                    c["→" + r["channel"]] += 1
            res[f"原{chan}格"] = dict(c)
        print(name, json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
