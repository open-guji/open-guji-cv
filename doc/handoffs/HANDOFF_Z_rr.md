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

## 追加（第二步：质量闸 + 非组内弃权，+17 格审查页）
- 审查页 17 格：https://claude.ai/artifact/D7epPjixiwqPTt3g2PXZDz （卡 id 冻结 dataset `char-groups/review/rr17_cards.jsonl`，脚本 `research/char_groups/rr/review_rr17.py`，复用 G1 的 `review_pages.py`，已拷入本分支，内容与 G1 分支一致）。收回用 `harvest_verdicts.py`。
- `rr/clf2.py`：质量闸（长线/散斑/贴边）+ 第 4 类「其他」。结果与局限见 dataset rr/README「质量闸与非组内弃权」与 `clf2_eval.txt`。要点：强真值不变（41–42/46 全对）；负例 5 折拦下 36–37/37（但负例只有久火尺今又，有同字泄漏）；弱标签放行格上阈值 0.5 弃权 0–4%，0.8 弃权 10–15%，**建议 0.5 + 质量闸**；闸阈值是看候选格定的，无独立验证。

## 追加（第三步：17 格人裁收回 + 最终评测）
- 裁决：八 6、人 5、入 4、看不清 2。已存 dataset `char-groups/review/rr17_verdicts.jsonl`，用 `rr/apply_rr17.py` 并进 `rr/items.jsonl`（15 格 A 档，2 格 X_unclear；`metadata.json`/格数表未重算）。评测脚本 `rr/run_v2.py`，结果 dataset `rr/clf_eval_v2.{json,txt}`，详述见 dataset rr/README「17 格人裁收回与最终评测」。
- **放行错**：分歧格里放行字被推翻 1/9（`vol09:134:9:5` 放行八→入，**整理本也错**）；随机样本 0/33。分歧格是挑出来的，不外推。
- **分类器在分歧格上 8/9 错**（含 `vol08:36:2:15` p=0.88），只能「分歧→送审」，不能改字。待审 6 格（整理本=分类器 p≥0.8）人裁 6/6 全对。
- 强真值 61 格（4 类+闸，p≥0.5）：给字 50 对 47（94.0%，CI 83.5–98.7%）；非分类器挑出的原 46 格 40/40（CI 91–100%）。p≥0.8 不更安全（弃权 28%，仍错 1）。3 类版在 vol04 错 2 格，4 类版弃权，别用 3 类。
- 建议：阈值 0.5 + 质量闸 + 4 类；分歧送审、整理本=分类器且 p≥0.8 放出待审（小规模先试）；不让分类器单独改字/放行。合 main：cv 只加研究脚本与 doc，不碰 Step/code_deps，可合；要不要合由总管定（我没合）。
