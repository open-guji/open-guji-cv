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

## 第二批（另一个提交，等 #414 交付后再合）

列宽下限闸（改 column_gate）、卷末印章排除（改版面层）。这两项都会让各书从 column_gate 往后
全部判过期，和 #376 的 S2 一起合。方案和数字见第二批的提交和卡上的评论。
