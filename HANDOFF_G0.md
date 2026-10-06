# HANDOFF G0 — 字组测试集 char-groups（overview#437）

分支：cv `claude/G0-char-groups-1006`（只加 `research/char_groups/` 与本档，**没改任何 Step、没改管线代码**，各书产物不会判过期）；
dataset `claude/G0-char-groups-1006`（提交 `9982f51`）。**没合 main、没开 PR。**

## 做了什么
1. **dataset `char-groups/`**：一组一个目录 `jys/`（己已巳）、`ry/`（日曰）、`rr/`（入人八），每组 `README.md`、`items.jsonl`、`crops/`、`baseline.json`、`context_stats.json`；
   顶层 `README.md`（字组、归组判据、真值分档、评测口径、快照与复现）、`groups.json`（登记表，含之后要加的异体组）、`metadata.json`、`_build_info.json`。
2. **全量**：vol02–vol10 九册有快照的都收（卡上说「有快照的册都算」），凡落在三组的格全收，带现行产物与真值档；外加 vol01 confusable-context 的 42 题（没有快照，只有文本）。
   core 格：jys 651、ry 1,395、rr 2,405（共 4,451；外围格另 516），字块图 4,409 张（vol01 无图）。
3. **真值来源**：人裁事件、`feedback/vision` 看图事件（`label_origin=vision`）、overview 看图清单（vol03/vol04 放行错穷举、vol04 己已巳、vol03 己已巳全族文意表）、#426 3 格、#352 样本里的人裁、confusable-context、vol03 muse 试点。
   分档 A_human / B_vision / C_weak（证人一致，循环，只作参考），所有来源逐条记在 `golds`。
4. **上下文**：刻本读序前后各 8 字 + 整理本对应位；外部语料（cv `corpus/external/daizhige_*`）与域内语料（《總目》）的搭配统计分开存，注明 sha256。
5. **基线**：现行 seed_admit 产物，每组每册：放行、放行错（强真值上，下界）、人裁、待审、送审率，按通道细分；强真值格上各来源首选字错率。
6. **划分**：dev vol02/03、**val vol04 留出**、pool vol05–10、extra vol01。
7. **N1 `near-form-groups/` 并入**：原目录只留指过来的 README（删了 items/crops/metadata）。

## 顺带发现（都已在数据里修掉）
- N1 vol03 用的上游快照 `20260928T1708-full` 与 seed_admit `20260930T0457` 不配套（seed_admit 的 `_manifest` upstream sha 对不上）；换成 `20260929T0451` 全部对上。N1 因此误收 2 行（`vol03:25:3:20`、`vol03:106:9:13`）。
- N1 解析 vol03 看图表取首字，「同形」「同上」「封口形…」被读成 同/封，vol03 己已巳 9 格真值丢了；改成只收单字，这 9 格的文意判从「全族逐格文意表」收。
- 人裁事件按编号取（快照不在工作区，绑定表算不出）：早于快照、快照又没采信的 3 格记 `X_stale`，不当真值（vol02 `75:1:12`、`75:6:9`，vol03 `105:4:3`，都是整列顺移）。
- **N1 上下文规则的第一个已知错**：vol04 `40:4:6`「中書【己】未召試」，键「書_」54/54 判「已」，看图判「己」（干支）。
- 日曰 2 格放行错是**整理本、证人、放行三方一致**都错（`vol02:188:5:19`、`vol04:133:3:7`，实为「曰」）：弱真值在这一组不可当金标。

## 基线要点（详表在各组 README 与 baseline.json）
- jys：送审率 69–92%；已知放行错 vol02 4/4（split_ref）、vol03 3/15（split_ref 3/3）、vol04 1/23（ji_yi_si，N1 规则）。
- ry：送审率 6–19%；放行格有强真值的只有 9 格，错 2。
- rr：送审率 0.6–5.5%；放行格有强真值 1 格——**放行错率量不出来**。

## 还缺什么数据
1. 日曰、入人八**放行格的随机样本**（每册约 100 格，看图存 vision 事件），否则这两组的放行错率不可知。
2. vol04 人裁（S10）做完后重建（现在 vol04 强真值全是看图）。
3. vol05–10 的己已巳全族（439 格）没有任何真值。
4. vol02/03/05–10 的产物早于 I1/N1，各册重跑 seed_admit 后换快照（`research/char_groups/common.py` 的 `SNAPS`）重建基线。

## 复现
见 dataset `char-groups/README.md`「快照与复现」与 `research/char_groups/README.md`。
