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

## 换一套书怎么办

**收尾词与「书名/注文分界」是书级约定，不是通用规则**（用户 2026-09-06 定的口径：
依赖文字可以，但必须「这套书用、下套书不用」）。所以两者都放 `books/<id>.yaml`
的 `jiazhu:` 段，用 `--book <id>` 取：

    python scripts/build_note_lexicon.py --book vol02

没配 `jiazhu.note_suffixes` 的书**直接报错退出**，不退回默认值硬跑——
那些「採進本 / 家藏本」是《四庫全書總目》的格式，套到别的书上只会静默出一堆错词条。
不带 `--book` 时才用模块里的兜底值，那条路只留给临时试跑。

**注意夹注的探测本身与文字无关**：`utils/jiazhu_split` 走的是墨迹跨度、缝中心、
段连缀，纯几何，换书照常工作。文字先验只用在「认字」这一层（本词表 + 判据 F 的分型）。

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

#: 兜底值——**只在没给 `--book` 时用**，且只对《四庫全書總目》成立。
#: 正途是 `--book <id>` 从 `Book.jiazhu` 取，见模块头。
DEFAULT_SUFFIXES = ("採進本", "家藏本", "藏本", "大典本", "進本", "刊本", "抄本",
                    "寫本", "進呈本", "刻本", "通行本", "敕撰本", "原本", "舊本")
NUM = "一二三四五六七八九十百千零〇"
#: 书名与版本注的分界（可被 Book.jiazhu.title_split 覆盖）
DEFAULT_TITLE_SPLIT = r"(?:[" + NUM + r"]+卷|無卷數)"
MIN_LEN, MAX_LEN = 3, 20


def derive(corpus_text: str, suffixes: tuple[str, ...] = DEFAULT_SUFFIXES,
           title_split: str = DEFAULT_TITLE_SPLIT,
           max_len: int = MAX_LEN) -> tuple[collections.Counter, list[str]]:
    """语料 → (短语计数, 切不动的行)。`suffixes` / `title_split` 来自 Book.jiazhu。"""
    counts: collections.Counter = collections.Counter()
    skipped: list[str] = []
    juan = re.compile(title_split)
    suffixes = tuple(suffixes)
    for line in corpus_text.split(chr(10)):
        line = line.strip()
        if not line.endswith(suffixes) or not (4 < len(line) <= 80):
            continue
        ms = list(juan.finditer(line))
        if not ms:
            skipped.append(line)
            continue
        phrase = line[ms[-1].end():].strip("　 	")
        if MIN_LEN <= len(phrase) <= max_len:
            counts[phrase] += 1
        else:
            skipped.append(line)
    return counts, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="", help="从 Book.jiazhu 取后缀/分界（推荐）")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    suffixes, title_split, max_len = DEFAULT_SUFFIXES, DEFAULT_TITLE_SPLIT, MAX_LEN
    if a.book:
        import sys as _sys
        _sys.path.insert(0, str(REPO))
        from open_guji_cv.core.book import load_book
        jz = load_book(a.book).jiazhu or {}
        if not jz.get("note_suffixes"):
            raise SystemExit(
                f"{a.book} 的 books/*.yaml 里没有 jiazhu.note_suffixes——"
                "版本注的收尾词是**书级约定**，不给就没法派生词表。"
                "别退回默认值硬跑：那是《四庫全書總目》的格式，换书必错。")
        suffixes = tuple(jz["note_suffixes"])
        title_split = jz.get("title_split") or DEFAULT_TITLE_SPLIT
        max_len = int(jz.get("note_max_len") or MAX_LEN)

    text = (REPO / a.corpus).read_text(encoding="utf-8")
    counts, skipped = derive(text, suffixes, title_split, max_len)
    phrases = [{"text": t, "count": n, "len": len(t)}
               for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    chars = sorted({c for t in counts for c in t})
    doc = {
        "meta": {
            "what": "版本注（雙行小注）短语闭集，由 scripts/build_note_lexicon.py 从整理本派生。永不手编。",
            "corpus": a.corpus,
            "book": a.book or "(默认约定，未指定 --book)",
            "suffixes": list(suffixes),
            "title_split": title_split,
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
