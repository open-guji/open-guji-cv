# 四庫 v1 旧刻例重键（任务书 H §二，2026-09-26 云端准备）

| 文件 | 是什么 |
|---|---|
| `siku_vol01_v1_map.jsonl` | `scripts/glyph_v1_map.py` 在**新鲜的** vol01 产物（云端沙箱，cv `92e75e3` 起 Step1–4 全书 108 页）上跑出的形状对照：exact 14,867 / match 168 / weak 49 |
| `siku_vol01_v1_rekey_table.tsv` | 旧 id → 新 id 对照表（`glyph_v1_rekey.py --table` 出的，沙箱库上试跑时的处置） |
| `siku_vol01_sandbox_report.json` | 沙箱试跑报告（冲突、碰撞、留下的清单） |

服务器执行（几分钟）：

```bash
systemctl --user stop guji-glyph-store-sync.timer
cp output/glyph.db output/glyph.db.bak-$(date +%Y%m%d)            # 在书目录下
GUJI_GLYPH_DB=<书目录>/output/glyph.db PYTHONPATH=. .venv/bin/python scripts/glyph_v1_rekey.py \
    artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl --dry-run      # 先看数，与沙箱报告对得上再跑
GUJI_GLYPH_DB=... PYTHONPATH=. .venv/bin/python scripts/glyph_v1_rekey.py artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl \
    --report /tmp/rekey_report.json
GUJI_GLYPH_DB=... PYTHONPATH=. .venv/bin/python scripts/glyph_v1_rekey.py artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl --dry-run  # 应 0 改动
python -m open_guji_cv glyph-db export     # 然后在沙箱 rebuild 一份比对条数、提交 glyph_store
systemctl --user start guji-glyph-store-sync.timer
```

详见 overview `进度/字形库/12-v1旧刻例重键.md`。
