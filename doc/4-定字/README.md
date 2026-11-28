# 4 定字（decide）

原九步的 Step5-d、Step6–7。先把整理本对到字格上，再把第三步的字形证据、整理本和上下文合起来，给每格定字，再判自动放行还是落人审。人审在 guji-manager（第二步 2b–2d、第四步）。

| 位置 | 步骤 id | 产出 |
|---|---|---|
| 4a 参照对位 | `align_ref` | 整理本（参校文本）与字格逐字对位，给每格整理本说的字（要语料；不读字块图，2026-11-22 起从 3 识字移来） |
| 4b 上下文 | `context_decide`、`context_rank` | 按前后文给候选排序：`context_decide` 门槛化给首选（要语料），`context_rank` 填空重排（缺省关） |
| 4c 格况 | （现在在 `seed_admit` 里） | 这一格有没有要定的字：有字／空白／遮挡／印章／切坏／非字 |
| 4d 字组 | （现在在 `seed_admit` 里） | 已登记字组里的格，合几路证据判组内是哪个字 |
| 收尾 | `seed_admit`（计划改名 `char_decide`） | 每格最后判断：自动放行（带通道）或落人审（带待审原因）；进库走裁定事件 |
| gate | `decide_gate` | **只检测、不判断**（2026-11-28）：读第四步全部产物，每页出检测清单（`fail`／`flag` 两级）；不改任何格、不挡别的步骤、不进任何步骤的指纹。挂在 `seed_admit` 出口，永远最后跑；检测项见 [decide_gate.md](decide_gate.md) |

- **子步、收尾与 gate 的划分（2026-11-28 用户定）**、与现有代码的对应、分期：[子步.md](子步.md)。现在是逻辑分组，步骤 id、产物、指纹不变。
- 各步的输入输出、参数缺省值：[步骤与产物.md](步骤与产物.md)（从代码生成）。
- 待审原因的取值：[../design/待审原因PendingReason.md](../design/待审原因PendingReason.md)。
- 本大步的工具命令：`guji-cv decide variants`（本书用字账）。
- 影子闸、第七步回放评测：[shadow_gate.md](shadow_gate.md)、[step7_replay_eval.md](step7_replay_eval.md)。
- 形近字组：[字组/](字组/README.md)；设计见 [形近字组-5a分流与第7步对接](../design/形近字组-5a分流与第7步对接.md)、[形近字组-按对分类器](../design/形近字组-按对分类器.md)、[variant_strategy](../design/variant_strategy.md)。
- 字格永久编号 u（裁定按 u 查、书级 `seed_admit.ruling_by_u`、人裁绑定与字形库键）：[../参考/字格永久编号u.md](../参考/字格永久编号u.md)。
- 相关设计：[14-准确率优先-Step6与Step7重设计](../design/14-准确率优先-Step6与Step7重设计.md)、[降人审漏斗-管线侧对照](../design/降人审漏斗-管线侧对照.md)、[15-人裁锚定与重切后重绑定](../design/15-人裁锚定与重切后重绑定.md)。

原第 8 步（裁定事件回流、入库）和第 9 步（排版输出）已移到 guji-manager：入库归它的第二步 `pipeline`，排版输出归第五步 `output`（`guji output export md|format|wikisource|reflow`、`guji output collation-report`）。第 9 步的代码（导出、对勘、体检表）在 cv v0.9.0 整个搬进 manager `guji_manager/output/`；cv 只留字位流 `report/slots.py` 和整理本 `report/witness.py`，`feedback/` 留作库函数给 manager 调。

## `seed_admit` 的代码分块（2026-11-28 起，P1a，纯搬家、指纹不变）

设计见 ai-team `domain/CV/A24/第四步定字-子步重构设计-2026-11-28.md`。步骤 id、产物、参数都没动；原先一个 7,500 行的 `seed_admit` 按位置拆成下面这些文件，`seed_admit.py` 只剩 `SeedAdmitStep`（主循环与后处理遍的次序，**改次序＝改产物**）并 re-export 全部旧名字。

| 文件 | 内容 | 对应设计里的位置 |
|---|---|---|
| `decide.py` | `ref_of(ctx, page)` 合并读口（`{格: {ref, via: text\|coord\|pin, op}}`）、`text_refs`／`coord_refs`（`seed_admit._align`／`_coord_refs` 只是它的包装）、`_opt` | 4a 读口 |
| `seed_admit_cell_state.py` | 遮挡、印章空白、墨点、字框几何（`seg_box_check`）、夹注不齐、符号、表头公式 | 4c 格况 |
| `seed_admit_groups.py` | group_flow、看图判裁定、日曰己已巳按文意定字（旧称折叠组）、近形 p、人裁字形表；`_flow_config`（字组流程配置，收尾与 4d 共用）、`_entry_config`（4d 出入口归属用） | 4d 字组 |
| `seed_admit_pick.py` | 选刻形、铁证、独证、文意异议、码位表、书级钩子取数 | 收尾·定字 |
| `seed_admit_lanes.py` | 整理本／无参照放行通道与降审护栏各遍 | 收尾·放行 |
| `seed_admit_veto.py` | `shadow_veto`、follow_ref 否决、witness3 近邻否决 | 收尾·否决 |
| `seed_admit_reasons.py` | 疑问码 `doubts`、上下文／乱码护栏 | 收尾·原因 |
| `seed_admit_altcut.py` | 备选切法挑列（`alt_select=admit`） | 挑切法 |
| `seed_admit_page_params.py` | 无参照页换参数、参校本准确度分档 | 按页参数 |
| `seed_admit_shapes.py`、`seed_admit_common.py`、`seed_admit_params.py` | 字形判官各遍、共用小工具、参数类（此前已拆） | 4d／共用 |

- 指纹：新模块都在 `seed_admit` 的 `code_deps` 里，`code_equiv.SPLITS` 把它们合回原来的 `seed_admit`／`seed_admit_lanes` 两项，各书各步指纹不变。
- 测试里换函数：各遍搬走后，调用方在哪个模块就查哪个模块的全局名，用 `tests/helpers.py` 的 `patch_seed_admit(monkeypatch, "名字", 值)` 在各模块里一起换。
- **收尾步改名 `seed_admit`→`char_decide`（2026-11-28）**：分两版发，本版只是兼容读口，产物仍写 `seed_admit`；新旧名读法、迁移命令、`pending_reason` 字段与 cv 将来直写的原因集合见 [pending_reason.md](pending_reason.md)。

## 4d `group_decision`（2026-11-28 起，P3c，缺省关）

Step `group_decision`，产物 kind `group_decision`（`products/kinds/group_decision.py`，numeric 一页一份）。**只出原料、不出决定**：

| 字段 | 内容 | 收尾读不读 |
|---|---|---|
| `cells[].lift` | 字组入口归属（待审口径）`[组 id, lift\|joint]` | 本版不读 |
| `near[<方法>]` | 3b `glyph_near` 看图判法原样结论快照（键形同 `_near_from_3b`／`_near_by_model_from_3b`） | 读（`ran` 里有 `near:<方法>` 才读） |
| `wh`、`cells[].aspect` | 字框宽高、按组宽高比（现 ry）；只是证据，窄宽判与门槛在收尾 | `wh` 读（`fold_aspect`） |
| `handling` | 按组处理方式定稿快照（登记表缺省＋书级 `params.group_decision.handling` 覆盖，`resolved` 进指纹） | 不读（本版只记） |

不做：补放／改字／降审、字组文意各层、裁定缓存、`vis_ruling`（读邻格放行状态，窗口键随前面各遍变）。`vis_ruling` 及其后各遍次序、`ask`、`evidence.vis_ctx`、`evidence.group` 位置不动。开关关时收尾现算、产物逐字节不变。书级开：`params.group_decision.enabled: true`。
