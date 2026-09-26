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

```bash
python3 prep.py
python3 harness.py --prompt v2 --model glm-5 --days all --workers 2
```
