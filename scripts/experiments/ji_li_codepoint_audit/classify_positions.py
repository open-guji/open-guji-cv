#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, json

CORPUS = "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本/corpus/zongmu_wenyuange_wikisource.txt"
with open(CORPUS, encoding="utf-8") as f:
    lines = f.readlines()

HEAD_RE = re.compile(r"^欽定四庫全書總目(卷[首一二三四五六七八九十百]+)$")
heads = []  # (line_no, label)
for i, ln in enumerate(lines, start=1):
    m = HEAD_RE.match(ln.strip())
    if m:
        heads.append((i, m.group(1)))

# 覆盖表：volNN -> 这一册包含的卷（正文标题里写的），只用于报告，不用于精确判定
VOL_COVERAGE = {
    "vol01": ["卷首一"],
    "vol02": ["卷首二"],
    "vol03": ["卷四", "卷五"],
    "vol04": ["卷六", "卷七"],
    "vol05": ["卷八", "卷九"],
    "vol06": ["卷十", "卷十一"],
    "vol07": ["卷十二", "卷十三"],
    "vol08": ["卷十四"],
    "vol09": ["卷十五", "卷十六", "卷十七", "卷十八"],
    "vol10": ["卷十九", "卷二十"],
}
juan_to_vol = {}
for v, js in VOL_COVERAGE.items():
    for j in js:
        juan_to_vol[j] = v

def juan_of_line(line_no):
    """返回 (juan_label, juan_start_line, juan_end_line_exclusive) 或 None（在第一个标题之前）"""
    if not heads or line_no < heads[0][0]:
        return None
    for idx, (ln, label) in enumerate(heads):
        nxt = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines) + 1
        if ln <= line_no < nxt:
            return label, ln, nxt
    return None

def context(line_no, col_in_line, radius=8):
    ln = lines[line_no - 1].rstrip("\n")
    lo = max(0, col_in_line - radius)
    hi = min(len(ln), col_in_line + radius + 1)
    before = ln[lo:col_in_line]
    ch = ln[col_in_line]
    after = ln[col_in_line + 1:hi]
    if col_in_line - radius < 0 and line_no > 1:
        need = radius - col_in_line
        prev = lines[line_no - 2].rstrip("\n")
        before = (prev[-need:] if len(prev) >= need else prev) + before
    if col_in_line + radius + 1 > len(ln) and line_no < len(lines):
        need = (col_in_line + radius + 1) - len(ln)
        nxt = lines[line_no].rstrip("\n")
        after = after + nxt[:need]
    return before, ch, after

def find_char(ch):
    hits = []
    for i, ln in enumerate(lines, start=1):
        col = 0
        while True:
            col = ln.find(ch, col)
            if col == -1:
                break
            hits.append((i, col))
            col += 1
    return hits

import random
random.seed(20260928)

report = {}
for ch, is_sample in [("即", False), ("歷", False), ("卽", True), ("厯", True)]:
    hits = find_char(ch)
    total = len(hits)
    chosen = hits
    if is_sample:
        chosen = sorted(random.sample(hits, min(5, total)))
    entries = []
    for line_no, col_in_line in chosen:
        b, c, a = context(line_no, col_in_line)
        j = juan_of_line(line_no)
        if j is None:
            juan_label = "现代影印说明前言（非原书内容，卷首一之前）"
            vol = None
        else:
            juan_label, jstart, jend = j
            vol = juan_to_vol.get(juan_label)
        entries.append({
            "line": line_no, "col_in_line": col_in_line,
            "juan": juan_label, "vol": vol,
            "context": f"{b}【{c}】{a}",
        })
    report[ch] = {"total": total, "entries": entries}

print(json.dumps(report, ensure_ascii=False, indent=2))
with open("/tmp/claude-0/-home-user/ed6dc98a-63ea-503e-a815-955ea868b72c/scratchpad/classified_positions.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
