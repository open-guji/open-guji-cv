"""字组成员字在语料里的搭配统计（overview#437，G0）→ <dataset>/char-groups/<组>/context_stats.json。

两类语料分开存，不混：
  external  cv 仓 `corpus/external/daizhige_{ru_yi,zhaoling}.txt`（殆知阁 儒藏易类/诏令奏议，`scripts/prepare_corpus.py`
            简→繁转换，已对《總目》做过 holdout 泄漏检查，见 doc/design/charset_and_lm.md §三）。N1 的己已巳表就用它。
            ⚠ 简→繁一对多会带噪声；己已巳在简体里本身也常被 OCR/录入混写，计数只当参考。
  in_domain 工作区 `corpus/siku_daizhige.txt`（文淵閣《總目》逐列本）、`corpus/zongmu_wuyingdian_reference.txt`（殿本整理本）。
            **与被测书同书**：拿来做词表/规则时必须分块留出（N1 `ctx_table.py` 的做法），否则等于背答案。
每个成员字：总次数；前 1/前 2/后 1/后 2 字的 top-K 搭配；以及「纯」搭配表——同一前字或后字在组内各字上的分布，
n≥5 且最多那个字占比≥0.95 的键（给词组匹配起步用，不是规则）。
用法：python research/char_groups/corpus_stats.py <dataset>/char-groups
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import GROUPS, SETS  # noqa: E402

ROOT = sys.argv[1]
CV = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WS = glob.glob("/home/user/guji-workspace/96mid1ogzk-*")[0]
CORPORA = {
    "external": [f"{CV}/corpus/external/daizhige_ru_yi.txt", f"{CV}/corpus/external/daizhige_zhaoling.txt"],
    "in_domain": [f"{WS}/corpus/siku_daizhige.txt", f"{WS}/corpus/zongmu_wuyingdian_reference.txt"],
}
TOPK = 60
PUNCT = set("，。、；：？！「」『』（）《》〈〉·　 \t<>|#@")


def lines(paths):
    for p in paths:
        for line in open(p, encoding="utf-8"):
            if line.startswith("#"):
                continue
            yield "".join(ch for ch in line.strip() if ch not in PUNCT)


def stats(paths, fam):
    tot = Counter()
    ctx = {pos: defaultdict(Counter) for pos in ("l1", "l2", "r1", "r2")}
    for s in lines(paths):
        for i, ch in enumerate(s):
            if ch not in fam:
                continue
            tot[ch] += 1
            if i >= 1:
                ctx["l1"][s[i - 1]][ch] += 1
            if i >= 2:
                ctx["l2"][s[i - 2:i]][ch] += 1
            if i + 1 < len(s):
                ctx["r1"][s[i + 1]][ch] += 1
            if i + 2 < len(s):
                ctx["r2"][s[i + 1:i + 3]][ch] += 1
    per_char = {}
    for ch in sorted(fam):
        per_char[ch] = {"n": tot[ch]}
        for pos, tab in ctx.items():
            c = Counter({k: v[ch] for k, v in tab.items() if v[ch]})
            per_char[ch][pos] = c.most_common(TOPK)
    pure = {}
    for pos, tab in ctx.items():
        keep = []
        for k, c in tab.items():
            n = sum(c.values())
            if n < 5:
                continue
            ch, m = c.most_common(1)[0]
            if m / n >= 0.95:
                keep.append([k, ch, m, n])
        keep.sort(key=lambda x: -x[3])
        pure[pos] = keep[:400]
    return per_char, pure


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def main():
    for gk, g in GROUPS.items():
        fam = SETS[gk]
        out = {"group": gk, "members": g["members"],
               "doc": "成员字在语料里的前后字搭配。external＝与《總目》无重叠的殆知阁语料；in_domain＝《總目》本身，"
                      "用时必须分块留出。l1/l2＝前 1/2 字，r1/r2＝后 1/2 字。pure＝组内分布纯（n≥5、占比≥0.95）的键："
                      "[键, 字, 该字次数, 总次数]。由 open-guji-cv research/char_groups/corpus_stats.py 生成。",
               "corpora": {}}
        for name, paths in CORPORA.items():
            per_char, pure = stats(paths, fam)
            out["corpora"][name] = {"files": {os.path.relpath(p, CV) if p.startswith(CV) else "guji-workspace:" +
                                              os.path.relpath(p, os.path.dirname(WS)): sha(p) for p in paths},
                                    "per_char": per_char, "pure": pure}
            print(gk, name, {ch: per_char[ch]["n"] for ch in per_char}, {k: len(v) for k, v in pure.items()})
        with open(f"{ROOT}/{gk}/context_stats.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
