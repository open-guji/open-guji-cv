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

详见 overview `进度/字形库/12-v1旧刻例重键.md`；**B 段（挪绑漂移）之后 conflict_human 换了一批
（148:5:17/148:5:7/148:6:10/5:7:6，即/卽、歷/厯 同字异码位），处置与新执行步骤见
`进度/字形库/任务书-H-v1重键与撤例按B后重定.md` 对应的 done 单。**

## `--book`：同字异码位不算冲突（2026-09-27 加）

`glyph_v1_rekey.py` 加了 `--book <书 id>` 参数：v1 与人裁同格异字时，如果两边按该书
`codepoints` 配置（`core/book.py::BookSpec.codepoints`）算同一个字（如即/卽、歷/厯这类
「两形人几乎分不出、一本书该统一用一个码位」），就不进 `conflict_human`——照常重键，
并把 v1 这份的 `label`/`semantic`/`unicode_cp`/`admissions.char` 一并落到书级码位。
不给 `--book`（缺省）行为与加这条规则之前完全一样。用法：

```bash
GUJI_GLYPH_DB=... PYTHONPATH=. .venv/bin/python scripts/glyph_v1_rekey.py \
    artifacts/glyph_v1_rekey/siku_vol01_v1_map.jsonl --book vol01 --dry-run
```

`vol01.yaml` 目前的 `codepoints:` 还没有即/卽、歷/厯——库计数与整理本（光盘版）都倒向
卽/厯（详细数字见 done 单），要落地这条规则得先把这两对并进 `codepoints:`
（`别/別`、`内/內` 已在，`set_codepoints` 是整块替换、记得带上旧的两对一起写）。
