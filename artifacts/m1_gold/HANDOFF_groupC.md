# HANDOFF · C 组（Step4 字框收缩层）：recrop / instance_quality / char_drop / crop_margin / left_cut / right_cut / jiazhu_tail

2026-09-30，分支 `claude/M1-gold-seg-0930`。**没有 git commit**，全部改动留工作区等统一提交。
所有数字都是在沙箱里真跑出来的（`GUJI_PRODUCTS_DIR=/home/user/sandbox/products`，`GUJI_WORKSPACE=overlay`）。
沙箱范围：vol01 body 108 页 + vol02 body 186 页（后台 `pipeline keben_body_v2` 跑到 cell_shrink）；另外我用 `_v2_step4.V2Book.ensure`
补跑了 vol01 非正文金标页 41 页、bxgb 41 页（modern_body 管线）。**不含 vol03**；bxgb 只用于 instance_quality 的「未验证参考读数」。

## 总览

| 评测 | 状态 | 新基线（一行） |
|---|---|---|
| recrop | 已迁移（40→31） | 含住+盖墨 **26/31**，flag 兜底 1，无声放行 4，格位消失 0；IoU 均值 0.712 |
| instance_quality | 已迁移（562→77，样本极薄）+ 推翻了一个前提 | 已验证层：clean 73 误报 **0/73**，缺陷 4 检出 **0/4**；另报未验证 v2 原生 585 条：缺陷检出 12%、误报 10% |
| char_drop | 无监督型，v2 重冻 | 单字段 **35197**，没被字格接住 **2**（0.006%），门通过 |
| crop_margin | **整分片退役**（v2 没有这一步） | 无新基线 |
| left_cut | v2 重扫重冻 | 穿边点 9，救回 **5/5**，无承载格 4，门通过（样本太少，仅烟雾） |
| right_cut | v2 重扫重冻 | 穿边点 16，救回 **7/10（70%）**，无承载格 6，**门失败**（3 条仍被剪，已逐条查因） |
| jiazhu_tail | 已迁移（57→44） | 44 条 **44/44** 判对：丢字 0、吞正文 0、消失 0，门通过 |

共用改动：新增 `scripts/_v2_step4.py`（读 v2 产物、缺页补跑到 cell_shrink 的共用件）；`open_guji_cv/eval/registry.py` 里只改了我这几行
（去掉 `v1_output`、补 note；crop_margin 只补 note）。评测脚本保持原指标名/口径，默认改读 v2，`--v1` 保留旧读法。
金标新文件（都在数据集本地克隆 `char-segmentation/` 下，已同时拷到 `artifacts/m1_gold/<评测id>/`）：
`instances/recrop_v2.json`、`instances/instances_v2.json`、`char-drop/expected_v2.json`、`left-cut/expected_v2.json`、
`right-cut/expected_v2.json`、`jiazhu-tail/expected_v2.json`。**旧的 expected.json / items.jsonl 一概没动。**

---

## 1. recrop

**空跑原因**：`eval_recrop.py` 现场重跑 v1 `CharExtractor.extract_page`，读 `./output/<册>/phase3_char_grid` + 整页 png。云端没有 phase3 → 40/40「格位消失」
（`--v1` 复现：`含住+盖墨通过 0 … 格位消失 40`）。v1 链已退役，不能靠补产物修。

**迁移结果**：40 条 → **31 迁移、9 失效**（`instances/recrop_v2.json`，脚本 `recrop/migrate_recrop.py`，详见 `recrop/MIGRATION.md`）。
判据全是图像：① 工作区 `output/<册>/<页>.png`（v1 页图，仍在）+ 人裁图块 `patches/` 证明页图坐标系与金标一致（10 条 exact、21 条 nearby）；
② 人当时看的页图块在现行原图里做归一化互相关 NCC≥0.85（31 条范围 0.857~0.999）换算坐标；③ corrected_bbox 与 v2 Step3 格 IoU≥0.30 锚 (col,slot)
（31 条 0.56~0.91，且全部 `slot = idx+1`）。失效 9：vol01/50 整页 5 条 + vol01/28:4:20（图块与 old_bbox 同尺寸却偏 20px，坐标系矛盾）、
vol01/15 两条（NCC 0.843/0.827）、vol01/9:3:20（金标框仅 33px 高，v2 无对应格）。**没有用算法一致性作判据。**

**新基线**：`python scripts/eval_recrop.py ../open-guji-dataset/char-segmentation/instances`（或 `eval --from-raw run recrop`）→
`review_recrop 31 条：含住+盖墨通过 26，未过但有 flag 兜底 1，无声放行 4，格位消失 0`；IoU 均值 0.712 / 中位 0.681。
无声放行 4 条都是「盖墨 1.00、越界」（5:6:6、15:6:21、8:9:12、5:5:17），即人拖框偏紧 vs 容差 8px，同 char_clustering_design.md:4039 记的老现象。
范围：vol01 10 页（5,6,8,11,14~18,20，即迁移条目所在页）。

**与 doc 上次值对照**：
- `doc/pipeline_handbook.md` §12（2026-08-28 裁边迁移后）：`recrop 32/40 → 33/40`；`char_clustering_design.md:4034`：含住+盖墨 32（无声放行 3→6）；
  r14：`recrop 28/33`；
- `doc/design/review_feedback_loops.md:44` / `segmentation_border_feedback.md:100`：IoU 基线 **0.671**（24 条，2026-08-25）。
- v2：26/31（84%）vs 旧 33/40（82.5%）、28/33（85%）；IoU 0.712 vs 0.671。**样本不同（40→31，丢的多是 50 页等坐标系存疑页），不能直接比**；
  量级持平，无退步迹象。

**仍跑不了**：无（评测层 `run recrop` 已绿）。

---

## 2. instance_quality ⚠ 需要你看

**空跑原因**：`eval_instance_quality.py` 读 `./output/<册>/phase4_chars/index.jsonl`；云端没有 → 打印「缺少 … 请先跑 chars」直接 return，一个指标也没有（n=0）。

**推翻前提（重要）**：任务书说 `instances/patches` 是「人当时看的图」。**实测不是**：README 明写 2026-08-24 重建轮把 415 张图块刷新成新产物，标签仍是刷新前人给的。
我逐张目视了过「图块=v2 字块」这道门的 139 张候选：标 contaminated/truncated/not_text 的 65 张里**只有 4 张图上真有所标缺陷**，其余 61 张图块画的是干净完整的字。
只用图像对得上这一道门会迁出大批「标着缺陷的干净字」，把自检检出率算成假的 0%。所以加了第二道门（目视一致性，`visual_review.json` 可复核）。

**迁移结果**：562 → **77 迁移**（vol01 clean 65 + vol02 clean 8 + vol01 contaminated 4）、485 失效（无图块 170 / 图块≠v2 字块 247 / 目视不符 61 / 拿不准 1 / 同键多标签冲突 6）。
详见 `instance_quality/MIGRATION.md`。**已验证层缺陷只剩 4 条很淡的残渣，样本无统计意义。**
v2 原生人裁 595 条（`items.jsonl` 无 legacy_source）没迁——它们没保存当时图块/指纹（`feedback/anchors` 里这类无字裁决的锚全是 null，「无当时图块，无从核对」）。

**新基线**：`python scripts/eval_instance_quality.py ../open-guji-dataset/char-segmentation/instances [--with-unverified]`
- 已验证层：`clean n=73 被标记 0（误报 0%）；contaminated n=4 被标记 0（检出 0%）`；确定层/疑似层全 0；
- `--with-unverified`（**参考读数，不进主结果**）v2 原生 585 条（vol01/vol02/bxgb，v2 有对应字位 579）：`clean 356 被标记 34（10%）；contaminated 70 被标记 13（19%）；
  truncated 153 被标记 14（9%）；缺陷检出率 12%（27/223）、标记精确率 44%、正例误报率 10%`；确定层召回 1%/精确 75%/误报 0%。
  分书：vol02 缺陷 89 条检出 20（22%）、bxgb 129 条检出 7（5%）、vol01 缺陷 5 条检出 0。
范围：vol01/vol02 body + 非正文金标页；bxgb 41 页用 modern_body 补跑。

**与 doc 上次值对照**：
- `instances/README.md`「当前基线」：`clean n=55 被标记 6（11%）；contaminated 4/4；truncated 2/2；not_text 1/1；缺陷检出率 100%、标记精确率 54%、正例误报率 11%`；确定层召回 29%/误报 2%；
- `metadata.json baseline`（91 实例：14 缺陷/77 正例）：召回 100%、精确 45%、误报 22%；`pipeline_handbook.md` §12：rigid 缺陷检出 55%→64%。
- v2 已验证层 0/4、误报 0/73 **不可比**：旧 14 个缺陷本体早被上游修好（README 自己说「缺陷本体已被修复」），样本构成整个变了。
  **真正有信息量的是未验证层**：v2 原生人裁缺陷的检出率只有 12%（vol02 22%）——这是最近一次人裁的 v2 缺陷，自检漏掉了 78%。
  但那批无图像凭证，可能含已被修好的，所以只能当线索。

**仍跑不了 / 需要你决定**：① 未验证层要不要升成正式金标？要升就得让人重审（或我继续目视现行字块，我试了 12 条，多数看不出所标缺陷，按「判不准不入金标」停手）。
② 审查页以后落人裁事件时应顺手存字块 sha/指纹（`gold/drift.py::fingerprint` 现成），这样下一轮金标可迁。

---

## 3. char_drop

**空跑原因**：读 `./output/<册>/phase3_char_grid` + 页图，云端没有 → 扫 0 页；`单字段 29791 → 0、没被字格接住 16 → 0`，`0 <= 16` →「回归门：通过」。**假通过。**

**迁移结果**：无监督冻结基线型。16 条旧丢字条目（v1 页图坐标、README 自认多为「列尾版框带里的横条/墨疙瘩」）全部标失效；评测改读 v2 重算、重冻 `char-drop/expected_v2.json`。见 `char_drop/MIGRATION.md`。

**新基线**：`python scripts/eval_char_drop.py ../open-guji-dataset/char-segmentation --update`（冻结）/ 去掉 `--update`（回归）→
`单字段 35197；没被字格接住 2；丢字率 2/35197 (0.006%)；回归门：通过`。范围：vol01 108 + vol02 186 = 294 页 body。
2 条逐条看过：vol02/16 c9 列首一根竖笔（Step4 自带 sliver,lost_patch flag）、vol02/188 c7 列首空格位里一根界行残渣，都不是真字丢失。

**与 doc 上次值对照**：`char-drop/README.md`：2026-08-26 首次冻结 n_segs 29791、丢字 **16**；`pipeline_handbook.md` §12 裁边修复后 **16→29**（没重冻）。
v2：**2**。**口径变化为主**：列图上的墨段更干净（基数 29791→35197），v1 那批列尾横条/墨疙瘩多半不再出现（推测，未逐条验证）。不能读成「16→2 真进步」。
改动：输出多印一行带分母的 `丢字率`、明细改写「盖住比例=0.00」（原「盖住 0%」被评测层 parse_metrics 误当总体指标）。

**仍跑不了**：无。

---

## 4. crop_margin

**空跑原因**：必须给 `--intermediate-dir`（v1 `preprocess --keep-intermediate` 的 `vol*/s3_crop`），否则只回显既存金标 394 页、不评测；注册表已因 `intermediate` 前提标 skipped。

**迁移结果**：**整分片退役，0 迁移、394 全部失效**。量的是 v1 s3 整页裁边后残留纸边；v2 没有「整页裁到版框外缘」这一步（Step1 只量边框、Step2 直接从原图出列图）。
金标是标量且无图像指纹，s3 输出图不在工作区。同类失手（外框探测失败）在 v2 由 `border-detection/` 分片与 `page_crop`（他组）覆盖。见 `crop_margin/MIGRATION.md`。

**新基线**：无，也不硬造。**与 doc 上次值**：README「2026-08-27 两册 394 页全扫：93 页/394（24%）残留≥50px，正文 66/294（22.4%）」→ 裁边修复后 93→6（4 页左右方向 + 2 页封面）；v1 读数，随该步退役。

**仍跑不了**：评测层继续显示「需要 s1~s6 中间产物目录」= skipped，这是期望状态（registry note 已写退役原因）。数据集侧建议把 metadata status 改「退役」，我没改。

---

## 5. left_cut

**空跑原因**：读 v1 `phase3_char_grid` + 页图，云端没有 → 113 个穿边点全成「无承载格」，`n_ok / tot` 在 tot=0 时 ZeroDivisionError（E 道基线里的崩溃）。

**迁移结果**：**旧金标整体失效（58 列/114 点，无图像凭证、裁切边定义已换），同一纯墨迹判据在 v2 列图上重扫重冻**（`left-cut/expected_v2.json`，脚本 `left_cut/scan_cut_crossings_v2.py`）。
扫描范围 291 页（body 294 去掉用户排除页 vol02/3、159、160）2619 列 → 9 列 9 点。见 `left_cut/MIGRATION.md`。

**新基线**：`python research/scripts_oneoff/eval_left_cut.py ../open-guji-dataset/char-segmentation` → `穿边点 9，救回 5/5（100%），无承载格 4（人工过目）；回归门：通过`。
改动：可评点为 0 时改为明确报「空跑，不算通过」。

**与 doc 上次值对照**：commit c1f5860c62 / README：58 列 114 点，救回 **88/97=91%**；`pipeline_handbook.md` §12（08-28）`87/96→82/96`。
v2 5/5。**可评点 97→5 是口径变化**（裁切边是 Step3 content_x，不是 v1 贴界行内缘的 cell_left_x；成因推测未逐页验证），n=5 分辨不出回归，只能当烟雾测试。

**仍跑不了**：无。

---

## 6. right_cut

**空跑原因**：同 left_cut（213 个穿边点全成「无承载格」，除零崩溃）。

**迁移结果**：旧金标（51 列/213 点）整体失效；v2 列图重扫：15 列 16 点。试过镜像左缘「不贴窗左缘」防线：右缘点 42→11，把「一」「大」的真长横/捺杀了，撤掉，保持 v1 口径（`right_cut/MIGRATION.md` 写了）。

**新基线**：`python research/scripts_oneoff/eval_right_cut.py ../open-guji-dataset/char-segmentation` → `穿边点 16，救回 7/10（70%），无承载格 6；回归门：**失败**`。
3 条仍被剪逐条查因：vol02/188:7 两点（墨到 185、框到 182）= **撞救援上限 `RIGHT_RESCUE_MAX=16`**（裁切边 166+16=182）；vol01/153:7 y=2424 = 列尾一条贯穿的横向版框残段。
**门是如实失败，不是脚本坏了**；要变绿得改算法（提上限 / 挡栏线残段），超出本任务边界。

**与 doc 上次值对照**：README「修后首测」救回 **166/175（95%）**；char_clustering_design.md 收尾表 **97%**。v2 7/10=70%。**可评点 175→10 是口径变化**，
失败的 3 条里 2 条是 v1 就有的「救援上限」老局限。不能读成「右缘救援退步 25 个点」。

**仍跑不了**：无（但门会红，见上）。

---

## 7. jiazhu_tail

**空跑原因**：现场重跑 v1 extractor 读 `phase3_char_grid`，云端没有 → 57 条全「格位消失」，而回归门只看 `丢字 0 & 吞正文 0`、**不看消失数** →「回归门：通过」。**假通过。**

**迁移结果**：57 → **44 迁移、13 失效**（`jiazhu-tail/expected_v2.json`，`jiazhu_tail/migrate_jiazhu.py`，`MIGRATION.md`）。失效：**10 条在用户排除页**（vol01/89、90、vol02/159——压缩职名页，2026-08-25 用户定不入测试集，本来就不该在金标里）；
3 条目视与原标签不符（vol01/184:5:7、184:9:8、vol02/100:4:16，键偏一格）。这分片从来没存图块，所以做法是：v1 idx→v2 pos=idx+1，出 v2 列图原图切片联系表（不叠算法判断），逐条目视确认标签，47 条里 44 一致。
**标签来源仍是模型目视（model_visual），不是人工。**

**新基线**：`python scripts/eval_jiazhu_tail.py ../open-guji-dataset/char-segmentation` → `44 条：实测 {row 4, tail_a 37, reject 3}；丢字 0，吞正文 0，拆法迁移 0，消失 0；回归门：通过`。
新增防线：格位消失 >0 也判失败。范围：vol01（184 页）+ vol02 共 44 条所在页。

**与 doc 上次值对照**：README 回归口径（丢字/吞正文零容忍）；`pipeline_handbook.md` §12 裁边修复后「丢字 2→1」；`char_clustering_design.md` 收尾表「丢字 0」。
v2 丢字 0 / 吞正文 0，口径相同；样本少了 13 条（10 排除页 + 3 漂移），不是同一批。

**仍跑不了**：无。

---

## 需要你决定的事

1. **instance_quality 金标几乎没救回来**：任务书「patches=人当时看的图」的前提不成立（图块 2026-08-24 被刷新过）。已验证层只剩 77 条、缺陷仅 4 条淡残渣。
   v2 原生人裁（595 条）没有图像凭证。要不要：(a) 接受现状；(b) 让人重审一批 v2 缺陷并**这次存指纹**（`gold/drift.py::fingerprint`）；(c) 把「未验证层」升级为正式金标（我不建议，违背「只留人当时看的图还在」）。
2. **right_cut 门是红的**（70%，3/10 仍被剪）——如实基线。要不要由算法组接「救援上限 16px」和列尾横向残段？
3. **数据集 `items.jsonl` 里的旧 legacy 条目我没标 stale/retired**（评测层 `_fill_gold` 用它报 n_gold/stale_gold，会显示旧数量）。要不要统一把
   recrop/instance_quality/jiazhu/left/right/char-drop 的旧条目置 stale？我没动是因为它们同时是别的东西的来源（instances 的 v2 原生条目混在同一个 items.jsonl）。
4. `left_cut`/`right_cut` 重扫后点数锐减（97→5、175→10），灵敏度基本没了，建议降级为烟雾测试（只判「空跑则失败」）。
5. 评测层 `--from-raw` 只补 Step1–3；我的脚本自己用 `V2Book.ensure` 补到 cell_shrink（只补缺、不 force）。如果你想统一，可把 `utils/bootstrap.BOOTSTRAP_STEPS` 末尾加 `cell_shrink`（我没动，怕影响他组耗时）。
