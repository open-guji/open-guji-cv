# 版本历史与 Wiki 维护

## Wiki 维护规矩

1. **平时不追着改**：PATCH 版（vX.Y.Z 的 Z 变）不要求动 Wiki。
2. **每升一次 MINOR（Y 变），必须整体重改一遍 Wiki**，算在发版清单里（`doc/版本号规矩.md` 第八节），发版 PR 写一行「Wiki 已按 vX.Y 重改」才算发完。做法：
   1. 列出上一个 MINOR 以来的全部 PATCH：`CHANGELOG.md` 里 `[X.(Y-1).0]` 到 `[X.Y.0]` 之间各节，加 `git log vX.(Y-1).0..vX.Y.0 --first-parent`；
   2. 归纳动了哪些 Step、加了哪些功能、哪些说法过时了（新开关缺省开、新通道、新套书、新页型……）；
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

### v0.7（2026-11-10，v0.7.0）

- **书级代码**：只给一本书用的切分代码搬出 cv，进各书工作区仓 `code/`，有自己的整数版本号 `k<N>`（tag 走中转站）；cv 留三条版式的缺省实现 `impl/keben|modern|free`（原 `books/siku_zongmu|beixing|zengguang_youxue`），书仓 `code/` 为空也能跑。史記、全唐文已搬（k1；史記 k2 把印泥、雙行小注两行字数可不等也搬了过去）。共用 Step 不再加单书开关，改留钩子（`jiazhu_step`、`seal_ink`）。
- **四库版本号统一「字母＋整数」**：c 语料、g 字形、m 模型、k 书级代码；册配置可写 `pin: c31-g19-m2-k3`，产物包标签 `cv0.7.0-c…-g…-m…-k…`。
- **模型文件搬出 git**：真源在 R2，cv 只带路径 → sha256 表，起跑、测试、装包时自动取回。
- v0.6.x 期间（39 个 PATCH，11-01 到 11-10）累积的主要变化：殿本换 Commons 新图源（第 7 轮起）与按版框重切；参校本属性 `reference_profile`（A／B／C 块）；页型表 `page_kinds` 取代散在各步的页号（老写法警告）；seed_admit 从 1.3x 到 1.8x，加了一大批按书开的放行／退审旋钮（`p_ref_*`、`solo_5b`／`solo_cal`／`solo_adapt_*`、`num_run_*`、折叠组 `fold_*`、`group_flow_*`、撤库重审闸 `evict_review` 缺省开等，见 [开关登记表](https://github.com/open-guji/open-guji-cv/blob/dev/doc/开关登记表.md)）；row_segment 到 1.49（等距格网优先、表挪一格、列端框线格记空、书名列 `layout_title_fit`、`grid_end_fit`）；border_detect 弱框护栏、`hline_hints` 页级人给框位；切点判官结果落盘复用；出单与网页校对的待审条目化（`republish.py`）；笔画模板算法库 `strokes`（研究用）。

**本次 Wiki 改写（2026-11-10）**：按 v0.7 改了切分代码的结构说法（管线全景、Step3、各书一览、实验与评测、页型、殿本页）、钉版本（产物与数据）、首页与侧栏版本号。**截图没有重出**：v0.6 版截图取自换图源前的产物包，殿本第 7 轮起图源换成 Commons，页面构图一致、坐标与图不同；等第 8 轮 main 包出来再按 `wiki/tools/make_shots.py` 重出。

### v0.6（2026-10-31，v0.6.0）

- **切分模块化**：共用原语库 `seg/`（找线、网格、折线、拉直、投影、走缝、切点裁判）＋每套书自管 `books/<套书>/`（殿本、史記、幼學、北行），套书登记 `core/seg_set.py`，各套书一份样页单。没有任何 Step 的 `code_hash` 变。
- **拆包**：控制台拆成独立包 `guji-console`；对外交互的命令陆续搬去 guji-manager。
- **任务库按书 ID 区分**，殿本工作区独立成仓，不同书的同名册可以并跑。
- 自由版式 `keben_free` 到第八轮（块格式 `fmt`、按识别行切字）。
- v0.5.x 期间（32 个 PATCH，10-20 到 10-28）累积的主要变化：殿本换图源 `siku-qiefen-v2`；字形库按版本钉 `glyph_pin`；印章定位 `seal_detect` 与遮挡格放行；待审补放通道（`witness3`、`coord_fallback`、印章区）缺省开；字组统一流程 `group_flow` 覆盖全部字组，加文意 L3 大模型；`shadow_veto`、`rare_ref` 等缺省开；产物只存 R2 包、标 main。

**本次 Wiki 写作（2026-11-03）**：首版，以 v0.6.0 为基线，截图取自殿本 vol04（cv 0.5.26 main 包）、vol16／21／40／46／84（0.6.1 开发版实验包）、史記 01、北行古本 bxgb 的产物包，幼學 yxat 第 9、10 页本地跑。

同日按 Sheldon 意见调整：重点放殿本四庫總目（加专页），捎带史記、全唐文（全唐文 R2 无产物包，v006 第 20、40 页本地跑 Step1–4），幼學鰲頭压成各书一览里的一小段，删「自由版式」页。

### v0.5（2026-10-20，v0.5.0）

切分 `layout_prior`：候选格网统一打分，殿本 vol04–10 逐格 98.79% → 99.03%。人裁事件规范 v1；人裁「后到覆盖」统一按时间序。

### v0.4（2026-10-18，v0.4.0）

字形库内容指纹：从中心库重建 glyph.db 时不再白白过期。

### v0.3（2026-10-17，v0.3.0）

形近字算法库 `groups/`（日曰、己已巳、入人八），Step1 窄对合并。

### v0.2（2026-10-17，v0.2.0）

版本号规矩定成 `vX.Y.Z`；包分层守卫 `tests/test_architecture.py` 与 `doc/module_map.md`。
