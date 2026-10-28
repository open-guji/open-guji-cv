#!/usr/bin/env python3
"""全部待审格分类统计（A31，2026-10-28，sheldon「把统计待审并分类规范化、脚本化、直接查库」）。

只查中心库，不下产物包、不拉原图，全套 99 册约 5 秒：
  - 线上待审单：`files` 表 `feedback/lists/proofing/<文本号>/<册号>.pending.json`（每格自带成因码 cause，republish 发布时写入）
  - 全册格数：`progress.volume.cells_total`（算人审率）
  - 码位表：`files` 表 `config/codepoints.yaml`（判「码位已定」）
分类规则见 `open_guji_cv/review/taxonomy.py`，跟进方与口径见 ai-team `domain/CV/质检/待审分类规范.md`。

  python scripts/zhengli/pending_stats.py --out /tmp/ps                 # 全套，写 report.md／cells.tsv／summary.json
  python scripts/zhengli/pending_stats.py --vols 20-50 --out /tmp/ps
  python scripts/zhengli/pending_stats.py --out /tmp/ps --prev old/summary.json   # 括号里写与上一份的增减
  python scripts/zhengli/pending_stats.py --from-dir lists/ --out /tmp/ps        # 离线：目录里放 <册号>.pending.json

统计的是「线上单」，不是 ★main 包：单子落后于 main 包时数字也落后（报告里列了每册单子的版本和时间，落后的先重出单）。
连库：GUJI_DATA_PG_DSN，或 NEON_DATABASE_URL（自动起 443 桥）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

CV = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CV))
from open_guji_cv.review.taxonomy import BIG, FIX, SUBS, classify, cell_pos, conc_tag  # noqa: E402

DEFAULT_WS, DEFAULT_TEXT = "siku-zongmu", "96mid1ogzk"


def parse_vols(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    out: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def load_db(ws: str, text: str, vols: set[int] | None):
    """→ (lists {册号: doc}, cells_total {册号: n}, codepoints {另一码位: 本书码位})。"""
    from open_guji_cv.datastore.connect import connect
    with connect() as con:
        cur = con.cursor()
        cur.execute("select src_path, doc from files where ws=%s and src_path like %s", (ws, f"feedback/lists/proofing/{text}/%.pending.json"))
        lists = {}
        for p, d in cur.fetchall():
            n = Path(p).name[:3]
            if vols is None or int(n) in vols:
                lists[n] = d if isinstance(d, dict) else json.loads(d)
        cur.execute("select vol, cells_total from progress.volume where book_id=%s", (text,))
        total = {v: int(t) for v, t in cur.fetchall() if t}
        cur.execute("select raw from files where ws=%s and src_path='config/codepoints.yaml'", (ws,))
        row = cur.fetchone()
    cp: dict = {}
    if row:
        import yaml
        cp = (yaml.safe_load(row[0]) or {}).get("codepoints") or {}
    return lists, total, cp


def load_dir(path: Path, vols: set[int] | None):
    lists = {}
    for f in sorted(path.glob("*.pending.json")):
        n = f.name[:3]
        if vols is None or int(n) in vols:
            lists[n] = json.loads(f.read_text(encoding="utf-8"))
    return lists, {}, {}


@lru_cache(maxsize=None)
def _group_of(ch: str) -> str | None:
    from open_guji_cv.groups.registry import groups_of
    gs = groups_of(ch)
    return gs[0].id if gs else None


def analyse(lists: dict, codepoints: dict, extra_cp: dict | None = None) -> list[dict]:
    """→ 每格一行 {vol, cell, big, sub, key, owner, fix, conc, cause}。"""
    cp = {**codepoints, **(extra_cp or {})}
    decided = lambda a, b: cp.get(a) == b or cp.get(b) == a   # noqa: E731
    rows = []
    for vol, doc in sorted(lists.items()):
        cells = [c for c in doc.get("cells") or [] if c.get("review") != "human"]
        occ_page, page_n, col_n = Counter(), Counter(), Counter()
        for c in cells:
            pos = cell_pos(c["cell"])
            if pos:
                page_n[pos[0]] += 1
                col_n[pos[1]] += 1
                if c.get("cause") == "D":
                    occ_page[pos[0]] += 1
        for c in cells:
            pos = cell_pos(c["cell"]) or ("?", "?")
            v = classify(c, occ_page_n=occ_page[pos[0]], decided=decided, group_of=_group_of)
            rows.append({"vol": vol, "cell": c["cell"], "big": v.big, "sub": v.sub, "key": v.key, "owner": v.owner,
                         "fix": v.fix, "conc": conc_tag(page_n[pos[0]], col_n[pos[1]]), "cause": c.get("cause") or "",
                         "slim": "cls" not in c})
    return rows


def summarize(rows: list[dict], lists: dict, total: dict) -> dict:
    by_sub, by_vol, keys, conc = Counter(), defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for r in rows:
        by_sub[r["sub"]] += 1
        by_vol[r["vol"]][r["big"]] += 1
        by_vol[r["vol"]]["n"] += 1
        keys[r["sub"]][r["key"] or "—"] += 1
        conc[r["big"]][r["conc"]] += 1
    vols = {}
    for v, doc in lists.items():
        t = total.get(v) or total.get(str(int(v)))
        vols[v] = {"n": by_vol[v]["n"], "cells": t, "rate": (by_vol[v]["n"] / t) if t else None,
                   "by_big": {b: by_vol[v][b] for b in BIG if by_vol[v][b]},
                   "rev": doc.get("rev"), "cv": doc.get("cv_version"), "at": doc.get("routed_as_of"),
                   "slim": sum(1 for r in rows if r["vol"] == v and r["slim"])}
    return {"n": len(rows), "by_sub": dict(by_sub), "keys": {k: dict(v) for k, v in keys.items()},
            "conc": {k: dict(v) for k, v in conc.items()}, "vols": vols}


def _d(now: int, prev) -> str:
    if prev is None:
        return ""
    d = now - prev
    return f"（{'+' if d > 0 else ''}{d}）" if d else "（0）"


def render(s: dict, prev: dict | None, top: int) -> str:
    n = s["n"]
    ps = (prev or {}).get("by_sub", {})
    tot_cells = sum(v["cells"] or 0 for v in s["vols"].values())
    out = ["# 待审格分类统计", "",
           f"口径：线上待审单（中心库 `files` 表），{len(s['vols'])} 册，待审 **{n}** 格"
           + (f"，占全册 {tot_cells} 格的 {n / tot_cells:.2%}" if tot_cells else "")
           + "。分类规则 `open_guji_cv/review/taxonomy.py`；跟进方见 ai-team `domain/CV/质检/待审分类规范.md`。"
           + ("括号里是比上一份的增减。" if prev else ""), "",
           "## 一、大类／小类总账", "",
           "| 小类 | 名 | 格数 | 占比 | 跟进方 | 处理方式 | 集中度（整页／整列／零散） |", "|---|---|---|---|---|---|---|"]
    by_big = Counter()
    for sub, k in s["by_sub"].items():
        by_big[SUBS[sub][0]] += k
    pb = Counter()
    for sub, k in ps.items():
        pb[SUBS[sub][0]] += k
    for big, (bname, _) in BIG.items():
        if not by_big[big]:
            continue
        cc = s["conc"].get(big, {})
        out.append(f"| **{big}** | **{bname}** | **{by_big[big]}**{_d(by_big[big], pb[big] if prev else None)} | {by_big[big] / n:.1%} | | | "
                   f"{cc.get('整页', 0)}／{cc.get('整列', 0)}／{cc.get('零散', 0)} |")
        for sub in sorted(k for k, v in SUBS.items() if v[0] == big and s["by_sub"].get(k)):
            _, name, owner, fix, _ = SUBS[sub]
            k = s["by_sub"][sub]
            out.append(f"| {sub} | {name} | {k}{_d(k, ps.get(sub, 0) if prev else None)} | {k / n:.1%} | {owner} | {FIX[fix]} | |")
    fixc = Counter()
    for sub, k in s["by_sub"].items():
        fixc[SUBS[sub][3]] += k
    out += ["", "按处理方式：" + "；".join(f"{FIX[f]} {fixc[f]}（{fixc[f] / n:.0%}）" for f in FIX if fixc[f]), "",
            "## 二、各小类的键（前 %d）" % top, "",
            "Z＝字组 id；M＝字对；L1＝缺字；L2／L3＝原因。", ""]
    for sub in sorted(s["keys"]):
        if sub[0] not in "ZMLR" or not s["by_sub"].get(sub):
            continue
        ks = sorted(s["keys"][sub].items(), key=lambda kv: -kv[1])
        out.append(f"- **{sub} {SUBS[sub][1]}**（{s['by_sub'][sub]} 格，{len(ks)} 个键）：" + "、".join(f"{k} {v}" for k, v in ks[:top]))
    out += ["", "## 三、分册", "",
            "| 册 | 待审 | 全册格 | 人审率 | " + " | ".join(BIG[b][0] for b in BIG if by_big[b]) + " | 单子 | cv | 出单时间 | 瘦单格 |",
            "|---|---|---|---|" + "---|" * (sum(1 for b in BIG if by_big[b]) + 4)]
    pv = (prev or {}).get("vols", {})
    for v, d in sorted(s["vols"].items()):
        out.append(f"| {v} | {d['n']}{_d(d['n'], pv.get(v, {}).get('n') if prev else None)} | {d['cells'] or '—'} | "
                   f"{'%.2f%%' % (d['rate'] * 100) if d['rate'] is not None else '—'} | "
                   + " | ".join(str(d["by_big"].get(b, 0)) for b in BIG if by_big[b])
                   + f" | {d['rev']} | {d['cv']} | {(d['at'] or '')[:16]} | {d['slim']} |")
    cvs = Counter(d["cv"] for d in s["vols"].values())
    slim = sum(d["slim"] for d in s["vols"].values())
    out += ["", "## 四、数据说明", "",
            f"- 单子 cv 版本不齐：" + "、".join(f"{k}×{v}" for k, v in sorted(cvs.items(), key=lambda kv: str(kv[0]))) + "。比较各册时带着这个前提。",
            f"- 瘦单格（单子里只有成因码、没有 ref／ctx／库候选）{slim} 格：O 类落 O0、Z 类字组 id 记 `?`，是因为该册单子发布时没带细节；重出单后自动变细。",
            "- 统计的是线上单，落后于 ★main 包时数字也落后；重出单见 `粗校进度填数/sync_online_lists.py`。"]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ws", default=DEFAULT_WS)
    ap.add_argument("--text", default=DEFAULT_TEXT, help="文本号（线上单目录名）")
    ap.add_argument("--vols", help="册号范围，如 20-50,56；缺省全部")
    ap.add_argument("--from-dir", type=Path, help="离线：读目录里的 <册号>.pending.json，不连库")
    ap.add_argument("--extra-codepoints", type=Path, help="再叠一份 {另一码位: 本书码位} 的 yaml（还没推库的码位）")
    ap.add_argument("--prev", type=Path, help="上一份 summary.json，报告里写增减")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    vols = parse_vols(a.vols)
    lists, total, cp = load_dir(a.from_dir, vols) if a.from_dir else load_db(a.ws, a.text, vols)
    extra = {}
    if a.extra_codepoints:
        import yaml
        raw = yaml.safe_load(a.extra_codepoints.read_text(encoding="utf-8")) or {}
        extra = raw.get("codepoints", raw)
    rows = analyse(lists, cp, extra)
    s = summarize(rows, lists, total)
    prev = json.loads(a.prev.read_text(encoding="utf-8")) if a.prev else None
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.md").write_text(render(s, prev, a.top), encoding="utf-8")
    (a.out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["vol", "cell", "big", "sub", "key", "owner", "fix", "conc", "cause"]
    (a.out / "cells.tsv").write_text("\n".join(["\t".join(cols)] + ["\t".join(str(r[c]) for c in cols) for r in rows]) + "\n", encoding="utf-8")
    print(f"待审 {s['n']} 格，{len(lists)} 册 → {a.out}/report.md、cells.tsv、summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
