#!/usr/bin/env python3
"""从整理产物生成 NNN.decision.json（guji-decision v0.2），F1 两类单列（GUJI-588；设计 §4.4 F1）。

来源：ai-team `team/整理/GUJI-588/decision_build.py`（说明见同目录 README.md），2026-10-20 迁入 cv `scripts/zhengli/`（GUJI-652）。
迁入适配：只给 main() 加了可选 argv 参数（便于测试），不依赖 cv 包与 ai-team 路径。
用途：收 char 的阙文格与 pending 待审格，按最新用户裁决分 ①看不出／②切分类写进 decision.json，供 book-text 打包。
注意：`--events-dir <ws>/feedback/events` 是中心库切换前的落点；现在人裁事件真源在中心库，
本机副本在 `$GUJI_DATA_HOME/<分支>/<工作区 id>/feedback/events/`（`guji db sync` 后），跑时 --events-dir 指那里。脚本逻辑未改。

只读：book-text 的 NNN.char.json／NNN.pending.json，guji-workspace 的 feedback/events/*.jsonl，
可选 cv Step5-d 的 align_ref 目录（服务器 products/<册>/align_ref）或 align_diff.py 出的 TSV。
只写 --out 指定的文件，不改 char、不写事件。

收哪些格（char 里 lacuna=True 的阙文格，以及 pending 里的待审格）：
  ② 切分没修所以没法判：该格最新一条用户 confirm 是 seg_defect（truncated／contaminated 等）
     → kind=uncertain，status=open，reason=seg_bad，route=list，route_ref=--route-ref
  ① 看不出：在 pending 里、没有用户定字裁决的格
     → kind=uncertain，status=open，不写 reason（缺省即 unclear），不得带 route
  已由用户定字（confirm 的 shape＝char 现字）的格不收：char 已是结果，没有候选要展示。
两类互斥：一格只按最新一条用户裁决归一类。

候选（cands，schema 要求 1–5 个且不得等于 current）：
  pending 的 lib_top（src=cv，conf＝分数）→ 整理本字 align_char（src=align_ref）。
  一个候选都没有的格不写，列在 stderr 的「无候选」里（服务器上带 --align-dir 跑就都有整理本字）。

退出码：0；有无候选的格 → 2（文件照写，缺的格不在里面）。
用法：
  python3 scripts/zhengli/decision_build.py --char 001.char.json --pending 001.pending.json --events-dir <ws>/feedback/events \
      --book vol01 [--align-dir <products>/vol01/align_ref | --align-tsv vol01-align_diff.tsv] \
      [--route-ref GUJI-588] --out 001.decision.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

SCHEMA = "https://open-guji.org/schema/decision/v0.2.json"


def char_cells(path):
    d = json.load(open(path, encoding="utf-8"))
    cells = {}
    for pg in d["pages"]:
        for col in pg["columns"]:
            for c in col["cells"]:
                cells[c["a"]] = c
    return d, cells


def user_verdicts(events_dir, book):
    """格 → 最新一条 actor=user 的 confirm payload（按 ts 排）。"""
    last = {}
    for f in sorted(glob.glob(os.path.join(events_dir, "*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            if not ln.strip():
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            key = (e.get("target") or {}).get("key") or ""
            if e.get("kind") != "confirm" or e.get("actor") != "user" or not key.startswith(book + ":"):
                continue
            cell = key[len(book) + 1:]
            ts = e.get("ts") or ""
            if cell not in last or ts >= last[cell][0]:
                last[cell] = (ts, e.get("payload") or {})
    return {k: v[1] for k, v in last.items()}


def align_chars(align_dir, align_tsv, book):
    out = {}
    if align_dir:
        for f in sorted(glob.glob(os.path.join(align_dir, "p*.json"))):
            for ch in json.load(open(f, encoding="utf-8"))["align_ref"]["chars"]:
                cell = ch["id"].removeprefix(book + ":")
                sub = ch.get("sub")
                if sub is not None and not cell.endswith(str(sub)):
                    cell += str(sub)
                if ch.get("align_char"):
                    out[cell] = ch["align_char"]
    elif align_tsv:
        for ln in open(align_tsv, encoding="utf-8").read().splitlines()[1:]:
            f = ln.split("\t")
            out[f[0].split("[")[0]] = f[2]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", required=True)
    ap.add_argument("--pending")
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--align-dir")
    ap.add_argument("--align-tsv")
    ap.add_argument("--route-ref", default="GUJI-588")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    char, cells = char_cells(a.char)
    pend = {}
    if a.pending:
        pend = {c["cell"]: c for c in json.load(open(a.pending, encoding="utf-8"))["cells"]}
    verdict = user_verdicts(a.events_dir, a.book)
    ref = align_chars(a.align_dir, a.align_tsv, a.book)

    want = [k for k, c in cells.items() if c.get("lacuna")] + [k for k in pend if k not in cells or not cells[k].get("lacuna")]
    items, nocand, stat = [], [], {"② 切分类": 0, "① 看不出": 0, "已定字不收": 0}
    for cell in want:
        if cell not in cells:
            nocand.append(f"{cell}(char 无此格)")
            continue
        cur = cells[cell]["c"]
        v = verdict.get(cell, {})
        if v.get("v") == "seg_defect":
            cls = 2
        elif v.get("shape") and v.get("shape") == cur and cell not in pend:
            stat["已定字不收"] += 1
            continue
        elif cell in pend or cells[cell].get("lacuna"):
            cls = 1
        else:
            continue
        cands, seen = [], {cur}
        for t in (pend.get(cell, {}).get("lib_top") or []):
            if t.get("c") and t["c"] not in seen:
                cands.append({"text": t["c"], "src": "cv", "conf": round(float(t.get("s", 0)), 4), "why": "字形库匹配"})
                seen.add(t["c"])
        if ref.get(cell) and ref[cell] not in seen:
            cands.append({"text": ref[cell], "src": "align_ref", "why": "整理本对齐"})
        if not cands:
            nocand.append(cell)
            continue
        it = {"cell": cell, "current": cur, "kind": "uncertain", "status": "open", "cands": cands[:5]}
        if cls == 2:
            it.update({"reason": "seg_bad", "route": "list", "route_ref": a.route_ref,
                       "note": f"人裁 seg_defect／{v.get('quality') or '未注明'}：切坏未修，按阙文录"})
            stat["② 切分类"] += 1
        else:
            it["note"] = "待审" if cell in pend else "阙文"
            stat["① 看不出"] += 1
        items.append(it)

    def order(it):
        return [int("".join(ch for ch in p if ch.isdigit()) or 0) for p in it["cell"].split(":")] + [it["cell"]]

    items.sort(key=order)
    out = {"$schema": SCHEMA, "book_id": char["book_id"], "volume": char["volume"], "items": items}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"{a.out}：{len(items)} 条；{json.dumps(stat, ensure_ascii=False)}；无候选 {len(nocand)}"
          + (f"：{' '.join(nocand[:40])}{' …' if len(nocand) > 40 else ''}" if nocand else ""), file=sys.stderr)
    return 2 if nocand else 0


if __name__ == "__main__":
    sys.exit(main())
