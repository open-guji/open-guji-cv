# A/B 实验框架（`guji exp`）

overview#457（E1）。回答「这个开关开不开、对哪本书有效、会不会让别处回归」：两份（或几份）配置各跑各的输出目录，再统一比较，出一份能据以决定开关的报告。决定记进 [开关登记表.md](开关登记表.md)。

代码在 `open_guji_cv/exp/`，命令在 `open_guji_cv/cli_exp.py`。框架是**外挂**，只用 `Engine(params=…)` 的调用方覆盖层和可改指的产物根，**不动任何 Step 模块和它的 `code_deps`**，不会让各书产物判过期。

## 一、怎么跑

```bash
guji exp run doc/exp/shadow_veto-vol05.yaml -w $WS --snapshot <快照产物根>
# 短写法（issue 原定）：每份 yaml 是一个变体，变体名取文件名
guji exp run --base A.yaml --var B.yaml --books vol02,vol04,vol05 --from seed_admit --snapshot … -w $WS
guji exp report <实验名> -w $WS          # 改了标签或判准后重出报告（只读产物）
guji exp list -w $WS
```

1. **准备上游**：快照（`guji snapshot` 出来的目录，或任何含 `<book>/<step>/` 的产物根）里 `from` 之前的各步**硬链接**到 `<exp>/_upstream/<book>/`（跨盘退回复制；`_manifest.jsonl` 一律复制），各变体共用一份。上游不跑，快照不写。
2. **每个变体**：`<exp>/<变体>/<book>/` 再从 `_upstream` 硬链接，然后 `Engine(params=评测口径∪变体覆盖)` 只跑 `from…to`。指纹照常判，同一实验再跑一次已新鲜的不重算（要重算加 `--force`）。
3. **护栏**：实验目录落在工作区 `products/`、仓内 `products/` 或快照之内，直接拒跑。

## 二、目录

```
<工作区>/experiments/<实验名>/      # --root 可改
  exp.yaml            合并后的配置 + 代码版本 + 快照戳（各步 manifest 的哈希）+ 各变体跑批计数
  _upstream/<book>/   上游，只读
  A/<book>/<step>/    基线产物；B/…、C/… 同理
  labels.jsonl        本次用到的标签（合并后，一格一行，带 source/selection）
  labels_extra.jsonl  翻转格审查页收回的裁决
  report.json / report.md / charts/*.svg
  flips/cards.jsonl, flips/review.html
```

## 三、实验 yaml

```yaml
name: shadow_veto-vol05
books: [vol05]
snapshot: /path/to/products        # 也可命令行 --snapshot
from: seed_admit                   # 第一个受影响的步
to: seed_admit                     # 报告目前只比 seed_admit 产物
pages: all                         # all（快照里有上游的页）| body | 页号表达式；报告总是正文/非正文分开
base: {}                           # 变体 A；省略 = 当前代码的默认参数
variants:
  B:
    params:
      seed_admit: {shadow_veto: true, shadow_conf: 0.8}
eval:
  use_human_verdicts: false        # 缺省就是 false
labels:
  - {source: human_events}                                          # <feedback>/events
  - {source: vision, path: reports/vol05/看图结论.jsonl}             # 缺省 picked
  - {source: gold, path: /path/to/char-recognition/xxx/items.jsonl}  # 缺省 random（带 stratum 的 picked）
guardrails:
  - {metric: admit_err_rate, scope: body, op: "<=", ref: base}
  - {metric: review_rate, scope: body, op: "<=", ref: base, delta: 0.005}
  - {metric: flips.right_to_wrong, op: "==", value: 0}
bootstrap: 2000
seed: 0
```

- **参数名逐个对 Step 的 Params 校验**。pydantic 缺省会静默吞掉多余字段，开关名写错（或开关还在别的分支上，如 `juan_rule`）两边就跑成一样，这里直接报错。
- **评测口径 `eval`** 对所有变体一样。`use_human_verdicts: false` 是为了去循环：Step7 会把人裁直接抄进产物，再拿同一批人裁考它没有意义（[step7_replay_eval.md](step7_replay_eval.md) §2）。它只在实验里关，不改 Step 的默认值。
- 判准里的 `metric`：`admit_rate`、`review_rate`、`excluded_rate`、`admit_err_rate`、`flips.<键>[.<子键>]`；`scope`：`body`（缺省）、`nonbody`、`all`；`ref: base` 加可选 `delta`，或 `value: 常数`。

## 四、标签与偏差

| `source` | 读哪里 | 缺省 `selection` |
|---|---|---|
| `human_events` | `<feedback>/events/<book>-*.jsonl`，`actor=user` 的 seed_admit 格级 confirm/verdict，每格取最新 | 批名带抽检标记（`audit` 等，同 `eval_step7_replay.py`）→ `random`，其余 `picked` |
| `vision` | `看图结论.jsonl`（`feedback/vision.py` 的格式）| `picked` |
| `gold` | 金标分片 `items.jsonl`（`anchor` 定格，`expected.char`）| 带 `stratum` → `picked`，否则 `random` |

- 每个来源都可在 yaml 里写 `selection:` 覆盖。
- **错误率与它的区间只用 `random` 标签。** `picked` 是被挑过的样本（审查队列、请审单、vol04 那 163 个 wrong），只进翻转表和 McNemar 的「全部」档计数，报告里标 ⚠，不得当错率。
- 某层「放行且有 random 标签」的分母为 0 时，报告写「无检验力」，判准记「判不了」，不输出 0% 或 100%。
- 人裁通道（`provenance=human`）的格不进任何错率（循环）。
- 同一格多来源：human > gold > vision；真值不一致的列在报告的「来源冲突」里。
- 字对不对按异体等价判（`VariantMap.semantic`），与 `eval_step7_replay.py` 同口径。

## 五、报告

`report.md` 每个变体对基线一节：

- **总体**：分正文、非正文（页型取 `border_detect_gate` 产物的 `page_type`；缺了记「页型未知」）、全部三档，各给放行率、送审率、排除率、放行错误率（random 标签，附 Wilson 区间）。差值的 95% CI 用**以页为簇的配对自助法**：两边用同一组重抽页，格在页内相关，按格重抽会把区间算窄。区间跨 0 标「与噪声不可分」。
- **分层**：按书（正文）、按通道（放行格数与 random 标签上的放行错）、按成因（送审格的 doubts 码）。
- **逐格翻转**：

  | 类型 | 含义 |
  |---|---|
  | 放行→送审 | 有标签的分「拦对」（基线那格是错的）和「误拦」 |
  | 送审→放行 | 有标签的分「放对」和「放错」 |
  | 两边放行、字不同 | 分 A对B错、A错B对、都错 |
  | A 对 B 错 | 有标签、基线不是放行错、变体是（新增放行错）|
  | A 错 B 对 | 有标签、基线是放行错、变体不是（含被拦回送审）|

  `report.json` 里有全部格号，md 只列前 20 格。
- **McNemar 精确检验**：对逐格的「放行错」指示做检验，分 random 和全部标签两档。
- **判准**：逐条给达标、不达标或判不了，末尾一句「判准 k/n 达标，开不开由人定」。
- **图**：`charts/<变体>-forest.svg`（各指标差值与 95% CI）、`charts/<变体>-channels.svg`（按通道放行格数），纯 SVG、零依赖，亮暗两套颜色，嵌在 report.md 里。

## 六、翻转格抽样页

```bash
guji exp flips <实验名> sample -w $WS [--n 60]     # 分层抽样 → flips/cards.jsonl（id 冻住，--resample 才重抽）
guji exp flips <实验名> page -w $WS                # 出页；工作区有 char_patch 缓存就带字块图（--no-images 不带）
# 用 Artifact 发布（capabilities 带 artifact，见 skill review-artifact），人裁完 Artifact read 回来：
python .claude/skills/review-artifact/scripts/harvest_verdicts.py page.html -o v.jsonl
guji exp flips <实验名> harvest v.jsonl -w $WS     # → labels_extra.jsonl
guji exp report <实验名> -w $WS
```

- 卡上**不印哪边是基线、哪边是变体**，也不印通道与把握度。候选字打乱顺序，只问「这格是哪个字」，另给「都不对」「切坏/非字」「拿不准」三档。
- 每层（变体 × 翻转类型）按大小比例抽，每层至少 5 格，记 `stratum_weight`。
- 已有标签的格不出题。
- 收回的裁决记 `source=human, selection=picked`，只写实验目录，**不写工作区 `feedback/`**。要落成正式人裁仍走 H 道的规矩。

## 七、已知限制

- 变体只能改参数，不能换代码。要比较两份代码（如 Y1 分支上的 `juan_rule`），等代码合 main，或另开一张卡做 `code: <git ref>` + `git worktree`。
- 报告只比 `seed_admit`。`to` 是更早的步时，`guji exp run` 照跑，但出报告会报错。
- 快照与事件的格号要同一次切分：快照比人裁旧或新，重切后格号会漂，对不上的标签记在「产物里找不到」。
