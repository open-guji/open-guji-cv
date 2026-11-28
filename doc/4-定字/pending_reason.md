# 收尾步写的送审原因（`pending_reason`）

> P3a-1（2026-11-28）起 `pending-cells` 每格带 `pending_reason`、`pending_reason_detail`、`form_src` 三个字段，**本版值一律 `None`**
> （产物仍是 `seed_admit`，没有这些字段）。收尾步（`char_decide`）改名并直接写原因的那一版起，下面这些值由 cv 写，其余仍由 manager 判。

## 约定

- enum 真源是 guji-manager `review/pending_reasons.yaml`（`PendingReason`，读取 `python -m guji_manager.review.pending_reason --json`）；
  cv 只写**第四步名下**的原因（yaml 里 `owner` 是第四步的那些值，下表 15 个），常量见 `core/decide_names.py::FINAL_PENDING_REASONS`。
- 不在这个集合里的格（切分 S、遮挡 D、刻例太少 L02–L04、复审 X……）cv 写 `None`：manager 自判类照旧覆盖，缺或 `unknown` 回退 `reasons_for_pending` 反推；
  过渡期两边都算，出差异表（GM4 方案），一两轮后 manager 切到读产物。
- 遮挡（D01／D02）、切坏（S04）随 P3b（4c 独立成 Step）改由格况状态给，到时本表增补。
- `pending_reason_detail`：自由文本，说明依据（命中哪条通道／护栏、原标注、事件 id）；`form_src`：选形来源 `lib|ref|group|code_table|human`。

## 第四步名下的原因

| 值 | 码 | 显示名 | 去向 | 谁看 |
|---|---|---|---|---|
| `hard_pair` | H01 | 极难形近 | deferred | none |
| `group_abstain` | Z01 | 形近字·没把握 | llm | llm_then_human |
| `group_conflict` | Z02 | 形近字·判法打架 | llm | llm_then_human |
| `group_demoted` | Z03 | 形近字·复核推翻 | llm | llm_then_human |
| `group_ref_dissent` | Z04 | 形近字·与整理本不同 | llm | llm_then_human |
| `group_weak` | Z05 | 形近字·证据弱 | llm | llm_then_human |
| `group_form_open` | Z06 | 写法待定 | algo | human |
| `near_form_guard` | N01 | 形近字 | llm | llm_then_human |
| `variant_pair` | V01 | 异体字 | human | human |
| `lib_missing` | L01 | 少见的字 | human | human |
| `garble_gate` | L05 | 像框线或墨点 | algo | llm_then_human |
| `ref_lacuna` | R01 | 整理本缺字 | algo | llm_then_human |
| `ref_gap` | R02 | 整理本这里没字 | llm | llm_then_human |
| `ref_replaced` | P01 | 整理本改过字 | llm | llm_then_human |
| `ref_mismatch` | P02 | 和整理本不一致 | llm | llm_then_human |

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
