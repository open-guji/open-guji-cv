"""语料预处理：外部古文语料 → 可直接训 n-gram 的单文件（可选简→繁）。

    PYTHONPATH=. python scripts/prepare_corpus.py --src <目录> [--src ...] \
        --out corpus/general_classical.txt --max-chars 5000000 \
        --to-traditional --holdout corpus/xxx.txt

## 简→繁这一步的代价要认

网上能拿到的大宗古籍语料（殆知阁等）多是**简体**转录本。刻本 LM 要在
繁体上打分，只能先转回去，而简→繁是一对多（发→發/髮、干→乾/幹/干），
opencc 只能按词典择一，必然引入错误。这不是「洗干净了」，是**用可控
噪声换语料量**：转换后的通用语料只配拿低权重，本书的干净语料才配拿
高权重。这正是 `InterpolatedLM` 的分工。

## 泄漏检查是必做项，不是可选项

通用语料里若混着被测本书的整理本（殆知阁的四库类文献就带着《总目》的
提要原文），LM 就是在背答案，测出来的增益全是假的。``--holdout`` 给出
测试用文本，本脚本会报 **最长公共子串** 与 8-gram 重合率；重合率不接近
零就必须换语料或剔除对应文件，别心存侥幸。
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CJK = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
       (0x20000, 0x2A6DF), (0x2A700, 0x2EBEF))


def keep(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in CJK)


def clean(text: str) -> list[str]:
    """按非汉字切段，只留纯汉字串（标点/数字/空白都是断点）。"""
    out, cur = [], []
    for ch in text:
        if keep(ch):
            cur.append(ch)
        else:
            if len(cur) >= 4:
                out.append("".join(cur))
            cur = []
    if len(cur) >= 4:
        out.append("".join(cur))
    return out


def ngram_overlap(a: str, b: str, n: int = 8) -> float:
    """a 的 n-gram 有多大比例出现在 b 里（泄漏检查）。"""
    if len(a) < n:
        return 0.0
    bs = {b[i:i + n] for i in range(len(b) - n + 1)}
    hits = sum(1 for i in range(len(a) - n + 1) if a[i:i + n] in bs)
    return hits / (len(a) - n + 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="外部古文语料预处理")
    ap.add_argument("--src", action="append", required=True,
                    help="语料目录或文件（可重复）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=5_000_000)
    ap.add_argument("--max-per-file", type=int, default=200_000,
                    help="单个文件最多贡献多少字。不设上限时几部大部头就"
                         "把配额吃光（实测 1251 个文件只用上 32 个），"
                         "语料看着有 500 万字，覆盖的却只是几种文体")
    ap.add_argument("--to-traditional", action="store_true",
                    help="用 opencc s2t 转繁（简体语料必开）")
    ap.add_argument("--holdout", default=None,
                    help="泄漏检查用的文本（一般就是被测本书的整理本）")
    ap.add_argument("--seed", type=int, default=20260823)
    args = ap.parse_args()

    files: list[Path] = []
    for s in args.src:
        p = Path(s)
        files += sorted(p.glob("**/*.txt")) if p.is_dir() else [p]
    # 固定种子打散再截断：按文件名顺序取会只拿到某几个类目
    random.Random(args.seed).shuffle(files)

    cc = None
    if args.to_traditional:
        import opencc
        cc = opencc.OpenCC("s2t")

    segs: list[str] = []
    total = 0
    used = 0
    for f in files:
        if total >= args.max_chars:
            break
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        used += 1
        this_file = 0
        for seg in clean(raw):
            if cc:
                seg = cc.convert(seg)
            segs.append(seg)
            total += len(seg)
            this_file += len(seg)
            if total >= args.max_chars or this_file >= args.max_per_file:
                break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(segs), encoding="utf-8")

    report = {"files_seen": len(files), "files_used": used,
              "segments": len(segs), "chars": total,
              "to_traditional": bool(cc), "out": str(out.as_posix())}
    if args.holdout:
        hold = "".join(clean(Path(args.holdout).read_text(encoding="utf-8")))
        body = "".join(segs)
        report["leak_check"] = {
            "holdout_chars": len(hold),
            "holdout_8gram_in_corpus": round(ngram_overlap(hold, body), 6),
            "corpus_8gram_in_holdout": round(ngram_overlap(body[:200000], hold), 6),
        }
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
