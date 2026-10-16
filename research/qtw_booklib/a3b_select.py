"""a3b：定进库名单（用户 09-27 22:20Z：书级库只收全唐文刻例，每字可多例，簇级确认的先抽查再进）。

  GUJI_WORKSPACE=$QTW_WS python a3b_select.py <imp_dir>   → <imp_dir>/lib_keys.json

规则（先稳后多）：
1. 不进库（照记人裁事件，`no_glyph_lib=true`），逐条带原因：
   - a3_screen 两道机器闸标出的疑错格；
   - 目检拼图看出的错格（`EYEBALL`，形近字混簇：平里的乎、申里的中/巾、其里的甚、授里的投……）；
   - 整理本对齐字与人裁字不同、且两者不是异体/码位关系（`內/内`、`誌/志` 这类放过）；
   - 人裁字是简化字（`闻`）——全唐文是清刻本，多半是输入法打出来的，**待用户定**是不是「聞」。
     例外：`内`（四庫书 yaml 已按用户裁定把 內 统一成 内，同一口径）。
2. 进库（每字最多 `CAP` 例）：逐格确认 → 整理本对齐也是这个字的格（两路独立来源一致）→
   没有对齐信息的格按同字 medoid 次序补（混进簇的少数异形排在最后，先被截掉）。
"""
from __future__ import annotations

import collections
import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from qb_common import QTW_BOOKS, align_chars  # noqa: E402
from a3_reps import order_by_medoid, vec  # noqa: E402

sys.path.append(str(Path(__file__).parent.parent / "qtw_libfail"))
from a1_score_dist import rel  # noqa: E402

CAP = 30
#: 目检拼图（montage m00–m05）里看出的错格：key → 看到的字
EYEBALL = {
    "v006:9:2:22": "肉（标 内）", "v006:38:6:3": "乎（标 平）", "v006:61:6:5": "乎（标 平）",
    "v006:4:1:12": "中（标 申）", "v006:10:4:20": "巾（标 申）", "v007:97:1:14": "甚（标 其）",
    "v009:81:2:1": "疑为 三（标 二）", "v007:27:6:20": "投（标 授）",
}
SIMPLIFIED_ASK = {"闻": "聞"}
CODEPOINT_OK = {("内", "內"), ("內", "内")}


def main():
    d = Path(sys.argv[1])
    final = [json.loads(l) for l in open(d / "final.jsonl", encoding="utf-8")]
    screen = {x["key"]: x["why"] for x in json.load(open(d / "screen.json", encoding="utf-8"))["flagged"]}
    P = pickle.load(open(d / "patches.pkl", "rb"))
    A = {}
    for b in QTW_BOOKS:
        A.update(align_chars(b))
    recs = [r for r in final if r["import"] and r["act"] == "confirm"]
    out_no, by = {}, collections.defaultdict(list)
    for r in recs:
        k, ch = r["key"], r["char"]
        a = (A.get(k) or {}).get("align_char")
        why = []
        if k in screen:
            why += screen[k]
        if k in EYEBALL:
            why.append(f"目检：{EYEBALL[k]}")
        if a and a != ch and (ch, a) not in CODEPOINT_OK and not rel(ch, a):
            why.append(f"整理本对齐字「{a}」≠人裁「{ch}」")
        if ch in SIMPLIFIED_ASK:
            why.append(f"人裁字是简化字，待定是否为「{SIMPLIFIED_ASK[ch]}」")
        if why and not r.get("per_cell"):
            out_no[k] = {"char": ch, "batch": r["batch"], "cluster": r.get("cluster"), "why": why}
            continue
        tier = 0 if r.get("per_cell") else 1 if a and (a == ch or (ch, a) in CODEPOINT_OK or rel(ch, a)) else 2
        by[ch].append((tier, k))
    keep, capped = {}, 0
    for ch, xs in by.items():
        t2 = [k for t, k in xs if t == 2]
        order = [k for t, k in sorted(xs) if t < 2] + order_by_medoid(t2, {k: vec(P[k]) for k in t2})
        keep[ch] = order[:CAP]
        capped += max(0, len(order) - CAP)
    n_keep = sum(len(v) for v in keep.values())
    dist = collections.Counter(min(len(v), 10) for v in keep.values())
    res = {"n_confirm": len(recs), "n_lib": n_keep, "n_chars": len(keep), "cap": CAP,
           "n_not_in_lib_flagged": len(out_no), "n_capped": capped,
           "not_in_lib_reason": dict(collections.Counter(
               ("机器闸" if any("留一" in w or "离群" in w for w in v["why"]) else
                "目检" if any(w.startswith("目检") for w in v["why"]) else
                "简化字待定" if any("简化字" in w for w in v["why"]) else "对齐字不一致")
               for v in out_no.values())),
           "exemplars_per_char_hist(10=≥10)": dict(sorted(dist.items())),
           "chars_ge3": sum(len(v) >= 3 for v in keep.values()),
           "lib": keep, "not_in_lib": out_no}
    json.dump(res, open(d / "lib_keys.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k not in ("lib", "not_in_lib")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
