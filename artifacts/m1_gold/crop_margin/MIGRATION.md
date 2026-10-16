# crop_margin 金标迁移（M1 道 C 组，2026-09-30）

## 结论：**整分片退役（已失效，不迁移、不重冻）**

| | |
|---|---|
| 原金标 | `char-segmentation/crop-margin/expected.json`：394 页（vol01 206 + vol02 188）每页 top/bottom/left/right 残留像素 |
| 迁移 | 0 |
| 已失效 | 394（全部） |

## 为什么跑不了

`scripts/eval_crop_margin.py` 量的是 **v1 的 s3 裁剪步**（`content_bounds._find_h_frame` 找外框线，
把整页图裁到「版框外缘」）**裁完之后**图像四边还剩多少空白纸边。它需要 `--intermediate-dir`
（`preprocess --keep-intermediate` 的 `vol*/s3_crop/*.{tif,png}`）。不给这个目录，脚本只回显既存金标、不评测
（所以注册表把它标成 `needs=("products","intermediate")`，云端 `eval list` 显示「需要 s1~s6 中间产物目录」）。

## 为什么不能迁到 v2

1. **被测的那一步在 v2 里不存在。** v2 链（`keben_body_v2.yaml`）没有「整页裁到版框外缘」的步骤：
   Step1 `border_detect` 只**量**边框（不裁图），Step2 `column_warp` 直接从**原图**按列射影出列图。
   原图上没有「裁剪」，也就没有「裁完残留多少纸边」这个量。
2. **金标没有可以迁的东西。** 金标是「当时 s3 输出图的四边残留」（标量），不是人标的位置，也没有图像指纹；
   s3 输出图本身（`output/vol*/s3_crop`）不在工作区，只剩页图 `output/<册>/<页>.png`（它是 s3 之后的图）。
   要重算也只能对 v1 链跑，而 v1 链已退役（CLAUDE.md「v1 命令仍可用，但那条链已退役，不要在它上面加新东西」）。
3. **这把尺子要防的失效模式，v2 由别的评测接管了。** 它当年查出的根因是「外框线探测彻底找不到线 → 那一侧完全不裁」。
   在 v2 里同一类失手表现为 Step1 外框探测不出 / 内外框错位，由 `border-detection/` 分片
   （`bottom-offset` 等、外框「条外必须是纸」闸 `_paper_beyond`）与注册表里的 `page_crop`（上游裁切，另一组负责）覆盖。

## 与 doc 上次值的关系（仅留档，无新基线）

- README「当前基线（2026-08-27，两册 394 页全扫）」：**93 页 / 394（24%）残留 ≥50px，正文页 66/294（22.4%）**；
- README「修复结案（2026-08-28，路线 A 整体迁移）」：全书残留 ≥50px 的页 **93 → 6**（剩 4 页左右方向、2 页封面 vol01/2 vol02/2）；
  `doc/pipeline_handbook.md` §12 同数。
  这两个数都是 v1 s3 裁剪的读数，随该步退役，**没有 v2 对应值，也不应该硬造一个**。

## 落实

- 评测脚本**不改**（保持 `--intermediate-dir` 语义；有人把 v1 中间产物拷回来时仍可跑）。
- 注册表 `crop_margin` 行：`needs` 不动（仍是 `intermediate`，云端 skipped）；`note` 补了一句退役原因。
- 数据集侧建议：`crop-margin/metadata.json` 的 status 改「退役（v1 s3 步已不存在）」；本次**没有**改数据集（云端无 push，且金标文件本身无害）。
