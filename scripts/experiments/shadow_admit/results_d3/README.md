# HANDOFF D3 — 规则 A（`rare_ref`）vs 影子升级（`shadow_promote`）（overview#349）

分支 `claude/D3-shadow-promote-1002`。两个开关都**默认关**，关着时参数 dump 不多键、产物逐字节不变（有单测）。
没跑整册上游、没打包、没导入、没碰工作区正式 products（沙箱用 `GUJI_PRODUCTS_DIR` / `GUJI_GLYPH_DB` 指到 /tmp）。

## 结论

1. **规则 A 做成了、有效、很干净**：人裁集上 493 格放行、2 错（都是罕见异体 蚤→𫊫、盡→𥁞，库、5-b、整理本、模型四路全一致，没有任何信号能拦）；
   现行 main 代码沙箱重跑，待审率 vol05 5.87→2.89%（−51%）、vol08 7.67→3.44%（−55%）、vol10 8.87→3.52%（−60%）；已放行格一个没被改字。
2. **影子升级没有明显赢过规则 A**：它学到的基本就是规则 A（共同 484–491 格），多出的 ~40–60 格是「库首位 = 5-b 首位但整理本缺失」型，
   同错数下放行量时赢（按页折 508 vs 493）、时输（按册留出 491 vs 493）——差别在 2~3 个错例的噪声里。
3. **「规则 A + 模型否决」≡ 规则 A**：模型在规则 A 放行的 493 格上一格都不否决（τ=0.5…0.95 全一样）；那 2 个错例模型也同意。否决没有可买的东西。
4. **推荐**：按验收口径「模型不输规则 A 就推荐模型」——**这里是平手，不是不输**；平手时规则 A 更简单（无模型文件、无 sklearn 依赖、可读），
   所以**推荐先开 `rare_ref`**。`shadow_promote`（conf 0.99）作为可叠加的第二档留着：vol05/08/10 上在规则 A 之外再多放 147/42/117 格，
   这部分**没有人裁真值可验**（人裁集只有 vol02/03），开不开请用户定。

## 对比表（人裁集，评测域 U = 人裁前待审且无硬护栏的 645 格：vol02 432 + vol03 213；1,737 个人裁格里另有 748+201 本来就放行）

按页分组 5 折（两册合训）：

| 方法 | 放行 | 错（逐字） | 错（字族） |
|---|---|---|---|
| 规则 A（线上 rare_ref 真实输出） | 493 | 2 | 2 |
| 影子升级 conf≥0.9 | 558 | 3 | 3 |
| 影子升级 conf≥0.99 | 533 | 2 | 2 |
| 影子升级 conf≥0.995 | 508 | 2 | 2 |
| A + 模型否决（任意 τ） | 493 | 2 | 2 |

按册留出（vol02↔vol03）：

| 方法 | 放行 | 错（逐字） | 错（字族） |
|---|---|---|---|
| 规则 A | 493 | 2 | 2 |
| 影子升级 conf≥0.9 | 544 | 5 | 4 |
| 影子升级 conf≥0.99 | 504 | 3 | 2 |
| 影子升级 conf≥0.995 | 491 | 2 | 2 |
| A + 模型否决（任意 τ） | 493 | 2 | 2 |

完整扫表（12 个门槛）、重叠分析、错例逐条见 `scripts/experiments/shadow_admit/results_d3/compare_v2_all.md`；
消融：`compare_v1_all.md`（只用 v1 特征：多错约 1 个，放行量略低）、`compare_v2_U.md`（只在待审格上训练：xbook 0.9 档错 7，不如合训）。

同放行量：影子升级要 conf≥0.995（page5）/0.99（xbook）才 ≥ 规则 A 的放行量，此时错 2 / 3 vs 规则 A 的 2。
同错数（≤2）：影子升级最多放 508（page5）/ 491（xbook）。

**错例**（逐字口径；格 id：人裁 / 放行 / 整理本 / 库首位 / 5-b 首位）
- 规则 A：vol02:57:7:20 𫊫 / 蚤 / 蚤 / 登 / 蚤；vol02:168:3:21 𥁞 / 盡 / 盡 / 畫 / 盡。
- 影子升级 conf≥0.9 另有：vol02:9:9:10b 别 / 別（整理本別，库首位别——写法异体，字族口径不算错）；
  vol02:182:9:7 龐 / 龎（整理本龎）；vol03:3:1:5 全 / 筌（**整理本缺失**，库与 5-b 一致认成筌）；vol03:104:8:21 一 / 二（库、5-b 都说二，整理本说一）。
  后两条是「没有整理本背书的库×5-b 一致」型——这正是 R 道早先量过的 97.6% 那档，模型多放的主要风险在这儿。

## 沙箱重跑（现行 main 代码，`step seed_admit --force`，只跑这一步，用 09-28 `-full` 快照的上游）

`scripts/experiments/shadow_admit/results_d3/rate_vol05_08_10.md`（待审率 = admit=False / 全部格）：

| 册 | base | rare_ref | shadow_promote 0.99 | 两者 |
|---|---|---|---|---|
| vol05 | 5.87% | 2.89%（−50.9%） | 2.45%（−58.3%） | 2.38%（−59.5%） |
| vol08 | 7.67% | 3.44%（−55.2%） | 3.20%（−58.3%） | 3.05%（−60.3%） |
| vol10 | 8.87% | 3.52%（−60.3%） | 3.30%（−62.8%） | 3.12%（−64.8%） |

「已放行格被改字」全是 0：两条通道只把待审挪到放行。vol05 的 base（5.87%）比 09-28 快照（5.52%）高，是因为沙箱用当前 glyph_store 重建的库 + 当前 main 代码，不是本改动造成的——比较只看同一列 base→方案。

## 做了什么

- `steps/seed_admit.py`：`rare_ref`（规则 A，纯函数 `rare_ref_decide` + 后处理 `_rare_ref_pass`）、`shadow_promote` / `shadow_promote_conf`（`_shadow_promote_pass`，在 veto 之后）、
  硬护栏 `_hard_blocked`（occluded / excluded / near_form / context_blank_cell / form_open / approx_exemplar / 库护栏 never_match·conflict）。
  规则 A 条件照任务书：replace 段、5-b 首位逐字 = 整理本字、非己已巳、库没 same 认别字、库首位不是整理本字的异体（只拦不放）。
  放行字 = 整理本字，channel/provenance=`rare_ref`，evidence `rare_ref={rare, ref, lib, cov}`。影子升级放行 channel/provenance=`shadow`，evidence `shadow_promote`（含 backed_by、prev_doubts）。
- `core/spec.py::live_optional_consumes`：同一产物种类可挂多个开关（原先 dict 只留最后一个，`rare_agree`/`rare_ref`/`shadow_promote` 会互相覆盖），任一为真即算数。
- `shadow/`：`SIGNAL_VERSION` 升 "2"（加 `rare_rank`/`rare_top1`/`ref_rare1`/`lib_ref_var` 四个特征 + 候选集加 5-b 名次首位）；`COMPATIBLE_VERSIONS=("1","2")`，
  v1 模型照样加载、候选集按 v1 口径（只开 `shadow_veto` 的书行为不变）；`promote_judge` / `decide_promote`；`models/shadow_admit/shadow_gate_v2.{joblib,json}`（vol02+vol03 人裁 1,737 格训练）。
  缺省模型：只开 veto 用 v1，开了 promote 用 v2。
- 测试 `tests/test_seed_admit_rare_ref.py`（自造数据）。

## 局限

- **LM 窗口分没做**（任务书标「可选」）；v2 特征里没有它。
- 人裁真值只有 vol02/vol03（1,737 格）；vol05/08/10 上的放行**没有真值**，待审率下降 ≠ 正确率，只能类推。规则 A 两个错例是罕见异体，新册若多罕见异体会按比例错放。
- 模型训练与评测在同一批 1,737 格上（按页折 / 按册留出控制泄漏，但样本小，门槛 0.99 是在这批上选的）；错例数 2~5，差异不显著。
- vol02/03 快照没有 `cell_shrink`（`char_index`），沙箱按 glyph_match 的 id 合成了一份（ink_ratio 固定 0.4）：只让 `context_blank_cell` 闸在这两册上不触发（真数据里 1 格）。
- 库用当前 `glyph_store` 重建，比 09-28/09-30 快照新；所有方案共用同一个库，对比是公平的，绝对数不是快照原值。人裁格的 `human_n` 摘本格自身，但含其它人裁格。
- 评测域 U 去掉了 143 个有硬护栏的人裁格；任务书的「560 格命中」是在全部 1,737 格上数的（含本来就放行的），本文 493 是 U 内数的，错数 2 一致。
- 模型文件 pickle 绑 scikit-learn major.minor（训练用 1.9.1），本地版本不同会被拒绝加载，需重训。

## 本地开法

```yaml
# books/<vol>.yaml
params:
  seed_admit:
    rare_ref: true             # 规则 A（推荐先开这个）
    # shadow_promote: true     # 可选第二档
    # shadow_promote_conf: 0.99
```
开了 `rare_ref`/`shadow_promote` 之后要重跑 `seed_admit`（参数进指纹，会自动判过期）。

## 复现

```bash
# 1) 解快照（guji-workspace 孤儿分支）
git -C guji-workspace fetch --depth=1 origin refs/heads/snap/96mid1ogzk/vol02/20260929T1024:refs/remotes/snap/vol02/20260929T1024   # 其余同理
git -C guji-workspace archive refs/remotes/snap/vol02/20260929T1024 products | tar -x -C $SNAP/vol02_20260929T1024
#   vol02 20260930T0339 / vol03 20260930T0457（人裁）、vol02 20260929T1024 / vol03 20260929T0451（上游）、vol05 20260928T1240-full、vol08/vol10 20260928T1455-full
# 2) 沙箱库与环境
export GUJI_WORKSPACE=<guji-workspace>/96mid1ogzk-…  GUJI_GLYPH_DB=$SB/glyph.db  GUJI_PRODUCTS_DIR=$SB/products
python -m open_guji_cv glyph-db rebuild
# 把各册上游（align_ref glyph_match rare_candidates context_decide，vol05/08/10 另有 cell_shrink row_segment page_survey）拷到 $SB/products/<vol>/
# vol02/03 另需合成 cell_shrink（见局限）
# 3) 重跑 seed_admit（同一书各方案分别跑、各存一份）
python -m open_guji_cv step seed_admit vol03 -w "$GUJI_WORKSPACE" --pages all --force --jobs 4 --params '{"seed_admit":{"use_human_verdicts":false}}'              # base
python -m open_guji_cv step seed_admit vol03 -w "$GUJI_WORKSPACE" --pages all --force --jobs 4 --params '{"seed_admit":{"use_human_verdicts":false,"rare_ref":true}}'  # rule
# 4) 正面比 + 训练
python scripts/experiments/shadow_admit/promote_vs_rule.py --up vol02=… --up vol03=… --human vol02=… --human vol03=… \
    --base vol02=… --base vol03=… --rule vol02=… --rule vol03=… --db $SB/glyph.db --out results_d3 [--features v1] [--train-domain U] [--save-model models/shadow_admit/shadow_gate_v2.joblib]
# 5) 待审率前后
python scripts/experiments/shadow_admit/rate_report.py vol05=<快照 seed_admit> … --runs $SB/runs
```
