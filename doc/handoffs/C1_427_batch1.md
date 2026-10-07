# C1 交单（overview#427）：context 通道放行乱码的护栏

分支 `claude/C1-garble-1006`。第一批（本提交）只改 `seed_admit`，基于 cv main `9ce4328`（已含 I1、N1）。
第二批（列宽下限闸、卷末印章）另起提交，等 #414 交付后再合，见文末。

## 改了什么

`SeedAdmitParams.context_garble_guard`（**缺省开**）＋三个阈值。挂在 context 通道的判断链上，位置在
`context_blank_gate` 之后、G1 的 `context_guard_*` 之前，只拦 context 这一条通道。

先看证人：整理本对齐字、坐标对位字（`align_ref.coord`）、OCR 候选三路里，只要有一路与 context 字
语义相同（`vmap.semantic`），就算有背书，不拦。没有背书（三路全空也算）时，按下面顺序判，命中一条就
不放行、落人审（`char` 不变，只是 `admit=False`，doubt 记命中的那条）：

| doubt | 判据 | 参数 |
|---|---|---|
| `ctx_garble_shape` | 库 top 相似度 `cov < 0.90`（字块不像任何一个刻例，即「墨形分低」） | `context_garble_cov` |
| `ctx_garble_rare` | 码位不在 U+4E00–9FFF，且 `cov < 0.95` | `context_garble_rare_cov` |
| `ctx_garble_run` | 本列库 top 字里，罕用码位在 ±3 格窗口内凑满 3 个 | `context_garble_run`（0 = 关） |

`ctx_garble_rare` 加 cov 条件，是因为「证人全空∧码位罕用」单独用会误拦 㫖/㕘：武英殿本里这几个
扩展区字是常规刻法，vol04 的 56:3:14 㕘、80:7:12 㫖，vol03 的 84:6:16 㫖 都是对的，库 cov 都 ≥0.966。

## 数字（快照重放，`research/garble_guard/replay.py`）

vol04 用 `snap/96mid1ogzk/vol04/20261006T0716`；vol03 的 seed_admit 用 `20260930T0457`，align_ref、glyph_match、
cell_shrink 用 `20260928T1708-full`（0930 快照只带 seed_admit）。重放的是现成的 context 放行格，
上游各通道不变。

**先更正卡上的口径**：12 个乱码列里放行的 111 格，按通道分是 context 93、match_ref 18（卡上写的
是 98/13）。match_ref 那 18 格（p63c1 的 聖人非之以易之以以、p220c3 的 三卷並其近時始佚歟）
看图都是对的，整理本逐字对得上，不该拦。真正放出去的乱码是 context 那 93 格。

### 三条判据各自单用

| 判据 | vol04 乱码列 context 93 格拦下 | vol04 其余 context 339 格拦下 | vol03 context 93 格拦下 |
|---|---|---|---|
| 证人全空∧罕用码位（卡上原话，不加 cov） | 30 | 17（含 2 格对的：㕘、㫖） | 1（对的：㫖） |
| 无背书∧罕用∧cov<0.95（`rare`） | 34 | 16 | 0 |
| 无背书∧cov<0.90（`shape`） | 84 | 42 | 7 |
| 无背书∧cov<0.85 | 74 | 33 | 4 |
| 列内罕用连串 k=3（`run`） | 32 | 4 | 0 |

### 缺省组合（shape 0.90 ∨ rare 0.95 ∨ run 3）

- **vol04 乱码列：拦 87/93**（shape 84、rare 1、run 2）。漏 6 格：217:2:15亅、217:3:13卜、217:3:14永、
  217:3:16夏、217:3:20氵、220:4:4一。漏的都是 cov ≥0.90 的残笔（亅、卜、氵、一这类笔画少的字形，
  和什么都有几分像）。p217c3 有坐标对位，但对位字与 context 字不同，不算背书。G1 的
  `context_guard_ref_prefer`（缺省关）能补上这几格。
- **vol04 其余 339 格：拦 42**。逐格看图：41 格本身就是错放或非字，包括版框角和十字交叉
  （6:6:-1、23:5:2、206:1:2）、圈号○（79:7:14）、页面噪点（3:1:13、130:2–4 共 5 格）、
  界行杆（216:6:2）、两个半字拼成的格（218:2:14–15）、错位的夹注（216:6:14a–19a 刻的是
  三子而後明，放成 𫡆𭙒𠕲陳𠯦）、刻甲放成乙（10:1:-1 乙→之、34:9:20 於→考、48:6:8 羽→翁、
  127:3:8 寺→奇、198:1:21 宗→宸、205:9:21 主→𠰅 等）。剩下 1 格 26:4:7 確看不准。
  **没有一格能确认是拦错了的。**
- **vol03：拦 7/93**。看图 6 格是错放（20:9:21 考→益、39:9:2 葢→審、39:9:3 益→尊、48:8:21 五→聖、
  59:4:9 两个半字→卽、94:9:2 界行→十）。**误拦 1 格：35:4:7 撰**。坐标对位给的是异体 𢰅，
  `vmap` 里这一对没有连上，所以不算背书。
- 拦下的格都进人审，不会出错字；代价只是人审多了这几格（vol04 +129、vol03 +7）。

## 缺省开不开：建议开

- 拦下的格几乎全是本来就该拦的。两册合计 136 格，能确认拦错的只有 1 格（撰/𢰅），看不准的 1 格。
- 本来就要因为 I1、N1 重跑 seed_admit。这次缺省开，参数进 dump，seed_admit 会判过期，
  但只需要再跑这一步，正好和那次重跑并成一次。
- 要回退：在册配置写 `params: seed_admit: context_garble_guard: false`。只想关连串这一条：
  `context_garble_run: 0`。

## 测试

- 新增 `tests/test_seed_admit_garble_guard.py`（6 条，数据全是自造）。
- `test_seed_admit_context_guard.py`、`test_seed_admit_context_blank_gate.py`、`test_seed_admit_context_verdicts.py`
  三个文件的 `_ctx` 默认关掉本护栏：它们自造的格子 cov 低、又没有证人，不关就会先被本护栏拦下，
  测不到各自要测的闸。断言一条没改。
- 全量 `python -m pytest tests/ -q -s -p no:cacheprovider`：2603 过、1 败、30 跳过。败的是
  `test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`，在 main `9ce4328` 上不带本改动
  也一样败（本机环境问题，与 seed_admit 无关）。

## 第二批（单独一个提交；等 #414 交付后，和 #376 S2 一起合）

### 列宽下限闸 L1n（`gates/column_gate.py`，已写代码）

`ColumnGateParams.narrow_ratio=0.75`、`narrow_reject=False`。文字带宽小于本页中位数 × 0.75、又不是夹注列
（夹注豁免）、也不是非正文列时：缺省记 flag `column_narrow：…`，`narrow_reject=true` 时改为整列拒。

| 册（快照） | 列数 | <0.75 的列 | 看产物文字 |
|---|---|---|---|
| vol04（1006 0716） | 1962 | 5 | 全是 #427 那 5 列乱码，一列不多，一列不少 |
| vol03（0928-full） | 972 | 2 | p49 c7/c8，读得对（match_ref 整列对上整理本） |
| vol05–10（0928-full） | 8739 | 18 | 大多是乱码（vol09 p132/p258/p261、vol07 p128 等）；**读得对的**有 vol07 130c3、vol08 47c4、vol09 260c7 这几列「X卷採進本」小字行，vol05 55c9 存疑 |

窄列大多是切坏的，但也有几列读得对：「採進本」那种小字行本来就窄，vol03 p49 的两列也读得对。
所以**缺省只标记，不拒**。整列拒要丢掉真字，而这些列里的乱码，第一批的护栏已经拦掉了绝大部分
（vol04 这 5 列 context 放行的 68 格拦下 63 格）。哪本书确认窄列都是切坏的，在册配置里开
`narrow_reject`，让这些列回炉重切。这条 flag 现在只落在 `column_gate` 产物里；要让它进请审单
或 close-check 的提示，需要再接一层（本批没做）。

测试 `tests/test_column_gate_narrow.py`（3 条，合成页）。

### 卷末印章（负结果，没进管线）

- 现有的 `occluded_gate`（`steps/occlusion.py`，overview#195）按页面上「中等墨点」的密度找印章，
  只认得斑驳的藏书印（vol04 p130 那种整页都脏的）。p127、p220 的「乾隆御覽之寶」是**清晰的双线方框**，
  框里是粗笔篆文，墨点密度只有 2~8，块内外对比也不够，所以没被认出来。
- 试了一个方框探测器（`research/garble_guard/seal_box_probe.py`）：先补横向断线，再把长横段两两配对，
  最后验两侧竖边。vol04 全书 222 页命中 4 页（p3、p127、p130、p220），p127、p220 的印章框都找到了；
  但 p3、p130 的框落进了正文：字的横笔被闭运算连成长段，配出了假方框。**不可用**，不进代码。
- 现在的兜底：这两页印章列里 context 放行的 25 格，第一批的护栏拦下 24 格（漏 220:4:4「一」）。
  另外 p220c3 前 4 格本来就没放行。印章格已经不会出乱码了，剩下的只是人审要多点几张「非字」。
- 想彻底解决，建议走「版式」而不是「图像」：卷末页上，正文最后一列之后的空列里还切出了字格，
  而坐标对位说这些位置没有字。这种格直接判非字，可以复用 `context_guard_ref_blank` 那一路。
  这需要坐标对位覆盖到卷末空列，我没量，留作下一张卡。

### 顺带：`occlusion.cell_densities` 坐标系疑似镜像（没改）

`cells.quad_page` 是右上原点（`products/kinds/cells.py:32`），`cell_densities` 却直接拿它当左上原点
去原图上数墨点，量到的是**左右镜像那一格**的密度。整页都脏的印章页（vol03 p3、vol04 p130）
镜像不镜像都命中，所以至今没暴露。修它会让 seed_admit 判过期，也会改变各书 occluded 的命中，
要不要修、什么时候修，请总管定。
