# H-evict8 交接（2026-09-30，overview#274）

用户 09-30 裁定：vol03 第 3 页 8 条人裁例子不入字形库。

## 结果
- 撤 **8** 例（全是 `v2:` 人裁例，无同格机器副本；字与裁定一致）：
  `v2:vol03:3:5:19 大`、`3:8:16 六`、`3:8:17 位`、`3:8:20 别`、`3:9:15 凶`、`3:9:16 悔`、`3:9:17 吝`、`3:9:19 視`。
- ws 提交：`open-guji/guji-workspace` main **`aa486dee`**（admissions / exemplars / glyphs / instances/v2 / evictions 五个 jsonl + 8 张 patch 删除，evictions +8 行）。
- 沙箱里 `--apply --expect 8` 后 `export_store`，与 ws 克隆 diff 只有上述文件。cv 代码未动。

## 两个要点
1. `find_and_evict.py` **撤不了这 8 条**：它们不在遮挡检测块内（沙箱现算 p3 cells，遮挡 136 格；c5 只到第15格、c8 到15、c9 到14），脚本 dry-run 对这 8 条给 0。所以按明确清单撤（脚本见文末，同一 `evict_instance` + `feedback_write_lock`，带 `--expect` 闸）。
2. **遮挡闸拦不住这 8 格**：`glyphdb_admit._is_occluded` 与 seed_admit `occluded_gate` 同用 `page_occluded` 的遮挡集，这 8 格不在其中；8 个事件（`evt_vol03-all-decide_000247/248/409–414`）`no_glyph_lib` 均为 false。事件已消费，不重放就不会再入库，但**重新消费这些事件会把它们收回库**。要根治：把这 8 格标 no_glyph_lib，或扩遮挡判据（需用户定）。

## 服务器值守（未执行）
db 里这 8 条还在。ws main 上 store 已撤，`guji-glyph-store-sync.timer` 拉取时理论上会把撤例三方合并进 db，**未验证**。值守先查 db 是否还有这 8 条，仍在则跑下面的脚本（存为 `evict_list.py` 放在 cv 仓根目录）：

```
GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python evict_list.py            # 干跑，应显示 n=8
GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python evict_list.py --apply --expect 8
```
撤完等下一轮 sync 导出，或手跑 `scripts/glyph_store_sync.py`。

## evict_list.py
```python
"""按明确 instance 清单撤库（H-evict8，2026-09-30）；与 find_and_evict.py 同一撤库路径（evict_instance + feedback_write_lock）。"""
import argparse, json, sqlite3, sys
from pathlib import Path
sys.path.insert(0, "/home/user/open-guji-cv")
REASON = "H-evict8 2026-09-30：vol03 第3页印章区人裁例子，用户 09-30 裁定不入字形库"
CELLS = {"3:5:19":"大","3:8:16":"六","3:8:17":"位","3:8:20":"别","3:9:15":"凶","3:9:16":"悔","3:9:17":"吝","3:9:19":"視"}
ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); ap.add_argument("--expect", type=int)
a = ap.parse_args()
from open_guji_cv.core.workspace import glyph_db_path, feedback_root
p = Path(glyph_db_path())
conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
rows = []
for cell, ch in CELLS.items():
    for iid, human in ((f"v2:vol03:{cell}", True), (f"vol03:{cell}", False)):
        r = conn.execute("SELECT a.provenance,a.char,s.pipeline_version FROM admissions a JOIN instances i USING(instance_id) LEFT JOIN sources s ON s.source_id=i.source_id WHERE a.instance_id=?", (iid,)).fetchone()
        if r is None: continue
        if not human and r[2] == "v1": continue
        rows.append({"instance_id": iid, "char": r[1], "provenance": r[0], "expected_char": ch, "char_ok": r[1] == ch})
conn.close()
rep = {"n": len(rows), "rows": rows, "applied": False}
if a.apply:
    if a.expect is not None and len(rows) != a.expect or not all(r["char_ok"] for r in rows):
        print("expect/字不符，整批不动", file=sys.stderr); print(json.dumps(rep, ensure_ascii=False, indent=1)); sys.exit(2)
    from open_guji_cv.clustering.audit import evict_instance
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.feedback.lock import feedback_write_lock
    with feedback_write_lock(feedback_root()):
        db = GlyphDB(str(p))
        try: rep["evicted"] = sum(evict_instance(db, r["instance_id"], reason=REASON) is not None for r in rows)
        finally: db.close()
    rep["applied"] = True
print(json.dumps(rep, ensure_ascii=False, indent=1))
```
