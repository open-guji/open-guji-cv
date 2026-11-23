# HANDOFF V1：看图结论事件通道（overview#428，2026-10-06）

分支 `claude/V1-vision-events-1006`，基于 main `9ce4328`。没有合进 main，也没有开 PR。

## 做了什么
「看图结论」指模型看图判的结论，不是人裁。现在它有了一条写入通道，下游一律不把它当人裁用。

| 改动 | 文件 |
|---|---|
| 新 kind `vision_check`；`counts_as_human(e)`：`kind=vision_check` 或 `payload.source∈MODEL_JUDGMENT_SOURCES`（目前只有 `vision`）的不算人裁 | `feedback/events.py` |
| 通道本体：jsonl 格式校验、`VisionLog`（落 `feedback/vision/`）、导入、金标、`vision_checks` / `flag_active` / `vision_pending` | `feedback/vision.py`（新） |
| `guji events import-vision <jsonl> [--book 册] [--judge 模型] [--as-batch 名] [--no-gold] [--dry-run] -w <ws>`；`gold rebuild` 一并重放 vision；`guji status` 加报告项 `vision_pending` | `cli_v2.py` |
| 不进字形库：`glyphdb_admit` 过滤非人裁；金标来源统一走 `label_origin_of`（vision → `vision`）；新增 `_expected_of(vision_check)`；`unsure` 记为 uncertain | `feedback/consumers.py`，`gold/item.py`（`LabelOrigin` 加 `vision`） |
| 不算人裁定字 | `feedback/lookup.py`：`human_chars`、`resolved_forced_jiazhu` |
| 不算已裁 | `review/verdict_view.py`：`_is_decision`（即 `decided_view` / `decided_cells`）、`shape_decided_cells`（收尾闸、裁放不一致报告）、`defect_only_cells`、`flagged_cells` |
| 不进绑定表、不重放进库 | `feedback/bindings.py::_verdict_events`、`feedback/replay.py` |
| 其余读 confirm 当人裁的地方 | `render/approx.py`、`feedback/collate_state.py`、`eval/llm_online_accuracy.py` |
| 看图判错的格送回待审：doubt `vision_flag` 加 `vision` 字段，不改字；对齐改字层的这类格归「逐张」，不进网格 | `review/cards.py` |
| close-check 第 2 项把看图判错的格数单独列出 | `ops/close_check.py` |
| jsonl 格式与用法 | `doc/runbook/整理一册书.md` 新增一节「看图结论存成事件（S8、S10 共用）」，S8、S10、S13 各补一句 |
| 单测 12 条 | `tests/test_vision_events.py` |

## 关键设计
- **存放位置分开**：看图结论只写 `feedback/vision/`，不写 `feedback/events/`。几十处读人裁的代码都直接扫 `events/`，分开放就是缺省安全。各处另加了 `counts_as_human` 判断，看图结论即使误写进 `events/`，也不会被当成人裁（双保险）。
- **不按 `actor="model"` 一刀切**（和卡上的字面说法不同，有意为之）：`events/` 里早就有两类 `actor="model"` 的 confirm。
  - 一类是人裁的机械更正，即 `glyph_codepoint_unify` 码位统一、`mojibake_census` 乱码还原。它们覆盖的正是人裁本身，如果不认，旧码位或乱码的那条人裁会原样复活。第一版按 actor 排除时，`test_glyph_codepoint_unify` 两条测试就挂了，这是实测出来的。
  - 另一类是 `book_lib_auto` 的 `source=auto`，有它自己的口径。
  - 所以只排除「模型判断」类来源。以后再有新的这类来源，加进 `MODEL_JUDGMENT_SOURCES` 即可。`replay` 原有的 `actor=model` 跳过保持不变。
- **没碰任何 Step**：seed_admit 没改，各书产物不会判过期（`feedback/` 和 `review/` 下的模块都不在任何 Step 的 `code_deps` 里）。看图判错的格只在 review 队列一侧处理。
- **人裁优先于模型**：人裁过的格（`decided`）不再送审。现行字已改成看图认的字，或现行字已不是 `shown`（字已经动过），也不再送审。
- 导入只追加、幂等：`seq` 取行号，同一文件重导，没改过的行不会重复写入。只要有一行格式不对，整批都不写。

## 测试
- 全量（`-s`）：2609 通过、30 跳过、1 失败。失败的是 `test_cut_select::test_ckpt_fingerprint_empty_for_missing_file`，原版代码上同样失败（N1 交单时也报过），与本改动无关。
- 环境：Linux 云端，uv venv 装 `.[console,dev]`，没装 torch，相关测试按规矩跳过。

## 待拍板 / 后续
1. 看图判错的格在待审队列里，会让 close-check 的「待审清零」不过，必须请人裁掉。我认为这样合理；如果只想报告、不挡收尾，在 `close_check._queue` 里扣掉 `vision_flag` 即可。
2. 前端还没有专门展示 `vision` 字段，卡片上只能看到 doubt `vision_flag`。要让卡片显示「看图认作 X（模型名）」，需要前端加几行。
3. `POST /api/events` 没有加 actor 参数（入口按卡上建议二选一，选的是命令行）。
4. vol04 的 `reports/vol04/看图结论.jsonl` 按 runbook 里的格式存好后，跑 `guji events import-vision … --book vol04 -w <ws>` 导入。
