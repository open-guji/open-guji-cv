"""形近对上下文消歧测试集：从已积累的裁决里抽出形近家族字位。

问题（用户 2026-08-26 提）：入/人、日/曰、論/諭 这几对反复出现，字形层
再准也难分——「这个时候要借助上下文」。两条路可试：n-gram 语言模型，和
大模型直接读上下文。本脚本只负责**建集**，不做任何判决、不碰答案。

金标口径与三道泄漏防线（这一集最要紧的东西）：

1. **金标只取人裁**（``provenance == "human"``）。人是看着字形定的，与
   LM、与整理本都无关，是唯一对三条路都中立的真值。自动进库的字多数由
   align（整理本）锚定，拿它当金标去考一个**在整理本上训练的 LM**，
   等于让考生带着答案进考场。
2. **题面挖空两处**：列内 OCR 转写的目标位，以及**整理本参照的同一位**。
   后者是实测出来的坑——``align.char is None``（管线没锚上）并不代表
   整理本那一位是空的，实测 43 条难档里仍有 12 条参照文本直接写着答案。
   两列按位等长对齐（161/161 实测），所以同一个下标挖两次即可。
3. **按整理本是否给出答案分档**。参照位就是金标的那些题，整理本本来就
   能锚定，属送分档，管线走 align 通道即可；真正要量的是参照位**不是**
   金标时（整理本有脱字/异文/根本没覆盖），上下文还救不救得回来。

题面是二选一，随机基线 50%。但类别先验极不平衡（諭 32 : 論 15、
日 28 : 曰 1），**多数类基线必须一并报**，否则「准确率八成」毫无意义。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.match import NEVER_MATCH_FAMILIES

MASK = "△"
GAP = "·"          # 整理本参照里表示「这一位没有对应」的占位

PARTNER: dict[str, set[str]] = {}
for _a, _b in NEVER_MATCH_FAMILIES:
    PARTNER.setdefault(_a, set()).add(_b)
    PARTNER.setdefault(_b, set()).add(_a)


def _mask_at(text: str | None, pos: int) -> str | None:
    if not text or not (0 <= pos < len(text)):
        return text
    return text[:pos] + MASK + text[pos + 1:]


def build(book_dir: Path, min_ctx: int) -> list[dict]:
    queue = book_dir / "phase9_seed" / "queue.jsonl"
    cases: list[dict] = []
    for line in queue.open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("provenance") != "human":
            continue
        if row.get("status") not in ("confirmed", "confirmed_label_only"):
            continue
        gold = row.get("decided_char")
        if not gold or gold not in PARTNER:
            continue
        ctx = row.get("context")
        if not ctx or ctx.get("pos") is None:
            continue
        col, ref, pos = ctx.get("col_ocr") or "", ctx.get("col_ref"), ctx["pos"]
        if not (0 <= pos < len(col)) or len(col) < min_ctx:
            continue

        # 整理本在这一位给的是什么（分档用；随后就挖掉）
        ref_at = ref[pos] if (ref and 0 <= pos < len(ref)) else None
        tier = "easy_ref_gives_answer" if ref_at == gold else "hard_ref_silent"

        match = row.get("match") or {}
        cands = {c: v for c, v in (match.get("candidates") or [])}
        for other in sorted(PARTNER[gold]):
            cases.append({
                "id": row["instance_id"],
                "pair": "/".join(sorted((gold, other))),
                "options": sorted((gold, other)),
                "gold": gold,
                "tier": tier,
                "ref_at_pos": ref_at,
                "align_anchored": (row.get("align") or {}).get("char") is not None,
                "ocr_char": (row.get("ocr") or {}).get("char"),
                "ocr_prob": (row.get("ocr") or {}).get("prob"),
                "shape_top": match.get("char") or (
                    (match.get("candidates") or [[None]])[0][0]),
                "shape_cov_gold": cands.get(gold),
                "shape_cov_other": cands.get(other),
                "pos": pos,
                "col_masked": _mask_at(col, pos),
                "col_ref_masked": _mask_at(ref, pos),
                "prev_ocr": ctx.get("prev_ocr"),
                "prev_ref": ctx.get("prev_ref"),
                "next_ocr": ctx.get("next_ocr"),
                "next_ref": ctx.get("next_ref"),
            })
    return cases


def main() -> None:
    ap = argparse.ArgumentParser(description="建形近对上下文消歧集")
    ap.add_argument("book", help="书输出目录 output/<book>/")
    ap.add_argument("--out", required=True, help="输出 json")
    ap.add_argument("--min-context", type=int, default=6,
                    help="列内至少这么多字才收（太短的上下文没信息）")
    args = ap.parse_args()

    cases = build(Path(args.book), args.min_context)
    hard = [c for c in cases if c["tier"] == "hard_ref_silent"]

    # 题面自检：答案不许出现在任何给出的字段里的目标位上
    for c in cases:
        assert c["col_masked"][c["pos"]] == MASK, c["id"]
        r = c["col_ref_masked"]
        if r and c["pos"] < len(r):
            assert r[c["pos"]] == MASK, c["id"]

    Path(args.out).write_text(json.dumps(
        {"mask": MASK, "cases": cases}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    print(f"共 {len(cases)} 题（全部人裁金标）"
          f"；送分档 {len(cases) - len(hard)}、真难档 {len(hard)}")
    for name, sub in (("真难档", hard),
                      ("送分档", [c for c in cases
                                  if c["tier"] != "hard_ref_silent"])):
        print(f"\n{name} 按形近对：")
        for pk, n in Counter(c["pair"] for c in sub).most_common():
            g = Counter(c["gold"] for c in sub if c["pair"] == pk)
            major = g.most_common(1)[0][1] / n
            print(f"  {pk:8s} {n:3d}  金标 "
                  + "、".join(f"{k}×{v}" for k, v in g.most_common())
                  + f"  多数类基线 {major:.0%}")
    print(f"\n写出 {args.out}")


if __name__ == "__main__":
    main()
