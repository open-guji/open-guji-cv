# HANDOFF L2 — 印章页切分（overview #318 §1）

分支 `claude/L2-seal-seg-0930`（基于 origin/main，**不合 main**）。只做了阶段一（量）；阶段二**没写算法**（理由见末）。
全程云端沙箱：`GUJI_PRODUCTS_DIR=/tmp/sandbox_*`，ws 用 guji-workspace 的 96mid1ogzk 工作区，未碰正式 products。
页：vol03 p3、vol02 p3、vol04 p130、vol09 p70（四页都是 `occlusion` 判出的真印章页），基线干净页 vol03 p4/5/6/20。
Step1–4 用 `pipeline keben_body_v2 <册> --pages N --to cell_shrink` 现跑（每页约 30s，row_segment 占 25s）。

## 阶段一结论（先行）

**切分层确实被印章弄坏了，但坏的只有一处可量化的：Step4 字框被印章斑点撑宽；Step1–3 没有证据显示比干净页更差，且有一种「非坏、但应标注」的现象（幻影字格）。**

| 层 | 结论 | 证据 |
|---|---|---|
| Step1 版框/界行 | **基本没坏**。竖线没被印章墨当线；唯一可疑：vol03 p3 第 5 条竖线 x_at_top 偏 −19px、`bend_w80_max` 22（全书中位 6、门槛 7）——印章斑点抬高「界行弯曲」指标，但因果不确定：抹掉斑点后 w80_max 反而升到 42，其余 9 条线 ≤2.7px | `compare_vol03_p3.txt` |
| Step2 列射影 | 无明显问题（列图正常、`stamp_noise` 字段已存在 0.015） | 叠图 |
| Step3 切点 | **没有比干净页更差**。用「格上沿压在字身墨（连通块面积>150）上的比例」量切点切字：印章页遮挡格 13–25%、干净页 5–19%（p4 19%、p20 12%），同量级；抹斑点反事实 25%→28%，没改善。切点在反事实下会移 71/132 条>5px（中位 7px、最大 110px）——说明 DP 在印章/稀疏区**不稳**，但没有哪边更对的证据，不能说「印章把切点带歪」 | `metrics.txt`、`compare_vol03_p3.txt` |
| Step3 char/blank 判定 | **症状（非错切）**：vol03 p3 第 1 列真实文字「欽定四庫全書總目卷四」10 字止于 y≈1490，但 pos11–14 四格仍记 `char`（y 1561–2030），`char→blank` 分界（2030）落在印章下缘而不是文字终点；反事实下分界移到 1972。这 4 格是印章盖着的空白纸，被当字格（已有 occluded 闸兜底不入库）| `artifacts/l2_seal_seg/overlay_vol03_p3.jpg`（红=遮挡格）|
| **Step4 字框** | **确证被撑大**。框宽/列宽：遮挡格中位 **0.83–0.91**、>0.9 的占 **31–53%**；同页非遮挡格 0.68–0.75（>0.9 仅 0–11%）；干净页 p4/5/6/20 **0.66–0.67、>0.9 仅 0–1%**。`boundary_ink/edge_blob` 旗：遮挡格 10–21%，干净页 1–4%。因果：抹斑点反事实把 vol03 p3 遮挡格的 >0.9 从 43% 降到 21%、中位 0.88→0.78（一半以上归斑点）。框高仅轻微偏大（0.65→0.70–0.74）| `metrics.txt`、`vol03_p3_col1-2_*.png` |

逐页（框宽/列宽中位；>0.9 占比）：vol03 p3 0.88；43% ｜ vol02 p3 0.91；53% ｜ vol04 p130 0.83；36% ｜ vol09 p70 0.85；31% ｜ 干净页 0.66–0.67；0–1%。

症状层 vs 病因层：症状=字块（char_patch）裁得过宽、含大量斑点→识别层看到的是「字+半幅印泥」，这正是用户说的「定字裁决有印章信息、切分时没有」——**切分把印章信息整块吞进了图块，却没有任何标记**；病因=`cell_shrink`（component_owner 策略）按连通块归属取框，面积 ≤150 的斑点也算「墨」、又在 `occluded` 判据之外（occlusion 只在 seed_admit/入库闸用，Step3/4 完全不知道）。

复现：`scripts/experiments/l2_seal_seg/{overlay,boxsize,cutmetric,compare,make_clean}.py`（用法见各文件头）。

## 阶段二：方案（未实现）

预算到 $6 线，阶段一已用掉大半；「最小改动＋前后对比 M1 迁移评测」跑一遍 row_boundaries/touching_cuts/column_warp 评测要补产物（cloud_eval §4 估 20+ 分钟）且 cell_shrink 内部走 `clustering.extractor`，不是小补丁，所以只给方案，等你裁：

1. **首选（最小、零回归面）：只打标，不改几何。** `cell_shrink`/`row_segment` 产物加 flag `seal_region`（复用 `occlusion.page_occluded` 的判据，Step3 后、Step4 前算一次），Step4 框与 char/blank 判定不动。价值：识别层/定字裁决拿到「这格在印章里」的标记；幻影 char 格（上面 col1 pos11–14）可在该 flag 下按「格内大块字身墨=0」降成 blank。验证：非印章页产物**逐字节不变**（flag 只在遮挡格出现），天然不回归。
2. **次选：遮挡格内 Step4 取框只认面积>150 的连通块**（斑点不参与 bbox）。预期框宽 0.88→≈0.7（反事实已示上限：0.78）。需要动 `extractor` 的 component_owner，回归面大，要过 frame_strip/char_drop/crop 评测。
3. **不建议：** 遮挡区切点改等分——没有证据 Step3 切点在此区更差，且反事实切点本身就不稳（见上），等分是无依据的改动。
4. **切分裁决卡（cutline）标「印章区」：** 方案=卡片 meta 带 `seal_region`（从 char_index flag 读），卡面角标「印章区·斑点多，以字身为准」，且该区默认不计入「切点争议」优先级（该区切点本就不稳，会刷屏）。前端未做。

## 注意
- 样本仅 4 个印章页、同一条量法；cut 指标较粗（基线干净页本身 5–19%），只用来判「没有更差」，不是精度。
- 反事实「抹面积≤150 的连通块」也会抹掉字的碎点，Step1 的 w80 因此可能被改动——只当方向性证据。
- 环境：torch 用 CPU 轮子（`uv pip install torch --index-url https://download.pytorch.org/whl/cpu`），cuda 版 nvidia-* 下载会超时；cloud_eval.md 的 `.[torch]` 这一步云端要换。
- #318 发评论：overview 仓不在本会话 scope，未发，请代贴本文件「阶段一结论」。
