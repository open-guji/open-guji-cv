# HANDOFF Z-rr — 入人八字形分类器（overview#442，父卡 #437）

分支：cv `claude/Z-rr-1006`（只加 `research/char_groups/rr/` 与本档、README 一段）；dataset `claude/Z-rr-1006`（`char-groups/rr/` 加 `clf_eval.json`、`clf_loo_probs.json`、`clf_candidates.json`，README 加一节）。
没改 Step 与 code_deps，没跑整册、没打包导入，没写事件/排除名单/字形库；没合 main、没开 PR。

## 结果（离线，详表在 dataset rr/README「字形分类器」）
- 方法：二值化→去碎点→24×24 网格 + 行列投影 + 顶部带结构，RandomForest。**训练只用弱标签（C 档 1,860 格），不含强真值格、不含 vol04**；阈值事先定 0.5/0.8。
- 强真值 A+B 46 格：**给字 42 格全对**（0/42，95% 上界约 7%）；p≥0.8 时 37 格全对。弃权 4 格（0.5）。val=vol04：A 11/11 给 11 对 11，B 2 格给 1 对 1。
  按册：vol02 15/15、vol03 15/18 给（3 弃权）全对、vol04 12/13 给全对。
- 对照：只用 7 个手工结构特征（`hand`）p≥0.5 错 3 格；logreg 错 3 格且 p≈1.0（过自信）。结论：要网格投影的 rf。
- 已放行格（弱标签，循环）按册留出：p≥0.8 给字 2,094 格，与放行字不一致 **1 格**（`vol08:36:2:15`）；p≥0.5 不一致 11 格。说明分类器与现行放行同口径，不是放行错率。
- 待审 34 格：p≥0.8 的 9 格，其中与整理本一致 6 格可作「放出」候选；不少待审格根本不在组内（流愧然大穴太丶），分类器无「都不是」类，只能靠弃权。

## 诚实交代
1. 放行错率仍量不出；强真值多是难例，不是随机样本；少数字「入」10 格、「八」9 格，样本小。
2. 我在定稿前跑过一次含 vol04 的 logreg/rf 对照表，之后没据此改特征或阈值，但 val 并非严格盲。
3. 噪声字块（整页竖线、斑点）无质量闸，应弃权；没试 CNN（无 torch）。
4. vol01 22 题无图，没接。

## 建议下一步（交总管）
- **请用户裁约 17 格**（量少而精）：`clf_candidates.json` 里「分歧」11 格 + 「待审:整理本=分类器」p≥0.8 的 6 格。裁完：分歧格里放行字错几个＝放行错率的第一个直接证据；6 格对＝可放出。我没出审查页（review_pages.py 在 G1 分支，用户累）。
- 之后给 Step6 接分类器：产物记（组名、字、p），Step7 只当一路证据；接之前先加质量闸（线噪/斑点）与「非组内」弃权。
- 复现：`pip install scikit-learn opencv-python-headless scipy`；`cd research/char_groups/rr && python3 run_final.py`（`GUJI_DATASET` 指 dataset）；`python3 loo_weak.py`。
