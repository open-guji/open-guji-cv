# -*- coding: utf-8 -*-
"""版本注词表：从整理本语料派生 ``config/jiazhu/version_notes.json``。

    python scripts/build_note_lexicon.py [--corpus corpus/zongmu_wuyingdian_reference.txt]
                                         [--out config/jiazhu/version_notes.json] [--dry-run]

**永不手编**——每次重跑整份重建（确定性输出，便于 diff），与
`build_book_variants.py` 同纪律。

## 这个表是什么

《四庫全書總目》每部书的书名行形如「**書名 + N卷 + 版本注**」，版本注在刻本上
是**雙行小注**（夹注），说这部书从哪来：「浙江巡撫採進本」「內府藏本」
「永樂大典本」……全书 1,026 行、去重只有 **78 个短语**——是个**闭集**。

夹注识别难在小字样本少（字形库里小字仅 59 例）。但闭集意味着可以走**段级**
证据：把一段夹注的读序串对着词表做模糊匹配，整段一起定，不必逐字硬认。
这与库/OCR 的误差**来源独立**（文本先验 × 形状证据），可以当双信号的一路，
与 `match_ref`「文本 × 形状同源性为零」是同一个论证。

## 切法

在**最后一个**「N卷」或「無卷數」之后切。用最后一个是因为书名里也可能含卷数
（「周易本義通釋十二卷」前面还有「附錄一卷」之类）。1,026 行里 1,023 行切得动，
剩 3 行是语料本身的毛病（「書經直解十三篇內府藏本」用「篇」不用「卷」、
「元吳澄原本」是正文句子被误判、「家禮辨定寸卷」是「六卷」讹成「寸卷」）——
**不特判**，宁可漏三条也不要为个例加规则。

## count=1 的条目要当心

36 条只出现一次，其中混着整理本自己的讹字：「巡撫採浙江進本」（字序错）、
「江西撫巡採進本」（撫巡倒置）、「浙江吳王墀家藏本」（玉→王）。它们**照收**
——匹配是模糊的，多一条讹形短语不会让正确的段匹配不上，反而可能救回刻本上
本来就刻错的那一处。但 `min_count` 字段留着，下游要收紧可以只用 count≥2 的。
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"
DEFAULT_OUT = "config/jiazhu/version_notes.json"

#: 版本注的收尾词。刻本上这些都是「……本」，用后缀而不是关键词是因为
#: 前半段（机构/人名）开放得很，后半段才是闭集。
SUFFIXES = ("採進本", "家藏本", "藏本", "大典本", "進本", "刊本", "抄本",
            "寫本", "進呈本", "刻本", "通行本", "敕撰本", "原本", "舊本")
NUM = "一二三四五六七八九十百千零〇"
#: 「N卷」或「無卷數」——书名与版本注的分界
JUAN = re.compile(r"(?:[" + NUM + r"]+卷|無卷數)")
MIN_LEN, MAX_LEN = 3, 20


def derive(corpus_text: str) -> tuple[collections.Counter, list[str]]:
    """语料 → (短语计数, 切不动的行)。"""
    counts: collections.Counter = collections.Counter()
    skipped: list[str] = []
    for line in corpus_text.split("\n"):
        line = line.strip()
        if not line.endswith(SUFFIXES) or not (4 < len(line) <= 80):
            continue
        ms = list(JUAN.finditer(line))
        if not ms:
            skipped.append(line)
            continue
        phrase = line[ms[-1].end():].strip("　 \t")
        if MIN_LEN <= len(phrase) <= MAX_LEN:
            counts[phrase] += 1
        else:
            skipped.append(line)
    return counts, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = (REPO / a.corpus).read_text(encoding="utf-8")
    counts, skipped = derive(text)
    phrases = [{"text": t, "count": n, "len": len(t)}
               for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    chars = sorted({c for t in counts for c in t})
    doc = {
        "meta": {
            "what": "版本注（雙行小注）短语闭集，由 scripts/build_note_lexicon.py 从整理本派生。永不手编。",
            "corpus": a.corpus,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_lines": sum(counts.values()),
            "n_phrases": len(counts),
            "n_chars": len(chars),
            "n_skipped": len(skipped),
            "note": "count==1 的条目里混着整理本自身的讹字（巡撫採浙江進本 等），照收；"
                    "要收紧就只用 count>=2。",
        },
        "phrases": phrases,
        "chars": "".join(chars),
        "skipped": skipped,
    }
    print(f"版本注词表：行 {sum(counts.values())}，短语 {len(counts)}，字种 {len(chars)}，"
          f"未切 {len(skipped)}；单例 {sum(1 for v in counts.values() if v == 1)}")
    for p in phrases[:12]:
        print(f'  ×{p["count"]:4} {p["text"]}')
    if a.dry_run:
        return
    out = REPO / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("写入", out)


if __name__ == "__main__":
    main()
