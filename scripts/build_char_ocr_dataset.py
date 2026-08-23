"""构建 char-ocr 测试集：(冻结图块, 参考整理本金标字)。

    PYTHONPATH=. python scripts/build_char_ocr_dataset.py <book_out_dir> \
        --corpus corpus/xxx.txt --dataset ../open-guji-dataset --shard book9

## 这个集测的是「输出」还是「能力」

测**输出**——「这一块图上是哪个字」。金标本该挂在图像上，所以本脚本
把图块像素**拷进数据集**（`crops/`），而不是留一个 `page:col:idx`
指针。这一步是有意为之：`char-segmentation/instances` 挂在编号上，
上游一重切就全部失效，本仓库已经重标 8 轮。图块一旦拷贝，这个集就
不再随切分漂移。

代价是另一种陈旧：图块是**某一版切分**产出的，切分变好之后，集里的
图块比生产环境的更差。所以 `metadata.json` 里必须记下上游 commit，
并在切分有实质改进后重建本集（重建，不是重标——金标是自动对齐出来的）。

## 金标从哪来

参考整理本，逐实例落标的规则见 `open_guji_cv/clustering/align_gold.py`。
一句话：金标的**取值**与任何 OCR 引擎无关，但**哪些位置能进集**取决于
转写能不能锚定——于是本集偏向容易的页面，准确率是乐观的。这条必须
写进 `known_limitation`，别拿本集的数字当全书真实字准确率。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git_rev(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()[:12]
    except Exception:
        return "unknown"


def safe_name(instance_id: str) -> str:
    """instance_id → 文件名。`:` 在 Windows 上非法，换成 `_`。"""
    return instance_id.replace(":", "_")


def main() -> None:
    ap = argparse.ArgumentParser(description="构建 char-ocr 测试集")
    ap.add_argument("book_out_dir", help="册输出目录，如 output/book9")
    ap.add_argument("--corpus", required=True, help="参考整理本 txt")
    ap.add_argument("--dataset", required=True, help="open-guji-dataset 根目录")
    ap.add_argument("--shard", required=True, help="分片标识，一般用册名")
    ap.add_argument("--sample", default=None,
                    help="样本目录名，默认 001-<shard>")
    ap.add_argument("--split", default="test", choices=["train", "test"])
    ap.add_argument("--variants", default=None,
                    help="异体字表（默认 config/charset/variants.tsv，"
                         "无则回落 config/dicts/variants.tsv）")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO))
    from open_guji_cv.clustering.align_gold import (MAX_REPLACE_RUN, MIN_FLANK,
                                                    gold_for_book)
    from open_guji_cv.clustering.variants import VariantMap

    vpath = Path(args.variants) if args.variants else None
    if vpath is None:
        auto = REPO / "config" / "charset" / "variants.tsv"
        vpath = auto if auto.exists() else None
    vm = VariantMap.load(vpath)

    book_dir = Path(args.book_out_dir)
    pages, _ = gold_for_book(book_dir, args.corpus)

    sample_dir = Path(args.dataset) / "char-ocr" / "samples" / \
        (args.sample or f"001-{args.shard}")
    crops = sample_dir / "crops"
    if crops.exists():
        shutil.rmtree(crops)     # 重跑先清目录：留下的孤儿图块会让人对着过期图片标注
    crops.mkdir(parents=True, exist_ok=True)

    patch_root = book_dir / "phase4_chars"
    items: list[dict] = []
    n_variant = 0
    for pg in pages:
        for it in pg.items:
            crop = safe_name(it.instance_id) + ".png"
            src = patch_root / it.patch_path
            if not src.exists():
                continue
            shutil.copyfile(src, crops / crop)
            is_variant = vm.semantic(it.gold) != it.gold
            n_variant += is_variant
            items.append({
                "instance_id": it.instance_id,
                "crop": crop,
                "char": it.gold,
                "label_origin": "align",
                "is_variant": is_variant,
                "column_id": f"{it.instance_id.rsplit(':', 1)[0]}",
                "slot_index": it.idx,
                # 冻结当次转写只为分析（哪些字被谁改错），**不是金标**
                "transcribed_at_build": it.transcribed,
                "align_opcode": it.opcode,
            })

    anchored = [p for p in pages if p.anchored]
    n_inst = sum(p.n_instances for p in pages)
    n_excl = sum(p.n_uncertain for p in pages)
    freq = Counter(i["char"] for i in items)

    expected = {
        "source_item": args.shard,
        "pipeline_version": git_rev(REPO),
        "label_origin": "align",
        "shard_id": args.shard,
        "split": args.split,
        "corpus": str(Path(args.corpus).as_posix()),
        "items": items,
    }
    (sample_dir / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=1), encoding="utf-8")

    info = {
        "id": sample_dir.name,
        "placeholder": False,
        "source": "open-guji-cv " + str(book_dir.as_posix()),
        "source_item": args.shard,
        "description": f"{args.shard} 逐实例单字金标，由参考整理本对齐生成",
        "tags": ["align", "body", args.shard],
        "build_command": (
            "PYTHONPATH=. python scripts/build_char_ocr_dataset.py "
            f"{book_dir.as_posix()} --corpus {args.corpus} "
            f"--dataset <dataset> --shard {args.shard}"),
        "upstream": {
            "cv_commit": git_rev(REPO),
            "phase4_chars": str((patch_root).as_posix()),
            "note": "图块像素已冻结进 crops/；切分有实质改进后应重建本集",
        },
        "coverage": {
            "pages_total": len(pages),
            "pages_anchored": len(anchored),
            "instances_total": n_inst,
            "gold_items": len(items),
            "excluded_uncertain": n_excl,
            "gold_rate": round(len(items) / n_inst, 4) if n_inst else 0.0,
            "align_opcode": dict(Counter(i["align_opcode"] for i in items)),
            "accept_rule": {
                "max_replace_run": MAX_REPLACE_RUN,
                "min_flank": MIN_FLANK,
            },
        },
        "label_stats": {
            "distinct_chars": len(freq),
            "variant_items": n_variant,
            "top_chars": "".join(c for c, _ in freq.most_common(20)),
            "hapax": sum(1 for c in freq if freq[c] == 1),
        },
    }
    (sample_dir / "info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({"sample": str(sample_dir), **info["coverage"],
                      **info["label_stats"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
