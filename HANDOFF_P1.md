# HANDOFF P1 — 「正文 / 非正文」学习模型（2026-10-01，分支 `claude/P1-pagetype-1001`，未合 main）

## 结论（如实）
**有提升，但不大，且零误判是"选出来的"、不是"保证的"。** 默认关，接入点已做好。

- 现行规则（`classify_page_type`）在 page-type 金标 394 页上：**非正文检出 4/100**（只抓到 cover 2/2、label 2/2），职名 0/44、目录 0/47、blank 0/3，正文误判 0/294。
- 学习模型（HGB，Step1 产物 + 列墨信号，门槛 = 训练集多种子折外正文最高分）：
  **正文误判 0（页折 0/882 次评、块折 0/294、独立留出 0/146），非正文检出约 57%（页折 170/300）／46%（块折 46/100）**，其中职名 55%/41%、目录 63%/57%。
- 极少类（cover/label/colophon/edict）模型基本抓不到（样本 1~2 页），**保留现行规则**——接入时 `policy == "skip"` 的页不进模型。

## 数据与口径（边界 #300：只在测试集上、沙箱工作区、没碰正式 products）
- 金标 `open-guji-dataset/page-type`（active 394 页：body 294 / toc 47 / roster 44 / blank 3 / cover 2 / label 2 / edict 1 / colophon 1；注意 vol01 有 roster 44，没有 uncertain）。「非正文」= 金标 ≠ body。
- Step1 用 `step border_detect`，在**沙箱工作区**（`GUJI_WORKSPACE` 的 books/config 拷贝 + data_full 软链）现跑，约 3 s/页。先跑分层抽样 247 页（vol01 非正文全跑+正文隔页、vol02 正文隔页），后补跑另一半正文 146 页作**独立留出**，最后 394 页全有特征。
- 特征 `features_v1.csv`（`scripts/experiments/pagetype_model/`，394×36）；`extract.py` 生成，`evaluate.py`/`ensemble.py` 评测，`scripts/pagetype_model_train.py` 训练。
- 信号 `open_guji_cv/pagetype_model/signals.py`（`SIGNAL_VERSION="1"`，35 个）：现有 8 个页面特征 + Step1 产物量（列数、列宽变异、抬头框数、界行 w80 med/max、上下外框有无、单边框、折线条数）+ 按 Step1 列窗口切开的各列墨量分布（均值/CV/最小/最大/空列数、纵向占用、上下半页墨比、首/末列相对中位列）+ 版心字距 period（行投影自相关）及强度、各列 period 变异。

## 对比表（正文零容忍：门槛由训练集内部定，不看测试折）
| 方法 / 验证 | 正文误判 | 非正文检出 | 职名 | 目录 | 备注 |
|---|---|---|---|---|---|
| 现行规则（全 394 页） | 0/294 | 4/100 | 0/44 | 0/47 | 只有 cover 2/2、label 2/2 |
| **HGB step1+col**，页折 5折×3种子 | **0/882** | 170/300 | 73/132 | 89/141 | 本分支采用 |
| 同上，块折（每册页号连续 5 块整块留出） | **0/294** | 46/100 | 18/44 | 27/47 | 更严的时间/相邻页泄漏口径 |
| 同上，训在 247 抽样页 → 测另一半 146 正文 | **0/146** | — | — | — | 最高正文分 0.929 vs 门槛 0.9999 |
| LR page8+step1，页折 | 3/882 | 193/300 | 48/132 | 125/141 | 召回高但出误判 |
| LR all，页折 | 5/882 | 243/300 | | | 同上 |
| HGB all，页折 | 1/882 | 198/300 | 85/132 | 102/141 | |
| HGB page8（仅现有 8 特征），页折 | 1/882 | 129/300 | 22/132 | 97/141 | |
| 合议 LR+HGB(page8+step1)，页折 | 0/882 | 143/300 | 33/132 | 98/141 | AND，margin 0 |
| 合议三模型 AND，页折 | 0/882 | 98/300 | 26/132 | 66/141 | 更保守 |

完整 24 种配置 × (按册留出/页折/块折) 在 `scripts/experiments/pagetype_model/evaluate.py` 输出里（我跑的全文留在沙箱，关键行已摘在此）。

### 混淆矩阵（采用模型；页折三种子合计，300 非正文评测次/882 正文评测次）
| 金标＼预测 | 判非正文 | 放行（走现行规则） |
|---|---|---|
| body | 0 | 882 |
| roster | 73 | 59 |
| toc | 89 | 52 |
| blank | 6 | 3 |
| cover/label/colophon/edict | 2 | 16 |
（即每页平均：394 页里约 57 页非正文被早早拦在 Step1，其余沿用现行行为；全部正文放行。）

### 跨册（按册留出）
**这一项几乎没有信息量**：vol02 只有 cover/label 各 1 页非正文，职名/目录全在 vol01。vol01→vol02：正文 0/186 误判（多数配置），非正文 0~2/2；vol02→vol01：训练集里没有职名/目录，学不到。别把它当泛化证据；块折和 146 页留出才是。

### 消融（HGB 页折，正文误判 / 非正文检出 /300）
page8 1 / 129 → +step1 1 / 161 → +col 1 / 222 → all 1 / 198 → **step1+col 0 / 170**。
- 列墨信号（col 组）是最大增量：职名检出 22→95、目录 97→116（page8 → page8+col）。
- 最强单特征（与 body 的 AUC）：目录 `txt_ink` 0.996、`col_updown_min`（上半页墨/下半页墨取对数，最小列）0.993；职名 `col_ink_mean` 0.96。
- 采用 step1+col 不是因为召回最高，而是它是**唯一在所有口径下 0 误判**的配置——这是事后选择（24 个配置里挑），见下面的局限。

## 局限（务必读）
1. **零误判是在 24 个配置里按"0 误判"挑出来的**，有选择偏差。同族配置里有 1~5 次误判（页折 882 次评中）。独立留出 146 页（训练时没见过的正文）0 误判、最高正文分 0.929，离门槛 0.9999 很远，是目前最干净的证据，但**配置本身是看过这批页的 CV 后选的**。
2. **HGB 概率饱和**：门槛 0.9997（OOF 正文最高），门槛再加 0.02 检出归零。门槛是"实测正文极值"，不是概率。别按"把握度 99%"理解。
3. **难例**：vol01/63（正文短页，只有上半页有字，像目录）、vol02/38、vol01/157 是 OOF 里最高分的正文；职名里 vol01/89~94（压缩型）基本抓不到。这些是特征盲区，不是调参能救。
4. 样本全是 vol01/vol02（同一部书、同一版式）；**其他册（vol03+）没验证**，正文页版式（卷末短页、序跋）可能碰到训练没见过的形态。开之前应在目标册先跑 `eval` 看被拦页清单。
5. **已有更强、更晚的信号**：Step3 "弹性 DP 无解"（`unsupported_layout_columns`）在 294 正文上 0 误判、职名 39/44，但要等 Step2/3 之后；本模型的价值只是**更早（Step1 出口）拦一部分**，省掉后面几步在垃圾页上的计算和假失败。若 Step3 的闸已够用，模型的边际价值有限。

## 接入方式（默认关；关闭时产物逐字节不变）
书 yaml：
```yaml
params:
  border_detect_gate:
    pagetype_model: true          # 缺省 false
    # pagetype_model_path: ""      # 空=models/pagetype/pagetype_v1.joblib；路径不进参数指纹
```
- 开了：`policy != "skip"` 的页，模型判非正文 → `reject: page_type_model：…` → `admitted=False`；manifest 多一个 `pagetype_model` 证据（得分/模型指纹/信号版本）。信号缺失、Step1 无列、异常 → **弃权，不拦**。现行规则不动、也不被模型"放行"（只拦不放）。
- 关着：`BorderDetectGateParams` 的三个新字段与 manifest 的 `pagetype_model` 都用 `model_serializer` 在缺省时不进 dump。**实测**：沙箱 23 页（含职名/目录/正文/封面）`--force` 重跑，产物与改前逐字节相同（cmp 0 差异）；开关打开后 23 页中 5 页被拦（62、161、162、163、206），正文 6 页全放行。注意改了 `border_detect_gate.py` 源码，代码指纹变了，按引擎规则该步会显示一次"过期"，重跑后产物不变。
- 模型文件指纹进参数指纹（换模型本步过期）；`SIGNAL_VERSION` 或 sklearn major.minor 不符 → 拒绝加载。
- 重训：`python scripts/experiments/pagetype_model/extract.py --ws <沙箱> --out feats.csv && python scripts/pagetype_model_train.py --feats feats.csv`。

## 建议门槛与预期（四庫）
- **门槛就用模型文件里的（0.9997），不要放宽**；放宽一点点就开始出正文误判（LR 族已经出了）。
- 预期：vol01 里约一半的目录页、四成到五成的职名页被拦在 Step1（见上表）；vol02 正文 0 页被拦（186 页留出/CV 皆 0）；封面/书签仍由现行规则拦。**其它册没数据，不建议整体打开**，先按册在测试页上看被拦清单再开。
- 我的建议：**先不默认开**。价值（省后续步骤、少一批假失败）真实但有限；风险是零误判带选择偏差。等拿到 vol03 以后任一册的 ~50 页人裁正文页再确认一遍召回，再决定开不开。

## 环境/流程说明
- **overview 仓挂不上**：`add_repo open-guji-core/overview (push)` 被权限分类器拒绝（"Permission Grant"），按规则没有绕过、没重试。所以**读不到任务卡 #334 / 总方向.md / 16-各步决策改学习模型-盘点.md，也无法在 #334 评论**；本任务只按 prompt 里的描述做。看到这份 HANDOFF 的人请代为转述。dataset（push）、guji-workspace（read）已挂并克隆。
- 测试：新增 `tests/test_pagetype_model.py`（5 条，自造数据，不依赖仓外），连同 `test_border_detect_gate / test_page_survey / test_shadow_gate / test_suite_hygiene` 共 46 条通过。
- 成本远低于 $8（无 GPU、无整册跑、Step1 共约 400 页 × 3 s）。
