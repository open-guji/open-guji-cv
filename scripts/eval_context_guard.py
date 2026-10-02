#!/usr/bin/env python
"""context 通道护栏（`seed_admit.context_guard_*`，overview#333）的评测。

只读产物，不跑任何步骤——先用 `guji step seed_admit <book> --force`（`GUJI_PRODUCTS_DIR` 指沙箱）
各出一份基线与若干变体，再拿这个脚本逐格对比：

    python scripts/eval_context_guard.py --book vol03 \
        --base $S/prod_base --variant diff=$S/prod_diff --variant all=$S/prod_all \
        --labels $S/labels_vol03.json --cells vol03:110:7:3,vol03:48:8:21

做两件事：
- **拦下多少**：基线里 `channel=context` 放行、变体里不再放行的格，按触发的 doubt 分；
  有人裁标签的，再分「拦对（基线字错）/ 误拦（基线字对）」。
- **代价**：全册待审率（`n_review / (n_auto + n_review)`，不含 excluded）基线 vs 变体。

标签文件由 `--make-labels <book> <out.json>` 生成（需 `GUJI_WORKSPACE`/`GUJI_GLYPH_DB`）：
`{格 id: {"kind": char|notchar|defect, "char": 字}}`——字取 `feedback.lookup.human_chars`（已重绑定）
与字形库人裁；`not_a_char`／`seg_defect` 取事件日志里**最后一条**。注意标签只覆盖人看过的格，
而基线若关了人裁与排除名单（评测要这样跑），人裁过的格才会真的走 context 通道被量到。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(root: Path, book: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted((root / book / "seed_admit").glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))["seed_admit"]
        for cc in d["columns"]:
            for r in cc.get("chars") or []:
                out[r["id"]] = r
    return out


def load_ref(root: Path, book: str) -> dict[str, str]:
    """整理本代理真值：坐标对位 `coord`（空串 = 空格位）优先，没有就用现役对位字。"""
    ref: dict[str, str] = {}
    for f in sorted((root / book / "align_ref").glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))["align_ref"]
        for c in d.get("chars") or []:
            ref[c["id"]] = c["align_char"]
        for c in d.get("coord") or []:
            ref[c["id"]] = c["ref_char"]
    return ref


def make_labels(book: str, out: str) -> None:
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from open_guji_cv.feedback.bindings import rebind_library_shapes
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.feedback.lookup import human_chars
    from open_guji_cv.steps.seed_admit import _human_shapes

    lab: dict[str, dict] = {}
    hs = rebind_library_shapes(book, _human_shapes(os.environ["GUJI_GLYPH_DB"]))
    for k, v in {**hs, **human_chars(book)}.items():
        if k.startswith(book + ":"):
            lab[k] = {"kind": "char", "char": v}
    for e in sorted(EventLog().iter_all(), key=lambda e: (e.ts, e.batch, e.seq)):
        key = (e.target or {}).get("key") if isinstance(e.target, dict) else getattr(e.target, "key", None)
        if not key or not key.startswith(book + ":") or key.count(":") != 3:
            continue
        v = (e.payload or {}).get("v")
        if v == "not_a_char":
            lab[key] = {"kind": "notchar", "char": None}
        elif v == "seg_defect" and key not in lab:
            lab[key] = {"kind": "defect", "char": (e.payload or {}).get("shape") or None}
    Path(out).write_text(json.dumps(lab, ensure_ascii=False), encoding="utf-8")
    print(f"{len(lab)} labels → {out}", Counter(v["kind"] for v in lab.values()))


def rate(recs: dict[str, dict]) -> tuple[int, int, float]:
    n_auto = sum(1 for r in recs.values() if r["admit"])
    n_rev = sum(1 for r in recs.values() if not r["admit"] and "excluded" not in (r.get("doubts") or []))
    return n_auto, n_rev, n_rev / max(1, n_auto + n_rev)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book")
    ap.add_argument("--base")
    ap.add_argument("--variant", action="append", default=[], help="名字=产物根目录")
    ap.add_argument("--labels")
    ap.add_argument("--cells", default="", help="逗号分隔的点名格 id")
    ap.add_argument("--make-labels", nargs=2, metavar=("BOOK", "OUT"))
    ap.add_argument("--json", help="结果另存 json")
    a = ap.parse_args()
    if a.make_labels:
        return make_labels(*a.make_labels)
    base = load(Path(a.base), a.book)
    labels = json.loads(Path(a.labels).read_text(encoding="utf-8")) if a.labels else {}
    named = [c for c in a.cells.split(",") if c]
    refs = load_ref(Path(a.base), a.book)
    ctx_cells = {k for k, r in base.items() if r["admit"] and r["channel"] == "context"}
    ba, br, brate = rate(base)
    print(f"[{a.book}] 基线：放行 {ba} 待审 {br} 待审率 {brate:.4%}；context 放行 {len(ctx_cells)} 格；"
          f"其中有标签 {sum(1 for k in ctx_cells if k in labels)}")
    res: dict = {"base": {"auto": ba, "review": br, "rate": brate, "context": len(ctx_cells)}}
    for spec in a.variant:
        name, _, path = spec.partition("=")
        var = load(Path(path), a.book)
        blocked = [k for k in ctx_cells if not var.get(k, {}).get("admit")]
        changed_ok = [k for k in ctx_cells if var.get(k, {}).get("admit")
                      and (var[k]["channel"] != "context" or var[k]["char"] != base[k]["char"])]
        by = Counter()
        right = wrong = unl = 0
        px = Counter()      # 无标签格的整理本代理：基线字 == 整理本 → 疑似误拦
        wrong_ids, right_ids = [], []
        for k in blocked:
            ds = [d for d in var[k].get("doubts", []) if d.startswith("ctx_guard")]
            by[ds[0] if ds else "(被别的通道/闸挡)"] += 1
            lb = labels.get(k)
            if lb is None:
                unl += 1
                rf = refs.get(k)
                px["无整理本" if rf is None else "整理本=空格" if rf == ""
                   else "整理本同字(疑似误拦)" if rf == base[k]["char"] else "整理本异字(疑似拦对)"] += 1
                continue
            base_char = base[k]["char"]
            base_wrong = lb["kind"] == "notchar" or lb["char"] != base_char
            if base_wrong:
                wrong += 1
                wrong_ids.append(k)
            else:
                right += 1
                right_ids.append(k)
        # 标签里 context 放行了错字、却没被拦下的（漏拦）
        lab_ctx = [k for k in ctx_cells if k in labels]
        miss = [k for k in lab_ctx if k not in set(blocked)
                and (labels[k]["kind"] == "notchar" or labels[k]["char"] != base[k]["char"])]
        va, vr, vrate = rate(var)
        print(f"  ── {name}: 拦下 {len(blocked)}（{dict(by)}）；"
              f"有标签 {wrong + right}：拦对错字 {wrong}／误拦对字 {right}；无标签 {unl}；"
              f"漏拦（有标签错字没拦）{len(miss)}；改字放行 {len(changed_ok)}；"
              f"待审率 {vrate:.4%}（{vr - br:+d} 格，{vrate - brate:+.4%}）")
        if wrong_ids:
            print("     拦对:", ",".join(sorted(wrong_ids)[:40]))
        if right_ids:
            print("     误拦:", ",".join(f"{k}({labels[k]['char']})" for k in sorted(right_ids)[:40]))
        if miss:
            print("     漏拦:", ",".join(sorted(miss)[:40]))
        row = {"blocked": len(blocked), "by": dict(by), "wrong": wrong, "right": right,
               "unlabeled": unl, "unlabeled_proxy": dict(px), "missed": len(miss), "review": vr, "rate": vrate,
               "wrong_ids": wrong_ids, "right_ids": right_ids, "missed_ids": miss}
        res[name] = row
        for c in named:
            b, v = base.get(c), var.get(c)
            if b is None:
                continue
            print(f"     点名 {c}: 基线 admit={b['admit']}/{b['channel']}/{b['char']} → "
                  f"{name} admit={v['admit']}/{v['channel']}/{v['char']} doubts={v['doubts'][:3]}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
