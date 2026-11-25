# char_drop 金标迁移（M1 道 C 组，2026-09-30）

## 结论：**无监督/冻结基线型 → 改读 v2 产物重算并重冻「新口径首个基线」**

| | |
|---|---|
| 原金标 `char-drop/expected.json` | 冻结值：n_segs 29791、n_dropped 16（2026-08-26），16 条 `[册,页,列,y0,y1,覆盖]`（v1 页图坐标） |
| 迁移 | 0 条逐条迁移（16 条全部标「已失效」：v1 页图坐标、且它们多是「列尾版框带里的横条/墨疙瘩」，README 自己写过「并非真字」） |
| 新基线 `char-drop/expected_v2.json` | n_segs **35197**、n_dropped **2**（列图坐标，col 右起 1） |

## 为什么原来是假通过

`eval_char_drop.py` 读 `./output/<册>/phase3_char_grid/*_char_grid.json` + 页图；云端没有 → 扫到 0 页，
`单字段 29791 → 0、没被字格接住 16 → 0`，`0 <= 16` →「回归门：通过」。**「丢字数只许降不许升」这条门对「什么都没扫」恒成立。**
（`--v1` 现场复现：`单字段 29791 → 0 / 没被字格接住 16 → 0 / 回归门：通过`。）

## v2 口径（脚本 `scripts/eval_char_drop.py`，判据常数一字不动）

- 对象：page-type 金标里 `page_type==body` 的 vol01 108 页 + vol02 186 页 = **294 页**（与 v1 口径一致；含 vol02/3 等用户排除页——
  这把尺子没有金标，排除页不影响它的意义）；
- 「单字墨段」取自 Step2 **列图**（已去噪、清过界行与上下版框）内容窗 `[content_x+4, content_x-4]` 的行墨投影，
  格高用 Step3 `period`；`RUN_INK/RUN_MIN_H/RUN_GAP/SEG_LO/SEG_HI/COVER` 不动；
- 「被字格接住」= 该段的行落在 **Step4 判为 `cell_type=="char"` 的格**对应的 Step3 格 [y0,y1] 内（夹注 a/b 在 Step4 合成一格，按 pos 并集）——
  墨被**取出来**才算；
- 输出多印一行 `丢字率（…） 2/35197 (0.006%)`（评测层才能解析出分母），逐条明细不再写「盖住 N%」（会被 parse_metrics 误当指标）。

**冻结命令**：`python scripts/eval_char_drop.py ../open-guji-dataset/char-segmentation --update`（写 `expected_v2.json`）。
**回归命令**：同上去掉 `--update`；门：丢字数只许降不许升（基线 2）。

## 新基线的 2 条（逐条看过图）

- vol02/16 c9 y49~103：列首一根竖笔（像「丨」或界行残段），Step3 格 1 判 char 但 Step4 打 `sliver,lost_patch`（Step4 自知丢了，带 flag）；
- vol02/188 c7 y39~170：列首两个 blank 格里一根竖条（界行残渣）。
两条都不是真字丢失。

## 与 doc 上次值对照（不同口径，只作趋势）

- 数据集 `char-drop/README.md`「2026-08-26 首次冻结」：n_segs 29791、丢字 **16**（clip_refit 之前 32、落地未修 35）；
- 同 README「修复结案（2026-08-28）」与 `doc/pipeline_handbook.md` §12：裁剪修复后 `char_drop` **16→29**（没重冻，记为「OFFPAGE_KEEP 同一机制的残留」）。
- v2：**2**。**这是口径变化为主，不是「16→2 的真进步」**：① （推测、未逐条验证）v2 列图经 Step2 清过上下版框，v1 那批「列尾版框带里的横条/墨疙瘩」
  （README 自认并非真字）在列图上不再出现；② 单字段基数 29791→35197（列图上的墨段更干净，切得出的更多）。
  真变化的部分只能说：vol01/47 那批（v1 占 8 条）在 v2 下不再丢。
