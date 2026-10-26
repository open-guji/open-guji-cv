# 殿本《四庫全書總目》换图源：siku-qiefen-v2（设计稿，A31，2026-10-26，GUJI-748）

> 用户 10-26 定：99 册整套换成 open-guji-core/file_archive release `siku-qiefen-v2` 的图，**按新包重编页号**，每册给下游一张「旧页号→新页号」对照表。
> 研究结论（页对应、变换精度、试跑数据）见 Claude 文档 https://claude.ai/artifact/5eEUAkUN72C7uWrMa9KZ1m ；
> 脚本与全套页对应在 ai-team `domain/CV/图源迁移/siku-qiefen-v2/`。
> 本稿说的是**怎么切过去**。先拿 vol11 试点，再做 vol04，最后批量做。

## 一、已知事实（研究阶段已核）

- 新包与旧图是同一套书影，**每页之间是一个相似变换**：缩放 0.66–0.79（中位 0.71），99% 的页旋转小于 1°。全套 16,366 个正文页都对上了。没对上的 14 页、变换可疑的 45 页要人看。
- 新包只收正文页：没有书脊、封面、重拍页。新包有、旧图没有的页 151 张，其中 110 张是卷末页，41 张是我们扫描缺的（vol11 占 13 张）。
- vol11、vol04 用新图整册重跑过。旧格 99–99.9% 在新图上找到同编号格；定字 99.7% 一致。vol04 的 693 条人裁迁过去后，现有重绑定机制自动绑回 683 条。
- 新图裁得紧，border_detect 越界：已由 PR #631 修复。注意它动了 `border_geometry`，会让全书的 border_detect 指纹过期，所以**跟换源批次一起合并**；试点任务用该分支的提交跑。

## 二、标识怎么定

| 标识 | 定法 | 理由 |
|---|---|---|
| cv 册名 | 不变，仍是 `vol11` | 产物包、任务库、网站后台、同步脚本都按册名走 |
| cv 页号 | 按新包（卷，页）顺序从 1 重编 | 用户定。旧页号里有书脊、封面、重拍页，vol11 还乱序 |
| 页表 | 同一个 `96mid1ogzk/11` 出新版 rev，源件记新包 | `guji source pull` 取最新版。旧版页表只增不改，还能按 rev 取旧图 |
| 页序 seq（IIIF canvas id 尾巴） | **待评审**，见 §五·1 | 旧 seq 已是网站 canvas id 和 cord 的依据 |

## 三、旧数据怎么处理

| 东西 | 处理 | 说明 |
|---|---|---|
| 页表 | 出新版（新图原样登记，不重编码） | `guji source register --dir --map --src-file`。源件是每册的新包子集（这几卷的 pages／text／annotation 打一个 zip），网址指向 release 资产 |
| `books/<册>.yaml` | 改 `raw_dir: data_full/qiefen/<册>`（不和旧图混在一个目录）。`period_prior`、`bottom_gap` 乘缩放比。去掉按旧页号写的配置：preclean、column_grid_pages、period_prior_pages、roster_pages 等 | 页号相关的历史注释留一行指向本稿 |
| `corpus/daizhige/page_map.jsonl`、`layout_slots.jsonl`、`layout_overrides.jsonl` | 本册各行按新页号重写；新增页按 daizhige 页号（新包页脚印的就是同一套号）补 | 已在本机验证过 vol11、vol04 两册 |
| 产物包 | 新图整册重跑，标 main | 旧包留在 R2 |
| 人裁事件 | **另写一批新事件**：锚框按页变换、页号与格键改成新的、去掉 `evidence` 指纹、没锚的老裁决按旧 main 的现行绑定补锚。新事件 id 加 `~q`，`anchor.migrated_from` 记旧册页。**旧事件不删** | 事件日志只追加 |
| 旧事件失效 | **要 cv 加机制，待评审**，见 §五·2 | 不失效的话，旧事件会按旧页号绑到新页的同号格上 |
| 裁决表 `feedback/verdicts`、glyph 进库、`crop_exclusions` | 由新事件经路由重新消费生成；`crop_exclusions` 的本册行按页变换 | 字形库已有的真刻例（instances）**不迁**：它们的图块不依赖页表，出处记旧页表 rev 即可 |
| book-text 已发文本（default/NNN.char／cord／punct／entity／norm） | cord 按页变换到新 canvas；新补的页的字走文本修订流程补进来；标点、实体由 A33 按对照表重挂 | 文本内容基本不变，升版规则按 `docs/design/2026-10-文本版本号与仓库流程.md` |
| 网站书影（COS IIIF）、char.json、待审单与票 | 书影从新页表重切（web 仓 `--source pages`）；待审单从新 main 包重出；**有票的册（vol04–10）先迁票再切** | 票的格键要按对照表和格对应改写 |

## 四、单册切换步骤（每步的输入与验收）

1. **准备（本机，可撤）**
   - 输入：新包、页对应结果。
   - 产出：新页集、`map.json`、旧→新对照表（`old_new_<册>.tsv`：旧页、新页、类别、变换 A）、新册 yaml、新 page_map／layout 行、迁好的事件 jsonl。
   - 验收：对照表覆盖全部旧页，没对上的有类别；本机沙箱整册跑通，旧格同编号对上率 ≥ 98%。
2. **切换（推库，一次做完）**
   - 依次：发新页表 → 推册 yaml 与版式先验 → 推迁移事件 → 打开旧事件失效开关。
   - 验收：`guji source show` 是新版；`guji db status` 没有残留改动。
3. **重跑并标 main**
   - 在任务库提交，cv 用含 #631 的提交。
   - 验收：整册失败 0 页；重绑定统计 valid＋rebound ≥ 97%，其余进待审单。
4. **下游**
   - 网站书影重切；char.json、cord 重出；待审单重出。
   - 把对照表发给 A32、A33。
   - 验收：网站该册翻页、点字定位正确（抽 5 页人看）。

## 五、请评审的点

1. **seq／canvas id**。两种做法：
   - (a) 旧页能对上的沿用旧 seq，新补的页另起 seq。好处：canvas id 不变，网站深链和意见挂点不断。坏处：seq 不再等于新页号，CDN 同路径换图要清缓存。
   - (b) 全部按新页号重编 seq。好处：干净。坏处：canvas id 换掉，cord、网站意见全要按对照表重写。
   - 倾向 (b)，再加一张 canvas 旧→新 的对照，因为反正 cord 要整体重出。请 A20、A41 定。
2. **旧事件失效**。提议在册 yaml 加 `source_epoch: <时刻>`。读事件时，本册 `ts` 早于该时刻、且没有 `anchor.migrated_from` 的事件一律不采信（绑定、裁决表、进库、裁切排除都看它）。实现放在 `feedback/events` 的统一读口。请 A30、A24 看。
3. **有票的册**：网站票按格键存，要和 A32 定迁票办法后再切 vol04–10。
4. **分辨率**：新图约是旧图的 0.7 倍。网站书影放大会糊一点，用户已知情并同意换。
