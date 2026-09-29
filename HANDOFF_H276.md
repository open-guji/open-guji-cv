# HANDOFF H276：人裁卡「无匹配（近似字）」

任务卡：open-guji-core/overview#276 · 分支 `claude/H-approx-0929`（基于 main `3e33b13`，未推 main）
无人值守完成：拿不准的地方按保守做法走，列在最后「拿不准」一节，请总管/用户过目。

> **09-29 更新：已按用户对 overview#277 的裁定改（总管转达）**——① 选 C：近似例照常参与自动放行，
> seed_admit 书级开关缺省改为**不拦**，靠近似例定下来的格在产物 `evidence.approx` 标注、进侧表、控制台卡片显示「近似」；
> ② 选 A：正文照填，侧表 `页:列:格 → 字 / ids / note / 来源（human=人裁近似 / matched=匹配到近似例）`。
> 下面第 6 节与测试数已是改后的状态。

## 一、改了什么

### 1. 前端（tsc 通过，`npm run build` 已重出 `console/static/dist/`）
- **定字裁决逐格卡**（`ReviewCardView.tsx` / `ReviewPanel.tsx` / `reviewClass.ts`）：卡头「字形不入库」旁加勾选
  **「无匹配（近似字）」**；勾上后展开两个输入框：IDS（可空）、备注（可空）。改字（点候选、输入框、己已巳三选一
  走的 `pickVerdict`、标记按钮走的 `setVerdict`）都保住勾选，与 `noGlyphLib` 同口径（`keepApprox`）。
- **按字种批审**（`GroupReviewPanel.tsx` / `clusterRows.ts`）：「定为」框后加同一勾选 + IDS/备注，整组选中的格共用；
  按组下标存，切组不丢，提交后随组一起摘掉。
- 事件行统一走 `reviewClass.approxFields`：**不勾时一个键都不加**，事件逐字段与原来相同（node 用例钉住）。
- `review/verdict_view.py::review_verdicts` 读回 `approx/approxIds/approxNote`，刷新不丢；老事件的读回形状逐键不变。
- 待审卡 doubt 码 `approx_exemplar` 加中文名「配上近似例」与悬停说明（`doubt.ts`，只在开闸时出现）。
- 卡片（`review/cards.py` 多出 `approx` 字段 = Step7 `evidence.approx`）：卡头显示「近似」标签，悬停看命中的库例与 IDS/备注。

### 2. 事件
`confirm` 的 payload（仅 `v=confirm`）多带 `approx: true`，可选 `ids`、`note`（空串不写）。不带这些键的老事件行为完全不变——
`test_old_event_behaviour_unchanged` 对同一库跑老事件，前后比对七张表内容 + 两个指纹逐项相同。

### 3. 库：稀疏侧表（`clustering/glyph_db.py` `_SCHEMA`）
```sql
approx_labels(instance_id PK → instances, label, ids, note, reviewer, created_at)
approx_clears(instance_id, label, at, PK(instance_id, at))   -- 撤销审计，见下
```
`instances` / `glyphs` schema 未动。`GlyphDB.set_approx / clear_approx / approx_of`。
- 写入口：`feedback/consumers.py::glyphdb_admit`（人裁 confirm → 进库这条路；seed_admit 只出裁决不写库，任务卡里
  「seed_admit → glyph_ledger / 入库代码」实际落在这里）末尾调 `_apply_approx`：
  带 `approx` → 记（覆盖；`created_at` 取事件 `ts`，同一事件重放写出同一行、内容不变不动时间）；
  不带 `approx` 且库里这格有近似标记且 `actor=="user"` → 人改口，撤并记 `approx_clears`；
  库里本来没有近似标记的格 → 什么都不做。幂等闸挡下的重复确认也会走到这里（先确认、后回头勾近似能记上）。
- 撤例 `audit.evict_instance`、`drop_edition`、同步替换 `_install` 都跟着删近似行（撤例已有 `evictions` 审计，不另记）。

**比任务卡多加了 `approx_clears` 一张表**：删除护栏要分清「db 撤了近似标记」和「db 根本没见过别人标的近似」，
没有撤销审计就只能二选一（要么拦住人改口，要么放过静默丢失），与 09-28 `evictions` 同一个道理。

### 4. store 导出与同步
- `export_store` 多出 `approx_labels.jsonl`、`approx_clears.jsonl`（借来的库 / 字体域不导出）；`rebuild_from_store` 装回
  （借来的库的近似行也装，只装真装进来的实例，导出时照旧跳过）。
- `clustering/store_merge.py`：近似行算进实例记录 `Rec.apx`（进 `key()`，时间戳进 `stamp()`，撤销时间 `apx_cleared`
  只参与 stamp），三方合并规则不变——别人标/撤了、db 没动 → 照 theirs；两边都动 → 时间新的赢；上游的
  `approx_clears` 也并进来。新增 `unexplained_approx_deletions`：实例留着、近似标记却要从 store 消失的，必须有
  `approx_clears` 或撤例审计（时间不早于 store 那条的 `created_at`），否则整本不导出。
- `scripts/glyph_store_sync.py`：接上近似护栏；`db_signature` 把两张表算进去（**空表不进哈希**，签名与加表前相同），
  否则只标了近似、别的没动时会被「无变化」跳过、推不上去。

### 5. 查询与控制台
- `clustering/glyph_ledger.py`：`approx_exemplars(conn, char=None)`（`approx_labels` JOIN exemplars/glyphs，排除字体域）、
  `has_approx(db, char)`；`char_table` 每字多 `approx`（近似例个数），`char_detail` 每例多 `approx`、整字多 `n_approx`。
- 控制台字形库页：字表格子左上角「近」角标 + 悬停计数 + 过滤项「含近似例」；单字页标题「近似例 N」、刻例图块角标「近」
  与悬停里的 IDS/备注。

### 6. 两个开关（用户 09-29 已裁定 overview#277：C + A）
- **seed_admit** `SeedAdmitParams.approx_gate`（缺省 **关 = 不拦**）：判「这一格的字靠近似例」——放行的字就是库给的字，且
  ① 库判 same 命中的 `matched_id` 是近似例（`via="matched_id"`），或 ② 走候选首位、而这个字在库里的刻例**全部**是近似例
  （`via="char_only"`）。命中时在 `evidence.approx` 记 `{source:"matched", via, exemplar, ids, note}`（取命中库例的 ids/note），
  照常放行；书 yaml `params: {seed_admit: {approx_gate: true}}` 打开后退回保守做法（`admit=False`、doubt `approx_exemplar`、字不改）。
  整理本/上下文定的字不算；人裁位照旧一票定案。
  参数哈希：`approx_gate` 缺省值不进 dump；`approx_fingerprint`（`approx_labels` 内容戳）**只在库里有近似例时**进 dump——
  没有近似例的书参数哈希与加字段前逐位相同；有了之后标注会改变产物，所以 seed_admit 跟着过期，这是对的。
- **文本** `render/approx.py`：缺省 `sidecar`——正文照填，另出侧表 `pos / shape / ids / note / source`：
  `human` 读事件（人裁勾的近似，含「字形不入库」的格），`matched` 读 `seed_admit` 产物的 `evidence.approx`（只收放行了的格，
  没放行的格正文不出字），同格两路都有时人裁为准（`book_marks`）。预留 `inline_ids`（正文 `字{ids=…}`，没 IDS 不括注）与 `off`。
  接到 `scripts/render_guji_markdown.py --approx`（侧表写 `<out>.approx.tsv`，无 `--out` 打到 stderr）与 `/api/step9/render?approx=`
  （响应多 `approx` 行）。

## 二、库指纹实测（任务卡第 3 条）

用仓内 `output/glyph_store`（900 刻例）重建一个库，逐步测（脚本思路见 `tests/test_approx_labels.py::test_fingerprints_ignore_approx_tables`，同一套）：

| 状态 | `db_fingerprint` | `human_verdicts_fingerprint` | 同步 `db_signature` | seed_admit dump 含 approx 字段（改口前实测；改口后同样「有行才含」`approx_fingerprint`） |
|---|---|---|---|---|
| 老库（没有两张表） | e4ecc42d6b4ba2d1 | baef0f6adcda38bc | 883ad4ce… | 否 |
| 打开建空表 | e4ecc42d6b4ba2d1 | baef0f6adcda38bc | 883ad4ce… | 否 |
| 记 1 条近似 | e4ecc42d6b4ba2d1 | baef0f6adcda38bc | bcaab628… | 是 |
| 撤掉（0 行 + 1 条撤销审计） | e4ecc42d6b4ba2d1 | baef0f6adcda38bc | b7c0a2b2… | 否 |

**空表时三个指纹都不变**（`_CONTENT_SQL` 只看 exemplars/glyphs/admissions/derived，结构上就碰不到侧表）。

**有行时的建议：`db_fingerprint` 也不变（现状即如此，未改）**。理由：
1. 这个指纹的语义是「匹配器看到的东西」，近似标记不改变任何匹配判决（same/unsure/cov/候选全一样）；
2. 09-25 起它已是 soft 参数、只记不判过期，改了也只是「漂移」列多报页数，没有实际作用；
3. 真正读近似标记的是 seed_admit（标注/闸），它带自己的 `approx_fingerprint`（有行才进参数哈希），标了近似只让 seed_admit
   过期、不惊动 glyph_match——正好是想要的范围。
4. 反过来，同步签名**必须**变（上表第三列），否则只标近似的改动推不上去。

## 三、同步用例（`tests/test_approx_store_sync.py`，复用 #234 的双克隆环境）
导出↔重建往返；无近似例时只多两个空文件；main 标近似 → 服务器 db 有、下一轮不被冲掉（含服务器第一次跑、没有 base）；
服务器标近似 → 推上 main、H 重建后有；main 撤近似 → 服务器跟着撤、下一轮不复活；服务器撤近似（有审计）→ 放行并同步；
两边都改 → 时间新的赢；db 静默丢了近似行（无审计）→ 护栏拦、store 与远端都留着；实例整个撤了 → 归实例护栏管、近似护栏不重复拦。

`tests/test_approx_labels.py`：读回、老事件不变、写/重放/机器事件不撤/人改口撤、改判与撤例、字形不入库、指纹、查询、
seed_admit 参数哈希、缺省标注放行与开闸拦截、文本侧表（人裁/匹配两种来源、人裁覆盖）与括注、前端 `verdictRow`（node）。
两个文件共 22 条。

## 四、测试
`.venv/bin/python -m pytest tests/ -s -q -p no:cacheprovider`：**2409 passed, 1 failed, 27 skipped**（改口后重跑）。
失败的是 `test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`——**main 上同样失败**（stash 掉本分支改动复测过），
本机没有 U-Net 切点模型文件 `DEFAULT_CKPT`，与本单无关。

## 五、拿不准 / 需要知道的
1. **与 `instances.fidelity='nearest'` 重叠**（字形库 04 已有「最近似码位、ids 写实际结构」）。按任务卡另建侧表、没动
   `instances`；两者目前各管各：体检台标的 fidelity 不进 approx_labels，人裁勾的近似也不写 fidelity。要不要统一请定。
2. **seed_admit 会整体过期一次**：闸的代码写在 `steps/seed_admit.py`，Step 指纹含本模块源码哈希，合入后各书 seed_admit
   都会报 stale 一次（参数哈希本身没变）。没法避开，其它步不受影响。
3. 近似只跟 `v=confirm`（定字）走；「字形不完整/有噪声但带字」（`seg_defect`+shape）不带近似。己已巳专用卡、对齐改字层网格
   没加勾选（那两类本来就是在已有码位里选）。
4. 「勾了字形不入库」的格不进库 → 库里没有近似行 → 闸看不见它（它本来也不当模板），但文本侧表从事件读，照出。
5. 近似例判定没覆盖铁证通道（`iron`）：它不暴露命中的是哪一例，所以铁证靠近似例放行的格**不会带 approx 标注、不进侧表**。
6'. `char_only` 标注没有具体库例，侧表里这类行 ids/note 为空。控制台卡片只对出卡的格显示「近似」——缺省放行的格
   平时不出卡（「抽查自动档」能看到）。
6. 人改口的判定：只有 `actor=="user"` 且不带 `approx` 的 confirm 才撤；机器事件不撤。文本侧表 `approx_marks`
   同口径，但**没走绑定表**（按编号认格；`human_chars` 会走）。
7. 首次导出后每本书 store 会多两个空文件 `approx_labels.jsonl`、`approx_clears.jsonl`（一次性 git 改动，与 `evictions.jsonl` 同）。
8. `inline_ids` 用的 `{ids=…}` 后缀属性语法与 `□{guess=…}` 同源，guji-markdown main 是否已合并那条分支需确认（缺省不开）。
9. 前端只过了 tsc + build + node 协议用例，**没在浏览器里点过**（云端无工作区数据）。建议合入后在控制台定字裁决勾一张、
   刷新看勾选与 IDS 是否还在，再到字形库页看角标。
