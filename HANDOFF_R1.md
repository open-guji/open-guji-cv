# HANDOFF R1（overview#418）：删 v1 聚类链

分支 `claude/R1-v1-cluster-1006`，起点 cv main `a985daa9c5`。未合 main，未开 PR。

## 约束核查
`grep code_deps open_guji_cv/steps/` 列出的模块（`clustering/candidates`、`extractor`、`verify`、`variants`、`align_label` 等共 36 个）**一个都没改**。删/改的 clusterer、labeling、review/state、feedback、glyph_db、cli_glyph_db 都不在其中。没碰任何书的 products 和工作区。

## 删了什么
| 位置 | 删除 |
|---|---|
| `clustering/clusterer.py` | 整个（`ConservativeClusterer`、`ClusterParams`） |
| `clustering/labeling.py` | 整个（`rank_book`） |
| `clustering/review/state.py` | 整个（`ReviewSession`） |
| `clustering/feedback.py` | `run_update`、`derive_truth`、`calibrate_threshold`、`_sample_pairs`；**保留** `LabelState`、`replay_events`、`remap_events`、`load_events`、`append_event` |
| `clustering/glyph_db.py` | `GlyphDB.import_book`、`_select_exemplars`、`_extract_pairs`、常量 `K_MAX`、`DUP_F1`、6 个随之无用的 import。`admit_instance` / `export_store` / `rebuild_from_store` / `query` 不依赖它们。表结构 `cluster_runs` / `cluster_members` 留着（旧库兼容） |
| `cli_glyph_db.py` | `guji glyph-db import` 子命令及其参数（path / --collection / --script-style / -o） |
| `clustering/__init__.py`、`review/__init__.py` | 去掉对应导出 |
| 文档 | `doc/design/char_clustering_design.md` 头部注记写明删了什么、哪里找回 |

## 改了哪些测试
- `tests/clustering/conftest.py`：`build_synth_book` 不再跑 clusterer / labeling / `CandidateGenerator`，只跑 M1 提取，簇按真值字分组直接写 `clusters.json`（`test_ocr_sources` 2 条、`test_vlm_assist` 1 条仍用它）。新增 `seed_glyphs(db, ...)`：用 `admit_instance` 往库里直接塞合成字形。
- `tests/clustering/test_glyph_db.py` 改成直接造库数据：
  - 保住：导出/重建往返（含 pairs、events 手工插入）、导出确定性、空库+非空 store 报错（3 条）、查询缓存失效、检索命中与分域隔离；
  - 换写：`test_admit_populates_tables`、`test_admit_idempotent`、`test_exemplar_floor_and_status`（exemplar 下限与 sparse 状态）、新增 `test_confusable_exemplar_cap`（上限用 `CONFUSABLE_SAMPLE_CAP`，因为 v1 的 `k_max` 随 `import_book` 没了）；
  - 删：`test_impure_flag_becomes_diff_pairs`（只测 v1 链的 pairs 抽取）。
- `tests/clustering/test_feedback.py`：删 3 条 `calibrate_threshold`；接收从 `test_update.py` 挪来的 `test_remap_requires_quorum`。
- 整个删除：`test_clusterer.py`（5 条）、`test_update.py`（`run_update` 4 条 + `derive_truth` 1 条；`remap` 那条已挪走）。

## 测试对比（`--junitxml` 逐条）
| | 过 | 失败 | 跳过 |
|---|---|---|---|
| 改前（a985daa9c5） | 2583 | 1 | 30 |
| 改后 | 2570 | 1 | 30 |

- 失败的是同一条 `tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`（改前就红，与本次无关）；
- 减少 19 条、新增 6 条（`test_remap_requires_quorum` 是挪家），其余逐条状态相同，无任何状态变化；
- 减少的 19 条：test_clusterer 5、calibrate 3、test_glyph_db 5（import_book 系）、test_update 6（含已挪走的 remap）；
- 环境：未装 torch，所以约 7 条 torch 用例是跳过，改前改后一致。
- 控制台前端 `npm run build` 通过。
- 字形库往返：用仓内样本库 `output/glyph_store`，在 main 与本分支上各跑一遍 `rebuild_from_store` + `export_store`，重建统计、导出统计、导出各文件 md5 完全一致。

## 遗留
1. **`candidates.py` 的 v1 `CandidateGenerator`（及 `fuse_candidates` 里 v1 专用部分）没删**：该模块是 `ocr_candidates` 的 code_deps，改了各书产物判过期。它现在只剩 `tests/clustering/test_ocr_sources.py` 一条测试在用（`test_generator_reports_source_failures`）；要删需要先定是否接受 `ocr_candidates` 及下游重算。
2. `clustering/vlm_assist.py` 留着：`candidates.py` 的 `VlmSeedSource` 依赖它的 `parse_spec`，同样被 code_deps 绑住。
3. `feedback.py` 的 `replay_events` / `remap_events` / `load_events` / `LabelState` 现在只剩测试在用（原来是 `import_book` 和 `ReviewSession` 用）。卡上写"要留"，所以留；可另议。
4. 注释里还点着已删函数名、没动：`clustering/verify.py:193`（code_deps，不能碰）、`align_label.py:132`（code_deps）、`align_gold.py` 两处、`scripts/canonicalize_glyph_db.py`、`doc/design/glyph_canonical_format.md`、`doc/research/*`（历史留档）。
5. `glyph_db.py` 的表 `cluster_runs` / `cluster_members` 无人写了；`scripts/glyph_v1_rekey.py` 还在引用它们，故保留。
