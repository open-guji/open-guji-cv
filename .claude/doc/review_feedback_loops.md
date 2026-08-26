# 审阅反馈三环：每轮人裁怎么流回三个方向

2026-08-25 十七轮定型。每轮审阅结束后，人的每个动作都要流到该去的地方
——这页是三条反馈环的**总入口**，逐环给：缺陷形态 → 回流通道 → 消费方
→ 本轮实据。固定操作步骤在 pipeline_handbook.md「每轮审阅后的固定流程」，
这里讲的是**去向与机理**。

```
              ┌─ ① 向上：切分层（G1/G2）
   人裁一轮 ──┼─ ② 向下：字形匹配栈
              └─ ③ 本步：进库准入规则 + 字形库本身
```

---
## 环① 向上：切分层

**缺陷形态**（实审反复出现的三类）：
- **上下内容混入**：邻字探入（上一字的脚/下一字的头）、版框横条；
- **中间截断**：格相位整体偏移把本字切半（列尾格 idx=20 最密集，
  框整体偏高 35~55px，14~18 页反复实锤）;
- **边框混入**：最左/最右列吃进断续内边框（segmentation_border_feedback.md
  四个惯犯位置）。

**第四种形态（2026-08-25 十九轮新增）**：**真字被判成空格位**。
`vol01:9:3:20`「一」——单横字墨少，`empty` 判据（ink_ratio 阈）把它当
空格位，`cell_type` 从 char 改成 empty。人裁确认是真字并已 human 进库。
这类行**不是幽灵行，不许删**：删掉等于把切分层误判的证据也删了。
`scripts/repair_seed_queue.py` 现在按「id 在不在 index 里」判幽灵，
`cell_type` 被改判的单独报出来（`⚠ 切分层改判成非 char`）。
目前孤例，但形态明确：**笔画数极少的字（一/二/丨）逼近空格位阈值**。

**回流通道**：
| 人的动作 | 事件 | 落到哪 |
|---|---|---|
| 拖框重切 | `recrop`（几何通道）| `seed-ingest` 改 index/patch/库真源 → `scripts/build_recrop_shard.py` 进数据集 `char-segmentation/instances`（`seed=review_recrop`，old_bbox=坏例、corrected_bbox=金标）|
| 判非字（版框/残带）| `not_a_char` | `scripts/build_seg_cases.py` 建切分金标分片 |
| 仅定字·不入库 | `confirm admit=false` | 同上（`review_label_only`，图块脏但字可认）|

**纪律**：`build_recrop_shard.py` 必须在**提交重切改动之前**跑（旧图块从
git HEAD 捞）；整册重跑后必须 `scripts/replay_recrops.py` 把人工框贴回
（已挂进 run_pipeline.sh，防手滑）。

**消费方**：切分优化会话从 segmentation_border_feedback.md 进。现成
回归尺：24 条人工重切框，现行算法 IoU 0.671（2026-08-25 基线）。

---
## 环② 向下：字形匹配栈

**缺陷形态**：形近异字排序倒挂（same 字形 cov 反而低于形近他字）。

**回流通道**：
- 审查里发现的匹配错误 + 体检（/glyphdb-audit）的 rival 旗 →
  `scripts/build_match_triplets_shard.py` 进 `glyph-match/triplets`
  **hard** 子集（构建时已知失败，基线≈0 是设计使然，就是优化靶子）；
- **control 子集不得回退**——为修 hard 把 control 改坏是净亏。

**消费方**：匹配优化会话从 glyph_match_stack.md 进。护栏：
`scripts/eval_match_triplets.py`（本轮 control 1.0 / hard 0.79）。

---
## 环③ 本步：进库准入规则 + 字形库

### 3a. 什么时候可以自动确认（多信号裁决）

信号共四路：**OCR**（只供候选，置信度不可靠，**永不参与自动判断**）、
**过闸对齐**（整理本×载体逐字印证）、**免闸参考**（整理本参考，噪声大）、
**库匹配**（形状证据）。核心机理：**两路零同源证据同指一字即可放行**——
文本（整理本）与形状（库）互证；同源的两路（OCR×库 都看图）不行，
实测 OCR×库 97.1% 就是不够。

现行放行通道（seeding.py `admission_decision`，全部人裁回放标定）：
| 通道 | 条件 | 标定 |
|---|---|---|
| 常规 | 过闸对齐 × OCR 同字，零疑问 | 定型 |
| dual_degraded | 同上，仅 degraded 疑问 | 58/58 |
| match_ref | 库 top × 整理本同字（degraded/near_form 可穿透，须过闸对齐）| 144/144 |
| **match_replace** | replace 层对齐 × 库 top 同字 @cov≥0.95（signal_conflict/replace_align 不拦——它们说的是 OCR，而 OCR 本不投票）| **70/70** |
| **match_ref_weak** | 免闸参考 × 库 top 同字 @cov≥0.98（weak_single 不拦）| **25/25**（0.97 出 祗/祇 一错，阈上顶一档）|
| match_solo | 无整理本，库 cov≥0.99 单独放行 | 定型 |
| match_solo_ocr | 库 cov≥0.95 + OCR **字符**背书（非家族）| 81/81 |
| context | 锚定页 LM margin≥0.70 | 门槛化标定 |

**db_inconsistent 分两种情况**（2026-08-25 十八轮，用户实锤
vol01:22:5:4 「詞」）：这条疑问判的是 **proposed**，而无对齐时 proposed
退回 OCR 字——于是它说的是「这块图不像库里的 **OCR 字**」。
- 要进的字**就是** proposed 时：直接相关，照拦（毒库防线）；
- 要进的是**别的字**（match_ref_weak 进参考字，OCR 字与它不同字）：
  这句话与放行无关，反而是「它不该是 OCR 字」的旁证 → 放行。
  实锤那张卡：OCR 司 18%、整理本 詞、库 top 詞 cov 1.00，疑问 5 说的是
  「不像库里的司」——完全正确。回放 @0.98 触发 25 → 38 全对。
与 signal_conflict 拦 match_replace 同一形态：**疑问码描述 OCR，而 OCR
不投票**。判疑问时记的是「对谁的怀疑」，放行时要核对是不是同一个对象。

**自证不是证据（同轮修）**：字位一旦进过库，重跑 seed / 复裁时它自己就在
matcher 里，「库匹配」拿到的是自比——cov 1.00、matched_id 就是它自己
（审查页上「最近刻例 vol01:22:5:4」编号与被审字位相同，一眼露馅）。
实测 vol01 队列 1333 行如此、1136 条 cov=1.0。进库通道的前提是「文本 ×
形状两路同源性为零」，自比把形状那一路变成「上次进库时定的字」，
独立性归零；match_solo 更会被自证直接喂饱。
`GlyphMatcher.match(exclude_id=)` 摘掉自身，seed 传 `rec.id`。
（本轮标定未受污染：790 条人裁行里只有 9 条自证，剔除后 67/67、22/22 仍全对
——人裁行大多没进过库，进了库就不出卡片。）

**队列与库不许分叉（同轮修）**：seed 重跑会重判 auto_admitted 行，判据
不放行就把它降回 pending——可库里的 admission **不会**因此撤销，于是
「库里已进、队列还在出卡片」，人白审一遍（实测 3 条）。现在重跑遇到
admissions 里已有的字位只复述不重判（`note=already_in_db`）。

### 3b. 字形直接进库 + 库真源卫生

- 人裁 `confirm` 即 human provenance 进库；机器通道进库字取**文本侧**
  的字（match_replace/match_ref_weak）或库匹配形（match_ref/solo）。
- 库真源是 **canonical 256×256**（glyph_canonical_format.md）。同步库内
  图块**只能走 `GlyphDB.refresh_instance_patch`**（canonical 化 + 重算
  派生 + 触碰缓存戳），直接 UPDATE 原始字节 = 破坏全库同一标准（犯过）。
- **短笔画被消掉**（2026-08-25 查明）：三个来源，全部已处理——
  1. `_drop_stray_components` 旧版把 <2% 墨量的 丶/短横 当残片删
     （另一会话已修：质心在字身框内的小块收回）；
  2. 修复**之前**进库的存量带着咬痕（58 条实测）→ 已全量重刷；
  3. `remove_edge_specks` 细线判据位置无关，把「壽」中部磨细断开的
     真横当界行删（vol01:26:3:5 实锤）→ 已加**位置守卫**（横线只删
     上下 25% 外带、竖线只删左右 25% 外带），回归钉在
     `test_thin_line_position_guard`。
  库卫生自查：全库「存的 canonical == 现行代码重算」扫描（本轮 779 条
  刷齐），改归一化/canonical 任一层后都该重扫。

### 3c. 每轮的标定动作（固化成脚本）

```bash
PYTHONPATH=. python scripts/calibrate_admission.py output/vol01
```
报三样：① 待审里有多少按现行规则已能自动进（>0 → 跑
readjudicate_pending 回填）；② 人裁被拦行按 疑问×信号 聚类（量大且带
「对齐/参考+库」的组合 = 下一条放行规则候选）；③ 新规则的回放纪律
（全量人裁、生产变体表、错例定阈值、落地后回填 + 单测钉住）。

本轮收益：readjudicate 清 223 条（match_ref 139 / match_replace 66 /
match_ref_weak 18），4~24 页待审 184 → 71。剩余拦截大头是「库无」
（该字在库里还没有形状证据）——冷启动问题，随库增长自然消解，
不需要规则。
