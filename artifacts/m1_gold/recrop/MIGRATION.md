# recrop 金标迁移（M1 道 C 组，2026-09-30）

## 结论

| | 条数 |
|---|---|
| 原金标（`instances/expected.json` 里 `seed=review_recrop`） | 40 |
| **迁移到 v2**（`instances/recrop_v2.json` 的 `items`） | **31** |
| 已失效（`recrop_v2.json` 的 `retired`，带原因） | 9 |

失效原因（9 条）：

| 原因 | 条数 | 条目 |
|---|---|---|
| 页图坐标系无图像凭证（整页失效） | 6 | vol01/28:4:20（图块与 old_bbox 同尺寸却偏 20px，坐标系自相矛盾）、vol01/50 整页 5 条（本页 2 个存着的图块落在别处、另 3 条连图块都没有） |
| 人当时看的页图在现行原图里定位不上（NCC<0.85） | 2 | vol01/15:1:20（0.843）、vol01/15:8:20（0.827）——页底贴版框，去斜后错位 |
| v2 Step3 没有对应格位（IoU<0.30） | 1 | vol01/9:3:20（人拖的框只有 33px 高，v2 没有这么矮的格） |

## 为什么 40/40「格位消失」

`scripts/eval_recrop.py` 原先现场重跑 v1 的 `CharExtractor.extract_page`，读
`./output/<册>/phase3_char_grid/<页>_char_grid.json` 与 `./output/<册>/<页>.png`。
云端只有页图（工作区 `output/vol01/*.png`，没有 `phase3_char_grid`），`index` 为空 → 40 条全是「格位消失」。
**这是空跑，不是算法回归。** v1 链已退役（CLAUDE.md），不能靠补 v1 产物修。

## 迁移判据（只看图像，不用算法一致性）

脚本：`artifacts/m1_gold/recrop/migrate_recrop.py`（可重跑，`--apply` 才写文件）。

1. **这批坐标系到底是哪张图的**：工作区 `output/<册>/<页>.png` 是 v1 页图（原图平移+去斜的裁剪，仍在）。
   人裁图块 `instances/patches/*.png` 是「人当时看的图」的现成证据——
   - 图块尺寸 == old_bbox 尺寸，且在页图 old_bbox 处找得到（NCC≥0.80、位置偏差≤8px）→ `exact`（实测 10 条：5:4:8、5:6:4、5:6:5、5:9:8、6:1:13、6:7:4、8:9:11、9:3:20、11:9:11、20:6:1；其中 9:3:20 后来死在第 3 步）；
   - 否则图块是后来刷新的紧框：要求它在页图里落在 old∪corrected 外扩 16px 内（NCC≥0.80）→ `nearby`（旁证，共 21 条，其中 20 条迁移）；另有 2 条迁移条目自己没有图块证据（5:5:16、15:9:20），靠同页其他条目的证据。
   一页内只要有一条 exact/nearby 且没有 conflict，这页页图坐标系就算与金标一致（页图是每页一张）。
2. **人当时看的那块页图在现行原图里找得回来**：取 old∪corrected 外扩 30px 的页图块（高斯 σ=2），
   在 `data_full/zongmu/<册>/<页>.png`（全局平移先验 ±50px）做归一化互相关，NCC≥0.85 才迁；
   换算用局部峰的平移（页图相对原图有去斜，整页平移不恒定，实测同页内偏移相差可达 19px，所以必须逐条局部配准）。
   31 条迁移条目的 NCC 范围 0.857~0.999（中位 0.954）。
3. **格位锚**：corrected_bbox（换算进原图坐标后）与 v2 Step3 格（`row_segment.cells[].quad_page` 外接框）取 IoU 最大者，
   ≥0.30 才锚，写 (col, slot)。31 条 IoU 0.56~0.91（中位 0.77）。
   顺带：全部 31 条满足 `v2 slot = v1 idx + 1`、列号不变——与 `cell_shrink.py` 里 `pos = idx+1` 一致，是独立旁证。

**没有用「v2 框与金标框一致」作任何一步的判据**（那是循环论证）。

## 坐标系

`recrop_v2.json` 里 `old_bbox` / `corrected_bbox` 是**原图坐标**、`raw_page_px@top-right`（`core/anchor.py` 口径，
x 从右往左量）。评测用 `tr2tl` 换回左上原点再在原图上数墨。v1 页图坐标（`*_v1`）留在 `retired` 与迁移记录里，不进评测。

## 文件

- `recrop_v2.json`（迁移后分片，本目录下 `recrop_v2.json` 与数据集 `char-segmentation/instances/recrop_v2.json` 同内容）
- `migrate_recrop.py`（迁移脚本）
- 评测：`scripts/eval_recrop.py` 默认读 v2（`--v1` 保留旧读法）；指标名与口径（含住 ±8px、盖墨 ≥0.95、IoU 仅趋势）一字未动。

旧 `instances/expected.json` / `items.jsonl` 里那 40 条**没有改动**（它们同时是 instance_quality 的一部分，见
`artifacts/m1_gold/instance_quality/`），只是 recrop 评测不再读它们。

## 已知局限

- 幸存者偏差：迁过来的是「v1 页图与原图对得上」的条目，被丢掉的 9 条里 6 条是 vol01/50、28 这类坐标系本身有疑问的页，
  所以 31 条不能读作「原 40 条的通过率」。
- 容差 `CONTAIN_TOL=8`、`INK_COVER=0.95` 不动（用户 2026-08-26 裁定拖框语义是「格位范围」）。
- 人拖框本身偏紧的老问题仍在（char_clustering_design.md 4039 行记过：vol01/50 c1 x 方向偏左 ~20px）。50 页已因此整页失效。
