# daizhige 逐列本当 Step3 结构约束：离线实测（2026-10-19）

结论与数字见 [doc/research/切分现状梳理与新方向-2026-10-19.md](../../doc/research/切分现状梳理与新方向-2026-10-19.md) §六。
这里只放脚本，**不改仓里任何生产代码**：约束全部在 `run_constrained.py` 进程内 monkeypatch。

| 文件 | 作用 |
|---|---|
| `structcmp.py` | 逐列结构比对：`cell_shrink` 产物的 `(slot, sub)` 集合 vs daizhige 格位（口径：pos≥0 → slot=pos+1，pos<0 → slot=pos；夹注 r→a、l→b）。分类 exact / offset_only / over_split / under_lost / note_* / col_fail |
| `constrained_dp.py` | `row_boundaries._bounded_elastic_dp` 的替身：取源码、按格加「该空 / 该有字」软罚分（该有字却空 → `PEN`；该空却有字 → `PEN × min(1, 像字墨行/period ÷ CONSTRAINED_MASS)`，版框那种满宽密行不计） |
| `run_constrained.py` | 在真管线里跑：①DP 换替身；②`resolved_forced_jiazhu/main` 换成 daizhige 的夹注格（只强制两半都有的格，段尾单 a 格交给现有段端收编）/ 正文格；③`CONSTRAINED_RAISE_EXACT=1` 时抬头级数按 daizhige 定；④`CONSTRAINED_KIND=narrow` 时 Step4 之后只对「列端、扁而宽」的格按转写二选一（框线 / 「一」） |
| `analyze.py` | 把错列归到 劈字 / 首末渣 / 丢字 / 夹注 / 格号平移 / 空列有字 |
| `viewcols.py` / `audit.py` | 基线与约束版并排叠框；被改了类型的格拼图——**数字之外一律看图** |
| `flipcmp.py` | 两份 structcmp 结果并排：逐格、字数两个口径各报准确率、修好、改坏，并列出改坏的列（交接单 `doc/handoffs/HANDOFF_殿本Step3结构先验.md` 用它验收） |
| `cutcheck.py` | 格线穿字检查（只看图）：两组 Step3 产物并排，列出 B 比 A 多横穿字格线的列。补 structcmp 的盲区：抬头字不在列图里时格号集合照样对得上（vol04 p84 c5） |
| `cell_ocr.py` | 「整理本不分行」实测（研究文档 §十一）：Step4 字块小图逐格 rapidocr 识别 top1，作对位载体串。要另装 `rapidocr-onnxruntime` |
| `unsplit_colcount.py` | 不分行的整理本 → 对位分列 → colgold 同格式的逐列字数表，喂 `row_segment.colgold_prior`。要另装 `opencc-python-reimplemented` |

## 复现

```bash
export GUJI_WS96=<guji-workspace>/96mid1ogzk-欽定四庫全書總目武英殿刻本 PYTHONIOENCODING=utf-8
# 沙箱工作区：books/ + data_full 软链；纯算法基线（不带 feedback）
guji pipeline keben_body_v2 vol05 --to cell_shrink --pages all --allow-cv-mismatch --why dzg_struct_prior -w $WS_BASE
# 约束版：复制基线产物后从 Step3 重跑
CONSTRAINED_MASS=0.3 CONSTRAINED_RAISE_EXACT=1 CONSTRAINED_KIND=narrow \
  python research/dzg_struct_prior/run_constrained.py --pen 0.5 -- \
  pipeline keben_body_v2 vol05 --from row_segment --to cell_shrink --pages all --force --allow-cv-mismatch --why dzg_struct_prior -w $WS_CON
python research/dzg_struct_prior/structcmp.py $WS_BASE/products vol05 --out base_vol05.json
python research/dzg_struct_prior/structcmp.py $WS_CON/products vol05 --out con_vol05.json
python research/dzg_struct_prior/analyze.py base_vol05.json con_vol05.json $WS_BASE $WS_CON
```

不分行实测（§十一）：

```bash
python cell_ocr.py --ws $WS_BASE --vol vol04 --out ocr_vol04.jsonl            # 约 100 格/秒
python unsplit_colcount.py --ws $WS_BASE --vol vol04 --ocr ocr_vol04.jsonl \
  --text <整理本 txt，换行会被去掉，小注 <右左>> --region 80000,130000 --start-from-image --out gp_vol04.jsonl
# 册 yaml 或 --params：{"row_segment": {"colgold_prior": "<gp_vol04.jsonl>"}}（feat/yolo-colcount-prior 的代码）
```

没装 torch（U-Net 裁判关），基线与约束版同条件；裁判只改粘连处的缝形，不改格数和类型。

## 踩过的坑（都已修，留着防再犯）

- **按 `border_top`/`content_x` 认列会认错**：同页多列这两个值相同，别列的格位被套上来，看起来像「约束改坏了 16 列」。改成从 `ctx.image('column_image', pXXXXcYY)` 取列号。
- **`CONSTRAINED_KIND=1`（按转写全面改格子类型）不能用**：真字被改成空（书名列首字、抬头字的格号口径差一格，卷端大字题名），空框被改成字（掩盖了上面的并格）。只留 `narrow`。
- **夹注段尾单 a 格不能进 `forced_jiazhu`**：会被拆出一个空的 b 半。
- **喂 `colgold_prior` 的表 `start` 不能留空**：C 按 `start`+`n` 定格位段，留空当 0，提要正文（缩进两格）段尾两格落到段外，末格常过不了「像字」检验，C 把末字切丢。vol04 一册坏 232 列。#204 起 `load_colgold` 不收 start 为空的行。按图推 start（纯算法第一个非空格）在 vol04/05 上没坏，但全书上会让 C 对 3,006 个本来对的列动手（真 start 79 列，设计 19 第八节），只当退路。
