# -*- coding: utf-8 -*-
"""四庫 v1 旧刻例 → 现格号：按 `glyph_v1_map.py` 的形状对照表，一次性改 instance_id（字形库 12 / 任务书 H §二）。

    GUJI_GLYPH_DB=<glyph.db> PYTHONPATH=. python scripts/glyph_v1_rekey.py <v1_map.jsonl> \
        [--dry-run] [--table <对照表.tsv>] [--report <报告.json>]

## 改什么

v1 刻例的 id 是 `<册>:页:列:idx`（idx 从 0，还数进了页边格），来源 `vol01`（`pipeline_version='v1'`）。

- 对照表里 `status == exact`（同页、同列 ±1 的现役字块里逐像素几乎一样，≥0.995）的 → 改成现格号
  `<册>:页:列:格号[a|b]`，与播种/机器准入同一种写法（格号坐标，从 1），来源仍是 `vol01`；
  `instances.col/idx` 改成现格，证据里记 `rekeyed_from`，`exemplars.added_at` 触碰一下（库指纹与匹配器缓存靠它）。
- 其余仍是 idx 坐标的（`match`/`weak`/表里没有/下面各种冲突）→ **id 加 `v1:` 前缀**（`v1:<册>:页:列:idx`），
  来源挪到 `v1`（`pipeline_version='v1'`）。任务书定「形状对不上的不改」——格号不改，只是让出 `<册>:` 这个命名空间：
  不让的话，没对上的 `vol01:10:5:16`（idx 坐标）会挡住另一例该落到格号 16 的刻例（旧对照表上试算挡住 1,207 例）。
- 来源 `vol01` 改成 `pipeline_version='v2'`（格号坐标）。下游判「是不是 v1」按实例所属来源（`glyph_ledger._v1_sources`），
  认 `v1:` 前缀的地方（`v1_twin_ids`、crosscheck、triage、v1_map）两种写法都认，重键前后都能跑。

⚠️ `clustering/match._cell_parts` 只剥 `v2:`，`v1:` 前缀的 id 解析不出格——摘自证时这部分只能按字面 id 摘。
要它们也按同一物理格摘，R 道在 `_cell_parts` 里把 `v1:` 当作「idx 坐标、格号 = idx+1」认即可（cross 单）。

## 冲突

- 目标格已有人裁 `v2:<格>`：同字 → v1 这份是重复，撤；**异字 → 不改、不撤**，列进 `conflict_human` 等人定；
- 两例 v1 对到同一格：留 cov 高的，其余不改（`collide`）；
- 目标 id 被一个非 v1 实例占着（现库里没有这种情况）：不改（`blocked`）。
所有 v1 实例先挪到临时 id 再落到终点，链式平移（5→6、6→7…）不会撞主键。

## 幂等

对照表的键认裸 id 与 `v1:` 两种写法；已重键的（来源不再是 v1）跳过；已带 `v1:` 的留下者不再加前缀。跑两遍第二遍 0 改动。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

V1_SRC = "v1"
BOOK_SRC = "vol01"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _evict(c: sqlite3.Connection, iid: str) -> None:
    """同 `audit.evict_instance`，但不提交（整轮一个事务）。"""
    row = c.execute("SELECT g.glyph_id FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id "
                    "WHERE e.instance_id=?", (iid,)).fetchone()
    for t in ("admissions", "exemplars", "derived", "instances", "cluster_members"):
        c.execute(f"DELETE FROM {t} WHERE instance_id=?", (iid,))
    c.execute("DELETE FROM pairs WHERE inst_a=? OR inst_b=?", (iid, iid))
    if row:
        left = c.execute("SELECT count(*) FROM exemplars WHERE glyph_id=?", (row[0],)).fetchone()[0]
        if left:
            c.execute("UPDATE glyphs SET n_confirmed=? WHERE glyph_id=?", (left, row[0]))
        else:
            c.execute("DELETE FROM glyphs WHERE glyph_id=?", (row[0],))


def _rename(c: sqlite3.Connection, old: str, new: str) -> None:
    c.execute("UPDATE instances SET instance_id=? WHERE instance_id=?", (new, old))
    for t in ("derived", "exemplars", "admissions", "cluster_members"):
        c.execute(f"UPDATE {t} SET instance_id=? WHERE instance_id=?", (new, old))
    c.execute("UPDATE pairs SET inst_a=? WHERE inst_a=?", (new, old))
    c.execute("UPDATE pairs SET inst_b=? WHERE inst_b=?", (new, old))


def _bare(iid: str) -> str:
    return iid[3:] if iid.startswith("v1:") else iid


def plan(c: sqlite3.Connection, rows: list[dict]) -> dict:
    """只读推演。rename: [(旧 id, 新 id, cov)]（新 id 可能与旧 id 相同 = 原地认定）；
    keep: [(旧 id, 留下后的 id, 原因)]；dup: [(旧 id, 人裁 id)] 要撤的重复。"""
    src_of = dict(c.execute("SELECT instance_id, source_id FROM instances"))
    label = dict(c.execute("SELECT instance_id, label FROM instances"))
    v1_ids = {r[0] for r in c.execute(
        "SELECT i.instance_id FROM instances i JOIN sources s ON s.source_id=i.source_id "
        "WHERE s.pipeline_version='v1'")}
    by_key = {r["v1"]: r for r in rows}
    out = {k: [] for k in ("rename", "keep", "dup", "conflict_human", "collide", "blocked")}
    best: dict[str, tuple[str, dict]] = {}
    for iid in sorted(v1_ids):
        r = by_key.get(iid) or by_key.get(_bare(iid))
        if r is None:
            out["keep"].append((iid, "no_map"))
            continue
        if r["status"] != "exact" or not r.get("cell"):
            out["keep"].append((iid, r["status"]))
            continue
        cell = r["cell"]
        prev = best.get(cell)
        if prev is None or r["cov"] > prev[1]["cov"]:
            if prev is not None:
                out["collide"].append({"v1": prev[0], "cell": cell, "cov": prev[1]["cov"], "lost_to": iid})
            best[cell] = (iid, r)
        else:
            out["collide"].append({"v1": iid, "cell": cell, "cov": r["cov"], "lost_to": prev[0]})
    for cell, (iid, r) in sorted(best.items()):
        twin = "v2:" + cell
        if twin in src_of:
            if label.get(twin) == label.get(iid):
                out["dup"].append((iid, twin))
            else:
                out["conflict_human"].append({"v1": iid, "v1_char": label.get(iid), "cell": cell,
                                              "v2": twin, "v2_char": label.get(twin), "cov": r["cov"]})
            continue
        if cell in src_of and cell not in v1_ids:
            out["blocked"].append({"v1": iid, "cell": cell, "occupant_source": src_of[cell],
                                   "occupant_char": label.get(cell)})
            continue
        out["rename"].append((iid, cell, r["cov"]))
    for d in out["collide"]:
        out["keep"].append((d["v1"], "collide"))
    for d in out["conflict_human"]:
        out["keep"].append((d["v1"], "conflict_human"))
    for d in out["blocked"]:
        out["keep"].append((d["v1"], "blocked"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("v1_map", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--table", type=Path, help="对照表 tsv：旧 id / 新 id / 处置 / 字 / cov")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    from open_guji_cv.core.workspace import glyph_db_path
    db = str(glyph_db_path())
    rows = [json.loads(l) for l in open(a.v1_map, encoding="utf-8") if l.strip()]
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True) if a.dry_run else sqlite3.connect(db)
    p = plan(c, rows)
    label = dict(c.execute("SELECT instance_id, label FROM instances"))
    keep_final = {iid: ("v1:" + iid if not iid.startswith("v1:") else iid) for iid, _ in p["keep"]}
    moved = [(o, n, cv) for o, n, cv in p["rename"] if o != n]
    summary = {
        "v1_before": len(p["rename"]) + len(p["keep"]) + len(p["dup"]),
        "rekeyed": len(p["rename"]), "rekeyed_id_changed": len(moved),
        "rekeyed_in_place": len(p["rename"]) - len(moved),
        "evict_dup": len(p["dup"]), "keep_v1": len(p["keep"]),
        "keep_prefixed_now": sum(1 for o, n in keep_final.items() if o != n),
        "keep_by_reason": {}, "conflict_human": len(p["conflict_human"]),
        "collide": len(p["collide"]), "blocked": len(p["blocked"]),
    }
    for _iid, why in p["keep"]:
        summary["keep_by_reason"][why] = summary["keep_by_reason"].get(why, 0) + 1
    if not a.dry_run and (p["rename"] or p["dup"] or summary["keep_prefixed_now"]):
        now = _now()
        for old, _twin in p["dup"]:
            _evict(c, old)
        # 两段改名：先挪到临时 id，再落到终点——链式平移不会互相撞主键
        changing = [(o, n) for o, n, _ in moved] + [(o, n) for o, n in keep_final.items() if o != n]
        for old, _new in changing:
            _rename(c, old, "__rekey__:" + old)
        for old, new in changing:
            _rename(c, "__rekey__:" + old, new)
        for old, new, cov in p["rename"]:
            b, pg, col, sl = new.split(":")
            c.execute("UPDATE instances SET page=?, col=?, idx=?, updated_at=? WHERE instance_id=?",
                      (pg, int(col), int(sl.rstrip("ab")), now, new))
            ev = c.execute("SELECT evidence FROM admissions WHERE instance_id=?", (new,)).fetchone()
            if ev is not None:
                try:
                    evd = json.loads(ev[0]) if ev[0] else {}
                except ValueError:
                    evd = {}
                evd = {**(evd if isinstance(evd, dict) else {"_raw": evd}),
                       "rekeyed_from": old, "rekey_cov": round(float(cov), 4)}
                c.execute("UPDATE admissions SET evidence=? WHERE instance_id=?",
                          (json.dumps(evd, ensure_ascii=False), new))
            c.execute("UPDATE exemplars SET added_at=? WHERE instance_id=?", (now, new))
        # 来源：留下的 v1 归 `v1`（idx 坐标），`vol01` 改为格号坐标
        src = c.execute("SELECT * FROM sources WHERE source_id=?", (BOOK_SRC,)).fetchone()
        cols = [d[1] for d in c.execute("PRAGMA table_info(sources)")]
        if src is not None and not c.execute("SELECT 1 FROM sources WHERE source_id=?", (V1_SRC,)).fetchone():
            row = dict(zip(cols, src))
            row.update(source_id=V1_SRC, pipeline_version="v1", created_at=now,
                       notes="四庫 v1 旧管线刻例里没能按形状对到现格的那部分：idx 坐标（从 0），id 为 "
                             "`v1:<册>:页:列:idx`。2026-09 v1 重键时从来源 vol01 拆出。")
            c.execute(f"INSERT INTO sources ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                      tuple(row.values()))
        c.execute("UPDATE sources SET pipeline_version='v2', notes=? WHERE source_id=?",
                  ("v1 管线刻例，2026-09 按形状重键到现格号（格号坐标，从 1）；没对上的在来源 v1（id 带 v1: 前缀）。",
                   BOOK_SRC))
        for new in keep_final.values():
            c.execute("UPDATE instances SET source_id=? WHERE instance_id=?", (V1_SRC, new))
        c.commit()
    c.close()
    print(json.dumps(summary, ensure_ascii=False))
    if a.table:
        with open(a.table, "w", encoding="utf-8") as fh:
            fh.write("old_id\tnew_id\taction\tchar\tcov\n")
            for old, new, cov in p["rename"]:
                fh.write(f"{old}\t{new}\t{'rekey' if old != new else 'rekey_in_place'}\t{label.get(old)}\t{cov}\n")
            for old, twin in p["dup"]:
                fh.write(f"{old}\t\tevict_dup_of:{twin}\t{label.get(old)}\t\n")
            why = dict(p["keep"])
            for old, new in keep_final.items():
                fh.write(f"{old}\t{new}\tkeep_v1:{why[old]}\t{label.get(old)}\t\n")
    if a.report:
        a.report.write_text(json.dumps({"summary": summary, "conflict_human": p["conflict_human"],
                                        "collide": p["collide"], "blocked": p["blocked"], "dup": p["dup"],
                                        "keep": p["keep"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
