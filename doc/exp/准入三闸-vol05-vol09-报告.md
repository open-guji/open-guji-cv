# 准入三闸 A/B：runt_cell_review、oversplit_gate、nonchar_gate（vol05、vol09，2026-10-23）

A22（切分）。开关登记表里归切分的三个 seed_admit 开关从没在 vol05–10 开过（`nonchar_gate` 只 vol04 开），按登记表规矩补 `guji exp` 证据。配置 [准入三闸-vol05-vol09.yaml](准入三闸-vol05-vol09.yaml)。

## 怎么跑

- 代码 dev `176eb14`（v0.5.8 之后；到 v0.5.9 为止 seed_admit、cell_shrink 没再改）。
- 上游：两册各自的 main 产物包（v0.5.7：`vol05 cv0.5.7-c14-g-eda521-full`、`vol09 cv0.5.7-c14-g-a55aa1-full`），只重跑 `seed_admit`。
- 基线 A＝册 yaml 现行参数（三闸全关）；B 开 `runt_cell_review`；C 开 `oversplit_gate: hint`；D 开 `nonchar_gate`。各变体只差这一个键。
- 标签：中心库人裁事件 734 格（都是 picked，random 0），所以错率「无检验力」，只能看逐格翻转。

## 结果：三个闸在现行切分上都是 0 格

| 变体 | vol05（28,915 格）| vol09（41,986 格）| 
|---|---|---|
| B 矮格转人审 | 放行 28,800 → 28,800，翻转 0 | 41,801 → 41,801，翻转 0 |
| C 过切提示 | 提示 0 格 | 提示 0 格 |
| D 非字过滤 | 放行 28,800 → 28,800，翻转 0 | 41,801 → 41,801，翻转 0 |

`guji exp report`：三个变体与 A 的放行率、送审率逐格相同（正文 99.58%／0.42%），带标签的 734 格两边全同。

## 为什么是 0：触发条件在现行切分里不出现了

不看放行与否，直接在产物上数各闸的**几何／标记命中**（vol04 也一起数，它是 `nonchar_gate` 唯一开着的册）：

| 册 | runt：正文格高 < 0.6×period | oversplit：相邻两格合起来像一个字 | nonchar：放行格带 `bad_seg`／`rule_bar` 或放行字是单笔画 |
|---|---|---|---|
| vol04 | 0 | 0 | 0（全册 `rule_bar` 仅 1 格，且没放行；main 产物里 doubt `nonchar` 0 格）|
| vol05 | 0 | 0 | 0（`bad_seg`、`rule_bar` 0 格）|
| vol09 | 0 | 0 | 0（同上）|

- **runt、oversplit**：两闸都是为「列里字数和格数对不上、DP 把一个字劈成两段矮格」写的（起因 vol02 15:9:20 等，那时还没有格位先验）。殿本现在走 `row_segment.layout_prior`（严格 21 格、格高均匀），vol05 全册正文格高最小 0.64×period、中位 1.01×，构造上就不会再出 <0.6 的矮格或「两格合一字」的对子。
- **nonchar**：靠 Step4 `char_index` 的 `bad_seg`／`rule_bar` 标记。现行产物里这两个标记基本不出现（三册合计 1 格）；推测是 10 月切分侧的一系列修复（格位先验、外框吸附、Step4 跨线部件归属等）让界行竖线不再混进字块，没逐项归因。单笔画放行字（丨亅丿丶）三册也是 0。

## 结论与建议

三闸在现行切分上**没有正收益也没有负收益**：开或关产物逐格相同。它们防的病已经在上游（Step3 格位先验、Step4 归属）治掉了。

建议（删要用户点头）：

1. **`oversplit_gate`：删。** 只加提示不改放行，几何命中 0，殿本的格网让它构造上无效。
2. **`runt_cell_review`：删。** 同理；以后若有不走格位先验的新书出现矮格劈字，应在 Step3 修切分，不该在 Step7 补闸。
3. **`nonchar_gate`（含 `nonchar_flags`、`nonchar_strokes`、`nonchar_jiazhu_ignore_rule_bar`）：删**，vol04 yaml 的 `nonchar_gate: true` 一并去掉（实测 0 格，去掉不改产物）。

备选：若想留作「上游回退时的保险」，可三个都改缺省开（现行产物不变，只是 `seed_admit` 参数指纹变、各册该步判过期一次）。但这会让 seed_admit 保留三段已不起作用的逻辑，与「算法保持简单」的规矩不合，所以不推荐。
