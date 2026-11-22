# 4 定字（decide）

原九步的 Step6–7。把三路证据和上下文合起来，给每格定字，再判自动放行还是落人审。人审在 guji-manager（第二步 2b–2d、第四步）。

| 小步 | 步骤 id | 产出 |
|---|---|---|
| 4a 上下文 | `context_decide` | 在候选里按上下文重排、门槛化定字（要语料） |
| 4b 放行 | `seed_admit` | 每格：自动放行（带通道）或落人审（带 `pending_reason`）；进库走人裁事件 |

- 各步的输入输出、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 待审原因的取值：[../design/待审原因PendingReason.md](../design/待审原因PendingReason.md)。
- 本大步的工具命令：`guji pipeline variants`（本书用字账）。
- 影子闸、第七步回放评测：[shadow_gate.md](shadow_gate.md)、[step7_replay_eval.md](step7_replay_eval.md)。
- 形近字组：[字组/](字组/README.md)；设计见 [形近字组-5a分流与第7步对接](../design/形近字组-5a分流与第7步对接.md)、[形近字组-按对分类器](../design/形近字组-按对分类器.md)、[variant_strategy](../design/variant_strategy.md)。
- 相关设计：[14-准确率优先-Step6与Step7重设计](../design/14-准确率优先-Step6与Step7重设计.md)、[降人审漏斗-管线侧对照](../design/降人审漏斗-管线侧对照.md)、[15-人裁锚定与重切后重绑定](../design/15-人裁锚定与重切后重绑定.md)。

原第 8 步（人裁事件回流、入库）和第 9 步（排版输出、`guji export`）已移到 guji-manager：入库归它的第二步 `pipeline`，排版输出归第五步 `output`。cv 里 `report/`、`feedback/` 的代码暂留，作为库函数给 manager 调。
