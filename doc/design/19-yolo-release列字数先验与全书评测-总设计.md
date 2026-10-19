# 项目总计划：yolo release 列字数先验与全书评测

> 状态：**设计中**（待评审）｜立项：2026-10-19（洛杉矶）用户定｜依据：[doc/research/yolo_release_comparison.md](../research/yolo_release_comparison.md)
> 项目主力、各块负责人：待指派

## 一、目标

把对方 release（四库总目殿本全书 16,516 页，人工修过的 YOLO 切分）里**每一列有几个字**这个数用起来，分两处：

1. **当 Step3 的列字数先验。** 殿本 vol01–vol10 切分逐列字数全对率，从纯算法的 96.6% 提到 ≥98%。
2. **当全书评测金标。** 切分有了覆盖全册的逐列字数评测，现在的列切人裁只有 60 页。

另有一条「可以考虑」的第二阶段：

3. **原生 YOLO 当并格闸。** 用 YOLO 字框抓我们把横画字（三、二）切开的错，**不依赖 release**，所以对以后的书也能用。

## 二、不做什么

- 用户 10-19 定的不做：
  - 不拿 release 的字或图训字形和识别（release 的字和直接匹配整理本差不多，没有增量）；
  - 不给对方提改流程的建议。
- 不改 yolo_tool，不重训它的模型。
- **以后不会再有 release 这样的人工修补数据**，新书只有 yolo-tool 原生输出，模型可能小幅更新。所以：
  - 第 1、2 条只对殿本（96mid1ogzk）成立，**不写成通用机制的前提**；
  - 原生 YOLO 的字数不当先验用：实测逐列全对只有 64%，轻清理后 84%。
- 不处理整页列错位（vol05 p55、p123 这类）。那是 Step1 的问题，字数先验救不了，另立卡。
- 夹注列先不接先验：夹注列字数和格数的换算规则还没定，见 §七。

## 三、现状（实测）

| 项 | 数字 | 来源 |
|---|---|---|
| release 与 daizhige 列边界吻合 | 146,450 / 147,345 列（99.39%） | `research/yolo_release_compare/evaluate.py dzg` |
| release ↔ 我们页面对齐（vol04/05） | 401/401 页对上，逐列字数一致 97.3% | `cmp_md.py`，同上文档 §二 |
| 纯算法逐列字数全对（vol04/05 抽 100 页） | 870/901 = 96.6%，整页全对 85 | `evaluate.py test-b`（不带 feedback） |
| ＋release 字数先验（只写错的 21 列） | 885/901 = 98.2%，整页 94；15/21 列修好 | `evaluate.py prior` 后重跑 Step3–4 |
| ＋原生 YOLO 并格闸自动并格 | 883/901 = 98.0%，整页 93；13 列修好、新错 0 | `gate_merge.py`（cover≥0.5、conf≥0.25、框高≤1.3×中位） |
| 并格闸精度（100 页） | 抓到多切列 13/19，误报 0 | 同上；不加框高上限时误报 7 |
| 并格闸在 release 低分辨率底图上 | 3/23，误报 0 | 同上，测试 A |

## 四、分块

| 块 | 交付物 | 依赖 | 估时 |
|---|---|---|---|
| **A 列字数表** | 脚本：release 页 → 我们 vol 页 → 逐列 `{n_big, n_small, trusted}` 表；产物写进工作区 `corpus/release_colcounts/volNN.jsonl` | — | 约 2 小时（机器约 10 分钟） |
| **B 全书评测**（第 2 条） | dataset 分片 `char-segmentation/column-counts/`、`scripts/eval_column_counts.py`、`eval/registry.py` 登记 | A | 约 1.5 小时 |
| **C Step3 字数先验**（第 1 条） | `feedback/lookup.py` 新增一种来源；`row_segment` 消费；单测 | A；用 B 验收 | 约 3 小时（重跑 vol01–10 约 40 分钟，4 核） |
| **D 并格闸**（第 3 条，第二阶段，评审后再定开不开） | YOLO 推理（onnxruntime + `best.onnx`）产物；`row_segment` 闸规则；模型文件进指纹 | 用 B 验收 | 约 3 小时 |

A、B 可以一个人连着做；C、D 各一人。

## 五、总体架构与契约

```
release zip ──A──▶ <ws>/corpus/release_colcounts/volNN.jsonl ──┬─B─▶ open-guji-dataset/char-segmentation/column-counts/（金标）
                                                               └─C─▶ row_segment 列字数先验
yolo-tool best.onnx ──D──▶ products/<book>/yolo_boxes/pNNNN.json ──▶ row_segment_gate 并格规则
```

**A 的行格式**（一列一行，B、C 共用）：

```json
{"book":"vol04","page":12,"col":7,"n_big":19,"n_small":0,"raised":0,
 "trusted":true,"src":{"ch":10,"p":10,"col":7},"page_match":0.97,"why_untrusted":null}
```

- `col` 用我们的口径：右起，从 1 开始。
- `trusted` 要同时满足三条：
  - 页面匹配分 ≥0.9；
  - 这一列在 release 里与 daizhige 列边界一致；
  - 本页列数等于 9。
- `raised` 是抬头级数，从 release 首字比同页正文首字高出几格推得。C 要用它把字数换成格数，换算规则在 C 的分块设计里定。

**C 的优先级**：人裁 `column-slots` 高于 release 先验，release 先验高于纯算法。release 先验**不写成 `label_origin: human` 的裁决**，另起来源 `release_witness`，评测按来源分层统计。

**指纹**：
- A 的表不进 Step3 指纹，跟人裁一样靠显式失效驱动重跑；
- D 的 YOLO 模型文件 sha 进 `yolo_boxes` 指纹。模型会更新，更新后要用 B 重新验证阈值。

## 六、项目验收标准

1. **A**：vol01–10 正文页的页对应率 ≥98%。抽 30 页目视对齐无误。`trusted` 列占比要报出来（预期 ≥95%）。
2. **B**：`guji eval run column_counts` 在 vol04/05 那 100 页子集上复现 96.6% 基线（±0.1）。vol01–10 全册各出一份报告，按正文列、夹注列分开报。
3. **C**：
   - vol01–10 全册重跑后，`trusted` 正文列的逐列字数全对率 ≥98%；
   - 原来对的列新错 ≤0.1%；
   - 带人裁 `column-slots` 的列结果不变；
   - `tests/` 有用自造数据的单测，`test_suite_hygiene` 通过。
4. **D**（若开）：
   - 殿本 vol01–10 上并格闸抓到多切列 ≥60%，误触发 ≤1 列/100 页；
   - 北行日錄抽 50 页，人看全部触发列，误触发 ≤2；
   - 换模型后用 B 重测，再决定闸开不开。
5. 研究文档补上用户决定和最终数字；临时工作区（scratchpad 里的 wsA、wsB）不进仓。

## 七、风险

| 风险 | 应对 |
|---|---|
| release 约 0.6% 列本身不准 | 只采信 `trusted` 列；C 的先验与纯算法冲突、且冲突超过 2 字时不套，送审 |
| 字数换格数：抬头、列末留白、夹注的格语义 | C 分块设计先定规则，用 B 在三类列上分别验；夹注列本期不接 |
| 页对应错一页，整页先验全错 | A 只信匹配分 ≥0.9 的页；C 在整页超过 3 列冲突时整页不套 |
| D 的阈值是 100 页上定的，样本小；模型更新后会漂 | D 开之前用 B 在全册重标；模型 sha 进指纹，换模型自动判过期 |
| 先验让 Step3 产物大面积过期，重算成本 | 只对有先验且与现产物不一致的列显式失效，不改 Step3 代码指纹的其余部分 |

## 八、时间线

| 里程碑 | 预计 |
|---|---|
| 总设计评审 | 用户看过本文后 |
| A＋B 完成 | 指派后约 3.5 小时 |
| C 完成（含全册重跑） | A 完成后约 3.5 小时 |
| D 评估（是否开） | B 完成后约 3 小时 |
