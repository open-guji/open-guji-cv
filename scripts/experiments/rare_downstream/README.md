# 5-b 生僻字候选接进下游：开/关对照（2026-09-28，D 道，overview#126）

只在沙箱里跑，不写任何书的正式产物。

## 输入

| 书 | 产物 | 真值 |
|---|---|---|
| 四庫 vol03 | guji-workspace `products-snap/vol03-20260927` 的 `cloud-20260927-4e2e0b7-iron.tar.zst`（含 5-b） | 光盘版（`guji collate` 放出格里与光盘版字面不同的 `sub.*`） |
| 全唐文 v006 | `products-snap/qtw-v006-v010-full-20260927`（Step1-7）＋ `snap/qtw-draft/v006/20260927T2215`（5-b） | overview `新书整理/书/全唐文/人裁待导入/` batch2/3/5（有字的格，563 格） |
| 北行 bxgb | dev_set 9 页从原图跑到 `glyph_match`（main 代码） | 只做关开关时 main vs 分支逐字节比 |

字形库：`glyph-db rebuild` 从四庫 `output/glyph_store` 重建到沙箱（全唐文借同一个库，同 Z15）。

## 跑法

```bash
# 四个沙箱变量都指到沙箱（子会话须知 §〇）：products / glyph.db / feedback / cache
run3.sh <cv代码根> <书目录> <book> <products目录> <沙箱根> '<--params JSON>' [pages]

# 开：
'{"align_ref":{"rare_topk":5},"context_decide":{"rare_topk":5},"seed_admit":{"rare_agree":true}}'
# 全唐文正式口径另加 "seed_admit":{"use_context":false}

python eval_rare.py vol03 <关> <开> --collate collate_关.json collate_开.json
QTW_TRUTH_DIR=<overview>/项目进展/新书整理/书/全唐文/人裁待导入 python eval_rare.py v006 <关> <开> --truth
```

⚠️ 全唐文沙箱里没有原图，`--pages all` 会解析成 0 页，要写 `1-86`。

数字见 `open_guji_cv/steps/align_ref.py`、`context_decide.py` 模块头「2026-09-28」一节与 overview#126 评论。
