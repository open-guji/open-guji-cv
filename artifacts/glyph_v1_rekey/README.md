# 四庫 v1 旧刻例重键（任务书 H §二，2026-09-26 云端准备）

| 文件 | 是什么 |
|---|---|
| `siku_vol01_v1_map.jsonl` | `scripts/glyph_v1_map.py` 在**新鲜的** vol01 产物（云端沙箱，cv `92e75e3` 起 Step1–4 全书 108 页）上跑出的形状对照：exact 14,867 / match 168 / weak 49 |
| `siku_vol01_v1_rekey_table.tsv` | 旧 id → 新 id 对照表（`glyph_v1_rekey.py --table` 出的，沙箱库上试跑时的处置） |
| `siku_vol01_sandbox_report.json` | 沙箱试跑报告（冲突、碰撞、留下的清单） |

服务器执行（几分钟）：

```bash
# 前提：vol01 Step1–4 已在同一 commit 上重跑新鲜（对照表的格号出自新鲜切分）
systemctl --user stop guji-glyph-store-sync.timer
cp output/glyph.db output/glyph.db.bak-$(date +%Y%m%d)            # 在书目录下
# 先把漂到邻格的人裁挪回来（否则 v1 与它们「同格异字」、重键跳过；沙箱实测 5 例）
GUJI_WORKSPACE=<书目录> PYTHONPATH=. .venv/bin/python scripts/glyph_crosscheck.py /tmp/cc.jsonl --drift \
    --v1-map artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl
GUJI_WORKSPACE=<书目录> PYTHONPATH=. .venv/bin/python scripts/glyph_rekey_drift.py /tmp/cc.jsonl --apply
GUJI_GLYPH_DB=<书目录>/output/glyph.db PYTHONPATH=. .venv/bin/python scripts/glyph_v1_rekey.py \
    artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl --dry-run      # 先看数，与沙箱报告对得上再跑
GUJI_GLYPH_DB=... PYTHONPATH=. .venv/bin/python scripts/glyph_v1_rekey.py artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl \
    --report /tmp/rekey_report.json
GUJI_GLYPH_DB=... PYTHONPATH=. .venv/bin/python scripts/glyph_v1_rekey.py artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl --dry-run  # 应 0 改动
python -m open_guji_cv glyph-db export     # 然后在沙箱 rebuild 一份比对条数、提交 glyph_store
systemctl --user start guji-glyph-store-sync.timer
```

详见 overview `进度/字形库/12-v1旧刻例重键.md`。
