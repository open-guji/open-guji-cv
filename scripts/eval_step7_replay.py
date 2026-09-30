# -*- coding: utf-8 -*-
"""Step7（seed_admit）放行判定 · 人裁事件回放评测（只读，不写任何事件 / 产物 / 库）。

    PYTHONPATH=. python scripts/eval_step7_replay.py --book vol01 \
        --products /path/to/products --events <ws>/feedback/events [--json out.json]

## 量什么

Step7 对每个字位给一个放行判定：`admit`（自动放行，带通道 channel 与 char）或落人审
（`admit=False`，`char` 是它拟的候选）。这里把 `feedback/events/` 里**人对同一格下过的裁决**
（`step=seed_admit, unit=cell, kind in {confirm, verdict}, actor=user`）当真值回放：

| 产物侧 | 人裁侧 | 读成 |
|---|---|---|
| 自动放行（非 human 通道） | confirm + reading/shape | **放行精度**：放行字与人裁字语义同（异体等价）不算错 |
| 自动放行（非 human 通道） | seg_defect / not_a_char | 放行了一个切坏 / 非字的格（另报，不并进精度） |
| 落人审 | confirm + reading | **可挽回**：拟的候选字就是人裁字 → 本可自动放行而没放（自动率的缺口）；拟错 → 人审是必要的 |
| 排除名单（`doubts` 含 excluded、无候选） | confirm + reading | 名单里的格人却读出了字（名单与人裁冲突，另报） |
| human 通道 | 任意 | **循环**：产物自己就是抄人裁（`use_human_verdicts`），只报一致率当健全性检查，**不进任何精度** |

## 必须读的三条口径（这套回放为什么不等于独立金标）

1. **人裁集合偏向「被送审的格」**：`*-decide` 批是审查队列，里面的格几乎全是 Step7 当时没放行的
   （难例）。所以能落到「自动放行 ∧ 有人裁」的格极少，放行精度的 n 很小——**别把它当自动放行的
   总体精度**。想量总体精度要靠随机抽检（shadow-review / p1-30-confirm 这类「对已放行格抽审」的批，
   下面单独标 `sampled` 档）。
2. **回放里的 match 通道有泄漏**：库里的刻例大多来自这些人裁（人裁进库），`glyph_match` 对同一格
   可能是在拿「人自己入库的那一份」匹配自己。严格的回放要留一法（摘掉该格入库的刻例再跑 Step5-a/7）
   ——那要整库 + 上游重跑，本脚本不做，只在报告里把这条风险标出来（见 doc/step7_replay_eval.md §4）。
3. **产物与事件的时间差**：产物是某次跑批的快照，人裁是更早（或更晚）发生的；格编号 `book:page:col:slot`
   在重切后会漂。所以找不到格的（`nocell`）单独计数。

## 不做的事

只读 `events/*.jsonl` 与 `products/<book>/seed_admit`；不 import `EventLog`（它带写锁）；不碰
`consumed/` 记账；不写产物。`--json` 只写到你指定的路径。
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: 批名命中这些子串的，是「对已放行格抽审」（采样）而不是审查队列
SAMPLED_MARKS = ("shadow-review", "confirm-2026", "glyphlib", "siku-claude", "audit", "snap-batch")
DEFECT_V = {"seg_defect", "not_a_char"}


def batch_kind(batch: str) -> str:
    return "sampled" if any(m in batch for m in SAMPLED_MARKS) else "queue"


def load_labels(events_dir: Path, book: str) -> tuple[dict[str, dict], Counter]:
    """格 key → 最新一条人裁（只要 actor=user 的 seed_admit 格级 confirm/verdict）。
    同一格多次取 (ts, batch, seq) 最大的；model 事件不算真值，只计数。"""
    best: dict[str, tuple] = {}
    skipped: Counter = Counter()
    for f in sorted(glob.glob(str(events_dir / f"{book}-*.jsonl"))):
        batch = Path(f).stem
        for ln in Path(f).read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            t = r.get("target") or {}
            if t.get("step") != "seed_admit" or t.get("unit") != "cell" or t.get("book") != book:
                continue
            if r.get("kind") not in ("confirm", "verdict"):
                continue
            if r.get("actor") != "user":
                skipped[f"actor={r.get('actor')}"] += 1
                continue
            key = t.get("key")
            if not key:
                continue
            rank = (r.get("ts") or "", batch, int(r.get("seq") or 0))
            if key not in best or rank >= best[key][0]:
                best[key] = (rank, r, batch)
    out = {}
    for key, (_, r, batch) in best.items():
        p = r.get("payload") or {}
        v = p.get("v") or p.get("verdict")
        out[key] = {"v": v, "reading": p.get("reading") or "", "shape": p.get("shape") or "",
                    "batch": batch, "kind": batch_kind(batch), "ts": r.get("ts")}
    return out, skipped


def load_cells(products: Path, book: str) -> dict[str, dict]:
    cells: dict[str, dict] = {}
    for f in sorted(glob.glob(str(products / book / "seed_admit" / "p*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8")).get("seed_admit") or {}
        for c in d.get("columns", []):
            for r in c.get("chars", []) or []:
                cells[r["id"]] = r
    return cells


def cell_class(c: dict) -> str:
    if c.get("provenance") == "human" or c.get("channel") == "human":
        return "human"
    if not c.get("admit") and "excluded" in (c.get("doubts") or []) and not c.get("char"):
        return "excluded"       # 排除名单里的切坏格：不进库不出卡，没有拟定候选
    return "auto" if c.get("admit") else "pending"


def rate(k: int, n: int) -> str:
    return f"{k}/{n} = {k / n:.1%}" if n else f"{k}/0 = —"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--book", required=True)
    ap.add_argument("--products", required=True, help="含 <book>/seed_admit/ 的产物根目录（只读）")
    ap.add_argument("--events", required=True, help="<工作区>/feedback/events（只读）")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    from open_guji_cv.clustering.variants import VariantMap
    vm = VariantMap.load(None)

    def same(x: str, y: str) -> bool:
        return bool(x) and bool(y) and (x == y or vm.semantic(x) == vm.semantic(y))

    labels, skipped = load_labels(Path(a.events), a.book)
    cells = load_cells(Path(a.products), a.book)
    if not cells:
        print(f"没有 {a.book} 的 seed_admit 产物：{a.products}/{a.book}/seed_admit", file=sys.stderr)
        return 2

    tot = Counter(cell_class(c) for c in cells.values())
    print(f"[{a.book}] seed_admit 格 {len(cells)}：自动放行 {tot['auto']} / 人裁通道 {tot['human']} / "
          f"落人审 {tot['pending']} / 排除名单 {tot['excluded']}")
    print(f"人裁标签 {len(labels)} 格（actor=user，每格取最新一条）；其中 queue 批 "
          f"{sum(1 for x in labels.values() if x['kind'] == 'queue')}，sampled 批 "
          f"{sum(1 for x in labels.values() if x['kind'] == 'sampled')}；跳过 {dict(skipped)}")

    nocell = Counter()
    prec = defaultdict(lambda: [0, 0])          # (kind,channel) → [对, 总]
    defect_on_auto = Counter()
    circ = [0, 0]
    rescuable = defaultdict(lambda: [0, 0])     # kind → [候选即人裁字, 总]
    pend_defect = Counter()
    excl_read = Counter()
    wrong_rows = []
    auto_rows: list[dict] = []
    for key, lab in sorted(labels.items()):
        c = cells.get(key)
        if c is None:
            nocell[lab["v"]] += 1
            continue
        cls = cell_class(c)
        human_char = lab["reading"] or lab["shape"]
        if lab["v"] in DEFECT_V:
            (defect_on_auto if cls == "auto" else pend_defect)[(lab["kind"], lab["v"])] += 1
            continue
        if lab["v"] != "confirm" or not human_char:
            continue
        ok = same(c.get("char", ""), lab["reading"]) or same(c.get("char", ""), lab["shape"])
        if cls == "human":
            circ[0] += ok
            circ[1] += 1
        elif cls == "auto":
            b, pg, col, slot = (key.split(":") + ["", "", "", ""])[:4]
            # 编号漂移嫌疑：同列相邻格放行的字恰好就是人裁字 → 八成是重切后格号错位，
            # 不是放行错了（vol02 旧快照上成片出现，见 doc/step7_replay_eval.md §3）
            drift = (not ok) and slot.lstrip("-").isdigit() and any(
                same((cells.get(f"{b}:{pg}:{col}:{int(slot) + d}") or {}).get("char", ""), human_char)
                for d in (-2, -1, 1, 2))
            auto_rows.append({"id": key, "page": f"{b}:{pg}", "channel": c.get("channel"), "admitted": c.get("char"),
                              "human": human_char, "batch": lab["batch"], "kind": lab["kind"],
                              "ok": bool(ok), "drift": bool(drift)})
        elif cls == "excluded":
            excl_read[lab["kind"]] += 1
        else:
            r = rescuable[lab["kind"]]
            r[0] += ok
            r[1] += 1

    # 整页剔除：只要一页里出现过漂移嫌疑，这一页的格号整体不可信（错位不会只错一格），
    # 该页所有自动放行的比对一并移出分母
    drift_pages = {r["page"] for r in auto_rows if r["drift"]}
    drift_rows = [r["id"] for r in auto_rows if r["page"] in drift_pages]
    for r in auto_rows:
        if r["page"] in drift_pages:
            continue
        p = prec[(r["kind"], r["channel"])]
        p[0] += r["ok"]
        p[1] += 1
        if not r["ok"]:
            wrong_rows.append(r)
    print("\n== 放行精度（自动放行 ∧ 有人裁字；异体等价算对）==")
    allp = [0, 0]
    for (kind, ch), (k, n) in sorted(prec.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        print(f"  [{kind:<7}] {str(ch):<14} {rate(k, n)}")
        allp[0] += k
        allp[1] += n
    print(f"  合计 {rate(*allp)}")
    if drift_rows:
        print(f"  （{len(drift_pages)} 页出现编号漂移嫌疑，这些页上 {len(drift_rows)} 格自动放行的比对整体移出分母，"
              f"不算对也不算错：{sorted(drift_pages)[:5]}…）")
    if defect_on_auto:
        print("  自动放行却被人标 切坏/非字：", dict(defect_on_auto))
    for w in wrong_rows[:12]:
        print(f"    ✗ {w['id']:<18} {w['channel']:<12} 放行 {w['admitted']} ≠ 人裁 {w['human']}  ({w['batch']})")

    print("\n== 落人审的格里，人裁字 == 拟定候选（本可放行而没放）==")
    for kind, (k, n) in sorted(rescuable.items()):
        print(f"  [{kind:<7}] {rate(k, n)}")
    if pend_defect:
        print("  落人审 ∧ 人标切坏/非字（人审拦对了）：", dict(pend_defect))

    if excl_read:
        print("  排除名单里的格人却读出了字（名单与人裁冲突）：", dict(excl_read))
    print("\n== 循环健全性（human 通道 vs 人裁，应≈100%，不进任何精度）==")
    print(f"  {rate(*circ)}")
    if nocell:
        print(f"\n产物里找不到的人裁格（重切后编号漂 / 产物范围外）：{dict(nocell)}")

    if a.json:
        Path(a.json).write_text(json.dumps({
            "book": a.book, "cells": len(cells), "cell_class": dict(tot), "labels": len(labels),
            "precision": {f"{k}|{c}": {"ok": v[0], "n": v[1]} for (k, c), v in prec.items()},
            "rescuable": {k: {"ok": v[0], "n": v[1]} for k, v in rescuable.items()},
            "circular": {"ok": circ[0], "n": circ[1]},
            "defect_on_auto": {f"{k[0]}|{k[1]}": v for k, v in defect_on_auto.items()},
            "excluded_but_read": dict(excl_read),
            "pending_defect": {f"{k[0]}|{k[1]}": v for k, v in pend_defect.items()},
            "nocell": dict(nocell), "drift_pages": sorted(drift_pages), "drift_cells": len(drift_rows), "wrong": wrong_rows,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
