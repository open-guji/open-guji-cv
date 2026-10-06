# research/char_groups — 字组测试集建集与基线（overview#437，G0，2026-10-06）

数据在 open-guji-dataset `char-groups/`（说明、口径、各组现状都在那边的 README）。这里只放建集脚本，**不进管线**，不改任何 Step。

| 脚本 | 干什么 |
|---|---|
| `common.py` | 字组登记、各册取哪几个快照（`SNAPS`）、按册划分（`SPLIT`：dev vol02/03、val vol04、pool vol05–10、extra vol01） |
| `build.py <snap_root> <dataset>/char-groups [--no-crops]` | 从快照 + 工作区事件/看图事件/原图 + overview 看图清单 + #352 样本 + confusable-context 建 `<组>/items.jsonl` 与 `crops/` |
| `baseline.py <dataset>/char-groups` | 现行 seed_admit 产物在每组每册上的成绩 → `<组>/baseline.json`，打印 markdown 表 |
| `corpus_stats.py <dataset>/char-groups` | 成员字在外部语料 / 域内语料的前后字搭配 → `<组>/context_stats.json` |
| `summary.py <dataset>/char-groups` | 格数与真值档 → `metadata.json`，打印 markdown 表 |

N1 的 `research/near_form/`（上下文决策表、规则回放）照旧在，读的是旧的 `near-form-groups/items.jsonl`（已从 dataset 删除，在 git 历史 `8567e16`）。

环境：`build.py` 写死了 `/home/user/guji-workspace/96mid1ogzk-*`（工作区）与 `/home/user/overview`（看图清单）两个路径，
dataset 默认 `/home/user/open-guji-dataset`（`GUJI_DATASET` 可改）。快照的解法见 dataset `char-groups/README.md`「快照与复现」。
人裁用 `human_chars(book, bind=False)`：快照不在工作区里，绑定表算不出来；早于快照、快照又没采信的人裁记成 `X_stale`，不当真值。
