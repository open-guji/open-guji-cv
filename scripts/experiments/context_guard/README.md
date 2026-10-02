# G1 交单：Step7 context 通道护栏（overview#333）

分支 `claude/G1-context-guard-1002`（基于 main `5217744`），未合 main、未开 PR。

## 结论

1. 在 `seed_admit` 加了四个**默认关**的开关，只作用于 context 通道，关着时产物逐字节不变（见下「验证」）：

   | 开关 | 对应建议 | 判据 | doubt |
   |---|---|---|---|
   | `context_guard_diff` (+`context_guard_cov`=0.8) | 1 前半 | 库判 `diff` 且 cov<0.8 | `ctx_guard_diff` |
   | `context_guard_flags` (+`context_guard_flag_set`) | 1 后半 | char_index 标记含 rule_bar／suspect_empty／bad_seg | `ctx_guard_flag` |
   | `context_guard_ref_blank` | 2 | `align_ref.coord` 说此位是空格（`ref_char==''`）且库不是 same → 不放字 | `ctx_guard_ref_blank` |
   | `context_guard_ref_prefer` | 3 | coord 整理本字与 context 字语义不同且库不是 same → 不放行，默认字取整理本字 | `ctx_guard_ref` |

   逻辑集中在 `_context_guard()` / `_coord_refs()` 两个独立函数，公共段落只多一个 `elif` 分支、两处小改（参数字段、`model_serializer` 一段）。**不直接放行整理本字**：这条路没有独立形状证据，保持送审。

2. **推荐开：`diff`、`ref_blank`、`ref_prefer` 三条**；`flags` 可开可不开（见下）。合起来 vol03 拦 29 格，有标签的 26 格里 25 格是错字。
3. **代价最大的一条单独标出：`ref_prefer`**——待审率 +0.10~0.14pp（vol05 为 0），且在 vol03 唯一一次误拦是异体字（见下）。若只想先上最稳的，开 `diff` + `ref_blank`。
4. 建议 4（印章框）：**阈值修不了**，原因已查清，未改代码（见 §4）。建议 5：只出诊断（§5）。

## 1. vol03 逐条对比（关人裁、关排除名单重跑，基线 context 放行 115 格，其中 34 格有人裁标签，33 格基线字是错的）

| 变体 | 拦下 | 有标签：拦对错字 | 有标签：误拦对字 | 漏拦（有标签的错字没拦） | 待审率 |
|---|---|---|---|---|---|
| 基线 | – | – | – | 33 | 4.098% |
| diff | 8 | 8 | 0 | 25 | 4.144%（+0.046pp） |
| flags | 2 | 2 | 0 | 31 | 4.110%（+0.012pp） |
| ref_blank | 9 | 8（另 1 无标签） | 0 | 25 | 4.150%（+0.052pp） |
| ref_prefer | 18 | 15（另 2 无标签） | 1（104:7:14 會） | 18 | 4.202%（+0.103pp） |
| **合起来** | 29（diff 8／ref 17／ref_blank 4） | 25 | 1 | 8 | 4.265%（+0.167pp） |

- 漏拦的 8 格（10:2:12、20:9:20、26:6:20、27:3:4b、32:9:11、43:5:4、44:8:20、52:2:12）**全是异体字**：context 取通行字（旨／彝／喪／叅），整理本与人裁都是异体（㫖／𢑴／喪…）。这是字形问题，不是这批护栏的对象，需要 variant 通道另处理。
- 误拦的 104:7:14：context=會、整理本坐标=㑹（异体），人裁=會。`ref_prefer` 用 `vmap.semantic` 比，会/㑹未被合并所以拦下——属于「整理本用异体、刻本是通行字」的反向形态。
- `flags` 在 vol03 上完全被 `diff` 覆盖（拦的 2 格都是 diff 也拦的）；其他册独有贡献：vol02 1、vol05 2、vol08 4、vol10 0。便宜（≤0.1pp），语义最直白（界行杆），要不要开看是否图个保险。
- **标签偏差必须声明**：标签基本来自人已经挑出的错例，context 放行里人没看过的格没有标签，所以「误拦对字」被低估、「拦对率」被高估。弥补办法是下面的「整理本代理」。

## 2. 点名格（vol03，基线都是 context 放行）

| 格 | 基线 | diff | flags | ref_blank | ref_prefer | 合起来 |
|---|---|---|---|---|---|---|
| 110:7:3（界行杆，𣏌） | 放 | **拦** | **拦** | 放 | 放 | **拦** |
| 110:4:1a 靈 / 1b 灑 / 2a 子 | 放 | **拦** | 放 | **拦** | 放 | **拦** |
| 110:5:1 秘（整理本空格） | 放 | **拦** | 放 | **拦** | 放 | **拦** |
| 110:6:1 而 / 6:2 以（整理本空格） | 放 | 放 | 放 | **拦** | 放 | **拦**（靠 ref_blank） |
| 94:9:2 十（斜笔画 rule_bar） | 放 | **拦** | **拦** | **拦** | 放 | **拦** |
| 48:8:21 聖（图是五） | 放 | **拦** | 放 | 放 | **拦**，默认字=五 | **拦** |
| 39:9:2 審（上半，葢） | 放 | 放 | 放 | **拦** | 放 | **拦** |
| 39:9:3 尊（下半） | 放 | 放 | 放 | 放 | **拦** | **拦** |
| 39:9:21 見（人裁兄） | 放 | 放 | 放 | 放 | **拦**，默认字=兄 | **拦** |
| 28:2:20 一（30px 空薄片） | 放 | **拦** | 放 | 放 | 放 | **拦** |

**全部拦住。** 没有单条能覆盖全部，说明三条是互补的而不是冗余的。

两点与任务书描述不符，供核对：
- 任务书说 39:9、28:2:20 上 cell_shrink 标了 suspect_empty／bad_seg。我拿 `20260928T1708-full` 快照里的 char_index 看，**这几格的 flags 是空的**（39:9:2 flags=[]，28:2:20 无这两个标记；110:4:1a/1b 只有 `jiazhu`，110:5:1/6:1/6:2 只有 `boundary_ink`）。可能是当时看的是更新的 cell_shrink；本快照里，这些格要靠 `diff`／`ref_blank`／`ref_prefer` 拦，`flags` 只拦得住 110:7:3、94:9:2。`boundary_ink` 在 p110 几乎每格都有，**不能**进拦截名单。
- 110:6:1、6:2 的库判是 unsure（cov 0.92 左右），不是 diff，所以 `diff` 拦不住它们，要靠整理本空格。

## 3. 其他册的代价（无标签，关人裁，默认排除名单；基线 context 放行数 vol02 206／vol05 395／vol08 118／vol10 268）

待审率（pp = 百分点）基线 → 合起来：vol02 3.259%→3.440%（+0.18）；vol05 5.875%→5.975%（+0.10）；vol08 7.674%→8.132%（**+0.46**）；vol10 8.870%→9.105%（+0.23）。

| 册 | diff 拦／+pp | flags | ref_blank | ref_prefer | 合起来拦／+pp |
|---|---|---|---|---|---|
| vol02 | 14／+0.046 | 1 | 9 | 42／+0.139 | 55／+0.182 |
| vol05 | 27／+0.093 | 5 | 0 | 0 | 29／+0.100 |
| vol08 | 31／+0.290 | 11 | 11 | 10／+0.094 | 49／**+0.458** |
| vol10 | 21／+0.072 | 1 | 29 | 36／+0.124 | 68／+0.234 |

vol05 的 `ref_blank`／`ref_prefer` 为 0 是因为该册 188 页 align_ref 都没有 coord 产物（弃权，已核）。**vol08 的代价最大**（+0.46pp），主要来自 `diff` 的 31 格，其中 24 格没有整理本可对照，无法判断拦得对不对——这是唯一值得先抽审再开的册。

「整理本代理」（无标签格：基线 context 字 vs 整理本字）——被拦格里**没有一格是「整理本同字」**（即没有疑似误拦）：ref_prefer 拦的 vol02 42／vol08 10／vol10 36 全是整理本异字；ref_blank 拦的全是整理本空格；diff 拦的 vol02 6 格空格＋5 格异字＋3 格无整理本、vol10 16 空格＋2 异字＋3 无整理本、vol08 6 空格＋1 异字＋24 无整理本、vol05 27 全无整理本。整理本不是真值（上文 104:7:14 就是整理本用异体），所以这只是弱佐证。

**vol02 的说明**：沙箱里 vol02 的 `cell_shrink` 取自 `20260929T1023`（`1024` 快照没带这一步），其余取 `1024`。

## 4. 建议 4：p110 印章框为什么没被遮挡闸认出

用 `data_full/zongmu/vol03/110.png` + 快照的 Step3 cells 直接量 `occlusion.cell_densities`：p110 共 191 格，密度中位 0.22、**最大 4.94**，≥4 的热格只有 5 个且彼此孤立（col6/slot1、col9/slot21、col3/slot21、col4/slot4、col3/slot1）；各种门槛组合（4/12、4/8、4/6、3/12、3/8、3/6）命中都是 **0**。对照 p3 真印章：同样口径命中 136~137 格。

原因：遮挡闸量的是「**中等大小墨点**的空间密度」（印泥斑驳的碎点），p110 顶部是**印得清楚的整框＋篆文笔画**（大连通块），碎点很少，密度根本不上去。降门槛不行：模块头已记「降到 6 格块就有 9 页误报」，而 p110 连 3/6 都不命中，不是阈值问题。要认这类页得换判据（例如：大连通块组成的方框／顶部区域的大块 + 低文字规整度），**未改代码**，建议另开任务，样本用 p110。

## 5. 建议 5（只诊断，没改切分）

p28c2、p39c9：`row_segment` 给 `n_raised=1`、`n_body_slots=21`，而 `column_gate` 里这两列 `raised=False`、`head_raise_inner_y=None`、`border_top_in_column=0`——**没探到抬头框**，`n_raised_hint=1` 是走「墨跨度」兜底分支（`column_gate.py` 约 L314–L323：`extra = int(span/period − expected_slots + span_margin)`）算出来的。症状三条：
- 列首两格都是空白：slot −1（91~117px）与 slot 1（100~120px）都是 blank，真正的字从 slot 2 才开始；
- 28c2 末三格被压矮（93／94／86px，period 111），整列被硬塞 22 格；39c9 末三格是 115／120／130px，没有压矮，但列首两格偏矮（91／100px）；
- 人裁结论都是 20 个正文格（`vol03-slotcount-fix-1001`）。

推断（未能看图复核，缓存里没有列图）：墨跨度被列图两端的残墨拉长，跨度量到 >21 个 period，hint 误加 1。**抬头提示把顶部空白误算成抬头**这个说法成立：hint=1 而首格 blank。

可用的筛查判据：「`n_raised=1`、无抬头框、且 slot −1 与 slot 1 都是 blank」——vol03 全书 90 个 `n_raised=1` 的列里，命中 **12 列**：p23c3、25c9、26c9、28c2、31c5、32c9、36c7、39c9、43c3、68c2、68c5、68c6。已知两条人裁（28c2、39c9）都在里面，其余 10 列没有人裁，精度未知。这 12 列里 context 放行的格共 5 个（28:2:20、32:9:11、39:9:2/3/21），合起来护栏拦下其中 4 个，漏的 32:9:11 是异体字（旨→㫖）。建议：这 12 列升级为列级复核（`slot_count_cards`），切分侧另行处理。
另外全书 64 列带 bad_seg／suspect_empty／rule_bar 标记的格（多数是 slot 21 的 `tail_junk`），升列级复核会太宽，不建议按标记整列升。

## 6. 验证

- **默认关逐字节不变**：同一批参数（关人裁、关排除名单，vol03 全 110 页）下，用 `git worktree` 的 main 代码与本分支代码各跑一遍，**110 页 `seed_admit/p*.json` 逐字节相同**，`params_hash` 均为 `e198735b90133da6`（`_manifest.jsonl` 只差时间戳）。
- 单测 `tests/test_seed_admit_context_guard.py`（自造数据）7 条：关着时四种形态都被放行（前提）、每条开关各拦各的且有「不该拦」的对照、`〓` 占位弃权、关闭时 dump 里没有任何 `context_guard_*` 字段。
- `tests/test_seed_admit*.py` + `test_suite_hygiene.py` 共 95 条全过。全量 `pytest tests/` 在本沙箱有 15 个模块收集失败（`test_console_*`、`test_review_*`、`test_step8_*` 等，ImportError，环境缺可选依赖），与本改动无关，未逐个排查。

## 7. 开法

书 yaml：

```yaml
params:
  seed_admit:
    context_guard_diff: true
    context_guard_ref_blank: true
    context_guard_ref_prefer: true
    # context_guard_flags: true   # 可选，独有贡献小
```

改了参数后重跑 `step seed_admit <book>` 即可（参数进指纹，产物自动过期）。开 `ref_prefer` 的册若没有 `align_ref.coord` 就自动弃权。

## 8. 复现命令

```bash
S=<scratch>; export GUJI_WORKSPACE=<…/96mid1ogzk-…> GUJI_GLYPH_DB=$S/glyph.db PYTHONIOENCODING=utf-8
# 1) 解快照（在 guji-workspace 里 fetch 对应 snap 分支后）
git archive snap/96mid1ogzk/vol03/<ts> | tar -x -C $S/snap/<ts>   # 依次叠 20260928T1708-full → 20260929T0451 → 20260930T0457 到 $S/prod_orig
# 2) 建字形库（约 3 分钟）
python -m open_guji_cv glyph-db rebuild
# 3) 基线与各变体（vol03 要关人裁和排除名单才能量到人裁过的格）
GUJI_PRODUCTS_DIR=$S/pv_base python -m open_guji_cv step seed_admit vol03 -w $GUJI_WORKSPACE --pages all --force \
  --params '{"seed_admit":{"use_human_verdicts":false,"use_exclusions":false}}'
# 变体：在 params 里加 {"context_guard_diff":true} / flags / ref_blank / ref_prefer / 全开，各出一个目录
# 4) 标签与对比
python scripts/eval_context_guard.py --make-labels vol03 $S/labels_vol03.json
python scripts/eval_context_guard.py --book vol03 --base $S/pv_base --variant diff=$S/pv_diff … \
  --labels $S/labels_vol03.json --cells vol03:110:7:3,vol03:48:8:21
```

注意：人裁模式（默认）下 seed_admit 每页要重算绑定表，110 页要十几分钟；关人裁模式约 1~2 分钟。沙箱基线以**当前工作区 main 的人裁**为准，比 `20260930T0457` 快照里的多（多出 step8-fix 等 10-01 事件），所以不能直接拿快照的 seed_admit 当基线对比。

## 9. 没做的／边界

- 没改切分代码、没碰工作区正式 products；其他册沙箱产物不入库。
- 其他四册没有人裁标签，「误拦」只有整理本代理一个弱佐证；vol08 的 `diff` 24 格无整理本可对照，建议开之前抽审。
- 异体字形态（漏拦的 8 格、误拦的 104:7:14）两个方向都存在，需要另外的设计，不在本次范围。
- 与 D3 道（`claude/D3-shadow-promote-1002`）的冲突面：`SeedAdmitParams` 末尾新增字段、`_drop_off_rare` 序列化多一段、context 通道 `elif` 多一个分支；其余都在新增的独立函数里。
