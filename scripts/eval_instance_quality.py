"""评测管线对切分缺陷的自检能力（char-segmentation/instances）。

【2026-09-30 M1 C 组：默认改读现行 v2 链】
原先读 v1 `output/<册>/phase4_chars/index.jsonl`（退役链，云端没有 → 「缺少 ... 请先跑 chars」直接 return，
一个指标都不印，评测层看到的是 n=0 的假结果）。现在默认：
  - 金标读 `instances/instances_v2.json` 的 `items`（迁移脚本 `artifacts/m1_gold/instance_quality/migrate_instances.py`：
    图块与 v2 字块同一张图 + 标签↔图块目视一致，锚到 v2 (col, slot)）；
  - 被测 flags 读 v2 `cell_shrink` 产物 `char_index` 的 `CharRec.flags`（任意 flag 即「被标记」，口径同前）；
  - 指标名（逐类检出率 / 缺陷检出率 / 标记精确率 / 正例误报率 / 确定层·疑似层）与计算函数
    `evaluate_self_detection` 一字未动，可与 README「当前基线」对照。
  - `--with-unverified`：另报 **v2 原生人裁**（items.jsonl 里没有 legacy_source 的条目，slot 键）——它们没有
    任何保存的图像凭证，只是「当时的 slot 键」，**参考读数，不进主结果**。
  - `--v1` 保留旧读法。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_guji_cv.clustering.instance_quality import (evaluate_self_detection,
                                                      format_report,
                                                      load_dataset)


def _v2_flags(pairs):
    """pairs: [(book, page, col, slot)] → {"book/page:col:slot": [flags…]}（同一 slot 的 a/b 半格 flag 取并集）。

    v2 里找不到这个字位（列不存在 / 该 slot 没有 char 记录）的不放进结果——调用方据此单列「无 v2 对应格」。
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _v2_step4 import V2Book
    books: dict = {}
    by: dict = {}
    for b, pg, c, sl in pairs:
        by.setdefault(b, set()).add(int(pg))
    for b, pgs in by.items():
        books[b] = V2Book(b)
        books[b].ensure(pgs)
    flags: dict[str, list[str]] = {}
    for b, pg, c, sl in pairs:
        pc = books[b].chars(int(pg))
        cc = pc.column(int(c)) if pc is not None else None
        recs = [r for r in (cc.chars if cc else []) if r.slot == int(sl) and r.cell_type == "char"]
        if not recs:
            continue
        flags[f"{b}/{pg}:{c}:{sl}"] = sorted({f for r in recs for f in r.flags})
    return flags


def main_v2(args) -> None:
    from open_guji_cv.clustering.instance_quality import InstanceQuality
    if args.with_intrusion:
        print("（--with-intrusion 只在 --v1 有效：v2 的 flags 已含版框/界行判据）")
    doc = json.loads((Path(args.dataset) / "instances_v2.json").read_text(encoding="utf-8"))

    def to_gold(items):
        return [InstanceQuality(book=i["book"], page=str(i["page"]), col=int(i["col"]), idx=int(i["slot"]),
                                quality=i["quality"], defect=i.get("defect"), seed=i.get("seed"),
                                layout=i.get("layout", "unknown")) for i in items]

    def run(items, title):
        gold = to_gold(items)
        flags = _v2_flags([(g.book, g.page, g.col, g.idx) for g in gold])
        have = [g for g in gold if g.key in flags]
        lost = [g for g in gold if g.key not in flags]
        print(f"===== {title}：{len(gold)} 条，v2 有对应字位 {len(have)}，无对应 {len(lost)}")
        for g in lost[:10]:
            print(f"   ? 无 v2 对应字位 {g.key}（{g.quality}）")
        if not have:
            print("没有可评条目——空跑，不算通过")
            return None
        rep = evaluate_self_detection(have, flags)
        print(format_report(rep))
        return rep

    rep = run(doc["items"], "已验证层（图像凭证：图块=v2 字块 + 目视一致）")
    if rep is None:
        raise SystemExit(1)
    if args.with_unverified:
        import json as _j
        rows = [_j.loads(l) for l in (Path(args.dataset) / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        nat = [{"book": r["anchor"]["book"], "page": r["anchor"]["page"], "col": r["anchor"]["col"],
                "slot": r["anchor"]["slot"], "quality": r["expected"].get("quality"), "seed": "v2native"}
               for r in rows if not r["input"].get("legacy_source") and r["status"] == "active"
               and r["anchor"]["book"] in ("vol01", "vol02", "bxgb")
               and r["expected"].get("quality") in ("clean", "contaminated", "truncated", "not_text")]
        run(nat, "v2 原生人裁（无图像凭证，仅 slot 键；参考读数）")
    if args.out:
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {args.out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="数据集目录（含 instances_v2.json；--v1 时含 expected.json）")
    ap.add_argument("--v1", action="store_true", help="旧读法（v1 phase4_chars，已退役）")
    ap.add_argument("--with-unverified", action="store_true", help="另报 v2 原生人裁（无图像凭证，参考读数）")
    ap.add_argument("--out", default=None, help="报告 JSON 路径")
    ap.add_argument("--with-intrusion", action="store_true",
                    help="把 crop_quality.detect_intrusion 的侵入码并入 flags "
                         "（它归确定层：版面线成因明确，下游可直接剥）")
    args = ap.parse_args()
    if not args.v1:
        return main_v2(args)

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
