# 4 定字（decide）

原九步的 Step5-d、Step6–7。先把整理本对到字格上，再把第三步的字形证据、整理本和上下文合起来，给每格定字，再判自动放行还是落人审。人审在 guji-manager（第二步 2b–2d、第四步）。

| 位置 | 步骤 id | 产出 |
|---|---|---|
| 4a 参照对位 | `align_ref` | 整理本（参校文本）与字格逐字对位，给每格整理本说的字（要语料；不读字块图，2026-11-22 起从 3 识字移来） |
| 4b 上下文 | `context_decide`、`context_rank` | 按前后文给候选排序：`context_decide` 门槛化给首选（要语料），`context_rank` 填空重排（缺省关） |
| 4c 格况 | （现在在 `seed_admit` 里） | 这一格有没有要定的字：有字／空白／遮挡／印章／切坏／非字 |
| 4d 字组 | （现在在 `seed_admit` 里） | 已登记字组里的格，合几路证据判组内是哪个字 |
| 收尾 | `seed_admit`（计划改名 `char_decide`） | 每格最后判断：自动放行（带通道）或落人审（带待审原因）；进库走裁定事件 |
| gate | （计划 `decide_gate`） | 只检测收尾结果有没有异常，不改格 |

- **子步、收尾与 gate 的划分（2026-11-28 用户定）**、与现有代码的对应、分期：[子步.md](子步.md)。现在是逻辑分组，步骤 id、产物、指纹不变。
- 各步的输入输出、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 待审原因的取值：[../design/待审原因PendingReason.md](../design/待审原因PendingReason.md)。
- 本大步的工具命令：`guji-cv decide variants`（本书用字账）。
- 影子闸、第七步回放评测：[shadow_gate.md](shadow_gate.md)、[step7_replay_eval.md](step7_replay_eval.md)。
- 形近字组：[字组/](字组/README.md)；设计见 [形近字组-5a分流与第7步对接](../design/形近字组-5a分流与第7步对接.md)、[形近字组-按对分类器](../design/形近字组-按对分类器.md)、[variant_strategy](../design/variant_strategy.md)。
- 字格永久编号 u（裁定按 u 查、书级 `seed_admit.ruling_by_u`、人裁绑定与字形库键）：[../参考/字格永久编号u.md](../参考/字格永久编号u.md)。
- 相关设计：[14-准确率优先-Step6与Step7重设计](../design/14-准确率优先-Step6与Step7重设计.md)、[降人审漏斗-管线侧对照](../design/降人审漏斗-管线侧对照.md)、[15-人裁锚定与重切后重绑定](../design/15-人裁锚定与重切后重绑定.md)。

原第 8 步（裁定事件回流、入库）和第 9 步（排版输出）已移到 guji-manager：入库归它的第二步 `pipeline`，排版输出归第五步 `output`（`guji output export md|format|wikisource|reflow`、`guji output collation-report`）。第 9 步的代码（导出、对勘、体检表）在 cv v0.9.0 整个搬进 manager `guji_manager/output/`；cv 只留字位流 `report/slots.py` 和整理本 `report/witness.py`，`feedback/` 留作库函数给 manager 调。
