"""context-correction v2：在 v1 冻结候选上重标「金标可达性」，剔掉构造痕迹口径。

    python scripts/build_context_correction_v2.py <dataset>/context-correction

为什么是「从 v1 派生」而不是重跑 build_context_correction_dataset.py --from-seed：
重建需要 vol01 的 phase9_seed/queue.jsonl 与 ocr_carrier.jsonl，二者都在本机
output/ 里、不进 git，云端拿不到。v1 的池子本身就是 queue 里
`fuse_priors(库匹配候选, OCR top1+s2t)` 的快照（脚本里没有 extra，整理本字
没被塞进池；见 HANDOFF_D1.md 的 9/9 逐位对账），所以 v2 的候选池与 v1 逐字相同，
只做三件事：

1. `source` 改成线上真实来源的名字：`glyph`（字形库 top-k）/ `ocr`（RapidOCR
   top1 及其 s2t 扩展，v1 叫 rapidocr）。不加任何候选。
2. 每格标 `gold_reach`：glyph（金标在字形库候选里）/ ocr_only（金标只在 OCR
   候选里）/ unreachable（金标不在池里，**如实保留不剔除**）。
3. `ocr_only` 另标 `selection_biased=true`：这些格有金标，是因为「整理本字 =
   OCR 读数」才被进库协议收下（align 通道要双信号一致、human 通道多半是对
   OCR 提议点确认）；OCR 读错且库也没有的格没有金标、根本不在集里。结果是
   「金标非首选时一定是 OCR 候选」，学出来的模型会学到这个选择规则而不是
   上下文纠错。评测须与 glyph 层分开报，头条数字不含这一层。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

SRC_RENAME = {"glyph": "glyph", "rapidocr": "ocr"}


def convert_slot(sl: dict) -> dict:
    cands = [dict(c, source=SRC_RENAME.get(c["source"], c["source"]))
             for c in sl["candidates"]]
    g = sl["gold"]
    hit = [c for c in cands if c["char"] == g]
    if not hit:
        reach = "unreachable"
    elif any(c["source"] == "glyph" for c in hit):
        reach = "glyph"
    else:
        reach = "ocr_only"
    out = dict(sl, candidates=cands, gold_reach=reach,
               top1_correct=bool(cands) and cands[0]["char"] == g,
               selection_biased=(reach == "ocr_only"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="<dataset>/context-correction")
    args = ap.parse_args()
    root = Path(args.root)
    dst_root = root / "samples_v2"
    dst_root.mkdir(exist_ok=True)

    tot = Counter()
    for d in sorted((root / "samples").glob("*/")):
        f = d / "expected.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if "columns" not in data:
            continue
        cols = []
        for col in data["columns"]:
            slots = [convert_slot(sl) for sl in col["slots"]]
            for sl in slots:
                tot["n"] += 1
                tot["reach_" + sl["gold_reach"]] += 1
                tot["top1_ok"] += sl["top1_correct"]
                tot[f"{sl['origin']}_{sl['gold_reach']}"] += 1
                tot[f"{sl['origin']}_n"] += 1
                if sl["gold_reach"] != "unreachable" and not sl["top1_correct"]:
                    tot["rescuable"] += 1
                    tot["rescuable_" + sl["gold_reach"]] += 1
                for c in sl["candidates"]:
                    tot["cand_" + c["source"]] += 1
            cols.append(dict(col, slots=slots))
        out = dict(data, version=2, derived_from="samples/ (v1)",
                   pool_policy="glyph top-k ∪ OCR top1+s2t, 无金标注入; "
                               "金标不在池 = unreachable（保留）",
                   columns=cols)
        dd = dst_root / d.name
        dd.mkdir(exist_ok=True)
        (dd / "expected.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        if (d / "info.json").exists():
            (dd / "info.json").write_text(
                (d / "info.json").read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps(dict(sorted(tot.items())), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
