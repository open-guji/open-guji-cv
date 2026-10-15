# 抽样脚本（sample_newadmit.py）说明

窗口后新放行格看图清单的生成脚本（GUJI-72）。本文件是 GUJI-208gi 补丁（`--force-all` 与红线按册）后的说明；补丁 diff 见 `补丁208gi.diff`。

## 基本用法
```
python sample_newadmit.py --base <零臂表> --arm <A臂表> --out <目录> \
      [--remap <对位表.tsv>] [--force-all <格号名单.txt>] [--seed 20261014] [--quota 5] [--max-total 60]
python sample_newadmit.py --selftest
```

## 层的划分（必读）
- **force 层**：`--force-all` 名单里的格，强制全看、不抽样。名单每行一个格号，`#` 开头为注释，行内 `#` 之后也是注释（208kd）；每个有效行须是 `volNN:页:列:行`，否则退出码 5（208kg）；不在新放行总体里的格不计入，摘要里列出「已忽略」。
- **hint／juan_rule 层**：provenance（`--source-field`）里含 `hint`／`juan_rule` 的格，全看。
- **other 层**：其余，按册抽 `--quota` 格。
- **事实（208gc 干跑核实）**：vol05 的 A 臂 provenance 里**没有** hint 标记（只有 match、rare_ref、context、witness3、seal、iron、coord_fallback、match_margin 等）。所以 hint 格不能只靠 provenance 进全看层，必须用 `--force-all` 显式给名单（名单由 Eden 的 hint 正式名单生成）。

## 红线（十格，Eden 全局 2，v2.14.2）
- 只检查 **A 臂表里出现的册**。本册内的红线格：缺失／基线已放行／从待审变放行 → 停（退出码 3）。
- 不在 A 臂册内的红线格：**不停线**，逐条列在摘要「本次未检」里；摘要首行写「红线未全覆盖，不得报 0」。
- **合并总跑必须覆盖十格全部**，否则不得报「红线 0」。
- 红线集合为空 → 停（退出码 3）。不再回落到全局十格。

## 退出码
0 正常；1 自测失败；2 超上限（force＋hint＋juan_rule 超过 `--max-total`，或抽样后仍超）；3 红线停线；4 无对位超线（阈值 min(20, 5%×A 臂放行格数)，先补 remap）；5 强制名单格式不合（208kg：逐行写到 stderr 与摘要「格式不合」一项，输出已写出但须修正名单后重跑）。

## 已知限制
- 无对位格（A 臂有、基线对不上）仍进清单，但超线即停（退出码 4）。208gc 干跑：vol05 有 118 格无对位，远超阈值；这是对位／基线口径问题，不是脚本能修的。
- `--remap` 对位表只能由产出方（Ethan 或 Eden）给出；本脚本不猜位置。

## 窗口当日怎么用（`run_window_sampling.sh`，208gq）
一条命令：**自测 → 主跑 → 自测**。任一步非 0 即停，退出码原样报告，不吞；退出码 2／3／4／5 会另印一行中文提示。

```
./run_window_sampling.sh <基线表> <A臂表目录> <force名单> <输出目录> [对位表.tsv]
```

- **基线表**：零臂产物（同 main yaml、同缓存、同 cv commit；见 §一）。窗口当日的零臂为 A-g0（零臂＋`iron_ex_missing_guard` 默认开，决定页 §七），由 Ethan 的 A-g0／A-br／A0／A 各臂 cell_table 导出提供（命令待 Ethan 补，**不猜**）。
- **A 臂表目录**：窗口当日候选 A 臂的各册 cell_table（`.jsonl` 或 `.jsonl.gz`）。**来源按册指定**：默认臂（seed_admit replay）的表用于 vol01–06；vol07 的 hint 四格实测走单独一臂（Ethan，`--from column_warp`），其 force 名单对着那一臂的表跑，不对窗口 A 表（决定页 §二十，Evan 208gg 件二）。脚本先合并成 `<输出目录>/_work/arm_combined.jsonl` 再跑；册头行无 `id`，合并时自动跳过。
- **force 名单**：Eden hint 正式名单里该册的格号，每行一个，`#` 为注释。vol07 为 4 格（128:4:17、128:4:18、128:4:21、129:7:3），名单由 hint 独立臂的表对位生成；**不得用窗口 A 表的 vol07 来源**（208gq 原文「窗口 A 表」一句作废）。
- **输出目录**：只写抽样输出（`抽样.tsv`、`cells.txt`、`回填.tsv`、`回退.tsv`、`摘要.md` 等）。
- **对位表**（可选）：hint 页的 remap，只能由 Ethan／Eden 给出。

窗口当日的做法：
1. 确认基线是零臂产物、A 臂目录是完整册表；**输出目录放沙箱**（`GUJI_PRODUCTS_DIR` 下），不写正式 products。
2. 跑脚本；退出 0 才看 `摘要.md`。
3. 摘要首行若是「红线未全覆盖，不得报 0」，只能算本次的看图清单，不能报「红线 0」（合并总跑须十格全覆盖）。
4. 退出 2：人定上限或规则，不要自行放宽。退出 3：红线格要人工核，不得继续出清单。退出 4：先由 remap 产出方补对位表再跑。退出 5：force 名单有格式不合的行，改正名单（只改格号写法，不得删行凑过）后重跑。
5. 摘要里「强制名单但基线同号已放行：对位待核」节的格，须核对位后再定去留，不计入看图清单。

干跑记录（208gq，验证脚本本身）：用 hint 分支的 vol04 基线 `exports/cell_table/vol04_base.jsonl.gz` 与窗口 A 表 `exports/window_replay_1020/vol04_A.jsonl.gz`，force 名单为空（只注释）。自测两次均通过；主跑退出 **3**：vol04 红线 `vol04:217:2:15`、`vol04:220:4:4`、`vol04:23:1:3` 在该基线里已是放行，不是待审，按规则停线。注意：该基线头部标的是 `seed_admit`，不是零臂重放产物，所以这次只验证脚本，不作为窗口结论。

### 窗口当日来源口径（208gt，Mila 10-14 决定页 §十九～§二十）
- **vol04 零臂表**：窗口当日由 Ethan 的 A-g0／A-br／A0／A 各臂 cell_table 导出（命令待 Ethan 补）。今天用 `seed_admit` 头的基线只验脚本，**结论不作窗口用**。
- **vol07 hint 四格来源**：hint 是 `column_gate` 参数，窗口 replay（`--from seed_admit`）测不到。vol07 hint 实测另走一臂（Ethan，`--from column_warp`），force 名单对着那一臂的表跑。
- **脚本**：没有写死「A 表来自同次 replay」的假设；来源由调用方按册给，脚本只做合并与对比。

10-15 Emi 据 208kq 再补七更正：本文件中以 column_gate 为起点的写法已改为 column_warp（column_gate 不是合法起点，CLI 与 exp 框架均报错，见 Ethan 208hq 回执）。
