# Step6 词典 + AI 排除法 · 评测框架（北行日錄）

方案与实验拆分：overview 仓 `项目进展/图片初步数字化/进度/Step6-上下文裁决/方案-Step6词典加AI-实验拆分.md`。

| 文件 | 作用 |
|---|---|
| `parse_bxgb_wiki.py` | 终稿 `reports/bxgb/wikisource/p*.wiki` → 逐格真值 `{key: 字}`（18,282 格） |
| `prep.py` | 生成 `data/`：真值、按天切分（148 段）、整理本逐天片段、难例集候选（`shadow/signals_labeled.jsonl`，去掉 label/human_*）、dev/test 切分 |
| `dictlib.py` | 词典层：`open_guji_cv/variants.py` + `config/gloss/gloss.json`；`group_cands()` 按异体（含两跳）确定性分组 |
| `harness.py` | 按天批量调用 → 解析 → 打分（真值被排除率 / 首组命中 / 校准）。流式调用（非流式长输出会被网关 502），磁盘缓存 |
| `prompts/v1.py` `v2.py` | 提示词版本；v2 = 词典预分组 + 硬规则（同组不得以文意排除、不得仅据整理本排除） |
| `runs/` | 每次运行的逐格结果（提交）；`cache/`、`data/` 不提交，可重建 |

不读人裁事件；上下文里所有难例格挖成 ▢ 或标为待判位。工作区路径取 `GUJI_WORKSPACE`，缺省为与 cv 仓并列的 `guji-workspace/988g7gsqhd-…`。

## 模型与用量

- `--model claude-haiku-4-5 | claude-sonnet-5`（需环境变量 `ANTHROPIC_API_KEY`）或智谱 `glm-*`。
- `--budget`（美元，默认 2）：本次新调用花费到了就停，缓存命中不计；`--max-cells N` 只问前 N 格（按批截断）。**先小样本，别直接 `--days all`。**
- 只能在自家客户端跑的模型（muse 等）：`--export prompts.jsonl` 只导出提示词；跑完把每行 `{"job_id", "text"}` 存成 JSONL，`--answers answers.jsonl` 导回打分。

```bash
python3 prep.py
python3 harness.py --prompt v2 --model claude-haiku-4-5 --days 62 --max-cells 20 --budget 0.5
```
