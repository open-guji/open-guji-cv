# HANDOFF X2 — Step4 字块质量标记：学出来的模型 vs 现行规则（overview #323）

分支 `claude/X2-step4-quality-1001`（基于 origin/main，**未合 main、未改任何默认行为、未写事件、未动字形库**）。
脚本都在 `scripts/experiments/step4_quality/`，结果 JSON 在其 `results/`。
注：cv 仓里读不到 #323 与 overview 盘点文档，按任务卡正文做；#323 评论权限没有，**本文件请代贴**。

## 一句话结论

**负结果。** 在人裁事件标签上，学出来的模型相对现行规则只有「小幅、不稳」的提升（同误报下检出 19%→25~29%，AUC 0.74~0.77）；
在 v2 验证层 77 条上，模型**反而更差**（误报 10~29%，规则 0%）。**不建议接入；先别换模型。**
真正的瓶颈不是模型，是**标签**：事件里的 `seg_defect` 大多描述的是旧产物的缺陷，现行产物上那格已经是干净完整的字（目视抽样 12 格未被规则标记的「缺陷」，多数是完整字）。
在没有「当时看的图」凭证的标签上学，学到的上限就是这么低。

## 数据与标签（实验①）

- 事件 `feedback/events/*.jsonl`，`kind=confirm`，`step∈{seed_admit,cell_shrink}`，仅 vol01/vol02（vol03 无云端产物，未用）。
- **事件 ≠ 独立标签**：任务书写的 ~1018 truncated / ~771 contaminated 是**事件条数**，同一格被反复记录；按键去重（取最后一条）后全部事件只有 **2277 个键**，其中缺陷键 **179**（truncated 111 / contaminated 68）。键上缺陷与干净/确认并存的 98 个（取最后一条，即视作「后来修好/确认了」）。
- 标签：缺陷=1：`seg_defect`+truncated/contaminated；强负=cell_shrink `clean`；弱负=`confirm`（人认出了字，没标缺陷——浅淡残渣可能漏标）。丢弃：not_a_char/skip/upstream_miscut 共 83 条事件。
- 为跑产物，只对**有标签的页**用 `guji pipeline keben_body_v2 --to cell_shrink` 在沙箱跑 Step1–4：vol01 95 页、vol02 132 页（含验证层 16 页），不碰正式 products、不跑整册。
- 绑定现行 v2 产物：2277 键 → **1869 绑定**（缺陷 174：vol01 94 / vol02 80；强负 194；弱负 1675）；`no_page_product` 399（页不在沙箱集，不是漂移，是我没跑）、`no_slot` 9、其余 0；**没有手工剔除**。
- **漂移无法逐条证明**：defect/clean 事件没有图块凭证（anchors 里全是 null）。能做的页级探针：vol02 的 confirm anchors（ink_bbox）对现行同键格 IoU>0.3 的比例，121 页均值 0.998（最低 0.75）→ vol02 **格位基本稳定**；但这只说明「格号没漂」，**不说明「缺陷还在」**（上面目视就是缺陷已被修）。vol01 无 anchors，未验证。

## 信号（实验②）

在 `CharExtractor.extract_page` 内**运行时挂钩**（monkeypatch，不改 extractor 源码、不动 cell_shrink 指纹）抓**裁紧前**图块上的原始量（不是二值）：
rule_bar/edge_blob/frame_bars/x_gap/off_center/上下带墨比/`_bar_crosses_column` 结果/aspect（bad_seg 的量）；
外加 7 组共 ~36 个特征：size（块宽高、格高 vs 页中位偏离）、ink（墨占比、行列占用、跨度）、cc（连通体数、最大/次大占比与几何位置）、edge（四边缘带墨比）、center（墨重心）、pos（slot、夹注子格、seal_region）。

## 结果（实验③，按页分组 5 折 × 5 种子，OOF 均值）

规则 = 7 个标记（rule_bar/edge_blob/frame_bars/wide_gap/off_center/boundary_ink/bad_seg）**任一为真**。

### A 集：全部 1869（弱+强负），正例 174

| | 检出率 | 误报率 | AUC | AP | 同规则误报下检出 | 同规则检出下误报 | 误报 5% 时检出 | 误报 10% 时检出 |
|---|---|---|---|---|---|---|---|---|
| **现行规则（任一）** | **19.0%** | **4.1%** | — | — | 19.0% | 4.1% | — | — |
| LR 仅原始量(9) | | | 0.700 | 0.26 | 22.4% | 2.9% | 25.3% | 37.4% |
| LR 全特征 | | | 0.743 | 0.27 | **28.7%** | 2.7% | 29.3% | 41.4% |
| HGB 仅原始量 | | | 0.671 | 0.22 | 17.8% | 4.4% | 20.1% | 33.9% |
| HGB 全特征 | | | **0.766** | **0.31** | 24.7% | **2.5%** | 26.4% | 37.9% |

各标记单独（A 集，检出/误报）：boundary_ink **17.8%**/2.2%；wide_gap 1.1%/1.2%；edge_blob 1.1%/0.1%；off_center 0%/0.7%；rule_bar、frame_bars、bad_seg 均 0%/0%。
→ 现行规则在这批标签上**几乎全靠 boundary_ink 一个标记**；「确定层」三个标记检出为 0——因为它们在 Step4 里已被「抹白/剥渣」处理掉，流到标记这一步时已不触发（与「当初 67 图块召回 100%」是两个世界）。

其它标签集（检出/误报，规则 vs LR 全特征 vs HGB 全特征 在规则同误报下的检出）：

| 集 | n / 正例 | 规则 | LR_all | HGB_all |
|---|---|---|---|---|
| B 强负 only | 368 / 174 | 19.0% @3.6% | 20.7% | 18.4%（AUC 0.717） |
| C vol02 格位稳定页 | 1079 / 73 | 19.2% @5.6% | 35.6% | 31.5%（AUC 0.814） |
| D vol01 | 700 / 94 | 19.1% @2.0% | 18.1% | 18.1%（AUC 0.731） |
| E 仅 truncated | 1801 / 106 | 18.9% @4.1% | 29.2% | 23.6% |
| F 仅 contaminated | 1763 / 68 | 19.1% @4.1% | 27.9% | 26.5%（AUC 0.797） |

读法：提升只在 vol02 / 弱负集上出现；**强负集（唯一「人明确判干净」的负例）上模型不优于规则**；vol01 上持平。子类上 contaminated（AUC ~0.80）略好于 truncated（~0.74）。正例 68~174，**95% 区间宽，上述 5~10 个点的差距不显著**。
PR：全表只报 AP 与固定误报点（完整 PR 点列可由 `analyze.py` 重算，OOF 分数未入库）。

### 实验④：v2 验证层 77 条（clean 73 + contaminated 4），训练集排除含验证格的页

| | 缺陷检出 (n=4) | 干净误报 (n=73) |
|---|---|---|
| **现行规则（任一）** | 0/4 | **0/73 = 0%** |
| LR 全特征 @规则同误报阈 | 0/4 | 19.2% |
| HGB 全特征 @规则同误报阈 | 1/4 | 9.6% |
| HGB 全特征 @误报10%阈 | 1/4 | 28.8% |
| LR 仅原始量 @10% | 1/4 | 8.2% |

验证层 4 条缺陷是「很淡的残渣」（M1 目视挑出），规则全漏；模型也基本抓不到（AUC 0.60），且干净格误报远高于规则的 0%。**77 条上规则：检出 0%、误报 0%；模型更差。**（n=4，只能说「没有证据显示更好」。）

## 消融（HGB，A 集 AUC 0.766 / AP 0.309，去一组 / 仅一组）

| 组 | 去掉后 AUC/AP | 只用它 AUC/AP |
|---|---|---|
| pos（slot/夹注/seal） | **0.746 / 0.267（掉最多）** | 0.641 / 0.21 |
| edge（四边缘带墨比） | 0.755 / 0.303 | 0.613 / 0.23 |
| ink（墨占比/跨度） | 0.755 / 0.312 | **0.710** / 0.22 |
| cc（连通体） | 0.762 / **0.291** | 0.703 / 0.19 |
| flag_raw（现行各量） | 0.759 / 0.313 | 0.671 / 0.23 |
| center | 0.763 / 0.313 | 0.653 / 0.17 |
| size | 0.770 / 0.308（去掉反而升） | 0.680 / 0.23 |

最有用：位置（slot 在列端更易缺陷）与墨/连通体几何；**现行 7 个标记的原始量是最弱的一组之一**（只用它们 HGB AUC 0.671，比 LR 0.700 还差）。no one group dominates，信号都很弱——也是标签噪声的症状。

## 接入方案（仅供决策，**不建议现在做**）

若以后有**干净标签**（见下）再做，接口如下，本分支未实现（避免动 cell_shrink 指纹）：
- `open_guji_cv/step4_quality/signals.py`：`SIGNAL_VERSION`、特征口径（本实验的 ~36 项，**必须在 Step4 内、裁紧前图块上算**，不能从 patch 回算——挂钩点已验证，见 `capture_features.py`）。
- `models/step4_quality/*.joblib` + 同名 `.json` 元数据（照 `shadow/model.py`：signal_version、特征表、训练书目与格数、cv commit、sklearn major.minor、sha256 指纹）。
- `CellShrinkParams.defect_prob: bool = False`（关着时字段不进 `model_dump`，指纹逐位不变，同 `shadow_veto` 做法）；开着时 `CharRec.defect_prob: float|None`，现行 flags **原样保留**，模型指纹进参数指纹。
- 下游：Step7 seed_admit 可把 `defect_prob` 当**只降不升的第二意见**（高于门槛的格不自动入库、落回人审，与 shadow_veto 同口径）；审查卡按 `defect_prob` 降序排队让人先看最可疑的；**不要**用它改几何或替换 flags。

## 要不要继续、怎么继续（给调度）

1. **先解决标签，不是模型**：审查页落人裁事件时**顺带存字块指纹**（`gold/drift.py::fingerprint`，M1 也提了），攒新标签再训。现有 179 个缺陷键里，估计相当一部分在现行产物上已不是缺陷。
2. 现行规则不要硬改阈值：它在**当前产物**上对「干净」几乎零误报（验证层 0/73），问题是对淡残渣检出低（boundary_ink 之外无贡献），那类缺陷下游代价也小。
3. 若要加信号，优先 `slot` 位置（列首/列末）与连通体几何——消融里这两类最值钱；但要在干净标签上重验。
4. 边界说明：只用 vol01/vol02 的 211 页小样本；vol03（有 67 条缺陷事件）无云端产物未用；LR/HGB 超参未调（样本小、调参只会过拟合）。

## 复现

```bash
# 环境：uv venv .venv --python 3.12 && uv pip install -e '.[console,torch,dev,shadow]' scipy opencc-python-reimplemented
# 工作区：guji-workspace 的 96mid1ogzk-… 稀疏检出 books/config/feedback/corpus + 标签页的 data_full/zongmu/<册>/<页>.png
export GUJI_WORKSPACE=<ws> GUJI_PRODUCTS_DIR=<沙箱>
python -m open_guji_cv pipeline keben_body_v2 vol02 --to cell_shrink --pages <页表> -w <ws> --jobs 4
python scripts/experiments/step4_quality/capture_features.py vol02 <页表> feat_vol02.pkl   # 挂钩重跑 cell_shrink 抓特征
python scripts/experiments/step4_quality/build_dataset.py dataset.pkl feat_vol01.pkl feat_vol02.pkl
VALIDATION=1 python scripts/experiments/step4_quality/build_dataset.py val77.pkl feat_vol01.pkl feat_vol02.pkl
python scripts/experiments/step4_quality/analyze.py dataset.pkl feat_vol01.pkl feat_vol02.pkl analysis.json
python scripts/experiments/step4_quality/val77.py
```
