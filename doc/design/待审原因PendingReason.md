# 待审原因 `PendingReason`（规范）

> 2026-11-03 sheldon 定，A31 落实；2026-11-04 全项目迁移完成。本文是唯一的完整说明，ai-team `domain/CV/规范/待审原因PendingReason.md` 只做索引。

## 一、是什么、不是什么

- `pending_reason` 回答一个问题：**这一格为什么还在待审**。用它决定派给谁修（`owner`）、谁来看（`reviewer`）、网页卡片长什么样（`ui`）、要不要先过大模型（`route`）。
- 它**不是判定依据**。机器为什么放了某个字、为什么怀疑，证据仍在 seed_admit 的疑问码 `why[]`，将来可另立 enum，不并进这里。
- 每格只有一个主原因，按配置里的 `priority` 从小到大取第一条命中的。
- **不确定一律写 `unknown`**，不留空、不写 null。历史数据回填、以后新增的数据都照此办。

## 二、真源与取法

| 东西 | 位置 |
|---|---|
| enum 定义 | `open_guji_cv/review/pending_reason.py`（`PendingReason`，字段名常量 `FIELD = "pending_reason"`） |
| 配置（码、显示名、去向、负责人、卡片形态、判法说明、旧字段对应） | `open_guji_cv/review/pending_reasons.yaml` |
| 判一格的原因 | `open_guji_cv/review/reasons.py`：`classify(cell, ctx)`；整张单 `reasons_for_pending()` ＋ `stamp()`；控制台卡 `stamp_cards()` |
| 导出给别的仓 | `python -m open_guji_cv.review.pending_reason --json`（键 version／field／categories／routes／reasons） |
| manager 里取 | `guji_manager._cv.pending_reason_specs`（经 cv `manager_api`，不直接 import cv 内部） |

常用接口：`parse(value)`（空值、认不出的都给 `UNKNOWN`）、`specs()`、`by_code("Z01")`、`legacy_candidates(cause=…, cls=…)`。

## 三、全部取值（29 个）

去向：`human` 一定人审；`llm` 大模型统一过一遍，只收 high，其余回人审；`algo` 先改算法，改完剩下的并入 llm；`deferred` 留到标点、专名阶段。

| 码 | 值（写进数据的） | 显示名 | 大类 | 去向 | 谁看 | 修算法 |
|---|---|---|---|---|---|---|
| D01 | `occluded_with_ref` | 有遮挡 | 遮挡 | algo | llm_then_human | A32 |
| D02 | `occluded_no_ref` | 有遮挡且参校本缺 | 遮挡 | human | human | A32 |
| H01 | `hard_pair` | 极难形近 | 极难形近 | deferred | none | A24 |
| L01 | `lib_missing` | 少见的字 | 字形库 | human | human | A24 |
| L02 | `lib_sparse_dissent` | 刻例太少·不一致 | 字形库 | llm | llm_then_human | A23 |
| L03 | `lib_sparse_agree` | 刻例太少 | 字形库 | human | human | A23 |
| L04 | `lib_unrecognized` | 库认不出 | 字形库 | algo | llm_then_human | A23 |
| L05 | `garble_gate` | 像框线或墨点 | 字形库 | algo | llm_then_human | A24 |
| N01 | `near_form_guard` | 形近字 | 形近护栏 | llm | llm_then_human | A24 |
| P01 | `ref_replaced` | 参校本改过字 | 与参校本不一致 | llm | llm_then_human | A24 |
| P02 | `ref_mismatch` | 和参校本不一致 | 与参校本不一致 | llm | llm_then_human | A24 |
| R01 | `ref_lacuna` | 参校本缺字 | 参校本缺位 | algo | llm_then_human | A24 |
| R02 | `ref_gap` | 参校本这里没字 | 参校本缺位 | llm | llm_then_human | A24 |
| S01 | `seg_page_unaligned` | 整页对不上 | 切分位置 | algo | human | A22 |
| S02 | `seg_col_unaligned` | 整列对不上 | 切分位置 | algo | human | A22 |
| S03 | `col_width_out_of_band` | 列宽异常 | 切分位置 | algo | human | A22 |
| S04 | `seg_defect` | 切坏格 | 切分位置 | human | human | A22 |
| V01 | `variant_pair` | 异体字 | 异体 | human | human | A24 |
| X01 | `ruling_conflict` | 裁定有冲突 | 复审与其他 | human | human | A31 |
| X02 | `vision_flagged` | 看图觉得不对 | 复审与其他 | human | human | A31 |
| X03 | `machine_changed` | 机器改了字 | 复审与其他 | human | human | A32 |
| X04 | `recheck` | 复审 | 复审与其他 | human | human | A32 |
| X99 | `unknown` | 原因不明 | 复审与其他 | human | human | A31 |
| Z01 | `group_abstain` | 形近字·没把握 | 形近字组 | llm | llm_then_human | A24 |
| Z02 | `group_conflict` | 形近字·判法打架 | 形近字组 | llm | llm_then_human | A24 |
| Z03 | `group_demoted` | 形近字·复核推翻 | 形近字组 | llm | llm_then_human | A24 |
| Z04 | `group_ref_dissent` | 形近字·与参校本不同 | 形近字组 | llm | llm_then_human | A24 |
| Z05 | `group_weak` | 形近字·证据弱 | 形近字组 | llm | llm_then_human | A24 |
| Z06 | `group_form_open` | 写法待定 | 形近字组 | algo | human | A24 |

显示名、卡片说明（`hint`）、卡片形态（`ui`）、判法（`detect`）见 yaml。对外一律说「参校本」，不说「整理本」。

## 四、各处数据怎么写

字段名一律 `pending_reason`，值写上表第二列的英文名，不写中文、不写码。可另带 `pending_reason_detail`（一句补充，如字组名、整理本字），有才写。

| 数据 | 写法 | 谁写 |
|---|---|---|
| 待审单 `feedback/lists/proofing/<文本号>/<章>.pending.json` | 每格 `pending_reason`（必有）＋`pending_reason_detail` | cv `republish.py` 出单（公众单、团队单都写） |
| 控制台待审卡 | 每张卡 `pending_reason`／`pending_reason_detail`，控制台显示「原因：显示名（补充）」 | cv `review/cards.py` → `stamp_cards` |
| 人裁事件 `feedback/events/*.jsonl`（`confirm` 等） | `payload.pending_reason`：裁的时候这格在单上的原因 | manager `cellvotes`（网站票落事件）；手写事件照写，不知道写 `unknown` |
| 文意裁定 `feedback/rulings/*.jsonl`（`ctx_ruling`） | `payload.pending_reason`：问的时候这格的原因 | 出裁定的脚本；字组裁定写 `group_abstain` 等 |
| 看图结论 `feedback/vision/*.jsonl`（`vision_check`） | `payload.pending_reason`，抽样核的写 `unknown` | 看图脚本 |
| 网站校对页、下载本 | 读单上的 `pending_reason` 分 tab、显示说明 | kaiyuanguji-web `src/lib/pendingReasons.ts` |
| 后台看板 | 按 `web.pending_reason` 计数，缺的算 `unknown` | open-guji-site `worker/collector.js`、`ops/text-progress/sync.py` |
| manager 统计 | `guji pending-stats` 有「按待审原因」一节，cells.tsv 有 `pending_reason` 列 | guji-manager `pending_stats.py` |
| book-text 文本 `NNN.char.json` | guji-format **char v0.4**（§4.8）：待审格带 `pending_reason`，不带 `lacuna`；`lacuna` 只给审过、定为阙字的格；`pending_reason` 与 `lacuna`／`guess_c`／`fig` 互斥；用到就写 `$schema` v0.4 | cv `republish.py` 升 book-text 时按同版公众单＋团队单写（`guji_char_cord.apply_pending`）；`export_guji_format.py --pending` 也可写 |

book-text 待审格的字：机器没给字的 `c` 为 □，分行稿照阙文写 `[[]]`；机器给了字的 `c` 照写机器字（标点按它记锚）。book-text 生成脚本、网站下载本都已认这条，校验器规则 F-OV-16 把关。

## 五、各仓副本与核对

别的仓不 import cv，各放一份导出副本（网站、book-text 有测试核对；控制台的副本照抄网站那份，改了要一起改）：

| 仓 | 副本 |
|---|---|
| kaiyuanguji-web | `nextjs/src/lib/pendingReasons.ts` |
| guji-console | `guji_console/frontend/src/pendingReasons.ts` |
| book-text | `scripts/pending_reasons.json`（校验器 F-OV-16 用） |
| guji-format | char v0.4 schema 只规定格式（`^[a-z][a-z0-9_]*$`），不列值 |

## 六、加、改、弃用一个原因

1. 改 `pending_reasons.yaml`（新值加在对应大类里，给新 `code`、`priority`）和 `PendingReason`，在 `reasons.py` 里加判法；补测试。
2. **码永不复用**；改名不直接改，旧值在 yaml 标 `deprecated_by` 指向新值，并在 `parse()` 里把旧值映射到新值（目前还没有弃用过的值）。
3. 合进 cv dev 后，重新导出 `--json`，同步上表各仓副本。
4. 判法变了不影响任何 Step 指纹（原因在 review 层），下次出单就生效；要改现有单，用 `scripts/zhengli/backfill_pending_reason.py`。

## 七、迁移记录（2026-11-03～04）

| 范围 | 做法 | 结果 |
|---|---|---|
| 殿本 99 张现行单 | `backfill_pending_reason.py`：取出单那一版的产物包，按 `reasons.py` 判 | 18,429 格，unknown 0，已推中心库 |
| 北行日录 1 张单 | 同上 | 351 格，unknown 0 |
| 历史事件 | `backfill_event_reason.py`：按 group／route／subclass／via／来源推，推不出 `unknown` | 殿本 65,617 条（rev 690917）、北行 1,766 条 |
| book-text 殿本 99 册、北行 | 按现行单给 char 写 `pending_reason`、去待审格的 `lacuna`，文本线升 patch（dev） | 殿本 18,427 格、北行 351 格 |
| 史记、全唐文 | 还没进 book-text；下次出单自动带原因 | — |

## 八、过渡期与待办

- 待审单上旧的 `cause`（cv 成因码）、`cls`（卡片类别）还在双写，等各处都只读 `pending_reason` 后删。新代码一律读 `pending_reason`，别再新造 `cause`／`cls` 类分类。
  11-04 盘点，还在读旧字段的（删双写前要先改完）：
  - guji-manager `pending_stats.py`（`cause == "D"`、出表带 cause）、`taxonomy.py`；
  - cv `ops/close_check.py`（按 cls 计数）、`review/causes.py`／`cli_close.py`（成因统计）、`review/proof_fields.py`（线上单写 cls）；
  - cv `scripts/zhengli/ledger.py`、`republish.py`（差异报告）、`pending_route.py`。
  网站校对页已改成先读 `pending_reason`、老单才退回 `cls`（kaiyuanguji-web #667）。
  另外，按成因码 `cause` 派单（11-01 起）比 29 个原因更细，删 `cause` 前要先定派单改按什么。
- 网站阅读页悬停显示原因：book-index-ui 0.65.0（book-index-manager #299）。
- 候选清单（`feedback/candidates`）：行上或 `_meta` 写 `pending_reason`，`load_list` 每行带出，缺省 `unknown`（11-04）。
