# 交接：D 道（geometry 版面几何评测）

## 空跑原因
1. `scripts/eval_geometry.py` 读已退役 v1 链：`./output/<册>/phase3_char_grid/<页>_char_grid.json`（列框 left_x/right_x + `grid.shear`）和 `output/<册>/<页>.png`。
   云端没有 `output/`，脚本遇到缺文件只 `missing += 1; continue`，0 页时 `evaluate([])` 照样打印空汇总 → **静默空跑**（E 道已用注册表 `needs=v1_output` 拦成 skipped）。
2. **更深一层**：金标本身也绑在 v1 帧上。39 页金标的 `image_size`（如 1717×2474）与工作区原图（如 2353×3053）**39/39 页都不同**——金标 x 量在 v1 预处理输出（透视校正+裁到版框）上。
   README 「金标不会过期」对「界行位置是图像性质」成立，但坐标帧不是原图；v1 帧不可复现（仓内 v1 链云端重放只有 2/39 页尺寸吻合），所以**金标不能原样用**。

## 迁移结果
- 39 页 → **30 页迁到原图帧**（body 17 / mixed 9 / roster 4；vol01 18 / vol02 12；界行 285→243，保留 85%），**9 页无法可靠迁移**标 stale（vol01/176、vol02/102、12、28、44、46、163、182、186）。
- 方法与判据（旧界行梳 × 原图墨列投影互相关 + 版框左缘先验 + 歧义判据 + 逐高度脊线拟合覆盖率 + 形状护栏；**全程图像内容，没用算法输出**）、新增字段、丢弃明细：`artifacts/m1_gold/geometry/MIGRATION.md`、`migration_log.json`。
- **改动文件（请统一提交）**
  - 金标：`artifacts/m1_gold/geometry/page-geometry/`（samples 30、items.jsonl 39=30 active+9 stale、metadata.json v0.4.0、README.md、report.json）——整体覆盖数据集仓 `page-geometry/`（我本地克隆里已同步改好）；旧金标留档 `geometry/pre_migration/`。
  - 引擎仓：`scripts/eval_geometry.py`（重写，读 Step2 column_windows）、`open_guji_cv/clustering/geometry_eval.py`（新增 v2 函数，v1 保留）、`open_guji_cv/clustering/page_geometry.py`（加 `coordinate_frame`/`frame_y` 默认字段）、`open_guji_cv/eval/registry.py`（仅 geometry 一行：去 `v1_output`）。注意 registry.py 工作树里还有同伴对别的行的改动，别整文件覆盖。
  - 迁移脚本：`artifacts/m1_gold/geometry/migrate_geometry_gold.py`（用法 `--old <旧分片> --out <新分片目录>`）。
- 判据验证：列带区间与 Step3 `quad_page` 对 vol01/149、33、40、66 最大差 1.4px；负对照（列带右移 6px/12px → rule_in_col 4.8%/84%）指标有分辨力。

## 新基线
- **n**：30 页 / 243 条界行（body 17 页 125 条、mixed 9 页 80 条、roster 4 页 38 条）。
- **命令**：`source /home/user/sandbox/env.sh; export GUJI_PRODUCTS_DIR=/home/user/sandbox/products_groupD GUJI_CACHE_DIR=/home/user/sandbox/cache_groupD; python -m open_guji_cv eval --from-raw --timeout 3000 run geometry`（产物齐后 6 s；直接跑脚本 `python scripts/eval_geometry.py ../open-guji-dataset/page-geometry --json-out r.json` 约 10 s）。报告 `runs/evals/geometry.json`。
- **沙箱范围**：只对这 30 页跑了 Step1–3（border_detect / column_warp / row_segment）到独立产物目录 `/home/user/sandbox/products_groupD`（没写主沙箱 products，也没碰 ws 正式 products；这样避开后台整册跑批的书级锁）。
- **指标**（注册表 ✓ 通过 1 / 失败 0，另有提示「9 条金标已过期」= 那 9 条 stale，属预期）：

| | 页 | 界行落入列框 | 全清页 | 残余倾斜 中位/P90 | 外侧漏墨 中位 | 净空 中位/P5/最小 |
|---|---|---|---|---|---|---|
| all | 30 | **0.00%**（0/729 采样点） | 30/30 | 1.5 / 2.9 px | 2.51% | 4.7 / 3.0 / 2.0 px |
| body | 17 | 0.00% | 17/17 | 1.5 / 2.8 | 1.85% | 4.5 / 3.0 / 2.1 |
| mixed | 9 | 0.00% | 9/9 | 1.6 / 3.4 | 5.15% | 5.0 / 3.2 / 2.3 |
| roster | 4 | 0.00% | 4/4 | 1.6 / 2.7 | 3.81% | 4.8 / 2.9 / 2.0 |

  坏页（>30%）0；外侧漏墨 >8% 的页 3/30（mixed 2 + roster 1）。`rule_in_col` 已触底，分辨力看净空与负对照。

## 与上次值对照
- **出处**：数据集仓 `page-geometry/README.md`「当前基线」与 `report.json`（v0.3.0，2026-08，v1 链；39 页 / 353 条）：

| 口径 | 页 | 界行落入列框 | 全清页 | 残余倾斜中位/P90 | 外侧漏墨中位 |
|---|---|---|---|---|---|
| 旧 v1（39 页全集） | 39 | 0.57% | 36/39 | 4.0 / 8.5 px | 4.07% |
| 旧 v1（取同一 30 页子集，由旧 report.json 逐页重算） | 30 | 0.23%（285 条） | 29/30 | 4.0 / 8.05 | 4.66% |
| **新 v2** | 30 | **0.00%**（243 条） | 30/30 | 1.5 / 2.9 | 2.51% |

- 「同 30 页」里旧 v1 body 17 页 0.00%、mixed 8/9 全清，新 v2 全清；方向一致（没有回归），但**不可当作改进幅度**：
  1. 列框口径变了：v1 竖直矩形 → v2 按高度取列带区间；
  2. **`residual_tilt` 不是同一个量**：v1 = 金标点去 shear 后三点极差（矫正残余），v2 没有 shear 概念，改为界行相对列带边缘偏移的三高度极差；4.0→1.5px 不能读成「矫正变好了」；
  3. `outside_ink` 窗口变了（金标界行跨度×frame_y vs v1 已裁版框整页）；
  4. 金标坐标帧与界行集合变了（243/285 条，位置由图像重量）；
  5. 被排除的 9 页多是 v1 时期指标较差的后半册页，存在幸存者偏差。
- README 里「vol01/166、174、198 是坏页」那段历史在新口径下 0 坏页（这三页新口径 rule_in_col 均 0%；166/198 在迁移集内）。

## 仍跑不了的原因
- 9 页金标（上面 stale 列表）**无法在原图上可靠定位**（梳子歧义/得分弱/先验矛盾），需要**在原图上人工重标**才能补回，迁移救不了；vol02 后半册金标因此只剩 12 页，样本小。
- 迁移后金标未经逐页人工复核（只抽查叠图），`label_origin=derived`；若要升格 human 需人过一遍。
- `eval --from-raw` 的缺产物判据查 Step3（row_segment），geometry 实际只需 Step2，多补 Step3（13 分钟大半是这个，机器被同伴占满）；没改 runner。
- `rule_in_col` 已触底 0%，作为回归门的灵敏度靠净空（中位 4.7px，最小 2.0px）与负对照，建议回归门改看 `clearance_min`/`clearance_p5`（未改，等你定）。
