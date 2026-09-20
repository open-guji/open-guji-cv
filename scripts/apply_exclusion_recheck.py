# -*- coding: utf-8 -*-
"""按复核裁决撤排除名单（配 build_exclusion_recheck_review.py）。

    python scripts/apply_exclusion_recheck.py <book> -w <workspace> --verdicts <jsonl> --cards <jsonl>
        [--release-unlabeled] [--apply]

## 规则

只动 `reason ∈ {seg_defect}` 的条目（切坏/带残留——人裁的是"图块不能进库"，不是"不是字"）：

| 裁决 | 处置 |
|---|---|
| ok（完整的字） | **撤名单**：从 `crop_exclusions.jsonl` 移到 `crop_exclusions_retired.jsonl`（带裁决、日期、来源），可逆 |
| bad（仍切坏/带残留） | 留在名单，`note` 记一笔复核日期 |
| nochar（不是字） | 留在名单，`reason` 改 `not_a_char`、`evidence` 加 `not_text` |
| idk / 没裁 | 默认留着；`--release-unlabeled` 时**没裁的按 ok 撤**（用户 2026-09-20：「绝大部分都没问题，进正常流程」——撤了之后 Step5–7 自己会把配不上的送人审，不会静默错） |

`not_a_char` 与 `damaged` 的条目一律不动（damaged 是"字在、原刻残"，占位出 □，本来就不该撤）。

撤名单之后 **Step7 要重跑**：名单内容不进指纹，`guji step seed_admit <book> --pages all --force -w <ws>`。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--cards", required=True)
    ap.add_argument("--release-unlabeled", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())
    from open_guji_cv.core.workspace import exclusions_path
    ex_path = exclusions_path()
    retired_path = ex_path.with_name("crop_exclusions_retired.jsonl")

    verdicts = {}
    for l in Path(a.verdicts).read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            verdicts[r["id"]] = r.get("verdict") or r.get("v")
    cards = {json.loads(l)["id"] for l in Path(a.cards).read_text(encoding="utf-8").splitlines() if l.strip()}

    keep, retire, changed = [], [], {"ok": 0, "unlabeled": 0, "bad": 0, "nochar": 0, "idk": 0, "untouched": 0}
    today = date.today().isoformat()
    for l in ex_path.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        iid = r["instance_id"]
        if not iid.startswith(a.book + ":") or r.get("reason") != "seg_defect" or iid not in cards:
            keep.append(r); changed["untouched"] += 1
            continue
        v = verdicts.get(iid)
        if v == "ok" or (v is None and a.release_unlabeled):
            r2 = {**r, "retired": today, "retired_by": "recheck:" + ("ok" if v else "unlabeled-released"),
                  "retired_source": Path(a.verdicts).name}
            retire.append(r2); changed["ok" if v else "unlabeled"] += 1
        elif v == "nochar":
            r["reason"] = "not_a_char"
            r["evidence"] = sorted(set(list(r.get("evidence") or []) + ["not_text"]))
            r["note"] = (r.get("note") or "") + f"；复核 {today}：不是字"
            keep.append(r); changed["nochar"] += 1
        elif v == "bad":
            r["note"] = (r.get("note") or "") + f"；复核 {today}：仍切坏"
            keep.append(r); changed["bad"] += 1
        else:
            keep.append(r); changed["idk"] += 1
    print(f"撤 {len(retire)}（ok {changed['ok']} · 没裁按 ok {changed['unlabeled']}）· 留 bad {changed['bad']} · "
          f"改非字 {changed['nochar']} · 拿不准/没裁留着 {changed['idk']} · 不在范围 {changed['untouched']}"
          + ("（已写）" if a.apply else "（试算）"))
    if a.apply:
        ex_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
        with open(retired_path, "a", encoding="utf-8") as f:
            for r in retire:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"名单 {ex_path} 剩 {len(keep)} 条；退役 {retired_path} +{len(retire)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
