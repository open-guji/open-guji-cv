"""给已有的人裁事件、文意裁定、看图结论补 `pending_reason`（A31，sheldon 2026-11-03 定：回写，推不出写 unknown）。

    python scripts/zhengli/backfill_event_reason.py -w <工作区> [--write] [--report out.md]

扫数据目录 `feedback/{events,rulings,vision}/*.jsonl`，只动三种事件，payload 加 `pending_reason`（已有的不动）：

| 事件 | 怎么推 |
|---|---|
| `ctx_ruling` 字组（group≠O） | `group_abstain`：文意裁定问的是字组判不了的格 |
| `ctx_ruling` 整理本（group=O） | route=code_conflict → `ruling_conflict`；subclass=PUA（整理本私用码缺字）→ `ref_lacuna`；整理本这格空 → `ref_gap`；整理本字≠机器字 → `ref_mismatch`；其余 `unknown` |
| `confirm` | via=newchar_review → `lib_missing`；via=seg_flag → `seg_defect`；via=collate_verdict → `ref_mismatch`；来源写着异体合审／异体对 → `variant_pair`；文意组刻形补标 → `group_abstain`；库无／缺字确认、补库确认 → `lib_missing`；其余（含遮挡怀疑，分不出整理本在不在）`unknown` |
| `vision_check` | 带 group → `group_abstain`，其余 `unknown`（看图是抽样核，不按待审原因挑格） |

别的字段一字不动；每行按原行的写法重写（EventLog 的 `sort_keys`，或 `~q` 迁移副本、模型裁定的插入序），认不出写法的文件整个不动并报出来。
缺省只试跑出报告；`--write` 在人裁写入锁内写回；推中心库另跑 `guji db push -w <工作区>`。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

CV = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CV))

from open_guji_cv.feedback.lock import feedback_write_lock  # noqa: E402
from guji_manager.feedback.migrate_v1 import dumps  # noqa: E402
from guji_manager.review.pending_reason import PendingReason as R  # noqa: E402

KINDS = ("ctx_ruling", "confirm", "vision_check")
DIRS = ("events", "rulings", "vision")


def reason_of(e: dict) -> str:
    k, p = e.get("kind"), e.get("payload") or {}
    if k == "ctx_ruling":
        if p.get("group") != "O":
            return R.GROUP_ABSTAIN.value
        if p.get("route") == "code_conflict":
            return R.RULING_CONFLICT.value
        if p.get("subclass") == "PUA":
            return R.REF_LACUNA.value
        ref, mach = p.get("ref"), p.get("machine")
        if ref == "":
            return R.REF_GAP.value
        if ref and mach and ref != mach:
            return R.REF_MISMATCH.value
        return R.UNKNOWN.value
    if k == "confirm":
        via, src = p.get("via") or "", p.get("source") or ""
        if via == "newchar_review":
            return R.LIB_MISSING.value
        if via == "seg_flag":
            return R.SEG_DEFECT.value
        if via == "collate_verdict":
            return R.REF_MISMATCH.value
        if "异体" in src:
            return R.VARIANT_PAIR.value
        if "文意组刻形" in src:
            return R.GROUP_ABSTAIN.value
        if "库无" in src or "缺字确认" in src or "补库确认" in src:
            return R.LIB_MISSING.value
        return R.UNKNOWN.value
    if k == "vision_check":
        return R.GROUP_ABSTAIN.value if p.get("group") else R.UNKNOWN.value
    raise ValueError(k)


_WRITERS = (dumps, lambda d: json.dumps(d, ensure_ascii=False))   # EventLog 的 sort_keys 写法；`~q` 迁移副本与模型裁定按插入序


def plan_file(f: Path) -> tuple[list[str], Counter, str | None]:
    """返回 (新的行, 计数, 不能动的原因)。"""
    raw = f.read_text(encoding="utf-8").splitlines()
    out, n = [], Counter()
    for ln in raw:
        if not ln.strip():
            out.append(ln)
            continue
        e = json.loads(ln)
        if not isinstance(e, dict) or e.get("kind") not in KINDS or "pending_reason" in (e.get("payload") or {}):
            out.append(ln)
            continue
        enc = next((w for w in _WRITERS if w(e) == ln), None)       # 按原行的写法重写（键序、空格）
        if enc is None:
            return raw, Counter(), f"{f.name} 有事件行重写后与原行不同，不动"
        r = reason_of(e)
        e.setdefault("payload", {})["pending_reason"] = r
        out.append(enc(e))
        n[(e["kind"], r)] += 1
    return out, n, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-w", "--ws", required=True, help="工作区（读 .central.json 找数据目录）或直接给数据目录的 feedback 上级")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    root = Path(a.ws)
    if not (root / "feedback").is_dir():
        from open_guji_cv.datastore.workcopy import data_dir   # 工作区 → 本机数据目录
        root = data_dir(root)
    fb = root / "feedback"
    files = [f for d in DIRS for f in sorted((fb / d).glob("*.jsonl"))]
    tot, skipped, todo = Counter(), [], []
    for f in files:
        lines, n, why = plan_file(f)
        if why:
            skipped.append(why)
        elif n:
            todo.append((f, lines))
            tot.update(n)
    md = [f"# 事件补 pending_reason（{fb}）", "", f"要改 {len(todo)} 个文件、{sum(tot.values())} 条事件；不动的文件 {len(skipped)} 个。", "",
          "| 事件 | pending_reason | 条数 |", "|---|---|---:|"]
    md += [f"| {k} | {r} | {v} |" for (k, r), v in sorted(tot.items(), key=lambda x: (x[0][0], -x[1]))]
    md += ["", *[f"- {s}" for s in skipped]]
    print("\n".join(md))
    if a.report:
        Path(a.report).write_text("\n".join(md) + "\n", encoding="utf-8")
    if a.write and todo:
        with feedback_write_lock(fb):
            for f, lines in todo:
                lines2, _, why = plan_file(f)       # 锁内重算，防止计划后有人追加
                if why:
                    print(f"✗ {why}")
                    continue
                f.write_text("\n".join(lines2) + "\n", encoding="utf-8", newline="\n")
        print(f"已写 {len(todo)} 个文件；推中心库：guji db push -w <工作区>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
