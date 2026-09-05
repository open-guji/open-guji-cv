"""char-ocr 评测：在冻结图块上量各引擎的 top1 / top5 / 异体字子集。

    PYTHONPATH=. python scripts/eval_char_ocr.py ../open-guji-dataset/char-ocr \
        [--engines rapidocr,rapidocr-raw] [--out report.json]

## 三件必须一起报的事

1. **可达性上界**。识别引擎的字表覆盖不到的字，排序再好也出不来。
   本脚本对每个引擎单算 `charset_ceiling`：金标字里有多少落在
   「引擎字表 ∪ 简→繁扩展 ∪ 异体字扩展」之内。top1 与这个上界的
   差才是**排序还能捞回来的部分**；直接看 top1 会把「字表不够」
   误诊成「排序不好」。
2. **分子分母**。比值单独看会骗人（切分变好→缺陷基数变小→误报占比
   反而升高，看着像退步）。所有比值都连着 n/N 一起打印。
3. **分层**。按 `align_opcode` 分开报：`equal` 是建集当时转写就对了的
   位置，`replace` 是当时错了的位置。合成一个数字会把「本来就会的」
   和「本来不会的」搅在一起——后者才是改进空间所在。
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_samples(root: Path) -> list[tuple[Path, dict]]:
    out = []
    for d in sorted((root / "samples").glob("*/")):
        exp = d / "expected.json"
        if not exp.exists():
            continue
        data = json.loads(exp.read_text(encoding="utf-8"))
        if not data.get("items") or data["items"][0].get("char") is None:
            continue          # 占位样本
        out.append((d, data))
    return out


def load_items_v2(root: Path) -> list[tuple[str, dict]]:
    """统一信封的 `items.jsonl`（scripts/build_char_ocr_gold.py 建的）→ (字块路径, item)。
    item 键与旧 samples 布局对齐：char / is_variant / align_opcode，另带 reading / label_origin。"""
    f = root / "items.jsonl"
    if not f.exists():
        return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        it = json.loads(ln)
        if it.get("status", "active") != "active":
            continue
        ex = it.get("expected") or {}
        if not ex.get("char") or "items" in ex:
            continue          # 占位骨架
        out.append(((it.get("input") or {}).get("patch", ""),
                    {"char": ex["char"], "reading": ex.get("reading"),
                     "is_variant": bool(ex.get("is_variant")),
                     "align_opcode": ex.get("align_opcode", "?"),
                     "label_origin": ex.get("label_origin", it.get("label_origin", "?"))}))
    return out


def reachable_set(base: set[str], vm) -> set[str]:
    """引擎字表 → 候选管线实际够得到的字集合（简→繁 + 异体字两跳扩展）。"""
    import sys
    sys.path.insert(0, str(REPO))
    from open_guji_cv.clustering.candidates import _load_s2t
    reach = set(base)
    for simp, forms in _load_s2t().items():
        if simp in base:
            reach.update(forms)
    for c in list(reach):
        reach.update(vm.variants_of(vm.semantic(c)))
    return reach


def engine_charset(spec: str) -> set[str]:
    if spec.startswith("rapidocr"):
        from rapidocr_onnxruntime import RapidOCR
        return {c for c in RapidOCR().text_rec.postprocess_op.character
                if len(c) == 1}
    return set()      # 未知引擎：不报上界，好过报一个假的


def rate(n: int, d: int) -> str:
    return f"{n}/{d} = {n / d:.2%}" if d else f"{n}/0 = -"


def main() -> None:
    ap = argparse.ArgumentParser(description="char-ocr 评测")
    ap.add_argument("dataset", help="char-ocr 数据集目录")
    ap.add_argument("--engines", default="rapidocr")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None, help="报告写到哪（默认 <dataset>/report.json）")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO))
    import cv2
    from open_guji_cv.clustering.ocr_bench import make_engine
    from open_guji_cv.clustering.variants import VariantMap

    # 语义层默认表（auto + 手工叠加，variant_strategy.md §3.4）；旧的 config/charset/variants.tsv
    # 只用 Unihan、建于关系图之前，不再采用
    vm = VariantMap.load()

    root = Path(args.dataset)
    items: list[tuple[str, dict]] = load_items_v2(root)      # (crop 绝对路径, item)
    samples: list = []
    if not items:
        samples = load_samples(root)
        for d, data in samples:
            for it in data["items"]:
                items.append((str(d / "crops" / it["crop"]), it))
    if not items:
        print("没有可用样本（只有占位骨架？先跑 scripts/build_char_ocr_gold.py）")
        return
    if args.limit:
        items = items[:args.limit]

    patches = []
    for path, _ in items:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        patches.append(img)
    n_missing = sum(1 for p in patches if p is None)

    gold = [it["char"] for _, it in items]
    report = {
        "dataset": str(root.as_posix()),
        "n_samples": len(samples),
        "n_items": len(items),
        "n_crops_missing": n_missing,
        "distinct_gold": len(set(gold)),
        "engines": {},
    }

    for spec in [s.strip() for s in args.engines.split(",") if s.strip()]:
        eng = make_engine(spec)
        t0 = time.time()
        preds = [eng.recognize(p) if p is not None else [] for p in patches]
        dt = time.time() - t0

        base = engine_charset(spec)
        reach = reachable_set(base, vm) if base else None

        strata: dict[str, Counter] = {}
        for (path, it), pred, g in zip(items, preds, gold):
            for key in ("all", f"opcode:{it['align_opcode']}",
                        "variant" if it["is_variant"] else "common",
                        f"origin:{it.get('label_origin', '?')}"):
                c = strata.setdefault(key, Counter())
                c["n"] += 1
                c["top1"] += bool(pred and pred[0] == g)
                c["top5"] += g in pred[:5]
                if reach is not None:
                    c["reachable"] += g in reach

        out: dict = {"chars_per_sec": round(len(items) / dt, 1)}
        for key, c in sorted(strata.items()):
            e = {"n": c["n"],
                 "top1": round(c["top1"] / c["n"], 4),
                 "top1_n": c["top1"],
                 "top5": round(c["top5"] / c["n"], 4),
                 "top5_n": c["top5"]}
            if reach is not None:
                e["charset_ceiling"] = round(c["reachable"] / c["n"], 4)
                e["charset_ceiling_n"] = c["reachable"]
            out[key] = e
        if base:
            out["engine_charset_size"] = len(base)
            out["reachable_charset_size"] = len(reach)
        report["engines"][eng.name] = out

        a = out["all"]
        print(f"\n[{eng.name}]  {a['n']} 条")
        print(f"  top1           {rate(a['top1_n'], a['n'])}")
        print(f"  top5           {rate(a['top5_n'], a['n'])}")
        if "charset_ceiling_n" in a:
            print(f"  字表可达上界   {rate(a['charset_ceiling_n'], a['n'])}"
                  f"   ← top1 与它的差 = 排序还能捞回来的部分")
        for key in sorted(out):
            if key.startswith(("opcode:", "origin:")) or key in ("variant", "common"):
                e = out[key]
                print(f"  {key:16s} n={e['n']:5d}  top1 {e['top1']:.2%}  "
                      f"top5 {e['top5']:.2%}")

    dest = Path(args.out) if args.out else root / "report.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"\n→ {dest}")


if __name__ == "__main__":
    main()
