# doc/design：设计文档索引

各步、跨步的设计与方案。**只放仍然有效的**：已经被取代、只剩历史价值的设计和一次性实测记录，2026-10-18 已移到 [../archive/design/](../archive/design/)（文件名不变，代码注释里按文件名还能找到）。
调研、文献、负结果在 [../research/](../research/)；格式规范在 [../formats/](../formats/)；整理一册书的操作在 [../runbook/](../runbook/)。

## 总览与流程

| 档 | 内容 |
|---|---|
| [流程与模块.md](流程与模块.md) | 管线几步、每步由哪些模块组成、输入输出、出口闸 |
| [Step5-7-操作一览.md](Step5-7-操作一览.md) | Step5／6／7 现在各做哪些操作（按代码整理，10-18） |
| [05-三模式管线方案.md](05-三模式管线方案.md) | 古籍／现代竖排／现代横排三种模式共用一条管线（已落地） |
| [12-重跑粒度-格级复用设计.md](12-重跑粒度-格级复用设计.md) | 重跑粒度从页到格，只对变了的格跑 Step4–8（已实现，`core/reuse.py`） |
| [16-各步决策改学习模型-盘点.md](16-各步决策改学习模型-盘点.md) | 各步写死阈值改「多信号＋学习模型」的盘点与实验排序 |
| [19-yolo-release列字数先验与全书评测-总设计.md](19-yolo-release列字数先验与全书评测-总设计.md) | 殿本逐列字数金标（daizhige × release 双源一致）、Step3 格位先验、原生 YOLO 并格闸（执行中） |
| [模块化后续计划（待Mila定）.md](模块化后续计划（待Mila定）.md) | 包级模块化剩下的 42 条向上依赖怎么分批（未执行） |
| [03-Step页面统一设计.md](03-Step页面统一设计.md) | 控制台各 Step 页面五点结构与复用组件规范 |
| [M9-平台粗校-调研与总设计.md](M9-平台粗校-调研与总设计.md) | M9（GUJI-636）平台粗校：一册从选书到 0.1.x＋待审单的现状、问题、八个领域的输入输出验收、存放原则、波次节奏、性能需求书（待评审） |

## 切分（Step1–4）

| 档 | 内容 |
|---|---|
| [row_boundaries_design.md](row_boundaries_design.md) | 列内字格纵向边界（弹性 DP），切分 v2 的 Step3 |
| [step3_touching_and_jiazhu.md](step3_touching_and_jiazhu.md) | 粘连切分与双行小注：测试集、实验、路线 |
| [peak_line_search.md](peak_line_search.md) | 投影峰匹配找版框线（独立工具，未接生产） |

## 字形库与识别（Step5–7）

| 档 | 内容 |
|---|---|
| [glyph_db_first_design.md](glyph_db_first_design.md) | 字形库优先的增量识别（取代先聚簇再定字） |
| [glyph_match_stack.md](glyph_match_stack.md) | 字形相似度匹配栈：四层链条、算法、测试集 |
| [glyph_canonical_format.md](glyph_canonical_format.md) | 字形图块统一存储格式（256×256） |
| [glyph_cnn_explained.md](glyph_cnn_explained.md) | 拆字识别（CNN 候选）给非机器学习读者的说明 |
| [glyph_set_roadmap.md](glyph_set_roadmap.md) | 字形套：共享度量网络＋可插拔原型库 |
| [charset_and_lm.md](charset_and_lm.md) | 字表标准与语言模型混合 |
| [variant_strategy.md](variant_strategy.md) | 异体字策略：忠于刻本字形下的识别与资料积累 |
| [14-准确率优先-Step6与Step7重设计.md](14-准确率优先-Step6与Step7重设计.md) | 准确率优先：铁证＝同形人裁实例、Step6 去 n-gram |
| [15-人裁锚定与重切后重绑定.md](15-人裁锚定与重切后重绑定.md) | 人裁带锚、重切后自动改绑（P1–P3 已做） |
| [review_feedback_loops.md](review_feedback_loops.md) | 人裁三条回流环：切分层、匹配栈、准入 |

## 字形库、语料库的版本与共享

| 档 | 内容 |
|---|---|
| [语料库版本化方案.md](语料库版本化方案.md) | 语料库 corpus-vN 清单与册钉子（P0–P2 已做） |
| [字形库与语料库-共享与中心化方案.md](字形库与语料库-共享与中心化方案.md) | 多工作区间哪些独立、哪些共享，在中心库里怎么放，归档回流（v3 按上线后的中心库重写，部分已定） |

## M7 形近字（GUJI-563）

| 档 | 内容 |
|---|---|
| [M7-形近字优化算法-总设计.md](M7-形近字优化算法-总设计.md) | 总设计 |
| [M7-分块-A-共用底座.md](M7-分块-A-共用底座.md) | 块 A：标注总表、IDS 展开（已完成） |
| [M7-分块-D+E-上下文路.md](M7-分块-D+E-上下文路.md) | 块 D＋E：上下文路 L1 规则、L2 提示词 |
| [M7-IDS路-扩展与训练增长.md](M7-IDS路-扩展与训练增长.md) | IDS 路：參㕘叅落地与训练扩充 |
| [M7-字形量横画法-土士未末.md](M7-字形量横画法-土士未末.md) | 量两横长短区分土士、未末（探索） |
| [M7-形近字解法模式与扩展.md](M7-形近字解法模式与扩展.md) | 解法模式总结与下一批字组 |
| [M7-形近字通用框架与字组普查.md](M7-形近字通用框架与字组普查.md) | 三条路的通用框架与字组普查 |
| [M7-下一波异体字组分析.md](M7-下一波异体字组分析.md) | 下一波异体字组逐组分析 |
| [M7-字组统一流程-variant-tie改造方案.md](M7-字组统一流程-variant-tie改造方案.md) | 字组统一流程 group_flow 方案（已实现） |
| [形近字组统一接口设计.md](形近字组统一接口设计.md) | 形近字组统一接口 `groups/`（S0／S1 已在 main） |

## 规矩
- 新设计写在这里；被取代或只剩历史价值的移到 `../archive/design/`，并在本表删掉那一行。
- 移动文件时文件名不改：Step 模块的注释里按文件名引用了一些设计档，改注释会让 `code_hash` 变。
