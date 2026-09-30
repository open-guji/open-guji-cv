# HANDOFF M1：Step1–4 评测空跑／假通过治理（2026-09-30）

分支 `claude/M1-gold-seg-0930`（基于 origin/main，**并入了 `claude/E-eval-baseline-0930`**——E 道的 `doc/cloud_eval.md` 与评测修复当时还没进 origin/main）。不合 main。
细节：`artifacts/m1_gold/HANDOFF_group{A,B,C,D}.md`（每评测五节：空跑原因／迁移结果／新基线／上次值对照／仍跑不了），各评测 `artifacts/m1_gold/<id>/MIGRATION.md`（迁移清单）。

## ⚠ 需要你代办 / 决定
1. **测试集仓推不了**：`add_repo open-guji/open-guji-dataset access=push` 被权限分类器拒，只有只读浅克隆。全部金标改动打成一个补丁
   `artifacts/m1_gold/dataset_m1_gold.patch`（47 文件，`git apply` 到 dataset 仓即可；`git apply --check -R` 已验可逆）；各评测目录另有分片副本。分支 `claude/M1-gold-0930` 未建。
2. **overview 仓未挂载**（E 道同样被拒，本次没再试）：#305 评论、overview 的 `云端评测基线.md` 由你代贴；下面「基线表」可直接拷。#305/#300 原文没读到，分工按任务书执行。
3. **C 组发现：任务书前提不成立**——`instances/patches` 不是「人当时看的图」，是 2026-08-24 重建轮刷新过的新图，标签仍是刷新前人给的。抽 139 张候选目视：标缺陷的 65 张里只有 4 张图上真有缺陷。所以 instance_quality/recrop/frame_strip/side_rule 的迁移都额外加了一道「目视一致性门」（`instances/…visual_review.json` 可复核）。v2 原生人裁（~595 条）没存图块/指纹，未迁；要恢复需重审一批并存指纹（`gold/drift.py::fingerprint`）。
4. **right_cut 回归门如实失败**（救回 7/10）：3 条仍被剪，2 条撞 `RIGHT_RESCUE_MAX=16`、1 条列尾贯穿残段。要变绿得改算法，超出本道边界——是否交算法组？
5. touching_cuts 的 1498 条 legacy（只有列图坐标+col_h，人裁图没存）怎么处置：(a) 分档报（现状）(b) 整批标 stale (c) 重新人裁带页面坐标的一批。B 组倾向 a+c。`items.jsonl` 里旧条目各评测**都没标 stale**，n_gold 仍显示旧数。
6. 值得肉眼看：frame_strip vol01/22:7:20（墨 2178<基线 2240）；column_warp vol02/11 c1（左界预测 10 vs 人标 5）、vol01/14 c3（欠 4px）；touching_cuts page 档有 19 条 >10px，多为列首列尾旧 `ok` 点偏了 30–50px（可能是 Step3 真变化，id 见 HANDOFF_groupB §2）。
7. column_warp 的 `border_class` 金标：metadata/README 写 64 条，**本克隆里 0 条**且无 `end_fingerprint`，没法迁（bxgb 另 31 条无指纹无图）。需从本机工作区/原始提交找回。

## 根因（共性）
切分口径换过几轮：**(1)** 10 个评测＋instance_quality/recrop/frame_strip 读 v1 链 `output/<册>/phase3_char_grid`／`phase4_chars`，云端扫到 0 页，回归门对「什么都没扫」恒成立 → 假通过（char_drop、jiazhu_tail、seam…），left/right_cut 在可评点为 0 时除零崩；**(2)** pagetype 读 `output/<册>/<页>.png`；**(3)** 金标挂 `page:col:idx` 与旧坐标，换链后键失效；**(4)** geometry 金标量在 v1「透视校正+裁剪」帧上（39/39 页 image_size 与原图不同），不是原图帧。
口径：只留「图像凭证还在」的条目（指纹 / 存图 NCC≥0.90 + 位移≤4px + 尺寸差≤12px / 投影曲线同一），**不用算法一致性当判据**；迁不了标失效，不造金标。评测脚本默认读 v2 产物，`--v1`/`--source v1` 保留旧读法，指标名与判据常数不动。

## 基线表（沙箱：vol01 108 + vol02 186 正文页 Step1→4，GUJI_PRODUCTS_DIR 沙箱，未碰 ws 正式 products）
我抽查复跑了下表标 ✔ 的项（`eval --from-raw run …`，与各组报告一致）；其余为各组自报。

| 评测 | 空跑/失败原因 | 金标迁移 | 新基线 | doc 上次值 | 对照结论 |
|---|---|---|---|---|---|
| pagetype ✔ | 读不存在的 v1 png，n=0 | 394 全留，未动 | n=394 策略 99.5%，误跳过正文 0，skip 检出 4/5 | README 99.5%（383 页+11 uncertain） | 同数无回归 |
| frame_strip ✔ | 格位指向 v1 patches，「65 格位已消失」 | 65→8（57 失效：47 无存图/10 图不同） | n=8：残余 0/3，误剥 0/5，字保全 3/8（容差 3% 时 8/8） | 残余 19%「天花板」、字保全红线 100% | 口径变（v2 重采样墨量差 0.2~2.8%），n 太小；看 22:7:20 |
| column_warp | 读 v1 step2_columns 缓存；border_class 金标缺 | 115 列→86（29 失效） | 86 列/66 页：文字带命中走廊 137/172，吃字身 21/86 列（最大 5px） | README 现行口径 58/64、吃字 1 列 1px；legacy 43/50 | 主因口径/图变（容差 1px 后 165/172）；真变化见决定 6 |
| row_boundaries ✔ | 旧坐标金标无列图缓存，「对齐相关 -2.00」是初值 | 18 列→5（13 失效） | n=110 点：≤3px 50~52.5%、≤5px 61~64%、≤10px 83~85% | ≤3px 30.3%／≤5px 48%／≤10px 67.7%（n=198，全来自 vol02/135） | 样本不同不可比；`--realign` 精确复现旧 198 点数 |
| touching_cuts ✔ | 缺 bxgb 产物；59 条折线缺 y 致崩 | active 1599：page 口径 101 迁、legacy 1498 无法验证（分档报） | 直线 n=553 mean 3.9/med 0.3/p90 12.2；page 档 n=90 ≤3px 72%；折线 n=776 ≤6px 47.6% | E 道 n=727 mean 7.4/med 1/p90 23；doc 折线 96.1% | E 的 727 无法复现（页集不明）；折线口径差（无 anchor 复核） |
| seam ✔ | v1，无金标点，空跑 | 无金标（无监督）；新口径首个基线 | 294 页：切缝 44287，重切缝 7，p99 0.0062 | 重切缝 179，p99 0.121 | 口径不同，仅趋势；阳性对照 +20px 平移→100/171 |
| truncation ✔ | v1，n=0 | 同上 | 294 页：≥10% 截断 133（0.35%），≥20% 84，≥30% 27，页级 p99 4% | 393（1.20%），p99 30.3% | 口径不同；阳性对照 2→104/168 |
| side_rule ✔ | v1；金标是算法挖的 | 264→2（25 条正样本全失效） | 计分 2，残余无法量，误剥 2/2，字保全 1/2 | 残余 25/25→2/25、误剥 1/240 | **n 太小不能当基线**；需在 v2 重挖正样本 |
| text_band ✔ | v1，「字格 47431→0」假回归 | 不迁，重冻 v2（`expected_v2.json`） | 门通过；首冻 109 页/17231 格/偏短 0（vol02 当时未跑完，见下） | 294 页/47431 格/偏短 2 页 | vol01/50 0.863→1.096、/88 0.898→0.967，真变化；**需 `--update` 重冻含 vol02** |
| page_crop ✔ | v1 | 不迁，冻 v2 | 318 页越界 0；最小余量 右 254/左 245px | 6 页越界（18/136/64/70 现均不越） | 真变化（口径与对象都换） |
| recrop ✔ | 40/40 格位消失 | 40→31（9 失效） | 含住+盖墨 26/31，flag 兜底 1，无声放行 4，消失 0，IoU 均 0.712 | 33/40，IoU 0.671 | 样本不同，量级持平 |
| instance_quality | v1 phase4_chars | 562→77（485 失效） | 已验层 clean 误报 0/73，缺陷检出 0/4（n 太小）；`--with-unverified` 参考：检出 12%/误报 10% | README：检出 100%/精确 54%/误报 11% | 无统计意义，见决定 3 |
| char_drop ✔ | v1；门对「没扫」恒真（假通过） | 无监督，v2 重冻 | 35197 字段，丢字 2（0.006%），门通过 | 旧基线 16 | 口径不同，仅趋势 |
| crop_margin | 需 s1~s6 中间产物；量 v1 s3 整页裁边 | 整分片退役 | 无 | — | v2 无此步，**退役** |
| left_cut ✔ | v1；可评点 0 除零崩 | v2 列图重扫重冻 | 穿边点 9，救回 5/5，无承载格 4，门通过 | 可评点 97/175 | 可评点骤降，当烟雾测试 |
| right_cut ✔ | 同上 | 同上 | 穿边点 16，救回 7/10，**门失败** | 同上 | 见决定 4 |
| jiazhu_tail ✔ | v1；门不看格位消失（假通过） | 57→44（13 失效：10 在排除页、3 键偏一格） | 44/44 判对，丢字 0 吞正文 0 消失 0 | — | 门通过 |
| geometry | v1 帧 + v1 产物 | 39→30 页（9 stale），界行 285→243，`derived` 未逐页复核 | 30 页/243 界行：界行落入列框 0.00%，全清页 30/30，倾斜 中位 1.5/p90 2.9px | 旧 v1 0.57%／36/39／4.0/8.5px | `residual_tilt` 已非同一量，9 页排除有幸存者偏差；不是改进幅度 |

## 已知遗留
- text_band 基线只含 vol01 108 页 + vol02 1 页（A 组取数时 vol02 row_segment 未跑完，现已跑完）：`python scripts/eval_text_band.py ../open-guji-dataset/char-segmentation --update` 重冻（我没动，冻基线需你认可）。
- 注册表解析的头条指标对 seam/truncation 显示「≥1 0%」这类，是解析器取首项所致，真数字看脚本输出。
- `BOOTSTRAP_STEPS` 未加 `cell_shrink`（`--from-raw` 只补到 Step3，Step4 类评测靠 `scripts/_v2_step4.py` 自补）。
- geometry `--from-raw` 会多补一遍 Step3（缺产物判据查 Step3）。
- 沙箱：`/home/user/sandbox/{products,A_products,products_groupD,cache…}` 随容器回收，不入库。
