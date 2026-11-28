# 版本历史与 Wiki 维护

## Wiki 维护规矩

1. **平时不追着改**：一般的 PATCH 版（vX.Y.Z 的 Z 变）不要求动 Wiki。**例外：新增小步、改大步划分（拆步、并步、挪步、改编号），即使发 PATCH 也要在同一批 PR 里改 Wiki**（2026-11-28 定，cv `doc/验收标准.md` B5）：改对应大步页的小步表、管线全景的总表与流程图、侧栏；首页顶上的版本行改成「对应 vX.Y.Z 起」。
2. **每升一次 MINOR（Y 变），必须整体重改一遍 Wiki**，算在发版清单里（`doc/版本号规矩.md` 第八节），发版 PR 写一行「Wiki 已按 vX.Y 重改」才算发完。做法：
   1. 列出上一个 MINOR 以来的全部 PATCH：`CHANGELOG.md` 里 `[X.(Y-1).0]` 到 `[X.Y.0]` 之间各节，加 `git log vX.(Y-1).0..vX.Y.0 --first-parent`；
   2. 归纳动了哪些大步、哪些步骤、加了哪些功能、哪些说法过时了（新开关缺省开、新通道、新套书、新页型……）；
   3. 逐页对照改，新功能补页，过时的页删掉或合并，同步改 `_Sidebar.md`；
   4. 截图重出：每部书取新版的 main 产物包，跑
      ```bash
      python wiki/tools/make_shots.py --ws 96mid1ogzk=<殿本工作区> --ws 988g3f0wsu=<史記工作区> \
          --ws 988g7gsqhd=<北行工作区> --ws 998a1ukohs=<幼學工作区> --data 96mid1ogzk=<殿本数据目录>
      ```
      页号换了（换图源、重编页号）就改 `wiki/tools/shots.yaml`，再逐张看一遍图对不对得上正文；
   5. 在下面「版本历史」加一段，首页顶上的版本号改成新的。
3. 源文件在 cv 仓 `wiki/`，走 PR（投 dev）；随发版合进 main 后，workflow `wiki-sync` 把它同步到 GitHub Wiki。不要在网页上直接改 Wiki，下次同步会盖掉。
4. 公开仓：不写令牌、密码、内部地址；截图只用已公开的影印图。

## 版本历史

每个 MINOR 一段：这一版多了什么。逐版细节见仓里 [CHANGELOG.md](https://github.com/open-guji/open-guji-cv/blob/dev/CHANGELOG.md)（含全部 PATCH）和 [RELEASES.md](https://github.com/open-guji/open-guji-cv/blob/dev/RELEASES.md)（MINOR 的发版说明）。

### v0.9.16 起（2026-11-28）：按四大步现行小步重改

0.9.13 起第三步重构、第四步子步、切字五小步、册号位数统一等都按 PATCH 发，没触发「MINOR 重改 Wiki」，Wiki 落后了五天（CV0 四大步审查 X10 指出）。这次按 cv dev 859b25e 的骨架 `stages:` 与四个大步 README（cv #2048）整体重改：

- **2 切字** 五小步拆成独立 Step（11-25，cv #1869、#1872）：2a 拉直 `column_warp`、2b 字带左右边 `column_band`、2c 列端字 `column_end`、列几何 `column_geometry`、2d 字间切分 `row_segment`、2e 字框压缩 `cell_shrink`，出口闸统一成 `cut_gate`。旧编号「2b 逐字切分、2c 字框收缩」改成 2d、2e。
- **3 识字** 重构（11-27、11-28，CV3）：3b 形近字组 `glyph_near`（第四步的 8 个看图判法搬进来）、3c 按图候选 `glyph_candidate`（取代旧生僻字候选）、3d 其他特征 `cell_traits`、3e 看图大模型 `glyph_vis`、收尾 `glyph_analyzer`；都缺省关。
- **4 定字** 分四个子步、一个收尾、一道 gate（11-28，CV4）：4a 参照对位、4b 上下文（加 `context_rank`）、4c 格况 `cell_state`、4d 字组 `group_decision`、收尾 `seed_admit` 改名 `char_decide`、gate `decide_gate`；三条纪律「子步只出证据、收尾做全部判断、gate 只检测」。
- 参校本四维（`form`／`punct`／`script`／`accuracy`）成唯一入口（4 定字页新一节）；册号位数按全书册数（产物与数据）；验收标准、bench 登记表、dataset STEP_MAP（实验与评测）。
- 维护规矩加一条：新增小步、改大步划分，即使发 PATCH 也要改 Wiki。
- **截图**：沿用 v0.8 的，图注里的小步编号改成新编号；新小步（2b、2c、3b–3e、4c、4d、gate）还没有专门的截图，等下一个 MINOR 按 `wiki/tools/make_shots.py` 补。

### v0.9（2026-11-23，v0.9.0）：按四大步重排

- 2026-11-22 用户定：单列拉直（原 1d `column_warp`／`column_crop`／`column_trace`）从 1 版面移到 2 切字，成 2a；原 2a 逐字切分、2b 字框收缩改称 2b、2c。1 版面只管认位置、判类型。步骤 id、产物、指纹都没变。
- 原九步并成四大步：**1 版面**（Step0–2）、**2 切字**（Step3–4）、**3 识字**（Step5）、**4 定字**（Step6–7）；Step8 入库、Step9 排版输出移到 guji-manager。步骤 id、产物、指纹都没变。
- 六个 Step 页合成四个大步页：`1-版面`、`2-切字`、`3-识字`、`4-定字`；Step0 页面预检从「管线全景」挪进「1 版面」。
- cv 有自己的命令行入口 `guji-cv`（本 Wiki 里 cv 的命令都写它；大步工具可带前缀，如 `guji-cv layout preclean`）；manager 的命令写总入口 `guji`（`guji start …`、`guji pipeline …`）。`--from`／`--to` 可写大步名 `layout`／`cut`／`read`／`decide`。删了 `fp-migrate`、`import-pdf`。
- 原第 9 步的代码（导出、对勘、体检表）整个搬进 guji-manager：`guji output export md|format|wikisource|reflow`、`guji output collation-report`；cv 删了 `guji export`。
- 识别结果不变：23 步 `code_hash` 与 v0.8.0 相同，各书不用重跑；截图沿用 v0.8 的。
- doc 与 Wiki 分工：doc 只写事实与 schema（各大步的「步骤与产物.md」从代码生成），介绍、教程、怎么用写在这里。

### v0.8（2026-11-21，v0.8.0）

- **新任务一律用 v0.8**：v0.7.0 以来 93 个 PATCH（11-10 到 11-21）累积，其中殿本、史記、全唐文各有自己的 patch 线。
- **书级开关与钩子继续增加**：殿本职名页格网占号（`roster_grid_slots`）、全唐文丢笔两个开关、印框压格记空、整理本字别名 `group_flow_ref_alias` 等；缺省都关、不进参数哈希，不影响没用的书。
- **切分开关收敛**：`det_warp`、`cut_judge=unet_f64` 缺省改开（见 1d）。
- **形近字与字形库**：5a 通用相似度底座、`hou_shape` 刻形判法、`never_group` 登记、字形库体检加「清边不变式」、库字档（见 识字、字组与异体）。
- **册 yaml 记缺页**：`gaps:` 只按图片页号记，导出时带出。
- **人裁回流**：网站票改读中心库（D1），不再经 KV；绑定加迁移补锚闸，旧格号人裁不再静默挂到邻格。
- **底库 b33**：新增 `config/dicts/variants.pairkind.tsv`；钉旧底库的册要换钉 b33。

**本次 Wiki 改写（2026-11-21）**：Home 版本号、中心库说法（不再写 Neon）、1d／识字 补 v0.8 缺省与新开关说明。逐页截图未重出（切分结果逐字不变，殿本／史記／全唐文的例页仍对得上）。

### v0.7（2026-11-10，v0.7.0）

- **书级代码**：只给一本书用的切分代码搬出 cv，进各书工作区仓 `code/`，有自己的整数版本号 `k<N>`（tag 走中转站）；cv 留三条版式的缺省实现 `impl/keben|modern|free`（原 `books/siku_zongmu|beixing|zengguang_youxue`），书仓 `code/` 为空也能跑。史記、全唐文已搬（k1；史記 k2 把印泥、雙行小注两行字数可不等也搬了过去）。共用 Step 不再加单书开关，改留钩子（`jiazhu_step`、`seal_ink`）。
- **四库版本号统一「字母＋整数」**：c 语料、g 字形、m 模型、k 书级代码；册配置可写 `pin: c31-g19-m2-k3`，产物包标签 `cv0.7.0-c…-g…-m…-k…`。
- **模型文件搬出 git**：真源在 R2，cv 只带路径 → sha256 表，起跑、测试、装包时自动取回。
- v0.6.x 期间（39 个 PATCH，11-01 到 11-10）累积的主要变化：殿本换 Commons 新图源（第 7 轮起）与按版框重切；参校本属性 `reference_profile`（A／B／C 块）；页型表 `page_kinds` 取代散在各步的页号（老写法警告）；seed_admit 从 1.3x 到 1.8x，加了一大批按书开的放行／退审旋钮（`p_ref_*`、`solo_5b`／`solo_cal`／`solo_adapt_*`、`num_run_*`、折叠组 `fold_*`、`group_flow_*`、撤库重审闸 `evict_review` 缺省开等，见 [开关登记表](https://github.com/open-guji/open-guji-cv/blob/dev/doc/开关登记表.md)）；row_segment 到 1.49（等距格网优先、表挪一格、列端框线格记空、书名列 `layout_title_fit`、`grid_end_fit`）；border_detect 弱框护栏、`hline_hints` 页级人给框位；切点判官结果落盘复用；出单与网页校对的待审条目化（`republish.py`）；笔画模板算法库 `strokes`（研究用）。

**本次 Wiki 改写（2026-11-10）**：按 v0.7 改了切分代码的结构说法（管线全景、2a、各书一览、实验与评测、页型、殿本页）、钉版本（产物与数据）、首页与侧栏版本号。**截图没有重出**：v0.6 版截图取自换图源前的产物包，殿本第 7 轮起图源换成 Commons，页面构图一致、坐标与图不同；等第 8 轮 main 包出来再按 `wiki/tools/make_shots.py` 重出。

### v0.6（2026-10-31，v0.6.0）

- **切分模块化**：共用原语库 `seg/`（找线、网格、折线、拉直、投影、走缝、切点裁判）＋每套书自管 `books/<套书>/`（殿本、史記、幼學、北行），套书登记 `core/seg_set.py`，各套书一份样页单。没有任何 Step 的 `code_hash` 变。
- **拆包**：控制台拆成独立包 `guji-console`；对外交互的命令陆续搬去 guji-manager。
- **任务库按书 ID 区分**，殿本工作区独立成仓，不同书的同名册可以并跑。
- 自由版式 `keben_free` 到第八轮（块格式 `fmt`、按识别行切字）。
- v0.5.x 期间（32 个 PATCH，10-20 到 10-28）累积的主要变化：殿本换图源 `siku-qiefen-v2`；字形库按版本钉 `glyph_pin`；印章定位 `seal_detect` 与遮挡格放行；待审补放通道（`witness3`、`coord_fallback`、印章区）缺省开；字组统一流程 `group_flow` 覆盖全部字组，加文意 L3 大模型；`shadow_veto`、`rare_ref` 等缺省开；产物只存 R2 包、标 main。

**本次 Wiki 写作（2026-11-03）**：首版，以 v0.6.0 为基线，截图取自殿本 vol04（cv 0.5.26 main 包）、vol16／21／40／46／84（0.6.1 开发版实验包）、史記 01、北行古本 bxgb 的产物包，幼學 yxat 第 9、10 页本地跑。

同日按 Sheldon 意见调整：重点放殿本四庫總目（加专页），捎带史記、全唐文（全唐文 R2 无产物包，v006 第 20、40 页本地跑 版面、切字），幼學鰲頭压成各书一览里的一小段，删「自由版式」页。

### v0.5（2026-10-20，v0.5.0）

切分 `layout_prior`：候选格网统一打分，殿本 vol04–10 逐格 98.79% → 99.03%。人裁事件规范 v1；人裁「后到覆盖」统一按时间序。

### v0.4（2026-10-18，v0.4.0）

字形库内容指纹：从中心库重建 glyph.db 时不再白白过期。

### v0.3（2026-10-17，v0.3.0）

形近字算法库 `groups/`（日曰、己已巳、入人八），1b 窄对合并。

### v0.2（2026-10-17，v0.2.0）

版本号规矩定成 `vX.Y.Z`；包分层守卫 `tests/test_architecture.py` 与 `doc/module_map.md`。
