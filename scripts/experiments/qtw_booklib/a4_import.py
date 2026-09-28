"""a4：人裁写成事件（走单写者锁）＋ 代表刻例进全唐文书级库。

  GUJI_WORKSPACE=$QTW_WS python a4_import.py events <imp_dir> [--dry-run]
  GUJI_WORKSPACE=$QTW_WS python a4_import.py lib    <imp_dir> [<mixed.db>]

events：
- 一个源文件一个批次 `qtw-human-<batchN>-20260927`；每格一条 `kind=confirm` 事件，
  `payload.v` = confirm（带 shape）或 damaged（看不清，guess 空）；
- 簇裁决展开成逐格，`payload.cluster` 带簇 id、`payload.src` 带「文件:行」；
- `reviewer` = 用户（校对者），`actor=user`，`ts` = 页面点击时间；
- 进库口径按用户 09-27 22:20Z（覆盖 22:15Z 的「每字 1～3 例」）：进库名单是 a3b_select 的
  `lib_keys.json`（抽查闸＋对齐交叉核＋每字上限），名单外的确认格 `no_glyph_lib=true`，
  `payload.lib_skip` 写原因（照常算人裁、记事件，但不进库）；
- 写入口是 `EventLog.append`：乱码/非单字闸 + `feedback_write_lock`（人裁单写者锁）。

lib：
- `$QTW_WS/output/glyph.db` 新建，声明本书 edition（`quantangwen`），用 `glyphdb_admit`
  （控制台同一条消费器）把代表格进库，导出成 `$QTW_WS/output/glyph_store`（本书真源）；
- 全唐文 glyph_match **只用自有库**（不挂四庫）。给了 `<mixed.db>` 时另建一份
  「自有＋四庫」对照库（`rebuild_from_store(..., extra_stores=[四庫 store])`），只做对照、不给管线用。
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qb_common import QTW_EDITION, QTW_WS, SIKU_STORE  # noqa: E402

REVIEWER = "sheldonli.dev@gmail.com"      # 校对者 = 用户（控制台账号口径：email）
FILES = {"batch1": "batch1-partial.jsonl", "batch2": "batch2-v2-partial.jsonl",
         "batch3": "batch3-v3-partial.jsonl", "batch5": "batch5-v5.jsonl"}
VIA = "H-qtw-booklib-0927"


def batch_name(tag: str) -> str:
    return f"qtw-human-{tag}-20260927"


def build_events(final, reps: set[str], skip: dict[str, str]):
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    log = EventLog(QTW_WS / "feedback")
    by = collections.defaultdict(list)
    for r in final:
        if r["import"]:
            by[r["batch"]].append(r)
    evs = []
    for tag, rs in sorted(by.items()):
        b = batch_name(tag)
        base = log.latest_seq(b)
        for i, r in enumerate(sorted(rs, key=lambda x: x["line"]), 1):
            bk, pg, col, slot = r["key"].split(":")
            p = {"v": r["act"], "cluster": r.get("cluster"), "pool": r.get("pool"),
                 "src": f"{FILES[tag]}:{r['line']}", "client_ts": r.get("t"), "via": VIA}
            if r["act"] == "confirm":
                p.update(shape=r["char"], no_glyph_lib=r["key"] not in reps,
                         lib_rep=r["key"] in reps, per_cell=bool(r.get("per_cell")))
                if r["key"] not in reps:
                    p["lib_skip"] = skip.get(r["key"], "每字进库上限")
            else:
                p.update(guess=None, note="看不清（审查页 blur / char:null）")
            ts = (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["t"] / 1000))
                  if r.get("t") else None)
            evs.append(make_event(b, base + i, "confirm",
                                  EventTarget(step="seed_admit", unit="cell", key=r["key"],
                                              book=bk, page=int(pg), col=int(col), slot=int(slot)),
                                  p, actor="user", source_format="z15-jsonl", ts=ts,
                                  reviewer=REVIEWER))
    return log, evs


def cmd_events(d: Path, dry: bool):
    final = [json.loads(l) for l in open(d / "final.jsonl", encoding="utf-8")]
    L = json.load(open(d / "lib_keys.json", encoding="utf-8"))
    reps = {k for ks in L["lib"].values() for k in ks}
    skip = {k: "；".join(v["why"]) for k, v in L["not_in_lib"].items()}
    flagged = skip
    log, evs = build_events(final, reps, skip)
    stat = {"events": len(evs), "by_batch": dict(collections.Counter(e.batch for e in evs)),
            "by_v": dict(collections.Counter(e.payload["v"] for e in evs)),
            "lib_rep": sum(bool(e.payload.get("lib_rep")) for e in evs), "reps_expected": len(reps)}
    print(json.dumps(stat, ensure_ascii=False, indent=1))
    assert stat["lib_rep"] == len(reps), "代表格没全部落到事件里"
    if dry:
        return
    n = log.append(evs)
    print("appended", n)
    json.dump({**stat, "appended": n, "flagged_not_in_lib": len(flagged)}, open(d / "events_stat.json", "w"), ensure_ascii=False, indent=1)


def cmd_lib(d: Path, mixed: str | None):
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store, rebuild_from_store
    from open_guji_cv.feedback.consumers import glyphdb_admit
    from open_guji_cv.feedback.events import EventLog
    db_path = QTW_WS / "output" / "glyph.db"
    store = QTW_WS / "output" / "glyph_store"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = GlyphDB(db_path)
    db.set_book_edition(QTW_EDITION, title="欽定全唐文（清嘉慶二十一年揚州刻本內府本）")
    db.close()
    log = EventLog(QTW_WS / "feedback")
    evs = [e for b in log.batches() if b.startswith("qtw-human-") for e in log.read(b)]
    res = glyphdb_admit([(e, None) for e in evs], db_path=str(db_path))
    print("admit:", {k: getattr(res, k) for k in ("n_events", "added", "updated", "skipped", "no_lib")},
          "errors:", res.errors[:5])
    log.mark_consumed("glyphdb_admit", evs, note=f"{VIA}: 全唐文书级库首建")
    db = GlyphDB(db_path)
    c = export_store(db, store)
    db.close()
    print("export:", c)
    r = rebuild_from_store(store, db_path)          # 只用自有库：从真源重建一次，与服务器上的路径一致
    print("rebuild(自有):", r)
    if mixed:
        rm = rebuild_from_store(store, mixed, extra_stores=[SIKU_STORE])
        print("对照库(自有+四庫):", rm)
    json.dump({"admit_added": res.added, "admit_no_lib": res.no_lib, "admit_errors": res.errors,
               "export": c, "rebuild": r}, open(d / "lib_stat.json", "w"), ensure_ascii=False, indent=1,
              default=str)


if __name__ == "__main__":
    act, d = sys.argv[1], Path(sys.argv[2])
    if act == "events":
        cmd_events(d, "--dry-run" in sys.argv)
    else:
        cmd_lib(d, sys.argv[3] if len(sys.argv) > 3 else None)
