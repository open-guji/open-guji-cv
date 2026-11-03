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

### v0.6（2026-10-31，v0.6.0）

- **切分模块化**：共用原语库 `seg/`（找线、网格、折线、拉直、投影、走缝、切点裁判）＋每套书自管 `books/<套书>/`（殿本、史記、幼學、北行），套书登记 `core/seg_set.py`，各套书一份样页单。没有任何 Step 的 `code_hash` 变。
- **拆包**：控制台拆成独立包 `guji-console`；对外交互的命令陆续搬去 guji-manager。
- **任务库按书 ID 区分**，殿本工作区独立成仓，不同书的同名册可以并跑。
- 自由版式 `keben_free` 到第八轮（块格式 `fmt`、按识别行切字）。
- v0.5.x 期间（32 个 PATCH，10-20 到 10-28）累积的主要变化：殿本换图源 `siku-qiefen-v2`；字形库按版本钉 `glyph_pin`；印章定位 `seal_detect` 与遮挡格放行；待审补放通道（`witness3`、`coord_fallback`、印章区）缺省开；字组统一流程 `group_flow` 覆盖全部字组，加文意 L3 大模型；`shadow_veto`、`rare_ref` 等缺省开；产物只存 R2 包、标 main。

**本次 Wiki 写作（2026-11-03）**：首版，以 v0.6.0 为基线，截图取自殿本 vol04（cv 0.5.26 main 包）、vol16／21／40／46／84（0.6.1 开发版实验包）、史記 01、北行古本 bxgb 的产物包，幼學 yxat 第 9、10 页本地跑。

### v0.5（2026-10-20，v0.5.0）

切分 `layout_prior`：候选格网统一打分，殿本 vol04–10 逐格 98.79% → 99.03%。人裁事件规范 v1；人裁「后到覆盖」统一按时间序。

### v0.4（2026-10-18，v0.4.0）

字形库内容指纹：从中心库重建 glyph.db 时不再白白过期。

### v0.3（2026-10-17，v0.3.0）

形近字算法库 `groups/`（日曰、己已巳、入人八），Step1 窄对合并。

### v0.2（2026-10-17，v0.2.0）

版本号规矩定成 `vX.Y.Z`；包分层守卫 `tests/test_architecture.py` 与 `doc/module_map.md`。
