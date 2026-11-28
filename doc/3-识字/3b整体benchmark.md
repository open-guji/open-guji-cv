# 3b 形近字组整体 benchmark 与临时校准表

2026-11-28 CV3 建（形近字组整体方案第八、十一节 D「3b 整体」）。脚本头是细则：`scripts/build_near_bench.py`（冻结）、`scripts/eval_near.py`（评测、拟合临时校准）。

## 数据

open-guji-dataset `glyph-near/bench3b/`：

| 文件 | 内容 |
|---|---|
| `bench.json` | 每书：工作区 id、册（`role: test` 报数，`role: fit` 只给临时校准拟合）、钉死的产物包标签、3b 书配置写法的 `groups`、模型文件 sha256 与训练说明 |
| `<书>/<册>/cells.jsonl.gz` | 这一册**每一格**：3a 首位／判档／护栏／候选、标签（`seed_admit` 放行字与通道；人裁 `gold_char`）、被触发格的字块图路径 |
| `<书>/<册>/img/` | 被触发格的 `char_patch`（`.p.png`）与原图裁块（`.r.png`，只给 `patch: raw` 的方法） |
| `<书>/<册>/meta.json` | 包标签、出图 cv 版本、格数、触发数、标签数 |

- 标签：人裁优先；否则放行字，去掉 3b 方法自己的放行通道（`bench.json` `labels.circular_channels`）。
- `_guard` 的 `gap` 一路（3a 没判 same 的格）量太大，只数不冻图、不判。
- 模型文件不进数据集：`models/…` 在本仓，`config/groups/…` 读本书中心库数据目录（`guji db pull -w <工作区>`）。对不上钉的 sha256 照跑，报告里 `pin_ok: false`。

## 报告（`--out`）

`books.<书>.per_vol.<册>.groups.<组>`：`triggered`／`by_trigger`、`coverage.{silver,gold}`（标签字在组内的格被这组触发的比例）、
`methods.<方法>`：`scored`、`abstain_rate`、`labeled`、`acc`（判出字的格）、`labeled_abstain_rate`、`errors`（前 20）、`ms_per_cell`、
`repeat_equal`（同批格再打一遍是否逐位相同）、`calib.{ece,brier,version,temporary}`（有校准表时）。
`per_vol.<册>.agreement`：方法两两、方法对 3a 首位、方法对标签的一致率。`models`：指纹、`model_sha`、sha256 与钉的是否一致。
`headline`：test 册每个「方法:组」一行（manager `guji eval run @near` 取数）。`methods_sha`：各书方法指纹。
`--calib-dir` 覆盖的校准表只记在 `models.<方法:组>.calib`，不进 `methods_sha`（指纹按数据目录里的模型文件算；表真放到模型旁时指纹才变）。
2026-11-28 三书基线与临时表清单见数据集 `glyph-near/bench3b/README.md`。

## 临时校准表（`--fit-calib DIR`）

- fit 册的 (正类原始分, 标签) 做保序回归（PAV，段值 `(正例+0.5)/(n+1)`），test 册报 holdout ECE（按册留出）。
- 至少 30 格、两类各 5 格才出表；不读校准表的方法（book_knn、near_knn）与已有正式表的（cnn_small 宫官）不出。
- 表是 `near-calib/1` 加 `version`、`temporary: true`、`fit_on`、`holdout`；放到模型文件旁（`<去 .json>.calib.json`）生效。
  收尾 `glyph_analyzer` 见 `temporary` 只写 `near[组].p_tmp`／`p_tmp_src`（`near:方法:组@版本~tmp`），
  **不进 `cands[].p`、`p_src`**——只给排序展示，不用于自动放行（Sheldon 11-28）。
- 放上线＝推到本书中心库 `config/groups/` 模型文件旁（改了模型目录指纹，3b 与收尾过期），要 Sheldon 批。

## 命令

    # 冻结一册（GUJI_WORKSPACE 指书的工作区：产物根里是钉的包，原图、书级代码都在）
    PYTHONPATH=. python scripts/build_near_bench.py <dataset>/glyph-near/bench3b --book 995ejelvk0 --vol 046
    # 评测（＋拟合临时校准）
    PYTHONPATH=. python scripts/eval_near.py <dataset>/glyph-near/bench3b --out report.json [--fit-calib DIR] [--calib-dir DIR]
    guji eval run @near
