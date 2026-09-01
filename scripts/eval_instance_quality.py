"""评测管线对切分缺陷的自检能力（char-segmentation/instances）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_guji_cv.clustering.instance_quality import (evaluate_self_detection,
                                                      format_report,
                                                      load_dataset)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="数据集目录（含 expected.json）")
    ap.add_argument("--out", default=None, help="报告 JSON 路径")
    ap.add_argument("--with-intrusion", action="store_true",
                    help="把 crop_quality.detect_intrusion 的侵入码并入 flags "
                         "（它归确定层：版面线成因明确，下游可直接剥）")
    args = ap.parse_args()

    gold = load_dataset(Path(args.dataset) / "expected.json")
    books = {g.book for g in gold}
    flags: dict[str, list[str]] = {}
    for book in books:
        p = Path("output") / book / "phase4_chars" / "index.jsonl"
        if not p.exists():
            print(f"缺少 {p}，请先跑 chars")
            return
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            # 键要带册名：数据集收了两册之后，只用 page:col:idx 会撞车
            flags[f"{book}/{r['page']}:{r['col']}:{r['idx']}"] = \
                r.get("flags") or []

    if args.with_intrusion:
        import cv2

        from open_guji_cv.clustering.crop_quality import detect_intrusion
        patches = Path(args.dataset) / "patches"
        n_added = 0
        for g in gold:
            p = patches / f"{g.book}_{g.page}_{g.col}_{g.idx}.png"
            if not p.exists():
                continue
            im = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if im is None:
                continue
            codes = detect_intrusion(im)
            if codes:
                # 归一到既有确定层码名（rule_bar / frame_bars），保持
                # CERTAIN_FLAGS 单一事实源
                mapped = {"rule_bar" if c.startswith("rule_bar") else "frame_bars"
                          for c in codes}
                flags[g.key] = sorted(set(flags.get(g.key, [])) | mapped)
                n_added += 1
        print(f"（detect_intrusion 追加标记 {n_added} 个图块）\n")

    report = evaluate_self_detection(gold, flags)
    print(format_report(report))

    # 分层：列型
    for layout in ("rigid", "elastic"):
        sub = [g for g in gold if g.layout == layout]
        if not sub:
            continue
        r = evaluate_self_detection(sub, flags)
        print(f"\n[{layout}] 缺陷 {r['n_defect']} 检出 {r['defect_recall']:.0%}"
              f"，正例 {r['n_clean']} 误报 {r['false_alarm_rate']:.0%}")

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
