# 收尾步写的送审原因（`pending_reason`）

> P3a-2（2026-11-28）起，收尾（`seed_admit`，改名后 `char_decide`）**每格直接写** `pending_reason`、`pending_reason_detail`、`form_src`
> （`AdmitRec` 三个可选字段，空不落盘）。放行结果一格不变。P3a-1 起 `pending-cells` 就带这三个键，现在 cv 有值就带上。
> 加了字段，第四步产物指纹变（seed_admit 起过期），跟各书下一轮整轮走；PR 为草稿，等主线通知后和改名那一版一起合。

## 约定

- enum 真源是 guji-manager `review/pending_reasons.yaml`（`PendingReason`，导出 `python -m guji_manager.review.pending_reason --json`）；
  cv 存精简副本 `open_guji_cv/ops/pending_reasons.json`（code、category、route、owner、reviewer、priority），
  测试 `tests/test_pending_reason_enum.py` 与 manager 导出逐项核对，不一致即失败（改了 yaml 就重新导出副本）。
- cv 只写**第四步名下**的原因（副本里 `owner == "CV4"`，下表 18 个；常量 `core/decide_names.py::FINAL_PENDING_REASONS`）。
  判法在 `steps/char_decide_reasons.py`，逐条搬自 manager `review/reasons.py::classify`：按 priority 从小到大试，第一个命中的是这一格的原因；
  **第一个命中的若归别人**（切分 S、遮挡 D、库刻例 L02／L04、复审 X02–X04……），这格写 `None`，manager 自判类照旧覆盖，缺或 `unknown` 回退 `reasons_for_pending`。
- 已放行的格、排除名单上的格：`pending_reason` 恒 `None`。
- `pending_reason_detail`：同 manager `detail_of`（组 id、字对、码位），不是判定依据；依据在格的 `evidence`／`doubts`。
- `form_src`：这一格放字（或默认字）的来源，`human`（人裁）｜`code_table`（私用码表）｜`group`（字组流程放行）｜`ref`（整理本，provenance=align／context 或通道带 ref）｜`lib`（字形库）；没放字（□、空）为 None。
- 过渡期两边都算，用 ai-team `domain/CV/A24/decide-bench/diff_pending_reason.py` 出逐格差异表（GM4 方案）；一两轮后 manager 切到读产物。
- 与 manager 暂不同：列级无参照（`reference_profile` 的 `col_none`，cv #2018）manager 还按整页；两边口径对齐前，这类格可能有差异。

## 第四步名下的原因（yaml owner＝CV4）

| 值 | 码 | 显示名 | 去向 | 谁看 |
|---|---|---|---|---|
| `hard_pair` | H01 | 极难形近 | deferred | none |
| `lib_missing` | L01 | 少见的字 | human | human |
| `garble_gate` | L05 | 像框线或墨点 | algo | llm_then_human |
| `near_form_guard` | N01 | 形近字 | llm | llm_then_human |
| `ref_ocr_diff` | P01 | 识别字与参校本不同 | llm | llm_then_human |
| `ref_final_diff` | P02 | 定字与参校本不同 | llm | llm_then_human |
| `ref_lacuna` | R01 | 参校本缺字 | algo | llm_then_human |
| `ref_gap` | R02 | 参校本这里没字 | llm | llm_then_human |
| `glyph_pending` | R03 | 待收字 | deferred | none |
| `variant_pair` | V01 | 异体字 | human | human |
| `variant_form_open` | V02 | 写法待定 | algo | human |
| `ruling_conflict` | X01 | 裁定有冲突 | human | human |
| `group_abstain` | Z01 | 形近字·没把握 | llm | llm_then_human |
| `group_conflict` | Z02 | 形近字·判法打架 | llm | llm_then_human |
| `group_demoted` | Z03 | 形近字·复核推翻 | llm | llm_then_human |
| `group_ref_dissent` | Z04 | 形近字·与参校本不同 | llm | llm_then_human |
| `group_weak` | Z05 | 形近字·证据弱（已停用） | llm | llm_then_human |
| `group_unconfirmed` | Z07 | 形近字·差一路确认 | llm | llm_then_human |

（`group_weak`、`group_form_open`→`variant_form_open` 等改名与停用以 yaml 为准；旧名数据由 manager `parse()` 换新名。）

## 兼容读口（本版）

新旧名并认，产物仍写 `seed_admit`；改名那一版把 `core/decide_names.py::ADMIT_STEP_ACTIVE` 改成 `char_decide`。

| 对象 | 读法 |
|---|---|
| 产物目录与页顶层键 | `core.decide_names.final_dir`／`final_page_dict`；新目录优先，并存以 `char_decide/` 为准，`guji-cv status` 对并存警告 |
| 读产物对象 | `steps.decide_final.read_final(ctx, page)`、`products.final_read.read_final_store(store, book, key)` |
| 参数 | `params.char_decide.*` 与 `params.seed_admit.*` 都认（册配置、管线 yaml、套书缺省、`--params`／`--override`）；同一层同时写报错 |
| 事件 | `feedback.decide_events.decided_view`／`ruling_by_u`／`invalidate_final`：`target.step` 两个名字当同一步，后到覆盖按写入时间，失效两个目录都标；D1 历史事件不改写 |
| 迁移 | `guji-cv decide migrate-name <册>`：改名不删、换算指纹、sha 清单存 `<产物根>/<册>/_migrate_char_decide.json`；本版只能 `--dry-run` |
| 导入 | `steps.char_decide.CharDecideStep`＝`steps.seed_admit.SeedAdmitStep` 同一个类（改名那一版两边互换，旧名留垫片） |
| manager | 以上都经 `manager_api` 导出（`read_final`、`decided_view`、`ADMIT_STEPS`、`fold_admit_params` 等） |
