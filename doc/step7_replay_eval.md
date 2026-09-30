# Step7（seed_admit）放行判定 · 云端人裁回放评测

2026-09-30 M2 道。回答「Step7 放行判定没有独立金标、只能复用人裁事件回放——云端能不能用 guji-workspace 的
`feedback/events` 人裁历史构造一个只读回放评测」。

**结论先说**：能做、已做出来（`scripts/eval_step7_replay.py`，只读），但**这套回放在现有事件上量不出放行精度**——
不是脚本的问题，是数据的结构问题（§2）。它能稳定给出的是另外三个数（§3），想要真正的放行精度要走
§4 的两条路（抽检批 / 留一重跑），都不是云端纯读文件就能拿到的。

## 1. 输入与口径（全部只读）

| 输入 | 来源 | 说明 |
|---|---|---|
| Step7 产物 `seed_admit/p*.json` | guji-workspace 孤儿分支 `products-snap/vol01-20260927`（`cloud-…-32b9c2b.tar.zst`，Step1–7 全书）；vol02 只有老快照 `products-snap/vol02-20260927`（cd04496，Step2 修复前）| 每格一条：`admit` / `channel` / `char` / `provenance` / `doubts` / `evidence` |
| 人裁事件 | `<ws>/feedback/events/<book>-*.jsonl` | 取 `target.step=seed_admit ∧ unit=cell ∧ kind∈{confirm,verdict} ∧ actor=user`；同一格取 `(ts, batch, seq)` 最大的一条；`actor=model` 只计数不当真值 |
| 异体等价 | `VariantMap.semantic` | 放行字与人裁字「语义同」不算错（忠于刻本字形方针） |

解快照：`zstandard` 解 `cloud-*.tar.zst`（云端没有 `zstd` 命令，`uv pip install zstandard`），
把 `vol01/` 摆到 `<产物根>/vol01/`。

```bash
PYTHONPATH=. python scripts/eval_step7_replay.py --book vol01 \
    --products <产物根> --events <ws>/feedback/events --json out.json
```

脚本**不** import `EventLog`（带写锁）、不碰 `consumed/`、不写产物；`--json` 只写你给的路径。

## 2. 为什么量不出放行精度（实测）

vol01（32b9c2b 全书产物，24,665 格）：自动放行 22,129（match_ref 20,697 / context 1,052 / match_solo 284 /
match_replace 81 …）、人裁通道 507、落人审 1,805、排除名单 224。人裁标签 741 格（queue 批 711、sampled 批 30）。

| 人裁标签落在哪 | 格数 | 读成 |
|---|---|---|
| 产物里 `provenance=human`（Step7 **自己抄人裁**，`use_human_verdicts=True`）| 502 | **循环**，不计精度；一致率 502/507 = 99.0% 只是健全性检查 |
| 排除名单（切坏格，无拟定候选）| 122（人却读出了字）| 名单与人裁冲突，另报 |
| 落人审、有拟定候选 | 0 | —— |
| **自动放行（非 human 通道）** | **0 条 confirm**（仅 1 条 `seg_defect`）| 放行精度分母 = **0** |

三个结构性原因：

1. **人裁集合 = 审查队列**。`*-decide` 批审的是 Step7 当时**没放行**的格；放行的格没人看，自然没有标签。
   Step7 放行精度的分母是「放行且被人看过」，而人只看没放行的。
2. **Step7 会把人裁直接抄进产物**（`SeedAdmitParams.use_human_verdicts`，`steps/seed_admit.py` 模块头「人裁是最强证据」）。
   用同一批人裁去考它，被考的格它本来就抄了答案——循环。
3. **字形库里的刻例大多就是这些人裁入库的**。5-a 已经在 2026-09-26 加了「按同一物理格摘自身」的留一
   （`abed89d9cc`，自证不是证据），所以 glyph_match 不会拿格子自己配自己；但同一批人裁入库的**邻近格**
   仍在库里，match 通道的「放行精度」天然带着同源偏差。

vol02（**老快照 cd04496**，Step2 修复前）上 `match_ref` 放行有 31/33 = 93.9%（n 很小），但要先剔掉 11 页
「编号漂移」页（同列相邻格放行的字恰好就是人裁字 ⇒ 重切后格号错位），否则会误报 57%。**这个数只当
演示**：产物与事件的切分口径不同步，不能拿来报放行精度。

## 3. 回放能稳定给出的三个数

| 指标 | vol01 现值 | 用途 |
|---|---|---|
| 循环健全性：`human` 通道 vs 人裁一致率 | 502/507 = 99.0%（vol02 老快照 1149/1150）| Step7 抄人裁有没有抄错 / 格号有没有漂；**掉了就是绑定表或重切出问题** |
| 落人审被人标 `seg_defect/not_a_char` | 95（92+3）| 人审拦对了多少切坏格；反过来 `自动放行 ∧ seg_defect` 目前 1 条（自动放行放过了切坏格）|
| 排除名单 ∧ 人读出了字 | 122 | 排除名单的误伤：名单里的格人却能读 → 该去复核名单（`exclusion_origins`）|

这三个是「事件 × 产物」能读出来的、且不循环的量，适合当回归护栏（阈值：健全性 ≥ 99%、自动放行 ∧ seg_defect 不升）。

## 4. 想量放行精度：两条路

**路 A：对自动放行格做随机抽检（推荐，独立金标）。** 现成的形态已经有了——`vol03-shadow-review-0929`
（D 道影子≠现字审查页）、`vol01-p1-30-confirm-20260916`、`glyphlib-audit` / `siku-claude-glyphlib`
（字形库体检）都是「对已放行格抽审」，脚本里记 `sampled` 档。缺的是**按通道分层的随机抽样**：
每个 channel（match_ref / context / match_solo / match_replace / …）各抽 N 格，出审查页（走 `review-artifact`
流程）、收回成 `kind=confirm` 事件到独立批 `step7-audit-<date>`（批名含 `audit`，脚本自动归 `sampled`）。
这样 `eval_step7_replay.py` 直接出「每通道放行精度 + 95% 区间」，且**没有循环**（抽的是放行格，产物没有抄它们）。
每通道 100 格起步，放行精度要验到 99.9% 需要的量级见 `doc/glyph_match_stack.md` 的 precision 口径。

**路 B：留一重跑（严格回放，需要整库 + GPU 外的 CPU 即可，但要本机库）。**
对有人裁的格：`use_human_verdicts=False` + 库里摘掉该格及其人裁入库的刻例，重跑 glyph_match → context_decide →
seed_admit，再与人裁比。云端的阻塞是 `glyph.db`（`glyph-db rebuild` 从 ws `output/glyph_store` 重建，
约 10 分钟 + 字体档 `import-font` 10 分钟）加上 Step5-7 的上游产物要对应同一批库——可行但工程量在
「按格摘刻例」这一步，**不是评测脚本能解决的**。先做路 A。

## 5. 已知限制（写在脚本头里的）

- 格号漂移：整页剔除规则（同列 ±2 格放行字 == 人裁字 ⇒ 该页漂移）是启发式，会漏掉「全页一致错位且
  相邻字都不同」的情形，也可能误剔。产物与事件应尽量同一次切分（`code_rev` 对得上）。
- `sampled` 批名靠子串（`shadow-review/audit/glyphlib/…`）识别，新增抽检批请把 `audit` 放进批名。
- 只比**字**，不比 `channel` 是否「该放行」——放行该不该由 §4 的抽检回答。
