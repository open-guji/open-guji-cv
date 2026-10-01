# 影子放行闸（shadow_veto）—— 只降级不升级的第二意见

> 2026-09-30 用户批准第一阶段，N1 道落地（overview #305）。**缺省关，不改任何书的默认行为。**
> 实验脚本在 `scripts/experiments/shadow_admit/`，线上模块在 `open_guji_cv/shadow/`。
> 实测与推荐门槛见 `HANDOFF_N1.md`、`scripts/experiments/shadow_admit/results_vol03/gate_eval_cv_0928.md`。

## 它做什么

`seed_admit` 的 `shadow_veto: true` 打开后，对**现行规则已放行（admit=True）**且**不是人裁**的格，
用影子模型再算一次：影子选了**不同的字**（己已巳合并后比较）且把握度 ≥ `shadow_conf` → 降回待审。
降级格：`admit=False`、`channel/provenance` 清空、`char` 不动、`doubts` 加 `shadow_veto`、
`evidence.shadow_veto = {reason, pick, conf, cur_conf, model, signals, conf_thr}`。

**不做的事**（硬约束，有单测）：不升级待审格；不碰 `human` 通道；印章遮挡、近似例闸等硬护栏都在模型外面；
信号缺失 / 本格自身在字形库里 / 单格异常 → **弃权**（不降级）；开了开关但模型文件读不到或口径不符 → **报错**（配置错，不静默当没开）。

## 参数（books yaml `params:` 或 `--params`）

```yaml
params:
  seed_admit:
    shadow_veto: true
    shadow_conf: 0.8          # 缺省 0.97；推荐值与证据见 HANDOFF_N1.md
    # shadow_model: <路径>     # 缺省 models/shadow_admit/shadow_gate_v1.joblib；路径不进指纹
    # shadow_low_conf: 0.0     # >0：影子最大把握度低于它也降级。缺省关（实测无标签可验，见 HANDOFF）
```

关着时五个 `shadow_*` 字段不进 `model_dump`：参数指纹与加字段前逐位相同（`tests/test_shadow_gate.py`）。
开着时 `shadow_model_fingerprint`（模型文件内容 sha256 前 16 位）进指纹，`shadow_model`（路径）经 `StepSpec.path_params` 剔出。

## 模块

| 文件 | 内容 |
|---|---|
| `shadow/signals.py` | `SIGNAL_VERSION`、`FEATURES`（12 个）、`CellEvidence`、`build_rows`、`load_context`。模块头写了防泄漏口径 |
| `shadow/model.py` | 模型文件读写（`.joblib` + 同名 `.json` 元数据）、指纹、版本闸（signal_version / sklearn major.minor） |
| `shadow/gate.py` | `ShadowGate.judge(CellEvidence) → ShadowVerdict`（veto / 弃权 / 同意） |
| `shadow/offline.py` | 从落盘产物还原 `CellEvidence`（评估、对账用） |
| `steps/seed_admit.py::_shadow_veto_pass` | 接线：所有通道与 `_resolve_ji_yi_si` 之后的一遍只降不升的后处理 |
| `scripts/shadow_gate_train.py` | 训练 → 模型文件（元数据：训练书目、标签数、特征、校准方式、cv commit、sklearn 版本） |
| `scripts/shadow_gate_eval.py` | 对一份落盘 seed_admit 产物扫门槛、分通道统计降级格，按页折交叉 `--fold M:i` / `--merge` |

## 信号口径（与训练一致）

12 个特征：库（lib_cov/lib_in/lib_top1/lib_margin/lib_top_cov/human_n/human_any）、5b（rare_score）、
整理本（ref_eq/ref_sem/ref_none）、形近（confusable）。候选集 = 库 top5 ∪ 5b top3 ∪ 整理本字 ∪ 现字。
**第一阶段不带**：OCR 组（vol03 没有）、**小笔画判别器**（慢、要原图；计划里的消融显示全局影响小）、`ref_op_equal`（vol03 上语义反转）、`n_cands`。
`tests` 之外另做了对账：`signals.build_rows` 与 `extract_snap.py` 的特征在 vol03 全书 17,321 格上逐值一致
（另 18 个待审格候选集差一个字——`extract_snap` 的现字来自 `page_slots`，待审格为 None，本模块取 seed_admit 默认字；只影响不会被 veto 的待审格）。

防泄漏：训练侧（`extract.py`）对「有 `v2:` 人裁实例」的格读图重算并摘自身；**线上不重算**——本格自身在字形库里
（`v2:` 与无前缀两种 id 都认）→ 弃权；`human_n` 摘本格 id（两种前缀）。机器放行的格不进库，进库的是人裁格（走 human 通道、本来就不受影子管），所以几乎零成本。

## 重训 / 换模型

```bash
python scripts/shadow_gate_train.py --out models/shadow_admit/shadow_gate_v2.joblib --model-id shadow_gate_v2 \
    --train bxgb=<…/signals_labeled.jsonl> --train vol02=<…/signals_labeled_v2_clean.jsonl> \
    --train-snap vol03=<extract_snap.py 出的 signals.jsonl>
```
信号口径一改就**必须**升 `SIGNAL_VERSION`（旧模型会被拒绝加载，不会静默用错口径）。
注意：`code_deps` 里**没有**加 `shadow` 包（加了会让所有书的 seed_admit 因 shadow 代码变动而过期）；
所以 shadow 代码变而 `SIGNAL_VERSION`/模型没变时，开了闸的产物不会自动过期——改信号抽取就升版本号。
