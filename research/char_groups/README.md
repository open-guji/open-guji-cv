# research/char_groups — 字组测试集建集与基线（overview#437，G0，2026-10-06）

数据在 open-guji-dataset `char-groups/`（说明、口径、各组现状都在那边的 README）。这里只放建集脚本，**不进管线**，不改任何 Step。

| 脚本 | 干什么 |
|---|---|
| `common.py` | 字组登记、各册取哪几个快照（`SNAPS`）、按册划分（`SPLIT`：dev vol02/03、val vol04、pool vol05–10、extra vol01） |
| `build.py <snap_root> <dataset>/char-groups [--no-crops] [--ctx N]` | 从快照 + 工作区事件/看图事件/原图 + overview 看图清单 + #352 样本 + confusable-context + 用户审查页裁决（`review/*_verdicts.jsonl`）建 `<组>/items.jsonl` 与 `crops/`；上下文前后各 `--ctx` 字，默认 30（G1 起，G0 是 8） |
| `baseline.py <dataset>/char-groups` | 现行 seed_admit 产物在每组每册上的成绩 → `<组>/baseline.json`，打印 markdown 表 |
| `corpus_stats.py <dataset>/char-groups` | 成员字在外部语料 / 域内语料的前后字搭配 → `<组>/context_stats.json` |
| `summary.py <dataset>/char-groups` | 格数与真值档 → `metadata.json`，打印 markdown 表 |
| `review_pages.py <snap_root> <dataset>/char-groups <ry\|rr\|jys> -o page.html` | G1：给用户亲自裁的随机样本页（壳是 skill `review-artifact`）；卡片 id 冻在 dataset `char-groups/review/<组>_cards.jsonl`，种子 `20261006` |

## 用户人裁（G1，2026-10-06）

三批，一批一页，发布到 claude.ai（声明 `artifact` 能力自存），HTML 快照在 `artifacts/char_groups_<组>_review.html`：

| 批 | 抽样 | 页面 |
|---|---|---|
| ry 日曰 | vol02/03/04 正文机器放行格（core、admit、channel≠human）每册随机 100（vol03 只有 76，全收），共 276 | https://claude.ai/artifact/9azjKLvjySe3N5mFCvZCr2 |
| rr 入人八 | 同上 | （待发） |
| jys 己已巳 | vol04 正文待审格全收 + vol05 正文 core 格随机 50 | （待发） |

收回：`Artifact action:"read"` 读回页面 → `python .claude/skills/review-artifact/scripts/harvest_verdicts.py <html> -o <dataset>/char-groups/review/<组>_verdicts.jsonl`
→ 重跑 `build.py`（裁决记 A 档、`label_origin=human`、src `user_review_<组>`；「看不清」记 `X_unclear` 不当真值）→ `baseline.py` → `summary.py`。

N1 的 `research/near_form/`（上下文决策表、规则回放）照旧在，读的是旧的 `near-form-groups/items.jsonl`（已从 dataset 删除，在 git 历史 `8567e16`）。

环境：`build.py` 写死了 `/home/user/guji-workspace/96mid1ogzk-*`（工作区）与 `/home/user/overview`（看图清单）两个路径，
dataset 默认 `/home/user/open-guji-dataset`（`GUJI_DATASET` 可改）。快照的解法见 dataset `char-groups/README.md`「快照与复现」。
人裁用 `human_chars(book, bind=False)`：快照不在工作区里，绑定表算不出来；早于快照、快照又没采信的人裁记成 `X_stale`，不当真值。
