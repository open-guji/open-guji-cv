"""字组基线：现行 seed_admit 产物在每组每册上的成绩（overview#437，G0）。

只数 `core=True` 的格（放行字/整理本/证人/库首位/真值任一在组里）。每组每册、正文/非正文分开：
  格数；机器放行（admit 且 channel≠human）；人裁（channel=human，已审）；待审（未放行）；送审率＝(人裁+待审)/格数；
  机器放行格里有强真值（人裁/看图）的几格、其中错几格（真值≠放行字），按通道细分；
  强真值格上各来源首选字（整理本/库首位/上下文/ji_yi_si 规则/OCR/5-b）的错率（分子/分母，来源没给组内字不计）。
弱真值（证人一致）对 match_ref 是循环的，**不拿来数放行错**，只报覆盖。

用法：python research/char_groups/baseline.py <dataset>/char-groups   → 写 <组>/baseline.json，并打印 markdown 表
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import GROUPS, SETS, SPLIT, STRONG, TIER_WEAK  # noqa: E402

ROOT = sys.argv[1]
SOURCES = ("ref", "lib", "ctx", "jys_rule", "ocr", "rare")


def pick(r, src):
    if src == "ref":
        return r["ref"] or r["coord_ref"]
    if src == "lib":
        return r["lib"][0][0] if r["lib"] else None
    if src == "ctx":
        return r["ctx"] or (r["ctx_ranked"][0][0] if r["ctx_ranked"] else None)
    if src == "jys_rule":
        return (r["ji_yi_si"] or {}).get("char")
    if src == "ocr":
        return r["ocr"][0][0] if r["ocr"] and r["ocr"][0] else None
    if src == "rare":
        return r["rare"][0][0] if r["rare"] else None


def body_of(r):
    return "body" if r["page_type"] == "body" else "nonbody"


def new_cell():
    return {"cells": 0, "admit_machine": 0, "human_channel": 0, "pending": 0,
            "admit_with_strong_truth": 0, "admit_wrong": 0, "admit_wrong_ids": [],
            "admit_with_weak_truth": 0, "by_channel": defaultdict(lambda: [0, 0, 0])}


def finish(c):
    c["sent_review"] = c["human_channel"] + c["pending"]
    c["review_rate"] = round(c["sent_review"] / c["cells"], 4) if c["cells"] else None
    c["by_channel"] = {k: {"admit": v[0], "with_strong_truth": v[1], "wrong": v[2]}
                       for k, v in sorted(c["by_channel"].items())}
    return c


def main():
    out_all = {}
    for gk in GROUPS:
        rows = [json.loads(l) for l in open(f"{ROOT}/{gk}/items.jsonl", encoding="utf-8")]
        rows = [r for r in rows if r["admit"] is not None]           # vol01（无快照）不进基线
        fam = SETS[gk]
        tab = defaultdict(new_cell)
        src_err = defaultdict(lambda: [0, 0])
        peri = defaultdict(int)
        for r in rows:
            if not r["core"]:
                peri[r["book"]] += 1
                continue
            for key in ((r["book"], body_of(r)), (r["book"], "all")):
                c = tab[key]
                c["cells"] += 1
                strong = r["gold_tier"] in STRONG and r["gold"] is not None
                if r["channel"] == "human":
                    c["human_channel"] += 1
                elif r["admit"]:
                    c["admit_machine"] += 1
                    ch = c["by_channel"][r["channel"] or "?"]
                    ch[0] += 1
                    if strong:
                        c["admit_with_strong_truth"] += 1
                        ch[1] += 1
                        if r["gold"] != r["char"]:
                            c["admit_wrong"] += 1
                            ch[2] += 1
                            c["admit_wrong_ids"].append(f"{r['id']} {r['char']}→{r['gold']}")
                    elif r["gold_tier"] == TIER_WEAK:
                        c["admit_with_weak_truth"] += 1
                else:
                    c["pending"] += 1
            if r["gold_tier"] in STRONG and r["gold"] in fam:
                for src in SOURCES:
                    x = pick(r, src)
                    if x is None or x not in fam:
                        continue
                    e = src_err[(r["book"], src)]
                    e[1] += 1
                    e[0] += x != r["gold"]
        res = {"group": gk, "members": GROUPS[gk]["members"],
               "doc": "现行 seed_admit 产物（快照见 ../_build_info.json）在本组 core 格上的成绩；"
                      "admit_wrong 只在有强真值（人裁/看图）的放行格上数，是下界。",
               "by_book": {}, "source_error_on_strong_truth": {}, "peripheral_cells": dict(peri)}
        for (bk, part), c in sorted(tab.items()):
            res["by_book"].setdefault(bk, {"split": SPLIT[bk]})[part] = finish(c)
        for (bk, src), (e, n) in sorted(src_err.items()):
            res["source_error_on_strong_truth"].setdefault(bk, {})[src] = {"wrong": e, "n": n}
        with open(f"{ROOT}/{gk}/baseline.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        out_all[gk] = res
    print_md(out_all)


def print_md(out_all):
    for gk, res in out_all.items():
        print(f"\n### {gk}（{res['members']}）\n")
        print("| 册 | 划分 | 格数 | 机器放行 | 放行有强真值 | 放行错 | 人裁 | 待审 | 送审率 | 非正文格 |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for bk, d in res["by_book"].items():
            a = d["all"]
            nb = d.get("nonbody", {}).get("cells", 0)
            print(f"| {bk} | {d['split']} | {a['cells']} | {a['admit_machine']} | {a['admit_with_strong_truth']} | "
                  f"{a['admit_wrong']} | {a['human_channel']} | {a['pending']} | {100 * a['review_rate']:.1f}% | {nb} |")
        print("\n强真值格上各来源首选字错率（错/计）：\n")
        print("| 册 | " + " | ".join(SOURCES) + " |")
        print("|---|" + "---|" * len(SOURCES))
        for bk, d in res["source_error_on_strong_truth"].items():
            print(f"| {bk} | " + " | ".join(f"{d[s]['wrong']}/{d[s]['n']}" if s in d else "—" for s in SOURCES) + " |")
        wrong = [x for d in res["by_book"].values() for x in d["all"]["admit_wrong_ids"]]
        if wrong:
            print("\n放行错：" + "；".join(wrong))


if __name__ == "__main__":
    main()
