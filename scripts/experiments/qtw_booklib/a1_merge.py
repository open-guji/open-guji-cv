"""a1：四批用户人裁 → 逐格一条（去重、校验、冲突清单）。只读，不写事件。

  GUJI_WORKSPACE=$QTW_WS python a1_merge.py <out_dir>

口径（任务书 18:50 / 19:00 / 22:15 三处补）：
- batch1（v1 按字种页）：`ok` = 逐格确认 AI 字；`bad` 是「太累了」时的整批拒绝，**不导入为 reject**，
  以后面的簇裁决为准，与后批冲突的逐条列出；`blur` = 看不清。
- batch2/3/5：簇裁决展开成逐格（带簇 id）；`blur` / `char:null` = 看不清。
- 同一格多条：按时间 `t` 取最新；结论不同的逐条列进 conflicts。
- 字形字段必须过 `feedback.mojibake.is_legal_shape` 且是单个汉字；键必须是 `书:页:列:格`、
  书在 v006–v010、格在 cell_shrink 产物里且是字格。不合格的进 rejects，写原因。
- `ai-vision-v1.jsonl` 不读。
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qb_common import HUMAN_FILES, QTW_BOOKS, QTW_TRUTH, cell_index  # noqa: E402


def rows():
    """逐条归一：{key, act∈confirm/damaged/v1_bad, char, batch, cluster, t, per_cell}"""
    for fn in HUMAN_FILES:
        tag = fn.split("-")[0]
        for n, line in enumerate(open(QTW_TRUTH / fn, encoding="utf-8"), 1):
            d = json.loads(line)
            key = d.get("id") or d.get("key")
            base = {"key": key, "batch": tag, "line": n, "t": d.get("t"),
                    "cluster": d.get("cluster") or d.get("cluster_id"), "pool": d.get("pool")}
            if tag == "batch1":
                v = d.get("verdict")
                if v == "ok":
                    yield {**base, "act": "confirm", "char": d.get("ai_char"), "per_cell": True}
                elif v == "blur":
                    yield {**base, "act": "damaged", "char": None, "per_cell": True}
                else:
                    yield {**base, "act": "v1_bad", "char": None, "rejected_char": d.get("ai_char"),
                           "per_cell": True}
            elif tag in ("batch2", "batch3"):
                ch = d.get("accepted_char")
                if ch:
                    yield {**base, "act": "confirm", "char": ch, "per_cell": False}
                else:
                    yield {**base, "act": "damaged", "char": None, "per_cell": False,
                           "raw_verdict": d.get("verdict")}
            else:  # batch5
                ch = d.get("char")
                if ch:
                    yield {**base, "act": "confirm", "char": ch, "per_cell": False,
                           "ai_char": d.get("ai_char"), "tier": d.get("tier")}
                else:
                    yield {**base, "act": "damaged", "char": None, "per_cell": False,
                           "raw_verdict": d.get("verdict")}


def check(r, cells) -> str | None:
    from open_guji_cv.feedback.mojibake import is_legal_shape
    k = r["key"] or ""
    parts = k.split(":")
    # 格号可以是负数：抬头格在列顶之上，slot=-1（cell_shrink 里就是这么编的）
    if len(parts) != 4 or not all(p.lstrip("-").isdigit() for p in parts[1:]):
        return f"键不是 书:页:列:格（{k!r}）"
    if parts[0] not in QTW_BOOKS:
        return f"书 {parts[0]!r} 不在 v006–v010"
    c = cells[parts[0]].get(k)
    if c is None:
        return "格不在 cell_shrink 产物里"
    if c.get("cell_type") not in (None, "char"):
        return f"格类型是 {c.get('cell_type')!r}，不是字格"
    ch = r.get("char")
    if r["act"] == "confirm":
        if not is_legal_shape(ch) or len(ch) != 1 or ord(ch) < 0x2E80:
            return f"字形 {ch!r} 不是单个汉字"
    return None


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    cells = {b: cell_index(b) for b in QTW_BOOKS}
    all_rows = list(rows())
    ok, rejects = [], []
    for r in all_rows:
        why = check(r, cells)
        (rejects.append({**r, "reason": why}) if why else ok.append(r))
    by = collections.defaultdict(list)
    for r in ok:
        by[r["key"]].append(r)
    final, conflicts = [], []
    for k, rs in by.items():
        rs.sort(key=lambda x: (x["t"] or 0, x["batch"]))
        imp = [x for x in rs if x["act"] != "v1_bad"]
        outcomes = {(x["act"], x["char"]) for x in imp}
        if len(outcomes) > 1:
            conflicts.append({"key": k, "kind": "后批之间结论不同（取时间最新）",
                              "records": [{f: x.get(f) for f in ("batch", "act", "char", "cluster", "t")}
                                          for x in rs]})
        bad = [x for x in rs if x["act"] == "v1_bad"]
        if not imp:
            final.append({**bad[-1], "import": False,
                          "why": "v1 整批拒绝，无后批簇裁决；按 18:50 口径不导入为 reject"})
            continue
        win = imp[-1]
        if bad and win["act"] == "confirm" and win["char"] == bad[-1].get("rejected_char"):
            conflicts.append({"key": k, "kind": "v1 判 AI 字不对，后批簇裁决确认的正是这个字（按后批）",
                              "records": [{f: x.get(f) for f in ("batch", "act", "char", "rejected_char",
                                                                 "cluster", "t")} for x in rs]})
        final.append({**win, "import": True, "n_records": len(rs),
                      "per_cell": any(x.get("per_cell") and x["act"] == win["act"]
                                      and x["char"] == win["char"] for x in imp)})
    for name, data in (("final", final), ("rejects", rejects), ("conflicts", conflicts)):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stat = {
        "rows_in": len(all_rows),
        "rows_by_file": dict(collections.Counter(r["batch"] for r in all_rows)),
        "rejected_rows": len(rejects),
        "reject_reasons": dict(collections.Counter(r["reason"] for r in rejects)),
        "cells": len(final),
        "cells_import": sum(r["import"] for r in final),
        "cells_act": dict(collections.Counter(r["act"] for r in final if r["import"])),
        "cells_not_import_v1_bad": sum(not r["import"] for r in final),
        "dup_cells": sum(1 for rs in by.values() if len(rs) > 1),
        "conflicts": len(conflicts),
        "conflict_kinds": dict(collections.Counter(c["kind"] for c in conflicts)),
        "chars": len({r["char"] for r in final if r["import"] and r["act"] == "confirm"}),
    }
    json.dump(stat, open(out / "stat.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(stat, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
