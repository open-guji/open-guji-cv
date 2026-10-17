# context 通道把无字页框噪点放行成「一」：诊断（GUJI-555，vol04 `220:4:4`，2026-10-17）

> 状态：**诊断，未改 seed_admit／context_decide**。动它们会让对应步产物判过期，先报 Mila。
> 本容器没有 vol04 数据，**`220:4:4` 本格的 `char_index` 标记／框／墨量／坐标对位没有看到**，下面的"为什么放行"是对代码路径的**逐闸核对＋最小复现**，是否正是这一格走的哪条路，需要 Owen 补一行数据（见末节）才能下定论。

## 结论

1. **缺的不是 `context_blank_cell`，而是它的判据对这类格天然不灵。** `context_blank_gate` 只看 `ink_ratio < context_min_ink(0.05)`，界是按「碎墨点／划痕」标的（vol03 `9:9:21` 0.0493 等）。**页框／界行残片的墨量是大的**（一条长横或竖条，`ink_ratio` 动辄 0.2–0.4），墨量闸一定放它过去。
2. **「一」是最难挡的字：** 一条长横条与「一」在单格里形状几乎无区别；字形通道（库匹配）本来就验不出"像"，context 只看文意，于是 context 按字频补出最常见的单笔假字——`_SINGLE_STROKES` 的注释写的正是这件事。
3. **挡它的闸都在，但缺省全关或口径不含这一型：**

| 闸 | 缺省 | 对"页框噪点放行成一"能不能挡 |
|---|---|---|
| `context_blank_gate`（墨量 < 0.05） | **开** | 不能：噪点墨量大 |
| `context_garble_guard`（乱码护栏） | **开** | 只在「没有证人背书」时拦（库 cov 低）。若整理本对齐字／坐标对位字／OCR 候选里有「一」，就算有背书，**不拦**——这一格如果恰好在整理本里对到「一」，就走这里漏过去 |
| `context_single_stroke_review`（单笔画字转待审） | **关** | **能挡**（`context_single_stroke`）。代价：真「一」「丨」经 context 放行的也转待审，多审几张 |
| `nonchar_gate`（放行后撤回） | **关** | 缺省 `nonchar_flags="bad_seg,rule_bar"`、`nonchar_strokes="丨亅丿丶"`——**不含 `frame_bars`／`edge_blob`，也不含「一」**，开了也挡不住（复现 D）。要放宽这两项才能挡（复现 E） |
| `context_guard_flags`（带标记不放行） | **关** | 缺省 `flag_set="rule_bar,suspect_empty,bad_seg"`，不含 `frame_bars`／`edge_blob`；放宽后能挡（复现 F）。**前提：Step4 真的给这一格标了该标记** |

4. **Step4 对 slot 4 的页框噪点大概率标不出 `frame_bar`**：`cell_shrink._is_raised_frame_bar` 只处理 `slot ≤ 1` 的"抬头框条"（`slot > 1` 直接 `return False`），这一格在列中间 slot 4，不在它的覆盖范围；是否带 `frame_bars`／`edge_blob`（`extractor._defect_flags`）要看数据。

## 最小复现（造数据，不入仓）

沿用 `tests/test_seed_admit_context_blank_gate.py` 的夹具：一格 `verdict=unsure, cov=0.5`，context 定「一」margin 0.9，`ink_ratio=0.30`，Step4 可带 `flags`；关掉乱码护栏（与该测试夹具一致，模拟「有证人背书」）。结果：

| 复现 | 参数 | 结果 |
|---|---|---|
| A | 缺省，无 flag | **放行，channel=context** |
| A2 | 缺省，`flags=[frame_bars]` | **放行，channel=context**（`frame_bars` 不在任何缺省闸里） |
| B | A2 + 乱码护栏缺省开（无背书） | 拦，`ctx_garble_shape` |
| C | A2 + `context_single_stroke_review=True` | 拦，`context_single_stroke` |
| D | A2 + `nonchar_gate=True`（缺省 flags/strokes） | **仍放行** |
| E | A2 + `nonchar_gate`，`nonchar_flags` 加 `frame_bars,edge_blob` | 拦，`nonchar` |
| F | A2 + `context_guard_flags`，`flag_set` 加 `frame_bars,edge_blob` | 拦，`ctx_guard_flag` |
| G（代价） | 真「一」ink=0.30，开 `context_single_stroke_review` | 也转待审（多审一张） |

脚本 15 行，调 `T._run`（测试夹具）五六组 `SeedAdmitParams` 即可，复现于 main `d72219fe`。

## 修法方案（按"是否让别的册产物过期"排）

**方案 1（推荐先做，不改代码）：只在 vol04 的册配置／pipeline params 里开。**
`seed_admit` 参数（`books/vol04.yaml` 或其 pipeline 的 `params:`）加 `context_single_stroke_review: true`，需要的话再加 `context_guard_flags: true` 且 `context_guard_flag_set` 含 `frame_bars,edge_blob`。**只有 vol04 的 `seed_admit` 参数哈希变（vol04 本来就要重落），其他册、其他步不受影响，零代码改动，`code_hash` 不变。** 局限：单笔画那条会让 vol04 里 context 放行的真「一」「丨」多出几十张待审；flag 那条依赖 Step4 真标出来。

**方案 2（要改代码，会让所有册 `seed_admit` 判过期）：** 把缺省改了——例如 `context_blank_gate` 之外新增"页框几何"闸（格在 `content_x` 外／贴 `border` 的格不走 context），或把 `frame_bars,edge_blob` 并进 `nonchar_flags`／`context_guard_flag_set` 缺省并默认开。改 `seed_admit.py` ⇒ `seed_admit` 的 `code_hash` 变（PATCH 档，但各册 `seed_admit` 产物过期，"1.5h 重跑十册"）。**我不建议为这一格改缺省；要做就并进下一次统一窗口。**

**方案 3（根治，在上游）：** 让 Step4 对 slot > 1 的页框／界行残片也标 `frame_bar`（扩 `_is_raised_frame_bar` 或在 `extractor` 加位置判据），产物里 `cell_type=empty`，下游自然不走 context。改 `cell_shrink`，让 `cell_shrink` 及其下游全部过期，影响最大，需要先在数据上量误伤。

## 需要 Owen 补的一行数据（决定上面哪条才是 `220:4:4` 真走的路）

`vol04` 的 `products/vol04/char_index/p0220.json` 里第 4 列 slot 4 那格的：`flags`、`ink_ratio`、`bbox_col`／`bbox_page`、`cell_type`；以及 `seed_admit` 产物里该格的 `evidence`（`context_decision` 的 `margin`，库 `verdict／cov`，`align_ref` 的整理本字／坐标对位字／OCR 候选里有没有「一」）。
- 若有整理本／坐标对位字「一」背书 ⇒ 乱码护栏漏过去，只有方案 1 的单笔画闸或方案 2/3 能挡；
- 若无背书、库 `cov` 低却没被 `ctx_garble_shape` 拦 ⇒ 是另一条路（例如这一格走的不是 context 通道，或乱码护栏当时在 vol04 的 params 里被关），要重新查，不一定是缺闸。

## 同批记录：`3:2:-1` 槽位号错位一格（印章区）——低优先，仅记录

GUJI-555 Lucian 粗校所见：`3:2:-1`（页3 列2 槽位 −1）的槽位号在印章区比实际字位错一格。**只记录，不排查**；后续要查时从 `cell_shrink` 的 `pos_to_slot` 与 seal 区（`seal_region` 标记）的槽位换算入手。
