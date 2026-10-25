# Changelog

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号规矩见 `doc/版本号规矩.md`。
本文件记录**全部**版本（含 PATCH）；动代码的 PR 投 `dev`，在 `## [未发版]` 下加一行；切 rc 时改成 `## [X.Y.Z] - 测试中`，发版时改成日期（见版本号规矩第三节）。

## [未发版]

- cellvotes：网站精校页新增 `damaged`（破损、阙字）档，映射成 `confirm v=damaged guess=<字>`（录阙字方框 □，票上带的字当「最像的字」）；页面单选组各项与档的对应写进 web_votes 模块说明。

## [0.5.21] - 2026-10-25

PATCH（#605 字组）。seed_admit 的 `code_hash` 变（`groups/` 注册表、流程、字形判法表）。

- 字组：新 SHAPE 组 yin 隱𨼆、suan 算𮅕、guanm 闗關（与 men 共用 關），模板库在 `config/groups/<组>/ids_bank.json`；新 `FlowSpec.ref_enter`（库首位是陪衬、整理本或坐标对位字在组里也进组补放，先于库首位字的组）；kui 陪衬补 𮑮襄𠮓變雙凌。册 yaml `group_flow` 不点名就不生效。vol21–50 离线回放补放 𮅕87 𨼆28 闗13、改码位 9（PATCH）。
- proof_cycle apply 加 `--reuse-products <目录>`：引擎换版本后产物已自己从头跑好，沙箱直接用它，不取出单版包、不重跑 seed_admit；发布用的 cv 版本取引擎的 tag。

## [0.5.20] - 2026-10-25

PATCH（#595 Step1 1.10 列距救援：出带列两边线吸到淡界行；#599 印章定位 1.2：窄密度区按小印取模板位置，不再套整页大印正方形）。Step1、印章定位的 `code_hash` 变。

- 印章定位 1.2：只有宽 ≥ 0.75×版框宽的密度区才按大印套版框正方形；窄的（卷末小印印得淡、碎墨成区）在区里找模板位置按小印记，分数 < 0.2 就不算印；小印覆盖门槛 0.6→0.5。修 v0.5.17 首跑卷末页小印被当整页大印、大半页正文判成遮挡（vol35 p173 42 格、vol31 p213、vol36 p110、vol46 p225、vol49 p196、vol50 p102），vol44 p237 漏测的卷末印测出；另有卷末页小印已认出、又多套了一个整页大印的 6 页（vol28 p102/p193、vol34 p153、vol38 p88、vol40 p174、vol48 p35）去掉假大印，vol46 p95、vol47 p7/p47/p63/p87 页角碎墨的假大印去掉。vol21–50 有印或疑印的 764 页前后对比只这 18 页变，卷首大印一页没动。印章定位的 `code_hash` 变（PATCH），输出格式不变。
- Step1 1.10 列距救援：前几路都不成时加第 4 路 `snap_lines`，把出带列两边的线吸到附近的淡界行细峰上、没有界行就吸到字间空白中点，列宽进带才收；网格模式线数比自由模式多（自由模式漏线）也照收。修 v0.5.17 首跑界行极淡的 5 页：vol24 p69、vol29 p28、vol37 p76、vol45 p54、vol48 p121（此前整列丢字或两列并一列）。vol11–50 的 100 页样本另有 4 页（vol30 p78、vol31 p159、vol35 p43、vol49 p128）线在列间空白里挪了 2–11px，看图都对；vol13 p46 不动。Step1 的 `code_hash` 变（PATCH）。

## [0.5.19] - 2026-10-25

PATCH（#593 Step3 自动配页，缺省关的新设置）。Step3（`row_segment`）的 `code_hash` 变：版本 1.39、`code_deps` 加 `steps/row_segment_pagemap`、`utils/page_align`、`utils/daizhige`；缺省 `page_map: off` 时参数与输出不变。

### Added
- Step3 自动配页 `row_segment.page_map: off|loose|strict`（Sheldon 10-25 定殿本 vol51 起不再离线补格位表）：开着时 Step3 开跑前读全册 Step2 列窗口与原图，每页 9×23 格墨量指纹与 daizhige 全书半叶对齐（带状粗找多候选 → 单调 DP → 局部重排 → 回填），得出页→半叶与格位表，存 Step3 产物目录 `_page_map.json` 复用，代替 `layout_prior` 的离线表；`strict` 整册配不上（正文页没配准超过 max(2, 3%) 或有字页平均得分 < 0.95）就拦。钉页 `corpus/daizhige/page_pins.jsonl`。新钩子 `Step.prepare`（引擎分发页前主进程调）、`Step.book_params`（按册填参数）。殿本 vol11/13/14/16/17/19/20/21 自动表与中心库人核表逐格一致，vol51 整册跑通（PATCH）。

## [0.5.18] - 2026-10-25

PATCH（#589 Step1 列距救援不甩出贴版框的真列，殿本 vol40 p14、vol46 p118、p148 丢整列正文；#587 新册首跑自动标 main；#586 出单版产物包记对 cv；#588 看板）。Step1 的 `code_hash` 变。

- Step1 1.9 列距救援：新加第 0 路「出带的窄外列、外侧半列宽内有版框残段 → 外框线吸到版框」（`snap_outer_to_frame`），并且任何一路都不许把贴版框的旧外列甩出新网（`drops_framed_col`）。修 v0.5.17 首跑 vol40 p14、vol46 p118/p148：版心条在版框外，fuse 外推进版心、整网平移一列，框里的真列整列丢掉、版心被当成一列（A31 报的「无整理本对位」成片页）。vol11–50 触发救援的 100 页样本只这 3 页变。Step1 的 `code_hash` 变（PATCH）。
- `guji products pack push`：这册还没有 main 指针（新册首跑）时存包后自动标 main，不用加 `--main`（sheldon 10-25 定：新册的第一个包只能是 main）。只在正式库、装的是正式版 cv 时自动；实验分支、dev／rc 版只提示不标。任务库 `push` 步走同一条命令，自动生效。只在 `cli_products.py`，不动任何 Step（PATCH）。

### Added
- 字组看板：`group_progress` 每个字组写一张卡（`group.<组>`，送审格＋出现、放行率、组判率），`guji groups status --progress <套书 id>` 出完报告顺手写网站后台 yiti／xingjin 两栏（Neon 正式库）。只是看板数据，`code_hash` 不变。

## [0.5.17] - 2026-10-25

PATCH（A24 字组成批上线第二批的代码部分：#552 suo 组与 719 库标研究；#555 變𠮓 改刻形组；#556 尙尚 恢复复核改字；#558 宮宫 暂归一登记；#570 字组状态写后台看板；另含 #563 #572 Step1 列距救援 fuse、任务库与进度上报若干）。新组要在册配置 `group_flow` 点名才生效；`groups/registry.py`、`groups/flow.py`、Step1 的 `code_hash` 变。

### Changed
- 出单版产物包记对 cv：`republish.py issue --engine <worktree>` 用重跑的那份 cv（`engine_run.py`＋PYTHONPATH）存 `rev-<rev>` 包，`proof_cycle apply` 自动传 `--engine`，`--cv-commit` 也改记引擎的提交。此前包里记的是本仓 dev（册006 rev-006-r5 记成 7b40f6e），下一轮 apply 核引擎对不上（A32，PATCH）。
- `proof_cycle plan --recheck-extra <tsv>`：把别处发现的疑点（如重标时看出的字错）并进本轮复审清单，同格以它为准，可带旧人裁 id 让网站写明「已有判断」（A32，PATCH）。
- 字组：新建取框组 suo 瑣𤨏（GUJI-719，#552）；bian 變𠮓 改成刻形组（下半 HOG，只给 變，#555）；尙尚 恢复复核改字（vol16 两格放大看是 尙，#540 的「只降不改」撤回，#556）；宮宫 登记为暂归一到 宫（#558）。

### Added
- `python -m open_guji_cv.eval.group_progress`：`guji groups status` 的 json 写网站后台「文本整理」的 yiti／xingjin 两栏（缺省只打印，`--write` 写库，#570）；`guji groups status --prev` 出送审分类与增减（#553）。

### Fixed
- 任务库：执行方同一会话接第二张单（准备带 `--reset`）时 `db pull --force --no-rebuild` 不建 glyph.db；上一次准备在拉库前就失败的会话里 glyph.db 从没建过，建钉版库报 `no such table: sources`（#3–#6）。`--reset` 改成照常重建。
- 任务库：准备脚本的「语料校验」也认 `GUJI_CORPUS_DRIFT=warn`（之前单上写了放行，准备阶段还是拦下，#1 vol07 因此失败）。常驻执行方两张单之间每 10 分钟看一次 dev 上 jobs 模块、准备脚本、启动器有没有更新，有就空闲时退出，线程重新 start 换上新代码。
- 任务库：`retry` 过的单再也领不到（领单序号按已清零的次数算，撞 `UNIQUE (job_id, n)`，又被当成「同册被抢」悄悄吞掉）；现在序号接着历来最大的排，只有同册互斥的冲突才换一条，别的冲突照常报错。
- 任务库：环境类失败（如会话没挂 guji-workspace 私仓）退回排队后冷却 5×次数 分钟（新列 `run_after`，schema v3，`GUJI_JOBS_BACKOFF_MIN` 可调），并优先让别的执行方领；之前同一个坏会话几秒内把 3 次机会用完。执行方领单前自检能否读 guji-workspace，读不了就只报到不领单（`workers` 列出原因），挂上后自动开始领。`workers` 的「跑完」改称「领过」。

### Added
- 任务库常驻执行方：新表 `jobs.worker`（执行方名字、会话、空闲／在跑哪条、最近报到），`guji job workers` 列在线执行方，`ls` 表头带在线数；执行方空闲每 30 秒报到、在跑每分钟心跳。`GUJI_JOBS_LEASE_MIN` 可调租约（测试用）。文档加常驻执行方线程的开法。

### Added
- 重跑任务库 `guji job`（云端 `guji_jobs`）：重跑、A/B、评测交到 Neon 中心库 `jobs` schema（job／attempt／event／result 四表），同配置按指纹只跑一次；执行方 `FOR UPDATE SKIP LOCKED` 领单、租约心跳，准备→铺底→人裁检查→跑→对比→存包一口气跑完，每步进展与结果（包标签、R2 位置）记库。见 `doc/design/重跑任务库.md`。`scripts/rerun_prep.sh` 加 `--reset`（同一会话接第二张单时先还原本机册配置）。
- `guji source commons-pack`：页表里修过的页（拆页、转正、换图）合进 Commons 根，出回传用的新版 DjVu，逐页解码核对；`guji source commons --reroot`：传完重登记，页序与页图字节不变（设计稿 §十三）。

## [0.5.16] - 2026-10-25

PATCH（A24 字组成批上线第一批的余下部分：#532 #537 #540 #545；#538 #544 起跑自检与人裁绑定；#539 意见池；#536 #542 #543 #546 #547 字组文档）。新组要在册配置 `group_flow` 点名才生效；`seed_admit`、`groups/flow.py`、`groups/registry.py` 的 `code_hash` 变。

### Fixed
- 只重跑 seed_admit（基线包没有 `cache/`）时老人裁静默丢：绑定要拿字形库存图比现格字块图，缓存没有就判 unanchored（殿本 vol10 78/146）。现在缺字块图就现切；切不出来报错（`GUJI_ALLOW_LOST_HUMAN=1` 放行）；`human_chars` 读工作区事件而目录不存在时报错（`GUJI_ALLOW_NO_EVENTS=1` 放行）。绑定缓存版本 7→8。`scripts/rerun_prep.sh` 末尾加人裁自检、写 `~/.guji_env`（GUJI_WORKSPACE）。
- 起跑自检：跑 seed_admit 时字形库有人裁、事件目录却不在（数据目录没指对）就拒跑。此前只在事件里的人裁会被机器通道悄悄放行顶掉（殿本 vol06／vol10 沙箱重跑实测 88／68 格）。

### Changed
- 字组残留送审清理（A24 10-25，铺开 #9）：sb ly mb wj em rr 的 L1 规则拿整部整理本逐处回测修订；rr 随机森林 `rr_img` 改为复核弱票（新 `FlowSpec.review_weak`）；徵徴 复核按刻形改字、门槛单独定（新 `FlowSpec.review_fix_margin`，zheng 0.70）；`seed_admit` 影子闸不再降「同义组已按刻形定的码位」和「形近组补放时整字 HOG 过门槛给的字」（vol16:42:4:3 傳 被降审后又被坐标兜底放成傅）。殿本 vol06–20 离线回放：这几组组内送审 182→133（zheng 35→13、rr 33→21、mb 61→53…），变了的格逐格看图 0 错。`groups/flow.py`、`seed_admit` 的 `code_hash` 变，缺省开。研究脚本在 `research/char_groups/residual_1025/`。
- 字组：码位组 huo 獲𫉬、kui 夔䕫、lie 獵𤢪（殿本每对只一种刻法，码位 sheldon 10-25 定，#532）；一二 yr 加数横第二路 `yr_bars`，整字 HOG 不许单独补放，新 `FlowSpec.lift_ref_veto`（#537）；尙尚 复核只降不改（vol16 两格刻 尚 被改成 尙，#540 #541）。
- 字组文档：码位归一分「真归一」「暂归一（可分待拆，只限同义）」两类并补标已有条目（#542 #543 #546 #547）；登记 寃𡨚（#536）。

## [0.5.15] - 2026-10-24
PATCH（#522 seed_admit 1.23 iron_coord_guard；#528 ref_lib_diff 不放行、ref_prefer 等缺省开；#527 #529 #530 #531 #520 字组；#515 重跑提速；#523 guji source commons；#521 #524 控制台插图块）。缺省输出只把少量放行挪到待审、不改字，不属「多数册值得重跑」的核心升级，按 PATCH。`shadow_veto` 从此缺省开，执行方要装 `.[shadow]`（用发版附件装时 `--extras shadow`），否则起跑前自检拒跑 seed_admit；#533 补了 8 条没装 sklearn 就红的老测试。

### Added
- seed_admit 1.23：铁证与坐标对位字互证 `iron_coord_guard`（缺省开，A31 cv v0.5.12 错放 vol07:30:4:8 水→木，cv#522）：现役对位字被库分歧过滤掉时，铁证字与坐标对位字语义不同、又无直接异体边 → 落审（`iron_vs_coord`）；殿本 17 册 main 包回放命中 14 格（宫/官 ×10 等），看图 13 错 1 难分。`ref_lib_diff`（#528）进 `_LANE_HARD`，待审补放通道不再按整理本字放回。版本号连同 #528 一起记 1.23。只会把放行挪到待审，不改字。
- `guji source commons`：以 Wikimedia Commons 上的 DjVu 为原图的根（10-24 用户定，设计稿第十二节）：核 Commons sha1、存 R2 镜像、`ddjvu` 原尺寸解页、发布页表；会话连不上 Commons 时 `--djvu` 配 `--commons-json` 用别处下好的文件。四庫總目 99 册全部登记（vol01–20 补记根，页图不变）。只在 `datastore/` 与 CLI，`code_hash` 不变（PATCH）。
- `groups.ctx_l2.add_verify`：逐格细读复核补进 L2 表（细读与表字不同 → `disagree:verify` 弃权；表里低把握而细读 high → 用细读的字；至少两遍都 high 同字才 strong）。L2 答案留痕加 `runs`（几遍给了这个字）。日曰／日目 vol11–20 细读 197 格与新表在 dataset `char-groups/variant/ry/`，随成批上线替换中心库表（A24）。

### Changed
- 字组补放与坐标对位互证（`group_flow_lift_ref_guard` 同一开关下）：没有现役对位时，坐标对位是**组内另一个字**而给字的只有单遍文意表（不 strong、不是 L1、不到两遍同字、别的方法也没同字）→ 不补放（`group_flow_coord_dissent`）；补放留审时文意（本组或共字组）给了与整理本不同的字另记 `group_flow_ctx_contra`，进 `_LANE_HARD`，witness3、坐标兜底等补放遍不按整理本字放回。殿本 vol11–20 回放：挡下单遍 haiku 读反的 3 格错放和 2 格被 witness3 放错的格；`ctx_contra` 对全部字组（vol04–20 现有产物）还挡下 witness3／rare_ref 按整理本放的 4 个错字（木族「與此本皆合」等应为本），多留审 1 格（間問）（A24）。`seed_admit` 与 `groups/flow.py` 的 `code_hash` 变，缺省开。
- `config/groups/ry/rules.yaml`、`rm/rules.yaml` 修订（vol11–20 全部日曰目格回测）：rm 规则去掉曰进得来的词组（子、名、題等，原 `rm-目` 334 次命中错 194 次）；ry 加否決「分子目」「◎註曰」「◎月／◎本」，`ry-日鈔書名` 放宽到所有日鈔／日抄，`ry-干支日` 除「乙卯自序」，`ry-ext-r1-日` 除「故曰干祿」（A24）。

## [0.5.14] - 2026-10-24

PATCH（#447 发版自动附带执行包，本版用来首次验证 release workflow；#512–#519 字组与 db sync 改进）。

### Added
- PATCH：发版自动附带 Python 执行包（#447；新增 `.github/workflows/release.yml`、`scripts/build_release_assets.py`、`scripts/install_release.py`）：推 tag 时 wheel ＋ 资源包（`models/`、`config/`、`formats/`、`precleaned/`，Sheldon 10-24 定过渡期随 CV 包；字体、语料不进）＋ `install_release.py` ＋ 校验和自动挂到 GitHub Release，执行方不必克隆整仓。wheel 补上控制台前端 dist 与 `ops/baseline_tests.json`。不改 `open_guji_cv/` 的 Python 代码，各步 `code_hash` 不变。
- `guji db sync` 顺带落库：拉完合完对还没落进字形库的人裁只跑 `glyphdb_admit`、`glyph_audit` 两个消费者，逐条记账（报错的留着下次再试），落了再推；`--no-admit` 或 `GUJI_AUTO_ADMIT=0` 关。起因是批量写进中心库的人裁事件没人落库（10-22 起积压 967 条）；字形库更新的分工（落库、出快照、改钉）见 `doc/受控重跑.md` 第六节。只在 `feedback/`、CLI，不动任何 Step（PATCH）。

### Changed
- seed_admit 四个开关改缺省开（2026-10-24 sheldon 定「确定该做的 feature 一律缺省开，别逐册开、过一阵又忘了其他册」）：`context_guard_ref_prefer`、`rare_ref`、`symbol_review`、`shadow_veto`（`shadow_conf` 缺省 0.97→0.8，殿本册配置一律是 0.8）。殿本 vol06–10 漏开 ref_prefer，vol06 v0.5.12 重跑 111:3:16 商→而（整理本「應時商確」）就是这条该拦的；在新包上开它另拦下旧错 130:5:9 于→子（「興國于氏」），多送审 3 格「入」（整理本作人）。殿本其余册 yaml 本来都开着，行为不变；别的书（北行日錄、全唐文等）从此也开，`shadow_veto` 要装 `.[shadow]`（起跑前自检会点名）。`seed_admit` 的 `code_hash` 不变、`params_hash` 变。
- `guji db sync`：字形库（`output/glyph_store/`）本地和库里都改了、本地又有库里没有的新人裁事件时不再整次停下：取库里的字形库、重建 glyph.db，删掉这些事件在字形库消费者（`consumed/glyph*.jsonl`）里的记账，在库里的字形库上重新消费一遍再推。本地字形库改了却没有新事件的照旧报冲突。省掉册 005 精校 10-23 三次手工 `pull --force`＋重写票（A32 复盘改进 1；只在 `datastore/`、CLI，不动 Step，PATCH）。
- `guji freeze register` 加 `--repo <cv 检出>`：产物是旧版 cv 跑的就指那个版本的 worktree，登记的 cv 版本与提交取自那里；检出认不出版本号（没拉 tag，记成 `dev+g…`）时计划报问题、不许执行，提示 `git fetch --tags`（A32 复盘改进 2；只在 `ops/`、CLI，PATCH）。
- close-check 1a 分开报过期原因：manifest 新记参数逐字段短哈希 `param_parts`（不进指纹，产物与 `code_hash` 都不变），`status` 的「参数变了」点名字段；只因共享输入（语料、证人、格位表、字组与异体表、借来的字形库等，`close_check.SHARED_PARAMS`）被别处更新而过期的页，1a（含冻结册）单列一句、不算失败；本册自己的变动照旧失败，两类都列。改动前跑的老产物分不出字段，照旧判失败（A32 复盘改进 3，标准 I；PATCH）。

### Fixed
- seed_admit `ref_lib_diff_guard`（缺省开，A24）：`relax_ref_agree` 的 `ref_lib` 分支在库判 `diff` 时不放行，记 doubt `ref_lib_diff`、退回人审。vol06 v0.5.12 重跑 149:3:3 图是「也」（框带版框竖线），整理本对位与库 top1 都给「十」、库判 diff（cov 0.83），旧版照放成「十」。vol06 新包 ref_lib 放行 13 格里只拦这 1 格，vol04–10 旧包 0 格。`seed_admit` 的 `code_hash` 变，各册只需重落 seed_admit。

## [0.5.13] - 2026-10-24

PATCH（#452 seed_admit 删准入三闸：`code_hash` 变、缺省参数下产物不变；#509 `guji recheck --glyph-diff`；#507 精校出单走 book-text dev）。

### Added
- `guji recheck <册> --glyph-diff <旧号|旧库>`：换字形库版本后只点名判决可能变的格（kNN 邻域差分：新旧库的 HOG 前 k 邻居、命中条目、共识门槛、近形对刻例），`--list` 逐格列理由，`--params` 指沙箱库。殿本 vol08 实测点名 6.7%（按字点名 32%），点名格重算＋其余照搬与整册全算 10,681 格逐字节相同（`doc/受控重跑.md` 第五节）。只在 `ops/`、CLI，不动任何 Step，`code_hash` 不变（PATCH）。

### Removed
- seed_admit 1.22：删准入三闸 `runt_cell_review`（矮格转人审，含 `runt_ratio`、`runt_min_ink`）、`oversplit_gate`（过切提示，含 `oversplit_*`）、`nonchar_gate`（非字过滤，含 `nonchar_flags`、`nonchar_strokes`、`nonchar_jiazhu_ignore_rule_bar`）。三闸缺省都关，A/B 在 vol05、vol09 上单开逐格不变，vol04、05、09 触发条件 0 命中（[报告](doc/exp/准入三闸-vol05-vol09-报告.md)，cv#450；Sheldon 10-23 定删）。`seed_admit` 的 `code_hash` 变，各书该步判过期；缺省参数下产物不变。vol04 册 yaml 原开着 `nonchar_gate`，删后该键被忽略（实测 0 格），该步重算一次即可，键要另在中心库删掉。

### Changed
- 精校出单的 book-text 改走 dev（book-text 10-24 新规矩，open-guji/book-text#235；#507）：`republish.py` 的 `bump_book_text` 先切到最新 dev，升版后跑 `local_check.py --dev`、不重建 `index/texts`，提交并推 dev（别人先推了就 rebase 再推），不再开分支和 PR；`proof_cycle apply` 导出前先切 dev，原第 6 步「推分支、开草稿 PR」去掉。CHANGES 的 PR 列写 `#TBD`，由 book-text 每日合并换号（A32，PATCH）。

## [0.5.12] - 2026-10-23

PATCH（殿本 vol11–20 统一重落要钉：并进 #504）。

### Fixed
- 异体组按刻形复核（#504，A24 异体线）：13 个异体组对已放行格只跑字形方法复核，判出另一形就降审、不改字（修 旨→㫖 24 格等错放）；`guji groups status` 标疑格号漂移。`seed_admit` 的 `code_deps`（`groups/registry.py`、`flow.py`）变，各册 seed_admit 判过期；vol11–20 回放送审约 +85 格，不新增放行。

### Added
- 字组规范化（#503）：`doc/字组/`（规范、总表、68 张组卡）＋ `guji groups status`，删旧 M7 文档。

### Changed
- `republish issue`（#500）：等发布认准 run、冒烟多等，冒烟没过不挡文本 PR。发布脚本，不进任何 Step。

## [0.5.11] - 2026-10-23

PATCH（殿本 vol11–20 统一重落要钉：0.5.10 之后只差 #498）。

### Changed
- 码位归一可放工作区级 `config/codepoints.yaml`（#498，Sheldon 10-24 定「归一放字形库这一层」）：`load_book` 先读与 `books/` 同级的该文件，再叠册 yaml 的 `codepoints:`（册里写的逐条覆盖）；没有这个文件行为不变。合并后的值经 `seed_admit` 的 `book_deps` 进指纹，加文件的工作区 seed_admit 判过期。

## [0.5.10] - 2026-10-23

PATCH（A30 要钉正式 tag 跑殿本 vol11–19；Sheldon 10-24 定带上 #471 及之后合进 dev 的改动，仍按 PATCH 发）。

### Fixed
- `proof_cycle apply` 用钉住的旧引擎重跑时经 `scripts/zhengli/engine_run.py` 起，读中心库事件跳过旧引擎不认的新种类（如 #485 的 `inverted_band`），并禁止 compact；重跑加 `--stop-on-error`，有一页失败就停，不再带着失败的产物接着导出出单（A32，册006 实跑 seed_admit 150 页全败后仍往下走）。发布脚本，不进任何 Step（PATCH）。
- 5a 简体参考字兜底（#486，A23，PATCH）：`match_replace` 系通道的参考字落在人工审定的纯简体清单（`config/dicts/simplified_refs.txt`，104 字）里、库 top 是其正字时，取库里的正字，不再把整理本混入的简体（贯/牵 等）放进产物。`clustering.seeding` 在 `seed_admit` 的 `code_deps` 里，`seed_admit` 的 `code_hash` 变，各册只需重落 seed_admit；输出会变，不能登记 `code_equiv`。清单文件本身不进指纹，以后改清单不会让产物判过期。
- seed_admit／align_ref 坐标冲突守卫（常开，无开关，A23）：`align_ref` 产物新增 `coord_conflict_ids`（坐标字≠现役 equal 字的格，全记）；match_ref 不放这些格、落人审（doubt `coord_conflict`）。起因：殿本 vol14 cv0.5.9 的 60:1:5 拱→撰、103:2:7（双行小注两字被切一格）放成「中」。vol14 两版回放每版约多送审 8 格。`seed_admit`、`align_ref` 的 code_hash 变，各册缺省输出会变；冻结册只登记不重跑。
- 生僻字面板（`rare_panel` 单格／批量入口）找不到识别权重文件时报 `CnnCheckpointMissing`，不再悄悄返回少 CNN／embedding 两路的候选（A23；wheel 安装后引擎仓根错位的同款坑）。只管文件缺席，没装 torch 仍由起跑前自检报；`GUJI_ALLOW_MISSING_DEPS=1` 放行。不在任何 Step 的 `code_deps` 里，`code_hash` 不变。
- 字形库体检（`glyph_audit`）撤库（evict）或改字（relabel）一个人裁入库的刻例时，同时把该格此前的人裁事件记进 `lists/stale_verdicts.tsv` 作废；撤下之后新裁的照常生效，机器入库的刻例不动（A23，GUJI-719 第 4 项）。此前撤库不留标记，旧人裁事件会让该格被误放行。不在任何 Step 的 `code_deps` 里。
- seed_admit `rare_ref`（两遍）也认 `lane_keep_ref_review`（A24）：被 `ctx_guard_ref`／`group_flow_ref_dissent`／`group_flow_coord_dissent` 拦下的格不再由 rare_ref 按整理本字放回（vol18:115:6:3 刻「本」、整理本与 5-b 作「木」，旧版放成「木」）。开了 rare_ref 的册参数 dump 多出该键，`code_hash` 变，各册只需重落 seed_admit。
- seed_admit `lane_keep_ref_review`（缺省开，A24）：被 `ctx_guard_ref`（ref_prefer）、`group_flow_ref_dissent`／`group_flow_coord_dissent` 拦下的格，不再由待审补放通道（witness3／coord_fallback／seal）按整理本字放回。vol20 实跑放回的格里改错 5 格（諸→諧、其→萁、本→木 等）：证人与整理本同为文渊阁系，与殿本刻字不同时照样一致。`seed_admit` 的 `code_hash` 变，各册只需重落 seed_admit。

### Added
- 图片格与插图块（GUJI-740，设计 book-text `docs/design/2026-10-图片格与插图设计.md` §五，格式 guji-format spec 09）：人裁 `confirm v=figure`（`alt` 说明）＝「这格是图形，不是字」，进排除名单（理由 `figure`），Step7 照排除格处理（不进库、不出卡），字位流占位出 □；网站精校票 `choice=figure`（带 `alt`）经 `guji cellvotes` 落成这一条。新 kind `figure_region`（控制台页级插图框，key `figure:<册>:<页>`）不配消费者。Step9 char-cord 导出用到图的册写 char v0.3（格 `fig`、图列 `kind: figure`）、cord v0.2（`marks.figure`）、新文件 `NNN.fig.json`（fig v0.1）与 `fig/NNN/<图 id>.png|webp`（按框外扩 2px 从页图裁，工作区原图 sha 对得上用它，否则取 R2 页图）；`--prev-fig` 沿用旧图 id、保留重绘图。没用到图的册导出逐字节不变。只动 `feedback/`、`report/slots`、`formats/`、导出脚本，不在任何 Step 的 `code_deps` 里，`code_hash` 不变；有图片格人裁的册 seed_admit 照常因名单变化过期（L0）。
- `scripts/zhengli/text_release.py`（M10 复盘第 6、7 项，A32）：`pin` 在冲 1.0 开始时记下册 yaml、语料版本与语料包、参照本、逐列格位表、字组配置、glyph_pin、产物包与引擎提交的指纹（数据目录 `feedback/lists/release/<册>.pin.json`，随 db sync 进中心库）；`check-pin` 分「本册输入变」（退出码 1）与「共享输入被别处更新」（2，冻结时记一笔不算失败）；`run` 按 1.0 标准顺序一次跑完输入锁、G0 票账、G1 待审与看不出 ≤2%、G3 close-check（钉住的引擎）、读者侧冒烟、冻结前能核的出口项，全过停在「请用户点头」。只读脚本，不进任何 Step（PATCH）。
- `proof_cycle.py`（M10 复盘第 4 项，A32）：重跑缺省全册 seed_admit（只跑有票的页会漏早有人裁的格）；`plan --engine <worktree>` 让重跑用出单版 cv、工具用本仓，核引擎的 HEAD 而非本仓；`plan --pack` 给没存 rev 包的老单指定包；导出后与 book-text 现文逐格比，人裁改字进文本、机器改判（无票变字）退回旧字并进下一张单的复审清单；出单换成 `republish.py issue`（只发这一章、等发布、冒烟）；新增只读 `status`（线上单投完没有，退出码 0＝可以落票），给定时任务用。发布脚本，不进任何 Step（PATCH）。
- 精校复审出单与网站推翻旧人裁（M10 复盘第 1、3、5 项，A32）：`republish.py prep/from-pack --recheck <清单>` 把指定格（人裁过的、已放行的都行）放回待审单，每格带 `recheck`、`note`（网站卡片头上常显的一句说明）、`prior`（已有人裁的字和 id），pending_route 不扣它们，现行切分里没有的列进差异单；`guji audit alt --extra` 给这些格也算相似字。`guji cellvotes draft` 另出 `recheck.tsv`（推翻旧裁、意见不一致、说无字又给字、格位变了四类挂起，可直接交 `--recheck`）；复审单上写明了旧裁、投票人投了不同的字，按有意推翻照写（payload `overrides`），出单后又来新裁的照旧挂起。新增 `republish.py issue`：出单、两道门、传图、推库、只发这一章（kaiyuanguji-web#584 的 `only`，网站没有就退回全站）、等网站发布、读者侧冒烟一条命令做完。发布脚本与 CLI，不进任何 Step，`code_hash` 不变（PATCH）。
- `guji opinions auto revert|finish-revert`（GUJI-734）：撤销已发布的修订批。在 book-text 开 `auto/revert-…` 分支把原批的格退回（A／B 整格还原，B′ 删格并把 cord 框放回、标点实体锚点跟回），文本线再升 patch，CHANGES 写明撤销了哪批、哪些意见、理由；现文已被后来改过则拒绝。合并后意见记 `reverted`、原批标 `reverted`、格谱系补撤销行，网站状态回到「还要再看」。只在意见池与 CLI，不动任何 Step（PATCH）。
- `guji source pull|show|list|check|ia|register|replace`：原图（源件 → 页图 → 页表）存 R2 正式桶，云会话一条命令取原图（`doc/design/古籍图片全流程-源件页图管线与IIIF.md`）。殿本 vol01–20、北行日錄、全唐文 v006–v010 已登记，与现用原图逐字节相同；`register --src-file` 登记 PDF、DjVu 等非 IA 源件。只在 `datastore/` 与 CLI，不动任何 Step，`code_hash` 不变（PATCH）。

### Changed
- 未发布版本跑管线正规化（A20，2026-10-23 sheldon 提）：① 不在 tag 上时 `cv_version` 改记 `0.5.10.dev12+g<12 位 hash>`（原 `0.5.9+12`，不带 hash、会撞号），浅克隆取不到 tag 记 `dev+g<hash>`（原记空、钉版册因此一律被拦）；② 钉版／冻结册在中心库实验分支（`GUJI_DATA_BRANCH=exp/*`，产物隔离）上跑自动放行；正式目录上 `--allow-cv-mismatch` 须带 `--why "<理由>"`；放行理由记进 manifest 新字段 `cv_override`；③ 非正式版 cv 出的产物包不能在正式库标 main（`--why` 例外）。只动 `core/cv_version.py`、`cli_v2.py`、`cli_products.py`、`datastore/packs.py`、`products/manifest.py`，都不在任何 Step 的 `code_deps`，各步 `code_hash` 不变，老产物不过期（L0）。见 `doc/版本号规矩.md` 第五节。
- Step0 invert_detect 1.2（Sheldon 10-23 审 vol11–20 候选）：建议修法改成新规则 `inverted_poly`（多边形，按黑区实际形状圈：可台阶、可分段，修时不再现量），vol11 p40 范围太大、vol13 p85/86、vol14 p87 略偏、vol17 p126 台阶被抹平都贴合了；下边框按位置排（黑条下方是空白地脚就不报，与页顶外框对称），vol16 p80/p104、vol20 p168 不再送审。`utils/preclean` 加 `inverted_poly` 与通用 `rule_mask`。`invert_detect` 的 `code_hash` 变，各册只需重落 Step0 候选；已在 yaml 登记的反色页不受影响。
- 删 `glyph_match.near_shape.allow_guarded`（A20／用户 10-24 定）：匹配器已判护栏（never_match／conflict）的格近形决胜一律不升档；书 yaml 里的旧键读进来被忽略。`glyph_match` 的 `code_hash` 变，vol02（唯一开着它的册）的 glyph_match 需重算一次。
- 放行开关缺省开（2026-10-23 sheldon 定「没问题的 feature 一律缺省开，开关只为方便 A/B」）：`seed_admit.context_guard_diff`、`context_guard_ref_blank`、`lane_witness3`、`lane_coord` 改缺省开，`group_flow` 缺省＝注册表里全部声明了 flow 的字组（书 yaml 写 `[]` 才关），书级 `iron_gate` 缺省开。殿本 20 册 yaml 本来都开着，行为不变；`seed_admit` 参数 dump 变，各册放行判过期。
- Step1 border_detect 1.6：列距救援 `pitch_rescue`（缺省开，`utils/pitch_rescue`）。自由模式列网里有列 < 0.7×中位列宽时（多挑一条假竖线把一列劈成两窄列、外侧一整列落在网外、字悄悄丢掉），先网格模式重探，选不出版框对再去掉劈线、在有字的一侧补外框；新网干净才接受，没触发的页逐字节不变。殿本 vol11–20 九页里修好 8 页（vol13 p75、vol14 p103/186、vol16 p120、vol19 p29/86、vol20 p68/113），vol16 p8 密排夹注页留人工。`border_detect` 的 `code_hash` 变，全书 Step1 起判过期。
- Step1 列距救援收紧到实测列宽带（Sheldon 10-23：殿本列宽极一致，按分布严格限）：殿本 vol04–20 共 2,969 页，内列宽／页中位 99.9% 在 0.907–1.088，最外两列 0.84–1.26。触发改为「有列出带」（内列 ±10%、外列 0.85–1.3），新列网也须全在带内；另加「列宽合格的列两边的界行不许动」，防网格把印好的真界行挪进空白（vol13 p46）。vol11–20 触发 31 页、改 8 页（原 7 页列网错位＋vol11 p55 右框线更贴界行），vol04–10 不变。

### Fixed
- `ops/col_gate.py`（A20，A24 报）：读原图改走 `utils.image_io.imread`，不再直接调 `cv2.imread`（Windows 非 ASCII 路径会静默读空；`test_image_io_guard` 在 dev 上因此失败）。缺原图照旧跳过。不进任何 Step，`code_hash` 不变（L0）。
- `scripts/dzg_import.py`（A20，A24 报）：daizhige 源用缅甸字母（U+1001 起，登记在每条 `glyphs`）当缺字图占位码，原先只转 PUA，233 处原样进了 `siku_daizhige.txt`、成了坐标对位的整理本字。现在与映不上的 PUA 同记 `〓`；新增 `fix-glyph-codes` 就地修已有整理本（一字换一字）。已据此出殿本语料 v18（中心库 rev 94678）。脚本不进任何 Step，`code_hash` 不变（L0）；换钉 v18 的册语料指纹变。
- `scripts/zhengli/republish.py add-sprites`（A20，A31 报）：核坐标时把 `img.s` 文件名也一起比了。线上单已是哈希名（`p0001.<sha8>.webp`，册 006–010 先前补过主雪碧图、只缺相似字图），重建出来是 `p0001.webp`，于是 105 格坐标全对也整单被拒。现在比之前去掉内容哈希，页名不同照样拒。发布脚本，不进任何 Step，`code_hash` 不变（L0）。

### Fixed（rc 上修）
- `guji db sync`／`pull` 读的过程中有人往同一工作区推新行（如 `admissions.jsonl` 追加）时，不再报「库里有超出 n_lines 的行」退出，而是重读（原来只在读完后核 rev，读到一半的不一致直接抛）；没有新写入的不一致照旧报错。10-23 A30 sync 殿本撞上（与 dev／v0.5.9 无关，同一段代码，换时间重试就过）。只动 `datastore/workcopy.py`，各步 `code_hash` 不变。

### Added
- 指纹覆盖守卫 `tests/test_code_deps_coverage.py`（A20）：`code_hash` 只认 Step 模块与手列的 `code_deps`，不顺 import 走；普查出 11 个 Step 共 39 处「import 了算法模块却没进指纹」（seed_admit 15 处，含 `shadow.*`、`feedback.mojibake`、`clustering.confusable`、`steps.align_ref`/`context_decide`）。现登记为存量、约定搭车补（该步下次本来就改算法时顺手补进 `code_deps`），新增 import 不登记就测试失败。只加测试，不碰任何 Step，`code_hash` 不变（L0）。
- `guji opinions auto`（M11，GUJI-735 起步；MINOR 级新命令，不碰任何 Step，`code_hash` 不变）：修订流程自动化调和器。`decide`（`to_user` 的意见按 `rules.json` 的 `auto.decide` 自动结案，`decided.by=policy:auto-v1`；刷票、用户亲裁、版本漂移、C 类、看不清、置信不足的留着）、`prepare`（每章聚一批，book-text 里建 `auto/<书>-<章>-<日期>` 分支，套 `revise`、升版本、跑 `local_check`、提交一次，失败不留半成品）、`finish-pr`（CHANGES 的 `#TBD` 换 PR 号）、`finish-merged`（记 `applied`、格谱系、度量、`publish-status`）、`digest`（汇总）。意见池新增 `releases.jsonl`、`lineage.jsonl`、`metrics.jsonl`（只追加）；日志新增 kind `batched`／`pr_opened`／`published`／`reverted`／`policy_applied`，只有 `reverted` 改状态。`rules.json` 升 version 2，加 `auto` 段；合并进 book-text main 缺省不自动（`auto.merge.enabled=false`）。设计见 book-text `docs/design/2026-10-修订流程自动化设计.md`。

### Fixed
- 续跑加固（#454，A20）：manifest 追加写被杀留下半行时，读表跳过坏行（该页按没记过、重跑补），下一次追加先补换行，不再整册起不来；跑批锁冲突报错在同机时标注持有者 pid「在运行／已不在（锁可能被子进程握着）」。不碰任何 Step，`code_hash` 不变（L0）。
- seed_admit 放行护栏七条（A24，殿本 vol11/14/15 用 v0.5.9 重跑后逐格核出的错放；新开关缺省开，`seed_admit` 与 `groups/flow.py` 的 `code_hash` 变）：
  ① `context_variant_form_guard`：Step6 margin 按语义合并算，參㕘叅、簒/篡 等异体各占一半也报 margin 1.0，context 在异体里抓阄（vol14 235:7:4 两版一次 㕘 一次 叅）；放行字在 ranked 里有语义同字的对手、库形又分不开 → 落审（doubt `context_variant_form`）。
  ② `iron_ctx_guard`：铁证字与上下文第一名（概率 ≥0.5）语义不同、两字在库里近平手（差 <0.005）→ 落审（`iron_vs_ctx`；vol11 12:2:14 官→宫）。
  ③ `match_tie_guard`：库判非 same、库前两名语义不同且 cov 差 <0.003 时 match_ref／match_replace／match_margin 不放行（`match_tie`）：对位载体取库 top1，近平手时「库与整理本一致」是自证（vol14 60:1:5 拱→撰）。**缺省关**：vol16–20 离线回放每册多送审 160–400 格（日曰、人八等库近平手而整理本给对），只多拦 2 格。
  ⑤ `context_lib_dissent_gap`（0.03，`context_lib_dissent_cov` 0.93）：库 top1 与 context 字语义不同，context 字在库里落后 ≥0.03 或不在库候选（top1 cov ≥0.93）→ 落审（`context_lib_dissent`；vol14 𣏌→相、㳫→書、牽→事）。原 `context_guard_diff` 只拦库判 diff，这几格库判都是 unsure。
  ④ `group_flow_lift_ref_guard`：字组补放时只有文意给字、整理本字是组内另一字 → 不补放（`group_flow_ref_dissent`；vol15 118:4:15 面→而）；共字组联合判（日曰目）不受此限。
  ⑦ 同一开关下加坐标对位拦补放：现役对位缺格、坐标对位（`align_ref.coord`）是组外另一字 → 不补放（`group_flow_coord_dissent`；vol18 107:6:7 叔→叙、vol16 109:6:21 樊→彝）。坐标对位字只用来拦，不参与判字。
  ⑥ `context_page_end_review`：本页读序最后一格不走 context 放行（`context_page_end`）。对位只收两头被 equal 夹住的 replace，页末格常拿不到整理本字，没人拦 context：v0.5.7→v0.5.9 放行字变率页末格 1.94%／1.67%（vol12／vol14），其余格 0.07%／0.05%。每册约多送审 2–5 格；根治在对位侧，另查。

## [0.5.9] - 2026-10-22

PATCH（Sheldon 10-23 定发，为殿本 vol11–20 带格位表全体重跑）。

### Fixed
- Step3 row_segment 1.37（PATCH）：`layout_prior` 开着、表在、表里却没有本册时直接报错，不再悄悄当关。殿本 vol11–20 首跑就是册配置写了关、表里也没这 10 册，对表逐格全对只有 94.7%（vol04–10 带表 100%）。同时中心库补了 vol11–20 的页映射与格位表（rev 93491，15,825 列），册配置改回开。`row_segment` 的 `code_hash` 变了，缺省输出不变（有表的册逐字节相同）。
- `guji opinions publish-status`（GUJI-714 后续，PATCH）：① 上次发过、这次算不出状态的 target（意见重开、改判成不写的状态）写一行 `state:"open"`，网站 proofing-sync 据此撤回 KV 里的旧状态（原来旧状态一直留着，实时页与 COS 清单不一致）；② 人裁驳回又没写公开理由、判定为原文不误的，回复用模板句「此处原文作「甲」，暂不改」（原来读者只看到「未采纳」）；③ 撤销过 dup 的意见照常带回复（原来只要有过 dup 记录就不回）。不碰任何 Step，`code_hash` 不变。

## [0.5.8] - 2026-10-22

PATCH（sheldon 10-22 定发）。主要内容：Step0 反色带候选 `invert_detect`、切分 `row_segment` 1.36、字框收缩 `cell_shrink` 1.19–1.20、外框线回直线 `border_detect` 1.5、文意组加字形第二路（cv#429，新增 12 个组模板库 rr ts ly wj zh yh yt js em fc yr xz）、厯歴／呂吕／徵徴 判法调整、己已巳／日曰 收口、影子复核按册码位归一（v0.5.7 漏带）。相对 v0.5.7，`border_detect`、`border_detect_gate`、`column_warp`、`column_gate`、`row_segment`、`cell_shrink`、`seed_admit` 七步 `code_hash` 变，另新增 `invert_detect`，**各书 Step1 起全部判过期**；其余 11 步不变。新组 weiw shan di qin 要在册配置 `group_flow` 点名；组模板库变了，配套出全局层新底库、各册改钉。rc 上全量测试：3851 过、66 跳过、1 条报错；报错的是一条测试守卫，已修（装了 psycopg 而没给测试库时，`test_datastore_expbranch` 一条用例报错而不是跳过，只改测试）。

### Fixed
- seed_admit 影子复核 `shadow_veto` 比字按册 `codepoints` 归一（d54fe0fc）：別别、晚晩、出岀 不再被误降。v0.5.7 切 rc 时没带上，本版补发。`seed_admit` 的 `code_hash` 变。
- Step3 row_segment 1.36：字内空隙里的格线不再把字头、点留在上一格（人审截断「良」的点、「晉」的头、「其」的脚、「二」的上横）。干净格线两侧有一格格高偏离 period 超过 15% 也过一次 U-Net 探针（vol02 1,800 条，原来只有一高一矮的 6 条）；探针分歧 ≥100、扩池补来的候选（U-Net 引导缝 / 按格高找的缝）与 U-Net 分歧 ≤30px 时直接改选，不再只记候选交人：粘连切点要穿墨 ≤20px，原本干净的格线只换成同样不穿墨的缝（换成穿笔画的缝会把上字底横的一截切给下格，「一」就成了「二」）。vol02 改 40 处、vol05 改 76 处，看图都是修好或持平；Step3 时长略增。
- Step4 cell_shrink 1.19：列端粗版框不再带进字块（重跑 v0.5.7 时害了认字）。`strip_frame_line` 两处放宽：线跟字之间隔着白行、线外到下一道线只有框的毛边和连墨的，双边框内外两道一起剥（vol05 p92「乾」）；厚过 0.12 格但墨铺满 ≥80% 的线行段算粗版框，贴着字也剥（vol06 p149「者」、vol08 p59「尚」）。vol05 全册只改「乾」和一格框渣、vol09 全册 0 格变化。框线只剩贴着字的碎段的（vol06「將」「而」、vol09「講」）还没修。
- Step4 cell_shrink 1.20：双边框内框贴着字脚、两头没到窗边的，不再带进字块（vol06 p112「而」）。全页框线线位原来只在版框往内 0.4 格里找，内框离版框可到半格，找不着；改为找到 0.8 格，并记下每道线的线厚。列端格里跨度 ≥0.8 窗宽的实线，中线落在线位上、厚度跟那道线差不过 2 行，就当框线剥。字的底笔碰巧压在线位上的厚度、跨度对不上（「士」的底横 0.7 窗宽、「是」的捺脚只有 1 行）。vol05 改 17 格、vol09 改 41 格，看图都是剥掉框线或框渣，「燧」辶的捺尾跟框线连成一片，随框剥掉一截。「將」那列框线跟邻列对不上、「講」是虚线贴字，还没修。
- Step1 外框线也按横带证据回直线（`border_detect` 1.5，`border_geometry.snap_verticals_to_evidence`）：原来「折点只许在有界行支撑的横带偏离直线」只管内部界行，首尾两条外框线没人管。vol08 p2（卷首大印页）左外框下半段印得淡，三段折线被第 9 列字的竖笔吸进 42px，s15–21 七个字只罩住右半。外框线现在只认两种证据：线就压着的框线（偏 <8px）原位，否则回直线位（直线已挑过细内框）；不用文字缝、不往远处的粗外条挪；内部界行先定、外框线最后按定下来的邻线过间距护栏，内部界行与改前逐位相同。vol04/08/09 三册 555 页里 34 页的外框线动了，Step3–4 新旧对比：对格位表逐格全对 279/279 列不变，字框横向变了的 13 列看图都是变好或持平（vol08 p2 c9 罩全，vol04 p178 c1、p63 c1、p91 c1、vol08 p12 c1 甩掉框线渣）。各书 Step1 起判过期。
- 导出 cord 时同一格号的两个 blank 格只发一个 mark：夹注 a／b 两半都被 Step3 记空（`layout_frame_junk`）后同一格号有两个 blank、blank 没有 sub，mark id 撞，`guji export`／`republish.py from-pack` 在页检查报「id 重复」（v0.5.7 重跑 vol05 p3 第 4 列 slot 11、12）。只改导出，不动任何 Step，`code_hash` 不变；Step3 产物里的重复 blank 留着无害。

### Added
- R6 整页／整列丢字检查 `ops/col_gate`（GUJI-661）：读 Step3 与原图，报「整列没切出」与「单字墨段没被字格接住」，抹掉版框折角与污渍后再判。`scripts/zhengli/col_gate.py` 单跑，`collect_exit.py` 加 R6 项（`exit_report.py` 有数才判）。只报告，不改产物，不动任何 Step。殿本 v0.5.7 包 vol04–10 误报每册 0–12 处；自造缺陷召回：整列格记空 100%、整列没切出约 85%、整列错位 0.6 格约 65–73%；真书历史案例（vol03 57:1 等）云端没有当时的旧产物，未能复现。
- `feedback/exclusion_check.stale_by_binding` + `scripts/zhengli/stale_exclusions.py`：列出人裁排除名单里裁决锚点与当前切图对不上的格（只报告；GUJI-659／623）。
- 粗校出口 R4 异常表可写成 JSON（GUJI-666，`scripts/zhengli/collect_exit.py` 的 `load_anomaly`）：`{"rows": [{n, text, cause, concl, pages?, cols?}]}`，`pages`／`cols` 给了就不再从「现象」里抠 pN colM；格式错报具体位置（JSON 报行列和 `rows[i]`，md 报第几行），不再是整表悄悄 FAIL 或悄悄少读几行。老 md 表照读。体检结果带字形库指纹那一半早由 GUJI-710 做掉。
- `guji pipeline`／`guji step` 起跑前自检依赖（GUJI-654，`ops/preflight.py`）：这次要跑的步骤用得上的东西本机缺了就拒跑（退出码 2）并点名——Step3 切点裁判（`cut_judge=unet`）和 Step5-b 要 torch 与权重，册配置开了 `shadow_veto` 的 Step7 要 joblib／scikit-learn。以前这些都是悄悄退回旧办法或整页失败（10-21 vol08 缺 joblib，seed_admit 69 页全失败，pipeline 仍返回 0）。`--allow-missing-deps` 或 `GUJI_ALLOW_MISSING_DEPS=1` 放行。不动任何 Step 与 code_deps。
- 待审单雪碧图改成「文件名带内容哈希、真源进 R2」（GUJI-675，方案 B）：`scripts/zhengli/sprite_pub.py`——`republish.py prep` 把图改名 `<原名>.<sha8>.webp`、单子顶层写 `sprites[]`，`push` 先把图按 sha256 传进 R2 main 桶（`datastore/r2.py` 认 `webp` 后缀）再写单子；新增 `republish.py add-sprites` 给线上旧单补图（重建后逐格核坐标，一格对不上就不动）。网站 proofing-sync 读 `sprites[]` 发到 COS（kaiyuanguji-web 同步改）。不动任何 Step 与 code_deps。
- Step0 反色带候选 `invert_detect`（Sheldon 10-22 定「自动认＋送审，人点头才修」）：排在 Step1 之前，判据是「长横黑条里界行翻成白缝、带外接着是黑界行」，产物 `inverted` 列出每页候选黑条、翻白界行道数和建议修法（一条 `preclean:` 规则，量不到上下沿就退成矩形）。只送审、不自动修：殿本十册原图上已登记的 15 处全中，另报 13 页，Sheldon 看过都是粗外框或封面。已登记 `preclean:` 的页读修好的图，不再报。控制台卡片和点头后自动修在下一个 PR。
- 反色带送审与点头才修：控制台 Step0 页加「反色带候选」卡，一页一张，原图与照建议修法修后的预览并排，点「是／否」落 `inverted_band` 事件（问题 `invert_detect.page.is_inverted`，裁决表 `preprocess/inverted-band`）。点「是」的页 Step0 照规则修，修好的图放派生缓存 `<cache>/precleaned/<book>/<页>_<规则哈希>.png`，`effective_raw_path` 读它，原图 sha 变、各步自然判过期；人审放行不再过墨量闸。点「否」的页不再出卡（勾「含已否」可改判）。书 yaml `preclean:` 登记的页照旧以登记为准。接口 `/api/invert-review/cards`、`/api/invert-review/preview`。
- 反色带候选 `invert_detect` 1.1：先排掉不在正文里的黑条（Sheldon 10-22 嫌 1.0 误报多）。黑条不足 12 行（上框粗线）、上方是空白天头（页顶外框）、上下是满纸花纹（封面、书衣）都不报。殿本十册 1,707 页：已登记 15 处全中，误报 13 页降到 2 页（vol06 p40、vol08 p67，抬头格下的粗横线，与已登记的 vol02 p136 几何上分不开）。阈值在同一批十册上定，没有留出验证。
- 复查已登记反色带：vol05 p22、vol07 p78、vol09 p174/p175 四页修完还留着黑块（登记的横向范围漏了一截，vol07 p78 左两格的带上沿是台阶形），中心库 yaml 补全规则（vol07 p78 左两格改用矩形），`precleaned/` 四张图重生成。修后再跑 `invert_detect` 不报，逐页看图核对干净。四页 Step1 起判过期。
- 特殊符号进字符候选集（Sheldon 10-21 定，设计 `doc/design/特殊符号进字符候选集-设计.md`）：人定的符号（○□△⊙ 等，`hanzi.symbols` 登记过的）能进字形库，`glyphdb_admit` 与 `glyph_ledger` 不再把非汉字码位一律拒收；相似字按图认符号（模板余弦 ≥ 0.93 且高过本格最像的字才并入）；5-b 字表开关 `font.charset.symbols`、seed_admit `symbol_review`（放行成符号的格退回人审，除非本书同一符号已有 3 条以上人裁）；送审原因显示「可能是符号」。没开开关的册产物逐字节不变。（#362、#377、#384）
- 从产物包出待审单时，相似字现切字块图、一格没出就报错、`republish.py add-alt [--replace]` 原地补。（#362）
- 日曰分歧复核（sheldon 10-22，重跑后 4–10 册 39 格组流与库分歧，长上下文读原典逐格定字）：日曰 18 格里 10 格是文意表（L2）错杀或错放，根因是表只取 haiku、Sonnet high 异议不起作用（5 格 Sonnet 5/5 对）。新 `scripts/l2_apply_dissent.py` 离线改表（Sonnet high 异字→以 Sonnet 为准），不动 Step 代码、`code_hash` 不变；抽样 8 页：6 格由降审回到放行且字对，其余不变。新表（另加长上下文判定 3 格 vol07:73、vol09:40、vol10:109）sheldon 10-22 说「推」，已推中心库＝书库语料 v15（base b4，册钉还没改到 v15）；项目文件 `jys-ry-rm-1022/round4/ry.json`。

### Changed
- 厯歴 `lih` 改取下半框 HOG（`ids_online.SPECS`：size 48、`region=(0,1,0.5,1)`、门槛 0.25；模板库同一 122 格重建）：按册留出 119 对/3 弃/0 错（原 92/122）。区域在同批数据上选，偏乐观。经验总结与逐组评估见 `doc/design/M7-切分识别经验推广.md`。PATCH；只影响点名了 lih 的册，重跑归 M8。
- 呂吕 `lv` 门槛 0.5→0.3、徵徴 `zheng` 0.6→0.45（sheldon 10-22 同意）：判别台复核（`research/m7/bench/check_prod.py`）发现两组各有 1 格在线上门槛之上判「错」，sheldon 看图确认是原人裁错（vol02:125:8:4 实为吕、vol01:70:7:10 实为徴；数据集与中心库已更正）。更正后按册留一：呂吕 68 对/2 弃/0 错（原 62），徵徴 49 对/26 弃/0 错（原 38，错例最大 0.336）。与上一条合计 PATCH；只有 `seed_admit` 的 `code_hash` 变（相对 dev：8a8925fc0ffbd21a→72120ef3f1a81eec）。
- 文意组加字形第二路（sheldon 10-22「能不能再进一步优化算法」）：入人八 土士 論諭 問間 曾會 遺還 圓圖 甲申 而面 傅傳 一二 共 11 组，方法数组在文意之后加整字／取框 HOG（`registry.GLYPH2`、`ids_online.SPECS` 同名行，模板库 `config/groups/<组>/ids_bank.json`）。文意弃权时字形可单独补放，两路都给字须一致，复核时字形给了别的字就降审。新的 `IdsSpec.clean`（`ids_whole.clean_patch` 去邻格碎墨）与 `aspect`（宽高比不合弃权）；模板＝人裁格＋vol04–10 已放行格（每册每字 ≤20），字块都是线上同款 char_patch；门槛＝按册留一人裁 0 错且已放行格异议 ≤0.2%，最低 0.4。象彖𧰼 的「象族」形判（象／𧰼）用左半中段 HOG，只在很像象时给象，𧰼 不足 20 例永不自动给。vol04–10 抽样 106 页对 dev：补放 10 格（逐格读上下文，1 格组外字判错，甲申门槛 0.4→0.5 后挡住）、降审 1 格（文意对、字形误报）。大太 未末 王玉 目自 千干 十卜 戊戌戍 木本 不上。`seed_admit` 的 `code_hash` 05f5830d581fee12→f035a1fe19ee8836；新模板库进下一版语料（`repo:` 文件），重跑归 M8。
- 己已巳／日曰 第三轮收口（sheldon 10-22；`doc/research/己已巳日曰日目-送审收口-2026-10-22.md`「第三轮」节）：① 己已巳 `pair`：读序紧挨的两格都进了组 → 前「己」后「巳」（干支，總目参考文本两两相邻 37 处全是己巳），不跑方法；② `ctx_l2.add_review` 放宽：主模型 low/mid/「其他」都可，复核模型 high 的组内字就收，主模型有一遍 high 给了别的字则不收（己已巳 179 格标注上 9 格全对）；③ 日曰 `review_fix_strong`：L2 表答案 strong（`ctx_l2.add_confirm`：另跑一遍 haiku 和 Sonnet 都 high 同字）且字形没明显反对时，复核改掉别的通道按整理本放的字，否则照旧降审（日曰 98 格标注上 haiku＋Sonnet 都 high 同字 66 格错 1）；④ 影子闸不降字组按文意定的字——影子只是挑了同组另一个字时（原来改成曰后被影子降、又被坐标兜底按整理本放回日）。抽样 261 页对 dev：新放行／改字 13 格，逐格核 0 错、0 降审；三组送审（不含遮挡）69→56，其中 strong 标记与放宽复核要新 L2 表推中心库后才生效。PATCH；只有 `seed_admit` 的 `code_hash` 变（cb2434a4a4c41d6e→8a8925fc0ffbd21a）。

## [0.5.7] - 2026-10-21

PATCH（Sheldon 10-22 定发，vol04–10 重跑用）。相对 v0.5.6，`cell_shrink`（1.17）、`row_segment`（1.35）、`seed_admit`（1.21，`code_hash` 85052303fa79a800→bff8f652ceae4de9）三步 `code_hash` 变，**各书 Step3 起判过期**；其余 15 步不变。新增 `qin`／`shan`／`weiw` 三个字组模板库，要在册配置 `group_flow` 点名才生效。

### Added
- 字形判法扩面（sheldon 10-22，#393 方法数组之后）：衛衞 `weiw`、刪删 `shan`、扺抵 `di` 三个异体对上线取框 HOG＋岭回归（`ids_online.SPECS`，`registry` 配 `config/groups/<组>/ids_bank.json`）。模板＝数据集 `labels/unified.jsonl` 里 sheldon 人裁刻形与 `variant/*/crops` 字块（衛41／衞14、刪111／删5、抵90／扺10）；按册留出 0 错：衛衞 37／55 对、刪删 97／116、扺抵 78／100，次形（衞／删／扺）几乎都弃权送人审，不会被放成主形。只补放，需在册配置 group_flow 点名，重跑归 M8。`ids_online` 与 `registry` 变，`seed_admit` 的 `code_hash` 变。建库与评测脚本 `research/m7/glyph_expand/`。
- 禽會俞命舍（`qin`）整字字形组：曾會㑹 里被点「其他」的 14 格多为禽。整字 HOG 一对多，模板＝殿本 vol04–10 放行格（每类 ≤60，曾合愈进库但非组员）＋禽 11 格（sheldon 10-22 已确认），按册留出成员格 150 对／19 弃／0 错（门槛 0.5）。单独成表 `registry.SHAPE_GROUPS`（只进 `FLOW_GROUPS`，不进 `GROUPS`：成员有命舍會 等常用字，进了会改 glyph_match／rare_ref_coord 的全局行为）；`ids_online` 改查 `FLOW_GROUPS`；与 zh 共用「會」（互相声明 overlaps）。需在册配置 group_flow 点名。

### Changed
- 字框收缩 `cell_shrink` 1.18：归属图（`partition_strip`）里跨格界、又不算小部件的连通体，整块归**墨多**的那格（1.17 归伸得深的那格）。vol05 p163 c9「上」断开的底横左段带个钩伸过格界，墨大半在「上」，1.17 却整块分给了「下」（Sheldon 看图指出）。vol05/09 对 1.17 只改这一对格。
- 字框收缩 `cell_shrink` 1.17：整列先算一张归属图，每个墨像素至多归一格（`extractor.partition_strip`）。规则有三条：跨 Step3 折线、或两边都伸过 0.1 格的连通体按格界切开；高不过 0.25 格的小部件整块归离它近的字；其余整块归伸得深的那格。图块只留本格的墨，替掉原先按格界外扩 8% 裁块后的三道逐块清理（`drop_pad_only_components`、`drop_neighbor_parts`、`clip_unions_at_line`，已删）。vol05/09 对 1.16 改 75 格：多为去掉压在格边的邻字碎笔，另有本字越界的笔画补回来（「學」的子钩、「丹」的底横、列末「隱」原先只裁到上半）。
- 字框收缩 `cell_shrink` 1.16：两字粘成一块、跨格界两边都伸过 0.1 格的连通体，按格界切开，各格只留界内的半边（`extractor.clip_unions_at_line`）。原先图块按格界外扩 8% 裁、跨界部件整块保留，两格各带走邻字一截（「家」的竖钩连「之」的点、「左」的底横连「字」的宀）。vol05/09 改 1199/1570 格，多为去掉邻字连过来的笔画，本字越界的笔尖会被切掉几像素。
- 己已巳／日曰／日目 送审收口（`doc/research/己已巳日曰日目-送审收口-2026-10-22.md`）：① 文意 L2 表键容许远处漂移——目标字两侧各 3 字内逐字相同、远处至多差 2 个字位仍用表里的答案（`group_flow_l2_drift`，缺省 2；建表后重跑邻格放行字会变，约 40 格因此整条对不上）；② 共字组联合判——分差内候选单组装不下、装得下「组＋共字组」（日曰目三字紧咬）时也进流程，主组定字后共字组须同意或明说「其他」且 high（`group_flow_joint`，缺省开；目仍是真竞争者，不当陪衬）；③ 己已巳前一字也是族字（干支「己巳」第二字）时不查 L2 表。殿本 vol04–10 抽样 141 页对 dev：新放行 39、复核降审 1，逐格核 0 错；三组送审（不含遮挡）139→101，其中约 20 格靠补跑的 haiku 表，表推中心库后才生效。PATCH；只有 `seed_admit` 的 `code_hash` 变（85052303fa79a800→57ce247a18aaf27c）。
- 己已巳／日曰 第二轮收口（同一文档「第二轮」节）：① L2 表键比对时，本格窗口是「□」而表键有字的位不算差（坐标兜底等组流之后的补放遍会把邻格放进来，按成品建表时有字、组流时是 □；vol09:251「祭統曰春祭曰礿」6 格因此对不上，还漏掉 2 格放错的日）；② L1 规则 `jys-年號己巳`：年號末字＋己（或已／巳）＋◎ → 巳（参考文本 23 处 22 处是巳，另一处是语料讹字）；③ `ctx_l2.add_review`：建表时第二个模型复核，主模型同字只是置信不够、复核模型同字且 high 才收（sheldon 10-22 定；己已巳 104 格人工标注上 0 错），跑批仍只查表。抽样 250 页对 dev：新放行 32、降审 2（都是放错的日），逐格核 0 错；三组送审（不含遮挡）99→69，其中 23 格靠 Sonnet 复核后的 jys 表，表推中心库后才生效。PATCH；只有 `seed_admit` 的 `code_hash` 变（相对合并时的 dev：eeee3347742102a0→bff8f652ceae4de9）。
- 切分与印章三个开关改缺省开，不再逐册设（Sheldon 10-22 定）：`row_segment.layout_prior` 缺省读 `corpus/daizhige/layout_slots.jsonl`，本工作区没有这张表（没有逐列本的书）就当关、不报错；书 yaml 写了别的路径而表不存在照旧报错，写空串＝关。`seed_admit.seal_blank_page`、`lane_seal` 缺省开（殿本十册原本就逐册开着）。殿本 vol01–03 从此也走逐列格位约束：vol02／vol03 p4–40 从原图重跑 Step1–4，逐格全对 329→330、319→330（各 333 列），没有回退列。各册 yaml 里这几行变成多余，留着无害。vol01–03 的 Step3 起参数哈希变，判过期。
- vol07 p44（御製序首叶）抬头框整格被翻成实心黑条，登记 `inverted_rect` 预清理，`precleaned/vol07/44.png` 进仓；原来 Step1 抬头闸量不到第 7 列，「玉」整字丢出列图。配合中心库格位表覆盖（第 1、5、8、9 列出格抬一格，第 6 列从第 1 格起，daizhige 记错），这一页 36/36 列逐格全对。

## [0.5.6] - 2026-10-21

PATCH（sheldon 10-22 定发）。主要内容：印章系统化 1–4 期（新增 Step0 `seal_detect`，切分与遮挡格改读印章定位）、字框收缩 `cell_shrink` 1.10–1.15、字组判法重构成方法数组并新增五个码位归一组、旨㫖整字判法上线、啓啟与教敎模板库重建。相对 v0.5.5，`row_segment`、`cell_shrink`、`seed_admit` 三步 `code_hash` 变，另新增 `seal_detect`，**各书 Step0／Step3 起判过期**；其余 14 步不变。新组（zy sy sz gm xb zhi 及码位归一组 nei bie chu juan wan）要在册配置 `group_flow` 点名才生效；组模板库变了，配套出全局层新底库、各册改钉。rc 上全量测试：3786 过、39 跳过。

### Added
- Step0 印章定位 `seal_detect`（印章系统化第 1 期，用户 10-22 定）：排在 Step1 之前，只读原图，产物 `seals` 列出每页每方印的类别（`stain` 大印＝卷首叶、卷端页的斑驳藏书印；`crisp` 小印＝卷末「乾隆御覽之寶」）、规范空间外框、分数、来源。大印按 150 px 网格的中等墨点密度认（峰值 ≥ 20、近方形，排掉 p2 书签条）；小印用印章模板整页找，分数取「模板笔画处有墨比例 − 空白处有墨比例」，印压正文时也认得出（vol09 p265 原来认不出）。书级 `params.seal_detect.overrides` 可人核整页覆盖。殿本十册 1,707 页认出 26 页（大印 13、小印 13），我逐页看图没发现误报（待 Sheldon 核图定为标准）。这一期只新增产物，别的步还不读它，各书已有产物不过期（新步自己要算一遍）。设计见 Claude Doc「印章系统化设计」。
- 旨㫖（`zhi`）上线整字判法（`groups/ids_online` SPECS、`registry` 配 `config/groups/zhi`）：整字 HOG＋岭回归，模板来自 R2 整册产物对位文字（353 格，sheldon 更正 18 个旨→㫖），按册 5 折留出 margin 0.5 → 348 对／5 弃／0 错。`zhi` 需在册配置 group_flow 点名才生效，重跑归 M8。

### Changed
- 字组判法重构成**方法数组**（sheldon 10-22 定，`groups/methods.py`）：每组在 `FlowSpec.methods` 里登记一串方法，依次试，`combine=first` 遇放行即停、`agree` 全跑须一致；每个方法输出放行字或待定，带 0–1 置信度与留痕。八类：码位归一 `codepoint`（新；配新组 內内 nei、別别 bie、出岀 chu、卷巻 juan、晚晩 wan，单独成表 `CODEPOINT_GROUPS`、不进 `GROUPS`，glyph_match／rare_ref_coord 的全局字组集合不变，要在册配置 `group_flow` 点名才生效）、字频 `freq`、上下文固定匹配 `ctx_rule`、LLM 答案表 `llm`（两者合成子数组 `ctx`）、整字 HOG＋岭回归 `hog`、IDS 部件 `ids`、复合 `composite`（取框→方法，教敎、徵徴）、自定义函数 `custom`（量横、日曰宽高比、入人八分类器、库形最近）。算法与留痕名不变：殿本 vol04 共 65 页、56 组全开，seed_admit 产物与改前逐字节相同；再加五个码位归一组，65 页 9,688 格逐格不变（这批格已被 #372 的码位判等放行）。`seed_admit` 的 `code_hash` 变（`code_deps` 加 `groups.methods`，`flow`／`registry` 改写），其余步不变。
- 字框收缩 `cell_shrink` 1.15：1.13 挪走的跨格界部件，伸进本格超过 0.1 格的不再挪（`NEIGHBOR_PART_DEPTH`）。伸得深的多半是两字粘成一块，整块挪走挖掉了本字的笔画（vol09「兵」「標」「諸」、vol05「荃」「字」「後」，Sheldon 看图指出）。
- 小印压着的字也算遮挡格（印章系统化第 4 期，用户 10-22 定）：`occlusion.page_occluded` 在大印之外，加与小印框重叠 ≥ 0.3 的格，除去盖章空栏候选（格里的墨全在印笔画上）。这些格同大印：Step4 打 `seal_region` 旗，seed_admit 默认整理本字、审核卡归「印章遮挡」组，定字入库闸不建字形库。殿本 10 页小印页：新增 59 格，全在印压字的 vol09 p68／p162／p265、vol10 p87／p175（各 16／5／17／10／10）和 vol07 p134（1 格）；印落在空白处的 4 页不变。PATCH；`cell_shrink` 1.14、`seed_admit` 1.20。
- 字框收缩 `cell_shrink` 1.13：跨格界的连通体若不高于一字、墨至少六成二在格界外、离格外的墨不比格内的远，算邻字越界的笔画，从本格抹掉（`extractor.drop_neighbor_parts`；在上下各多一格的列条里找部件，Step3 选了折线的那条格界不查）。原先跨界的部件两格都留，一格多笔、一格缺笔（「上/下」「宜/賓」「聖/經」）。vol05/09 改 30/34 格，逐张看过，改坏 1 格（vol05 p122 c3「字」丢宀）。
- 切分 `row_segment` 1.34（印章系统化第 3 期）：大印压着列首的列（列首格一半以上在 `seals` 的大印框里）直接取逐列格位表的等距格网（抬头听表、格线就近落缝），不再在几张候选格网里按坏格挑。印泥斑点连着字，劈字、穿字都量不准：闸把列首斑点当抬头字（vol04 p3 c2/c3、vol05 p3 c3、vol10 p88 c1），DP 为躲斑点把格挤歪（vol07 p2 c1、vol09 p70 c1），字整列错一格而格号集合照样对得上。评测 `structcmp` 加「对位」口径（同页同格号的字格高度应一致，偏半格以上记错位），`flipcmp` 一并报，卷端页缺省在内。殿本七册 20 页印章页重跑：大印页错位列 12 → 0，逐格、字数两口径修好 0、改坏 0。PATCH；`row_segment` 的 `code_hash` 变。
- 遮挡格与盖章空栏改读印章定位 `seals`（印章系统化第 2 期之二）：`occlusion.page_occluded`（seed_admit `occluded_gate`、字形库入库闸、Step4 `seal_region` 旗共用的唯一入口）改为「与大印框重叠 ≥ 一半的格」，不再按格算墨点密度；`page_seal_blank` 改用小印框和它的笔画覆盖区（`seal_detect.stroke_mask`），不再在 (830,330) 窗口里找模板。修了两处旧坐标错：旧判据把右上原点的格框直接套在左上原点的原图上，量到的是左右镜像的位置，印正好在页中间才没出事。殿本十页大印页：遮挡格 1,226 → 1,290，新增的非空格 62 个（vol08 p2 印淡，旧判据只认出半方，占 57 格），减少 24 格（印框外的边角）。十页小印页：盖章空栏候选里的非空格减少 9 个（vol09 p162 c4、vol10 p87 c3/c4，都是压在印下的真字「文淵閣著錄」等，旧路径因坐标镜像误入候选），vol07 p134 多 2 个、少 1 个。没有 `seals` 产物的旧产物照旧走原判据。PATCH；`cell_shrink` 1.12、`seed_admit` 1.19，新读 `seals`，`code_hash` 变；`row_segment` 补登记 `seal_detect` 为代码依赖。
- 切分 `row_segment` 1.33（印章系统化第 2 期之一）：列端表空格「落在印里就记空」改读印章定位 `seals` 产物，删掉 `_seal_box`（窗口模板找印）和 `_empty_zone_seal`（表空段墨团）。大印按框量（格与印框重叠 ≥ 一半）；小印按笔画量：格里 ≥ 70% 的墨属于压着印笔画覆盖区的连通块（`_in_seal`），印边只压住一列一小半也认得出。顺带修好旧坐标错：原印框是左上原点、格是右上原点，卷末印正好在页中线附近才一直没出事。殿本七册 20 页印章页 Step3–4 重跑，与 dev 逐列对比：修好 0、改坏 0。PATCH；`row_segment` 的 `code_hash` 变，并新读 `seals`。
- 印章定位 `seal_detect` 1.1：大印外框改按版框定——紧贴版框上边与右边、边长＝版框宽（九列）的正方形（Sheldon 10-22 给的规律），不再用墨点密度区的外接框（偏大）；密度只判有没有大印。这一步因此挪到 `border_detect` 之后（读 `borders`），读不到版框才退回密度框。殿本 13 页大印逐页看图都贴合。小印不变。
- 啓啟（`qik`）整字模板库用 dataset 98 格重建（原 24 格＋R2 整册产物里对位文字与整字判法一致的 74 格）：按册留出门槛 0.5 → 97 对／1 弃／0 错（原 17／7／0）。qik 的 group_flow 指纹变。
- 中心库令牌缺省用读令牌：没设 `GUJI_DATA_TOKEN` 而有 `GUJI_DATA_TOKEN_READ` 时，`import open_guji_cv` 就把前者设成后者（云端 Default 环境只放 `_READ`／`_PROD`／`_EXP`，sheldon 10-21）。拉库、取 R2 字体包／产物包／语言模型不用再手动 export；推送照旧要显式设正式或实验令牌。不碰任何 Step，`code_hash` 不变。
- 字框收缩 `cell_shrink` 1.11：列端框线按全页线位认淡线。同一页各列的框线离版框一样远，先拿全页的实线定线位（`extractor.page_frame_line_offsets`，至少 3 列落在同一处），线位上下 0.04 格高内覆盖 0.1、跨度 0.6、断成至少 3 段的行也算线行——印得淡、断成虚点的框线单看一格认不出（覆盖 0.1–0.6、两头缺点）。压在线位上的字底横是一整笔（列尾「土」「士」），不剥。vol05／vol09 比 1.10 多改 161／248 格，逐格看图改坏 0，格的类型不变。PATCH；`cell_shrink` 版本与 `code_hash` 变，各书 Step4 起判过期。
- 字框收缩 `cell_shrink` 1.10：贴着版框的列尾格、列首格，把格里横贯内容窗口的版框细线（双边框的内框，印得细、常断成虚线）连同线外抹白（`extractor.strip_frame_line`）。原来 `strip_frame_debris`、`carve_end_edge` 剥不掉，殿本列尾字约一成带着一道横线进字块。线只在离格外沿 0.4 格高内找；线外还有成片墨的（「其」「兵」底横下的两点）是字自己的横，跳过；列首格要求线和字之间隔着白行；夹注格不剥。vol05／vol09 改 145／229 格，逐格看图改坏 0，格的类型不变。PATCH；`cell_shrink` 版本与 `code_hash` 变，各书 Step4 起判过期。
- 书级 `codepoints:` 并进 seed_admit 的语义判等（`codepoint_semantic`，缺省开；关掉回旧行为）：巻→卷、别→別、岀→出、晩→晚、內→内 在 `context_vs_ref`、`replace_align`、`match_replace` 等一切「语义同字」比较里按同一个字算，放行字最后落册指定码位；`group_flow` 文意 L2 表的键按码位归一再比（否则邻格新放行会让组内格误降）。起因：此前 `vmap` 不认这些码位对，整理本排异体、刻本与文意都对的格全被 `context_vs_ref` 拦下（殿本 vol04–10 送审里这类 217 格：卷巻 178、別别 33、出岀 4、晚晩 2）。没配 `codepoints` 的册产物不变；参数指纹不变（缺省值不进 dump）。PATCH；`seed_admit` 的 `code_hash` 变（合入 dev 时 5335145caae3→a4f8dc68effc），别的 Step 不变。抽样重跑这类格所在 140 页：新放行 216，降级 0，仍送审 1（被遮挡）。

## [0.5.5] - 2026-10-21

PATCH（Sheldon 10-21 定发）。glyph_match 的 `batch_knn`、`font_tier` 改为缺省开（vol06：glyph_match 959 s → 349 s，送审 142 → 143，两边都放行而字不同的 0 格）。相对 v0.5.4，8 步 `code_hash` 变：`border_detect`、`border_detect_gate`、`column_warp`、`column_gate`、`row_segment`、`cell_shrink`、`glyph_match`、`seed_admit`，**各书 Step1 起全部判过期**；其余 9 步不变。rc 上全量测试：3755 过、9 跳过；修了 8 条随 #366 进来、在有 CNN checkpoint 的机器上失败的测试（#370，只改测试）。

### Changed
- **glyph_match 两个提速开关改为缺省开**（用户 10-21 定，PATCH）：`batch_knn`（整页合批算近邻）与 `font_tier`（分级查库：先查刻本库，命中弱再查整库）。两个都开时两档都合批：刻本库那档每格都查，整库那档按 64 格一块惰性算，块里有命中弱的格才算，两档共用一份查询特征。显式写 `false` 关回去，关时不进参数 dump，参数指纹与 v0.5.4 的缺省相同。**会改产物**：glyph_match 参数指纹与 `code_hash`（4b3ff0e181cdc99d → a0b27c7c2fdaae05，其余 16 步不变）都变，各书 Step5-a 起判过期，下一次重跑整册重算。单开时的证据见 `doc/开关登记表.md`（batch_knn：vol06 1282 s → 367 s、送审 222 → 222；font_tier：粗校基准新增错放 0、送审 413 → 414）；两个同开（vol06 150 页，同一份上游，4 核云端，特征缓存热）：glyph_match 959 s → 349 s，从 glyph_match 到 seed_admit 1048 s → 431 s；`guji products diff` 送审 142 → 143（人审率 0.60% → 0.61%），放行转送审 2 格、送审转放行 1 格，**两边都放行而字不同的 0 格**。另修：库是空的（新书刻本库还没有字）时合批的矩阵乘出错、整页失败，改为逐格判。
- 切分 `row_segment` 1.32：印框的第二个来源——相邻列的表空段（表首字之上、末字之下，整列空的列就是整列）在同一高度都有像字的墨，就把这一团墨的外接框当印框（`_empty_zone_seal`），列端表空格落在里面的记空。补上模板认不出的空心印和模板框没盖住的印边。`_in_seal` 改收印框列表。PATCH；`row_segment` 的 `code_hash` 变。殿本修好 vol09 p68 c5/c6、p265 c4/c5/c6，vol05 p188 c7（另 p3 三列），vol09／05／06 全册改坏 0。
- 格位表 `scripts/dzg_layout.py`：读同目录 `layout_overrides.jsonl`（看原图核过的列，写要改的 slots/notes/half/raised 加 `why`），盖在 daizhige 推出的行上，重生成不丢；评测 `research/dzg_struct_prior/structcmp.py` 的参照同样按它改。首批 4 列（殿本 vol04 p11 c1/c4/c5、p79 c7：daizhige 起始格错一格、漏抬头、把「○」当空格）。代码不动，表变 → 用到这几页的 `row_segment` 产物过期。vol04 第 4 页起错列 3 → 1（另 2 列原来就切对了，错在参照）。
- 闸2 `column_gate` 1.12：页级周期估值偏离书级 `period_prior` 超过 `period_prior_tol`（缺省 10%，0 = 关）时回落先验，记 flag `period_fallback`。殿本正文页估值都在先验 ±5% 内；卷末大印、整页空白的页会被带偏（vol04 p127/128/220 估 89–95，vol05 p188 102，vol09 p69/162/163/224/225 79–127，先验 114–115），Step3 拿错的格高切，抬头格数、格网整列错位。修好 vol04 p127 c3（整列格线错半格）、vol09 p162 c3，表上改坏 0；其余页估值没偏，产物不变。没配 `period_prior` 的书不受影响。PATCH；`column_gate` 的 `code_hash` 与参数指纹变，各书 Step2 闸起判过期。
- 切分 `row_segment` 1.31：列端表空格记空（`_blank_frame_junk`）不再只看字格和單行小注格，被切成雙行小注半格（jiazhu_a/b）的印章墨也记空。PATCH；`row_segment` 的 `code_hash` 变。殿本修好 vol10 p175 c5、vol09 p265 c7，vol09、vol10 全册改坏 0（vol10 第 4 页起已无错列）。
- 切分 `row_segment` 1.30：格位表说只有一半有字（`half`）、判据又认成單行小注的格，按夹注半格发 `jiazhu_a`／`jiazhu_b`（缝取小注左缘，只发墨多的一半），不再发 `jiazhu_solo`。管列里没有雙行段时小写靠右的「臣」之类（1.26 只管列里有雙行段的）。`row_boundaries.segment_column` 的 `half_notes` 参数行为扩大，不传仍不变。PATCH；`row_segment` 与 `column_gate` 的 `code_hash` 变。殿本修好 vol04 p110 c1、vol07 p29 c9，两册全册改坏 0。
- 切分 `row_segment` 1.29：列端表空格里墨只是一两道竖线的格记空（有墨的像素列不到内容宽的 20%，`VLINE_COLS`；印框的边、界行残段）。PATCH；`row_segment` 的 `code_hash` 变。殿本 vol04／05 修好 vol04 p127 c7，改坏 0。
- 教敎（`groups/ids_online`，`jiao`）改用整字左上角一块（左 0–55%、上 0–46%）做 HOG＋岭回归：按册 5 折留出 93 格，门槛 0.4 → 87 对／6 弃／0 错（此前整字／U-Net／自动缝给字格 0 错覆盖 ≤8%）。`config/groups/jiao/ids_bank.json` 用 dataset 93 格重建（教 68／敎 25，含 vol01 四格教→敎更正）。jiao 的 group_flow 指纹变，seed_admit code_hash 变。记录见 `doc/research/形近字组实验记录.md`。

### Added
- `glyph_match.font_tier`（缺省关，GUJI-726）：分级查库，每格先只查刻本库；命中弱才查含字体域的整库，那一格与关着时相同。命中强＝判 same 或「unsure、首选 cov ≥ 0.98、比次优异字高 ≥ 0.03」，且首选字不是字组成员、没有形近对手。vol06 glyph_match 770 s → 606 s、vol05 1022 s → 770 s；粗校基准新增错放 0、送审 413 → 414。会改产物，开不开由 M9 定；关时产物与参数指纹不变（代码等价登记）。
- `guji cellvotes draft|write`（`feedback/web_votes.py`、`cli_cellvotes.py`）：网站精校页投票直接转人裁事件草稿。取票（数据目录快照／`--from-kv` 管理读／文件）→ 去测试票、同格同来源留最新 → 六档映射（与 ai-team `web_opinions.py` 同口径）→ 对正式库最新人裁（一致的跳过、要推翻的挂起）→ 对格位（现行 `cell_shrink` 对出单版 book-text `cord.json`，列被重切过的挂起）→ 「无字」缺省挂起；`write` 走控制台同一条写入路径（带锚、消费、按草稿内容判重）。殿本 vol04 004-r3 的 31 票回放：可写 19、格位对不上 6、无字 6，与 10-21 手工核对一致。不动 Step 模块，各书产物不过期。

### Fixed
- `guji pipeline` 每步一个子进程（`--isolate-steps`，多步时缺省）跑完后，父进程读 manifest 数失败页，有失败页就不自动存包、在 stderr 列出来（原来子进程里有页失败照样返回 0，父进程当全过：10-21 基线重跑 vol08 seed_admit 69 页全失败仍自动存了包）。返回码与单进程连跑一致（不加 `--stop-on-error` 仍是 0）。不动 Step 模块。

## [0.5.4] - 2026-10-20

PATCH（Sheldon 10-21 定发，vol04–10 基线重跑用）。`border_detect`（1.3）、`row_segment`（1.26、1.27）、`column_gate` 与形近字组 `group_flow` 的 `code_hash` 变，**各书 Step1 起全部判过期**。#345 改了 `config/groups/{jue,lih,qik,xu}/ids_bank.json`、新增 `xu/unet.npz`，配套语料库出全局层 b4，殿本 vol04–10 钉子账升 n=12、册 yaml 改钉 `corpus: 12`（v0.5.4 配 `corpus: 11` 会 CorpusDrift 拒跑）。
验收（rc 上）：全量测试 3709 过、14 跳过；修了 1 条随 #345 过时的测试（`test_repo_by_form_banks_load`：整字组不再要求 `by_form`）。

### Changed
- 边框探测 `border_detect` 1.4：抬头框加字凸出判据（`border_geometry._raised_text_top`，`detect_head_raise(text_rule=True)` 缺省开）。有的抬头框只印了粗外框、没有内细线，有的连顶线都没有，横线判据找不到，抬头字落在列图外。现在前面都没认下的列，主上边框上方 [btop−130, btop−45] 一段先去掉整段有墨的竖条（墙线），再按行看：像字的行（墨占比 0.1~0.6）占四成以上，并且至少一侧界行外 70px 内有墙线（覆盖 ≥ 0.5），就算抬头，inner_y 取抬头字上沿往上 8px。墙线这一道挡「上諭」那种字紧贴笔直版框的页。殿本 vol04／06／07 全部 506 页，只有预期的 6 列变（vol04 p65 c8、p84 c5、p11 c5，vol06 p58 c6，vol07 p46 c7、p77 c2）。Step1–4 重跑修好 4 列（vol04 p65 c8、p84 c5，vol06 p58 c6，vol07 p77 c2），改坏 0。PATCH；`border_detect` 的 `code_hash` 变，各书 Step1 起判过期。
- 切分 `row_segment` 1.28：印框记空挪进候选格网打分之前，跟框线碎墨一起「先记空再打分」（`_blank_frame_junk` 加 `in_seal` 判据；原来选完格网才记空的 `_blank_seal_cells` 删掉）。印框里列端表空格是單行小注格的也记空。印框查找抽成 `occlusion.find_seal_box`（`seal_blank_cells` 照用，输出不变）。PATCH；`row_segment` 与 `seed_admit`（`code_deps` 含 `occlusion`）的 `code_hash` 变。殿本 vol04／05／09 对旧产物修好 13 列、改坏 0（vol04 p130 页首噪点 5 列、p35、p191、p3 五列，vol09 p68 c7；对比基线里有些页不是最新代码出的，修好数偏高）。
- 形近字 IDS 路按组换法（`groups/ids_online`、`ids_unet`）：叙敘 用左右向 U-Net 一条折线切线（`config/groups/xu/unet.npz`，留出册覆盖 33%→87%）；絕絶、厯歴、啓啟 改整字岭回归；冊册 踢出 IDS 路（SPECS 删 `ce`）；教敎 不变。实验记录见 `doc/research/形近字组实验记录.md`。xu/jue/lih/qik 的 group_flow 指纹变。

### Fixed
- `glyphdb_admit` 取图前查绑定（规范 §9 F-10）：补消费积压时重切后格号顺移的按现格取字块，绑定判不该采信的不进库（计 `unbound`）。实时消费不受影响；不在任何 Step 的 `code_deps` 里，各书产物不过期。

### Added
- 字形库按版本钉（GUJI-727，设计 `doc/design/字形库按版本钉-细设计.md`）：`guji glyph-db snapshot` 出只读快照 g<N>（清单随 `config/` 进中心库、一个号只写一次，文本随 push 按 sha 进 R2），册 yaml `glyph_pin: N` 有快照时本册读字形库的步改用 `output/glyph-g<N>.db`、字形库指纹换成快照内容哈希；`pin-build`／`pin-list`／`pin-verify`／`snapshot-upload`，`db pull/sync` 与 `pipeline` 起跑前自动建库。没钉的册、钉了号没快照的册行为与指纹逐位不变；**17 步 `code_hash` 全部不变**。
- `scripts/zhengli/republish.py from-pack`：取别人跑好的产物包直接重发待审单，不重跑任何 Step——拉库、取包、按锚框核人裁绑定（包后新到的、按格号扣会扣错的、绑不上的都列进差异单「人裁合并」）、导出（文本版本读 book-text 线上值，单子头记包的 cv 版本）、prep，vol05 实测一条命令 4 分钟。`push --book-text` 顺带把同一次导出拷进 book-text、文本线升 minor、本地校验后提交到新分支；收尾提示请网站总管按顺序手动跑文本与待审单两段发布（每日定时里待审单比文本早 20 分钟）。不在任何 `code_deps` 里，各书产物不过期。
  - 后续修两处（vol04–10 实跑发现）：from-pack 自己设 `GUJI_WORKSPACE`（之前没设时人裁绑定读到 0 条）；原格号上有人裁、但人裁绑到别处或绑不上的格不再被 `pending_route` 按格号扣掉（新参数 `--keep`），照旧留在单上。
- `feedback/migrate_dedupe.py`：删整轮重发的人裁事件副本（规范 §9 M-3，原 O-8），记账、补锚档、金标 `source_events` 跟着改，带核对与 `gold rebuild` 比对；10-21 已写中心库（殿本 3,638 条、北行 76 条）。不动 Step 模块，各书产物不过期。

### Changed
- `guji pipeline` 整册（`--pages all`）从头跑到尾、没有失败页时，**缺省自动把产物打包存进 R2**（`products pack push`，标签 `<版本三段>-full`，不标 main；sheldon 10-21：免得忘）。`--no-pack` 或 `GUJI_AUTO_PACK=0` 关；没设 `GUJI_DATA_TOKEN`、存失败只提醒，不改返回码。不碰任何 Step，`code_hash` 不变。
- 边框探测 `border_detect` 1.3：抬头框向邻列延伸（`utils.border_geometry._extend_head_raise`，`detect_head_raise(extend=True)` 缺省开）。已认下的抬头列，邻列在同一高度（±18px）有淡一些的细锐线（墨占比 ≥ 0.12，够不上原来的 0.35）、线下有抬头字的墨（≥ 一半行）就并进同一个抬头块，再照旧过墙线判据。管内边框印得淡、被抬头字压着的列：原来这一列按普通列取窗，抬头字整个落在列图外。PATCH；`border_detect` 的 `code_hash` 变，**各书 Step1 起全部判过期**（Sheldon 10-21：过期不是顾虑），只有抬头框变了的页输出变。殿本 vol04／07／09 全部 621 页里 4 页的抬头框变了，Step1–4 重跑修好 4 列（vol04 p9 c8、vol07 p44 c8、vol09 p109 c5/c6），改坏 0（vol09 p106 c7 并进抬头块，切分不变）。
- 切分 `row_segment` 1.27：印框记空门槛 NCC 0.35 → 0.30（非印页实测最高 0.282；这里只动表说该空的列端格）。vol10 p175 修好 2 列；vol10、vol07 全册改坏 0。
- 切分 `row_segment` 1.26：`layout_prior` 加两处。格位表说只有一半有字的夹注格（`half`，如「無巡卷撫數採進」里的行内空格、段尾奇数字），列里有雙行段时按段缝（各段格缝的中位数）拆、只发墨多的那一半（`row_boundaries.segment_column` 新参数 `half_notes`，缺省 None 不变）。PATCH；`row_segment` 与 `column_gate`（`code_deps` 含 `utils.row_boundaries`，闸不传这个参数、输出不变）的 `code_hash` 变。殿本对 1.25：vol06 第 9/32/37/63 页、vol08 p46 修好 5 列，vol05 全册修好 3 列、改坏 0，vol09 全册不变。
  - 印框记空：模板（`config/seal_templates/`，「乾隆御覽之寶」）命中的印框里、表说该空的列端格记空（`steps.occlusion.seal_blank_cells`，NCC ≥ 0.35、重叠 ≥ 一半；进 `code_deps`）。管篆文刻得清楚、墨连成笔画的大印，碎墨判据认不出这种。vol05 p188、vol06 p149、vol09 p162、vol10 p87 修好 9 列；vol05、vol10 全册改坏 0。
- 跑批、冷启动再提速（GUJI-647 后续，PATCH；**17 步 `code_hash` 全部不变、产物逐字节不变**，改的都是引擎、登记表与不在任何 `code_deps` 里的模块）：
  - 页级并行新登记 6 步（`core/parallel.py`）：`column_warp`、`border_detect_gate`、`column_gate`、`row_segment_gate`、`align_ref`、`context_decide`（后两步 `warm_first`）。vol06 150 页串行／4 进程：8 步产物逐页 sha 相同，`column_raw`／`column_image` 各 1332 张列图逐张相同。`context_decide` 开了 `enable_online_llm` 时退回串行（新字段 `ParallelAudit.serial_when`）。
  - 跑一步期间每步参数只构造一次（`Engine._run_one_step` 与 `RunContext._params_memo`，并行 worker 每进程一次）：参数构造时要对 glyph.db 算人裁、库指纹，原来逐页在指纹、落盘、run_page 里各算一遍，vol06 seed_admit 主进程 600 多次。seed_admit 整册 185 s → 79 s，150 页产物与 manifest（指纹、参数哈希、上游）逐项相同。
  - `glyph-db rebuild` 补放人裁：遮挡查询（`feedback.consumers._occluded_lookup`）在一次 `glyphdb_admit` 里按册只解析一次 seed_admit 参数（原来逐页解析，补放 1180 条人裁、711 页占 95%）：补放 139 s → 25 s（剖析下），14 张表、补放报告、消费记账逐项相同。
  - `fold_compat`（`utils/cjk_compat`）只换正则扫到的兼容区段字符：整部语料有一个兼容字时原来逐字进 Python，align_ref 起跑折语料 4.5 s → 0.05 s，2 万条随机串与两部整理本逐字相同。
  - `guji db pull`：重建 glyph.db 的派生表示按 CPU 数多进程（同 `glyph-db rebuild`，原来单进程）；取图（R2）与向库要文本行同时跑；读令牌先问 `whoami`，不再白打一个注定存不上的快照包（约 9 s）。
  - 冷启动端到端第二轮（vol06 150 页，空数据目录、空图缓存、空缓存、空产物，4 核云端）：`db pull` 211 s（上轮图缓存是热的）→ 166 s（图全冷），`glyph-db rebuild` 133 s → 55 s，Step0–7 2028 s → 1878 s（seed_admit 185 → 99、column_warp 62 → 21、三道闸合计 62 → 35），close-check 35 s；合计约 41 分 → 36 分。

## [0.5.3] - 2026-10-20

PATCH（Sheldon 10-21 定发）。`row_segment`（1.23 → 1.25，新增 `code_deps` `utils.row_grid`）与 `column_gate`（`code_deps` 含 `utils.row_boundaries`，只加了缺省不走的格网入口，闸的输出不变）的 `code_hash` 变，各册 column_gate 与 Step3 起判过期；只有开了 `layout_prior`、命中格位表的页（殿本 vol04–10）输出变，别的书逐字节不变。

### Changed
- 切分 `row_segment` 1.25：`layout_prior` 列端表空格里的墨大多连不成笔画（落在面积 > 150 像素连通块里的不到 75%：印章的印泥斑点、篆文残笔）也记空。PATCH；`row_segment` 的 `code_hash` 变，各册 Step3 起判过期。殿本 vol04–10 全部页 10,620 列对 1.24 逐格 99.03% → 99.51%，修好 51 列、改坏 0（第 4 页起 99.33% → 99.55%，修好 23）；修的是各册首叶（p2/p3 藏书印）和卷端大印（vol04 p130、vol09 p70/p164、vol10 p88）。
- 切分 `row_segment` 1.24：逐列格位约束 `layout_prior` 加三处（只作用于命中格位表的页；开关关着、或没有表的书逐字节不变）。PATCH；`row_segment` 的 `code_hash` 变（新增 `code_deps` `utils.row_grid`，`utils.row_boundaries` 加了不跑 DP 的格网入口），各册 Step3 起判过期。殿本 vol04–10（第 4 页起 10,521 列）对 1.23 逐格 99.03% → 99.33%，修好 32 列、改坏 0；穿字格线七册合计 6061 → 5941。
  - 等距格网（`utils/row_grid`，用户 10-21：殿本正文每列严格 21 格、格高相近）作候选格网：格号按行墨投影的周期相位排，格线在 ±0.2 格内就近落缝。修列首印章、墨损处 DP 多切一格、整列格号错位（vol04 p6 c2、p8 c2/c4/c8，vol06 p33 c4）。
  - 各候选格网先把列端表空格里不像字的墨记空，再打分。
  - 不像字加「越过界行」（印章、墨污：墨伸到列的左右边上）；一页最后一列表行之后的列按整列空处理（卷末印章空列）。

## [0.5.2] - 2026-10-21

PATCH（sheldon 10-21 定发）。相对 v0.5.1 只有 `seed_admit` 的 `code_hash` 变（c1cc30263b355ed5 → e3566f98f5046f0d），其余 16 步不变。配套语料库（分层版本 P3 起）：全局层 b3（含 #332 的彝组模板库与 U-Net 权重）＋殿本书库 v10，十册钉子账 n=11、册 yaml 改钉 `corpus: 11`，`group_flow` 点名 `lv`、`zheng`（中心库 corpus-base rev 34273、siku-zongmu rev 34313）。**v0.5.1 配 `corpus: 9` 会因 `yi_560/ids_bank.json` 与 v9 清单不符被起跑校验拒跑**，各册重跑请用 v0.5.2。
验收（rc 上）：殿本 vol05–07 共 141 页 seed_admit，对 v0.5.1＋语料库 v9，送审 205 → 205、逐格无变化；全量测试 3695 过、38 跳过，1 失败 1 错误在 dev 上同样存在（`test_pagetype_model::test_model_roundtrip_and_gate_abstain`、`test_datastore_expbranch` 缺 PG）。

### Changed
- 彝组 `yi_560` 改走 U-Net 切三段（#332，`groups/ids_unet.py`，纯 numpy 推理，权重 `config/groups/yi_560/unet.npz` 1.0 MB；窗口法退为后备），模板库按 U-Net 切分重建。按册留出（超参也只在训练册选）82 格：79 对／2 弃权／1 错，窗口法同口径错 5。`seed_admit` 的 `code_hash` 变（38f5371fe3279014）。

### Fixed
- 中心库不再收人裁写锁 `*.write.lock`（空文件，曾被推进殿本、北行的 `files` 表，10-21 已从库里删掉）。

### Added
- 粗校基准（M9 D6-5，GUJI-669）：`open_guji_cv/exp/rough_bench.py`、`scripts/rough_bench.py build`（冻结页＋标签进测试集仓 `rough-bench/`）、`scripts/eval_rough_bench.py`（登记为 `guji eval run rough_bench`）。在各册 main 快照上用 `guji exp` 重跑 seed_admit（或从 `--from` 起），报正文送审率和有标签格的错放；有变体时**新增错放必须为 0**。人裁按绑定表对到快照切分，看图结论只收现行字＝当时显示字的格。不碰任何 Step，`code_hash` 不变。
- `scripts/zhengli/wave_report.py`（M9 D6-6，GUJI-670）：一波各册待审格按主成因码汇总，出成因分布、派单（按交给谁，列最常见的字对／字组码）、与上一波比的增减、粗校基准结果、下一波目标（`wave.json` + `wave.md`，贴 Jira）。只读产物。

### Changed
- 人裁事件规范 §9 F-6／F-7／F-8（原 O-1／O-6／O-7）：`guji db sync` 合并同批次撞号时本地新行顺延重编、本地记账等引用跟着改；`guji db import` 导完自动对导入的事件 route（`--no-route` 关）；`guji events lint` 新增 `W-unconsumed`；刻例库升格记账改写到 `feedback/promote.jsonl`，`migrate_v1` 能把旧的挪过去。不动任何 Step 的 code_hash。
- `guji exp`：`pages` 可以按册给（`{vol05: [3, 9], …}`）；`human_events` 标签读 `feedback/events/` 下全部文件、按 `target.book` 筛（原来只读 `<册>-*.jsonl`，H 道 `H-M7-…` 这类批名的人裁全漏了，vol04–10 只认出 1 条）；金标标签认 `expected.wrong`（只知道不是哪些字）。

## [0.5.1] - 2026-10-21

PATCH（sheldon 10-21 定发）。相对 v0.5.0，17 步 `code_hash` 全部不变（rc 上与 v0.5.0 逐步比对）。

### Added
- 语料库分层版本（#317，PATCH；**缺省不影响现有册**：没有钉子账的册，`corpus: N` 与指纹 `corpus-vN` 逐位不变，17 步 `code_hash` 不变）：语料库分全局（底库 b）／整套书（书库 v）／册 三层各一个整数版本；`guji corpus pin [--dev]`、`release`、`build/verify --vol`、`upload/fetch`；册有钉子账后指纹取清单内容哈希、不含版本号；册 yaml `corpus_dev: true` 开发中跳过清单校验（带它的册配置不许 `db push`）；≥1MB 的文本文件清单标 `store: r2`，内容按哈希存 R2。提示词模板占位符渲染 `groups/prompt_template.py`（不动 `ctx_l2`）。设计与 P3 迁移步骤见 `doc/design/语料库分层版本.md`。
- glyph_match 开关 `batch_knn`（GUJI-647 第 7 项，PATCH；**缺省关**，关着时产物与参数指纹逐字节不变）：一页的格每 64 个做一次「查询 × 整库」矩阵乘，库矩阵每 64 格才读一遍。库含字体域（17.4 万条、1.2 GB）时逐格算卡在内存带宽，vol06 全册 glyph_match 1282 s → 367 s。**会改产物**：浮点末位不同，vol06 23,517 格判决、字、cov 全同，8 格候选排序变；`guji products diff` 送审 222 → 222、变了的列 0。开不开按 M9 波次窗口定：书级 `params: {glyph_match: {batch_knn: true}}`。
- `guji audit changes <册> --base <上一基线产物根>`（M9 D5，GUJI-664）：列出新放行、放行字变了的格（`放行变化.md／json`）；zl.py 设 `ZL_BASE_PRODUCTS` 后这些格进联系页，看图闸要每格都有结论才过。联系页另存单格图与 `tiles.json`。
- `scripts/zhengli/vision_ask.py`（GUJI-665）：联系页每格交外部视觉模型看，`merge` 两家一致才算、不一致记看不清，`score` 对参照计分。智谱免费模型在 vol06 上误判太多（负结果，见 `doc/research/M9-粗校调研/E-…`），不默认接入。
- `guji audit reasons <册>`（M9 D6，GUJI-668）：每个待审格打一个主成因码（`review/causes.py`：A1–A9 切分／对位、B 码位异体、C 形近字组、D 遮挡、E 与整理本冲突、F 库缺字、G 对齐改字、H 库＝整理本仍被拦、I 证据不足），出 `reasons.json`／`reasons.md`（按码写交给谁）。`republish.py` 把码并进待审单的 `cause`、台账记 `reasons.cause`；`cls` 不动。vol06 175 格里「证据不足」8%。只读产物，不碰任何 Step。

### Changed
- 冷启动、内存、出口检查提速（GUJI-647，PATCH；**17 步 `code_hash` 全部不变**：`glyph_match`、`match`、`seeding` 的改动在 vol06 30 页、库含字体域时与改前逐字节相同，已登记代码等价）：
  - 字体域预建件（`clustering/font_pack.py`）：`glyph-db import-font` 先找同一套字体文件、字表、渲染代码出过的字体域（本机 `cache/fontdb/` 或 R2 `derived/fontdb/`，读令牌就够），整表拷进 glyph.db，与逐字渲染逐列相同、字体域指纹相同。两套 15.5 万字：渲染 12.6 分钟 → 拷表 43 秒（加下载约 1.8 GB）。从 R2 取来的包导完即删。推送手动：`glyph-db font-pack-push`（正式令牌）。`--no-pack` 强制渲染。
  - R2 通道（`datastore.packs.push_file`／`fetch_file`）改流式、可选 gzip，取时 8 段并发（实测单路 11 MB/s、8 路 44 MB/s）；旧 manifest 照认。
  - glyph_match 匹配器特征按内容缓存（`seeding._matcher_arrays`，`cache/glyph_feats/`）：字体域进库后库有 17.4 万条，每个进程建匹配器原要约 2 分钟（逐条解 PNG、算 HOG），命中缓存 2.4 秒；整库特征矩阵只存一份（原来列表一份、堆起来又一份），建库峰值 4.5 GB → 2.1 GB，命中时走 mmap、多进程共享页缓存。`GUJI_MATCHER_FEAT_CACHE=0` 关。
  - glyph_match 登记 `warm_first`：主进程建一次匹配器，fork 后共享。改前 dev 上库含字体域时 `--jobs 4` 四个 worker 各建一份（各约 3.5 GB），被 OOM 杀。
  - `guji pipeline` 跑多步时缺省每步一个子进程（`--isolate-steps`；`--no-isolate-steps` 退回单进程，`--json` 时不隔离）：vol06 单进程连跑到 seed_admit 主进程 3.5 GB，隔离后 seed_admit 1.95 GB、context_decide 1.48 GB。
  - 页级并行的内存登记：glyph_match 3.6 → 1.5 GB（warm_first 与特征缓存之后 worker 不再自建匹配器；vol06 冷启动主进程峰值 2.2 GB、主进程加 4 个 worker 合计 PSS 2.6 GB；按 3.6 算 13 GB 的容器只开得出 2 个进程），seed_admit 3.0 → 2.0 GB（实测主进程 1.95 GB、4 进程合计 PSS 3.3 GB）。
  - `glyph-db rebuild` 派生表示（归一、骨架、HOG）多进程算（`--jobs`，缺省 CPU 数），主进程按原顺序写库，14 张表与单进程逐行相同：殿本 1.85 万例 163 s → 38 s，整条命令连补放人裁 265 s → 133 s。`import-font` 的 `--jobs` 缺省仍是 1。
  - `close-check` 1a／`guji status`：一次 `status()` 里每步的参数只构造一次（构造时要对 glyph.db 算库指纹，库含字体域时 3 GB；原来逐页逐步现算）。vol06 close-check 粗校档 126 s → 31.5 s，各项结论逐行相同。
  - `guji cache verify`／`close-check` 1b：戳与现行产物对得上的页免查（引擎重跑一页先清再写、读时戳不对整页作废，这类缓存一定是这一代切的）。vol06 150 页 1.4 秒（原约 5 分钟）；`--full` 照旧全查。

### Fixed
- **seed_admit 并行时影子模型极慢（#255 引入，0.4.9、0.5.0 受影响）**：开了 `shadow_veto` 的册（vol05、vol09 等），影子模型（scikit-learn HistGradientBoosting）predict 用 sklearn 自带的 OpenMP，主进程暖机时按核数建好线程池，fork 出的 4 个 worker 各开 4 线程、16 线程抢 4 核，每页从几秒拖到约 700 s（vol09 实测）。worker 里用 threadpoolctl 把已加载的 OpenMP 运行库压到每 worker 线程数；vol09 20 页 4 进程 63 s、串行 102 s，产物逐页相同。产物从来不受影响，只是慢。
- 缓存页戳会把老缓存「洗白」（GUJI-647）：一页没戳、目录里却有记戳机制之前的老图时，惰性补一张新图（或 `cache warm` 收尾补戳）会给整页记上戳，`cache verify` 从此跳过它。现在这类页不记戳，留给内容校验。
- `--isolate-steps` 下某一步崩了（异常、护栏拒跑）父进程照样接着跑下游、最后返回 0；现在停在那一步、返回它的返回码。控制台取消工单（只 terminate 父进程）时把 SIGTERM 转给正在跑的那一步，不留孤儿接着写产物。

## [0.5.0] - 2026-10-20

MINOR（sheldon 10-20 定发 v0.5.0）。相对 v0.4.9 只有 `row_segment`（d5f4ceedcfbd2d06 → 89ea9a967e3dd407）、`cell_shrink`（17162d9e3ed6047f → f9206af1e771f0e5）、`seed_admit`（3337e7b0b2dc43ec → c1cc30263b355ed5）的 `code_hash` 变，其余 14 步不变；各册 Step3 起判过期。rc 上全量测试 3632 过、32 跳过，2 条失败在 v0.4.9 上同样失败（`test_cut_select::test_ckpt_fingerprint_empty_for_missing_file` 缺检查点，`test_datastore_workcopy::test_corpus_adopt_push_and_pull`）。

### Added
- 人裁事件规范 v1（#300，GUJI 人裁事件格式调研）：`doc/formats/人裁事件规范.md` 与 `formats/guji_feedback_event_v1.schema.json`；`guji events lint -w <工作区>` 按规范只读体检。全部「后到覆盖」统一按 `replay_key=(ts, batch, seq)`（`gold rebuild`、`route_and_consume`、`EventLog.resolve/pending`、`label_batches`、`vision` 重建、复核冲突、事件列表此前按批次名序，殿本 351 个单位、北行 11 个两种顺序取到的最终裁决不同，下次 `gold rebuild` 会按时间序改正）；`EventTarget` 从 key 补全空的 `book/page/col/slot`；`resolve(kinds=, unit=)`；控制台写入把秒级 `client_ts` 归一毫秒。PATCH；不在任何 Step 的 `code_deps` 里，17 步 `code_hash` 不变。
- 人裁事件历史遗留迁成现行格式（#321）：`python -m open_guji_cv.feedback.migrate_v1 --ws <工作区> [--apply]`（撞号／错文件、旧 id、空 target 字段、秒级 client_ts、`product_key` 两种形状；连带改 consumed、金标 `source_events`、补锚档；核对重放顺序与 `gold rebuild` 不变）；`datastore.importer.import_scans(only_paths=)` 只差分点名的文件。锚里切分产物的 sha 改写进 `anchor.cells_sha`，`product_key` 只留 `{step, key, fingerprint}`；lint 新增 `E-key-empty`、`E-product-key`，`E-id-shape`／`E-batch-file`／`E-client-ts-sec` 升为错误。中心库 10-21 已迁（殿本 import 118、北行 import 119）。PATCH；17 步 `code_hash` 不变。
- `scripts/check_release_tags.py`：发版后核对每个发进 main 的版本都有 `vX.Y.Z` tag、且 tag 在 main 主线的发版合并提交上（用户 10-20 定「打了 tag 才算发完」，写进 `doc/版本号规矩.md` 第三节第 5、9、10 条）。PATCH；不碰任何 Step，`code_hash` 不变。
- 字组：呂吕、徵徴 走在线 IDS 的「整字岭回归」判法（`groups/ids_whole.py`，`ids_online.IdsSpec.whole`；组 id lv、zheng）。按字分类（`by_form`）切缝比不了这两对（呂吕 差在中间连笔，徵徴 差在字中上部细节），改整字裁外框归一后二类岭回归（呂吕 取像素，徵徴 取字块中上部 HOG），判别值不够弃权。模板＝殿本 vol01–10 人裁事件格，建库与按册留一评测 `research/m7/lane1/build_whole_bank.py`。按册留一：徵徴 |d|≥0.6 → 38 对／37 弃权／0 错；呂吕 |d|≥0.5 → 62 对／8 弃权／0 错（vol07:4:4:21 按 sheldon 复看更正为呂）。PATCH；只有 seed_admit 的 `code_hash` 变（d277e5d75f708d82 → d8e0c8279a4419c2）。要在册配置 `group_flow` 点名才生效，字频表／册配置由收口线程改。

### Changed
- 切分 `row_segment` 1.23、`cell_shrink` 1.9：逐列格位约束 `layout_prior` 三处结构化改动（只作用于命中格位表的列；开关关着、或没有表的书逐字节不变）。PATCH；只有 row_segment（d5f4ceedcfbd2d06 → 89ea9a967e3dd407）、cell_shrink（17162d9e3ed6047f → f9206af1e771f0e5）的 `code_hash` 变，各册 Step3 起判过期。殿本 vol04–10（第 4 页起 10,521 列，对 v0.4.9 现行 main）逐格 98.79% → 99.03%，修好 27 列、改坏 1 列（vol09 p162 c3 卷末小计列，看图新切法更好，金标口径多一格）。
  - 候选格网统一打分：表格网、闸抬头格网（抬头级数表与闸不一致时）、无先验格网（前两者都劈了字、且不看表切出的字比表少时）按「坏格数＝劈开的字＋违表的格 → 劈字数 → 穿字格线」取最小。新增劈字判据 `_split_chars`（一个连通体被格线劈成两段、两段各占三成以上）。修 vol06 p94 c6 列首「二」被单切一格后丢失、vol07 p44 c8「年」被劈。
  - 列端框线残渣记空的范围从「物理首／末格」放宽到「表的首字之前、末字之后那一段表空格」，判据不变（首字上方隔一格的碎墨、斜笔残迹）。
  - Step3 给表认下的字格记 `layout_char`；Step4 列端渣格闸遇到这种格、且格里有成笔的墨时不判渣（列尾「一」被判 tail_junk，vol05–10 共 16 列）。白纸照样判空。
- 请审单（`guji audit sheet`）第 4 节按已导入的看图结论自动填「看图判错、人还没裁」的格，新增第 5 节「看不清」；原来要会话手工追加。不碰任何 Step，`code_hash` 不变（M9，GUJI-653）。
- `scripts/zhengli/zl.py`（M9 基线跑 vol06 整册后，GUJI-653／654）：新增 `db`（拉中心库）、`pending`（待审单草稿，只给 2c 核数、不上线）两步；书 yaml 改从数据目录 `books/` 找；稀疏克隆按 `<书目录>/data_full/<丛编>/<册>/` 取本册原图；BrokenProcessPool 归「疑似内存不足」，前台、后台都减半并行续跑；缓存只在校验报错时 `--fix`；导出不再缺省 `--text-version 0.1.0`，要 `ZL_TEXT_VERSION`；`close` 改跑粗校档 `--tier rough`，出 R1–R5 报告、2d 列交代草稿，剩下的活写 NEXT.md。`collect_exit.py` 加 `--close-check-json` 复用已跑的体检（省一遍约 5 分钟）。
- 新增 `scripts/zhengli/republish.py`（GUJI-680 第一步）：一册重跑后重发待审单。`prep` 按现行产物出新单（audit alt → pending_list → pending_route 扣已人裁 → 雪碧图），rev 按线上单自动加一，出差异单（去掉的格按「人裁过／机器放行了／格号没了」分，列出旧 rev 上的网站精校票）；`push --yes` 才写进数据目录并记台账，`--sync` 再推中心库。不碰任何 Step。

### Fixed
- 语料库清单不再收字组 `config/groups/*/prompt.md`（只给离线 L2 拼消息，Step 不读）；老清单里登记了的也跳过核对。此前改提示词（cc6f455f）会让钉了 corpus 的册在 glyph_match 起跑前报 CorpusDrift 拒跑（M9 基线跑 vol06 撞上，GUJI-636；PATCH，各步 code_hash 不变）。
- 并行限流按容器内存算：可用内存取 /proc/meminfo 与 cgroup 上限（减去已用、不算页缓存）中小的；glyph_match 单进程登记从 1 GB 改为 3.6 GB（导了字体域后 vol06 实测 3.4–3.7 GB，原登记让 4 进程在 14.3 GB 容器里被 OOM 杀）。只改进程数，产物与 code_hash 不变（M9 基线，GUJI-636）。

## [0.4.9] - 2026-10-20

PATCH（sheldon 10-20 定）。相对 v0.4.8 只有 `rare_candidates`（8d081ec338766152 → b92a99fa13957185）、`seed_admit`（19fbae2631200652 → 3337e7b0b2dc43ec）的 `code_hash` 变，其余 15 步不变。配套语料库：殿本 v9（日曰、入人八文意表按提示词 v2 重建，覆盖 vol01、vol04–10；`group_flow` 点名彝组 `yi_560`）——v9 清单登记了新提示词，旧版 CV 配 v9 会被语料钉拒跑，换版要同时改钉。
验收（rc 上，殿本 vol05–07 共 141 页 seed_admit，对 v0.4.8＋语料库 v7）：送审 223→205；新放行 19 格（日曰 15、彝 4）逐格核对全对；新送审 1 格（vol07:102:9:21「五事一曰貌至五曰」，v0.4.8 误放「日」，现被文意表拦下）；随机抽的 60 页无变化。

### Added
- 字组：第四批只看字频的异体组 爲為 說説（wei shuo；殿本人裁只见一形，≥10 且来自 ≥2 册）。PATCH；只有 seed_admit 的 `code_hash` 变。要在册配置 `group_flow` 点名才生效。
- `guji opinions publish-status`（M11 B2，GUJI-714；PATCH）：意见池里网站来源（改字、一段有问题）的处理结论按网站 target 聚合，写中心库 `feedback/lists/web/<书>/status.jsonl`（已进文本→adopted＋版本、已采纳→adopted、未采纳→rejected＋公开理由、交用户／讨论→discussing；精校票不发），幂等；网站 proofing-sync 读它回写 `/api/fixes`。顺手修回复草稿把模板句与公开理由叠在一起的毛病（GUJI-713）。不碰任何 Step，`code_hash` 不变。
- 控制台「相似字」字形图下的小标签：扩 B 以后、私用区的字改显示码位 `U+XXXXX`（悬停看原字），两套字体都渲染不出字形图时同样显示码位（`reviewClass.zhLabel`，用户 10-20）。控制台不带网页字体，原来这些字在阅审人电脑上多半是方框；字形图本身照旧由后端用 I.Ming／Jigmo 渲染。不碰任何 Step，`code_hash` 不变。
- M11 第一阶段：意见池、AI 初判的确定性部分、修订工具（GUJI-712／713／715，设计 `doc/design/M11-分块-第一阶段最小闭环.md`）。新包 `open_guji_cv/opinions/`（L4）与 `guji opinions …`：`ingest`（中心库 `feedback/lists/web/<书>/` 的改字／精校票、网站公开读 `/api/fixes`、`/api/feedback` 文字类 → 中心库 `feedback/lists/opinions/<书>/`，幂等，去测试票、记重复与转出）、`list`／`show`、`versions`（book-text CHANGES → `text_versions.json`）、`locate`、`normalize`、`pack`（IIIF 原图档裁格与列条带、上下文、marks，`sheet.png`／`sheet.md`）、`triage`（会话判、`config/opinions/rules.json` 定去向）、`to-user`／`decide`、`revise`（A／B／B′ 类改 book-text 冻结册 char／cord，伴生层跟随，调 `bump_original.py` 升 patch，CHANGES 引意见 id）、`reply-drafts`。PATCH；不碰任何 Step，17 步与闸 `code_hash` 不变。
- M10 小件（#286，v0.4.8 发版后直接合进了 main，dev 已含）：`resolved_manual_cells` 遇坏行改为逐行读、跳过并在 stderr 报出（原来一行坏整片静默退回自动切分），新增 `scripts/zhengli/check_manual_cells.py`（GUJI-692）；公众意见台账 `scripts/zhengli/opinion_ledger.py`（GUJI-690）；runbook S25「1.0 之后的修订」（GUJI-696）。`lookup.py` 不在任何 Step 的 `code_deps` 里，`code_hash` 不变。

### Changed
- 管线提速（#255，PATCH；产物逐字节不变，**只有 rare_candidates、seed_admit 的 `code_hash` 变了**，其余 15 步不变）：
  - 页级并行：`row_segment`、`cell_shrink`、`glyph_match`、`rare_candidates`、`seed_admit` 登记进 `core/parallel.py`（不进指纹）。四庫 vol04 46 页串行对 `--jobs 4` 逐字节相同：row_segment 65→26 s、cell_shrink 28→9 s、glyph_match 231→80 s、rare_candidates 65→24 s、seed_admit 82→50 s。worker 里 OpenBLAS／torch 压 1 线程、`cv2.setNumThreads` 置空（fork 子进程里调它会卡死）；seed_admit、rare_candidates 先在主进程暖机、`parallel_warm` 预建大缓存再 fork；进程数按可用内存压。seed_admit 并行前要先把字块缓存建好。
  - 代码等价登记（`core/code_equiv.py` + `scripts/code_equiv.py check`，用户 10-20 定）：新旧代码同一批页产物逐字节相同才登记，指纹换回旧哈希，各册不过期。
  - 热点：glyph_match 逐页 −24%（wmax 按需算、同格查找分桶、HOG 向量化）；seed_admit 每页 2.3→0.85 s（事件读缓存；铁证匹配器归一图按内容缓存）；context_decide 热缓存首页 6–7→2 s（本书与通用 LM 按语料内容 + 代码指纹缓存）；align_ref 起跑 16→7 s；印章遮挡每页 0.21→0.02 s。
  - 训好的语言模型跨机分发：本机没命中先用读令牌去 R2 取 `derived/lm/…`，`guji products pack push-index` 手动推（用户 10-20 定）。runbook S1 设 `GUJI_DATA_TOKEN=$GUJI_DATA_TOKEN_READ`。

### Fixed
- `font_candidates._row_norms` 按 `id(mat)` 缓存行模长：lru 挤掉的矩阵释放后 id 被复用、行数相同时用错模长，余弦全错、结果随页序变（#255）；seed_admit 补登记 `code_deps` 里的 `font_candidates`。**rare_candidates、seed_admit 判过期，各册要重跑这两步**（vol04 46 页上未触发，产物相同）。
- 并发写（#255）：`_stamps.json` 加跨进程锁、临时文件带进程号（原来并行再生图块会整页记失败、丢戳）；`ImageCache.put`、绑定逐页缓存、字体索引改原子写。

## [0.4.8] - 2026-10-20

### 流程
- 分支与发版流程改为 **dev 集成＋发版时切 rc**（用户 10-20 定，`doc/版本号规矩.md` 第三节）：日常 PR 投 `dev`；准备发版时从 dev 切 `rc/vX.Y.Z` 测试，rc 只收本版修复并合回 dev；测完 rc 用 merge commit 合进 main、打 tag；main 不直接收 PR。`scripts/check_rc_target.py` 跟着改：目标 `dev` 返回 0，`main` 返回 4。

### 并入 main 上 v0.4.7 之后直接合入的改动
- 汉字关系库 hanzi：总设计、B0/B1/B7（#256）、B2 全字表字形向量包（#276）、B3 以字找字候选池改由 hanzi 库给（#266）、B4 字统网按字典存派生事实（#267）、真书实测文档（#278）。
- Step3 `row_segment` 人工指定整列格 `manual_cells`（#251，main 上记作 1.20；没有指定的列逐字节不变）。
- hanzi 库 B2 续：向量包存 int8／fp16／fp32（#281）；真刻本评测过判据，Step5-b 也切 8 位向量包（#284）。
- M10：待审分流脚本 `pending_route.py`（GUJI-688）、冻结册运行护栏（GUJI-694）（#279）。
- 文档：人审率分析补列级对位救援的离线评估（#247）；M10 精校调研与总设计、已知错单脚本、`guji exit-check`（#273）。
- **`row_segment` 版本合为 1.22**（本线 1.20／1.21 的 layout_prior 改动＋main 的 manual_cells），`code_hash` e82f08017e79c63a（rc）／bb4f3830915bcdf0（main）→ d5f4ceedcfbd2d06：各册 Step3 起判过期，冻结册按冻结规则不受影响；开关（layout_prior、manual_cells）不开的列产物逐字节不变。其余各步 `code_hash` 与 rc/v0.4.8 相同（相对 v0.4.7 变了的步见下面各条）。

### Added
- 产物包按「三样版本」打标签、每册有 main（用户 10-20 定：不同版本的结果分开存、不覆盖，main 是最新正式结果；cv、字形库、语料库三个版本号共同决定结果）：`guji products pack push` 不给 `--label` 时标签拼成 `cv<版本>-c<语料库号>-g<字形库号>-<改动名>`（`--change`；字形库没钉写 `g-`＋人裁指纹前 6 位），三样完整值记进 manifest 的 `versions`；新 `pack promote <册> --label …`／`pack push --main` 追加 main 指针（`main-ptr/`，只增不改，Worker 不用改）；`fetch` 缺省取 main，没标过才取最新；`list` 标 ★ 并列三样版本。不碰任何 Step，`code_hash` 不变。

- 产物包记字形库的内容版本、没存包提醒、实验记录（用户 10-20 定）。不碰任何 Step，`code_hash` 不变：
  - 每条产物 manifest 新字段 `db_rev`（跑时本机数据对应的中心库版本 `<工作区>@<分支>:<rev>`，不进指纹）；包的 `versions` 加 `db_rev`、`db_revs`（seed_admit 各页的 rev 与页数）、`corpus_base`。`glyph_pin` 只钉指纹不钉内容，要复现某份包读的库就从这个 rev 开 Neon 分支。
  - `guji pipeline`／`step`／`status`／`close-check` 末尾：本机这册产物在最后一次存／取包之后又跑过（各步 `_manifest.jsonl` 摘要对不上，记在 `<产物根>/<册>/.pack.json`），印一行提醒存包。只提醒不挡。
  - `pack push` 在工作区仓写 `experiments/<册>/<标签>.md`（基线、三样版本、中心库 rev、册 yaml、`--report` 给的 diff 报告）；`promote`／`--main` 往页尾追「标为 main」。`--no-record` 不写。
  - 实验记录开头加「摘要」（用户 10-20：每跑完一次都在记录里简单总结配置和结果）：`pack push --summary "…"`（或 `@文件`）写目的、改了什么、结论；给了 `--report` 时自动加一行结果（送审前后、人审率、变了的列、逐格翻转）；从产物 manifest 自动列各步最后一轮的起止时刻（洛杉矶）与耗时，看得出这一轮从哪步起重跑、哪步最慢。

- `guji products exclusions <册> --a <重切前> [--b <重切后>] [--apply]`（`ops/exclusion_rebind.py`，用户 10-20 同意方向）：排除清单按格号记、不带框，重切后可能落到别的格。按重切前的框到重切后找 IoU ≥ 0.85 的格：没动不改、顺移改号（`rekey_from`）、找不到或改号撞上撤到 `crop_exclusions_retired.jsonl`。缺省只报计划。不碰任何 Step，`code_hash` 不变。

- 控制台记下选的字是从哪儿点来的（`doc/research/人审找字-以字找字与异体族按图排序.md` §5.3，用户 10-20 要量相似字的真实命中）：
  - **定字卡**：confirm 行多带 `pick_src`、`pick_rank`、`pivot`、`pick_from`（`reviewClass.pickFields`）。`pick_src` 取值：
    - `cand`：主候选，`rank` 为键位表第几个，`from` 为哪几路；
    - `alt`：相似字，带 `pivot`；
    - `alt_q`：键入近似字后的相似字；
    - `rare`：「查候选」；
    - `custom`：手输；
    - `jys`：己已巳卡；
    - `cnn`／`ctx`／`llm`／`ocr`／`ai`／`form`：证据行上的「采信」。
  - **Step8「都不对」**：`collate_verdict` 与 `confirm` 带 `pick_src`／`pick_rank`／`pivot`，取值为 `alt`／`alt_q`／`custom`。
  - 切分缺陷等档不带；没点过的行逐字段不变。网站精校页同名字段见 kaiyuanguji-web#531。不碰任何 Step，`code_hash` 不变。
- char 导出：阙文带推测字（GUJI-717，用户 10-20 定「录文以图为准」，guji-format#21 char v0.2 `guess_c`）。人裁 `confirm v=damaged` 带 `guess=X` 的格（9.1 写 `□{guess=X}`），`scripts/export_guji_format.py --format char-cord` 与 `scripts/convert_pages_to_char_cord.py` 改写成 `{"c": "□", "lacuna": true, "guess_c": "X"}`，不再写成残字 `guess: true`、`c: X`（阅读器显示灰字 X，与「图上无字录 □」相反）。`guji export format` 出的旧形态（lines.md、pages.json）不变。只有带这种格的册 `$schema` 写 char v0.2，其余册导出逐字节不变（book-text 现存 char 里 `guess: true` 为 0 处）。往返核对按 9.1 写法比；`formats/` 加 `guji_char_v0.2.schema.json`。PATCH；改 `formats/guji_char_cord.py`、两个导出脚本，不在任何 Step 的 `code_deps` 里，17 个 Step 和闸的 `code_hash` 全不变。
- `guji audit alt <册> --reviewed`：已人裁、已放行的格也算相似字（只写进 `cards.alt.json` 给 `alt-eval`，不进待审单），拿历史人裁量相似字的真实命中——这些格裁的时候人还看不到相似字，没有「看了候选才选它」的偏倚。10-20 殿本 vol01–03 实测：人定的字不在卡上原有候选里的难格 75 格，相似字前 5 命中 55 格、前 10 命中 59 格（79%），第 1 名 36 格。不碰任何 Step，`code_hash` 不变。

- `scripts/check_rc_target.py <rc 分支>`（GUJI-657）：合 PR 前核对目标待发分支是否已发版（远端有 `vX.Y.Z` 返回 1 并提示改投哪条；不是最新待发分支返回 2）。只读，用 `git ls-remote`。不碰任何 Step，`code_hash` 不变。
- 粗校出口报告单列「钉版」一行（GUJI-656）：`collect_exit.py` 读册配置的 `cv_version`、`corpus`、`glyph_pin`，没钉的标 ⚠，只提示、不挡出口；规矩见 `doc/版本号规矩.md` 第七节（每波开工发一个正式 tag，各册钉 tag＋语料号＋字形库号）。不碰任何 Step，`code_hash` 不变。
- `scripts/zhengli/ledger.py`（GUJI-667）：粗校台账与统一人审率口径（用户 10-20 定：正文页送精校的待审格 ÷ 正文页字格，不含标题槽、非字格；重切清单、非正文另报），`review_rate()` 纯函数＋CLI 追加一行到数据目录 `feedback/lists/ledger/<册>.jsonl`。不碰任何 Step，`code_hash` 不变。
- `scripts/ia_download_zongmu.py` 改按全书 99 册两段编号（`06061300`–`06061320`、`06066140`–`06066217`，GUJI-648 逐号核过；原来按「199 册连号」，照默认跑会从 vol22 起下别的书）：新 `--vols 11-20` 按册号选，缺省取 `_tif.zip`（与工作区现有原图逐像素一致）。书单 `doc/runbook/书单-四庫總目.md`。不碰任何 Step，`code_hash` 不变。
- 粗校待审单脚本迁进本仓 `scripts/zhengli/`（GUJI-652）：`pending_list.py`、`sprite_build.py`、`ex_build.py`、`alt_build.py`、`decision_build.py`，原在 ai-team 工单目录、runbook 直接引用、没有测试；行为不变，`--cv-root` 缺省本仓根，各配单元测试。`ex_build`／`decision_build` 的用法示例仍写中心库切换前的路径，文件头注明。不碰任何 Step，`code_hash` 不变。

### Changed
- `scripts/export_guji_format.py --format char-cord` 的 `--text-version` 改为必填、不再缺省 0.1.0（GUJI-679）：已在 book-text 上的册要写线上现行版本，以前缺省写 0.1.0，出补丁前得先手工改回。`zl.py` 导出步显式传版本。不碰任何 Step，`code_hash` 不变。

### Fixed
- 产物包键的工作区名不再瞎猜（GUJI-671）：`datastore/packs._ws_name()` 先读 `.central.json` 的 ws，再读 `workspace.yaml` 的 id，都没有就报错；以前回退成目录名首段或 `ws`，vol01–03 的包因此落在 `products/ws/` 下、用 `-w` 取不到。不碰任何 Step，`code_hash` 不变。
- 中心库客户端超时分两档、超时快速重试（GUJI-707；国内节点连 data.open-guji.com 约 15% 卡在 TLS 握手，GUJI-703）：小 JSON 请求（查表、签名、状态、whoami、分支、追加事件）缺省超时 120 → 25 秒（`GUJI_DATA_TIMEOUT` 可改），超时走原有退避重试，且网络错至少试 4 次（原先查表、签名只试 2 次）；收发大块字节的（快照、备份、产物包、R2 直取图、`r2` 上传的 PUT）维持原值。`r2.upload_via_worker` 的签名请求同样用短超时。PATCH；不碰任何 Step，`code_hash` 不变。
- `guji close-check` 第 2c 项的待审单改读中心库（GUJI-711）：10-20 起公众待审单只在中心库 `feedback/lists/proofing/<书>/<章>.pending.json`，`--pending` 不给（或只写 `--pending`）就读数据目录里本册本章那份（书 id 按 `meta_<册>.json`，取不到在 `proofing/*/` 下找唯一一份；章号取 `--chapter`、导出目录唯一的 `NNN.lines.md` 或 `volNN`）；也认册（`vol04`）、章号、`<书>/<章>`；给了 book-text 的旧路径且文件不在，提示已迁移并指出新路径（新路径在就改读）。数据目录里没有就照旧只认重切清单，2c 说明里写清。runbook 同步。PATCH；不碰任何 Step，`code_hash` 不变。
- 字形库体检结果带库指纹，过期不出卡（GUJI-710）：`guji glyph-db selfcheck` 把开跑时的库指纹（本书套刻例 `(实例 id, 字, 图块 sha)` 排序后哈希）记进 `summary.json` 的 `db_fp`，每张卡记本例与本书对手的图块 sha；控制台体检 tab 出卡前核对，结果没带指纹或卡上刻例的图对不上（刻例重排编号）→ 409「体检结果已过期（库已变），请重跑 guji glyph-db selfcheck」，一张卡也不出；只是撤了、改了字的，那几张卡不出、其余照出。起因 GUJI-623：09-26 的结果在 09-27 重排编号后照样出卡，9 张错位。`glyphdb-audit` skill 与 `glyph_audit.py` 的说明改成中心库口径（数据目录、`guji db sync`，不再进 git）。PATCH；不碰任何 Step，`code_hash` 不变。
- 语料库任何内容变了都要改版本号（用户 10-20）：`guji db push`／`sync` 推送前，最新一版清单登记的工作区文件被改、缺，或清单之外多了新语料文件 → 拒绝，提示先 `guji corpus build` 出新版本一起推；已发布的某一版 `manifest.json` 库里已有且本地不同 → 拒绝（旧版本不可改）。只看工作区文件；引擎仓里的表仍由起跑前硬校验管。10-20 的起因：v1 登记的 `freq.json`、`l2/jys.json` 钉选后被重新生成，`glyph_match` 因此拒跑。改 `core/corpus_pin.py`、`datastore/workcopy.py`，`code_hash` 不变。
- `guji db pull`／`sync` 遇到库里引用、R2 上却没有（404）的图不再停下：跳过、stderr 打一行并在 `materialize` 结果的 `missing_images`（相对路径→sha）里列出，其余照常还原。要像以前一样遇到就停：`GUJI_DATA_MISSING_BLOBS=error`。不碰任何 Step，`code_hash` 不变。
- Step3 逐列格位先验 `layout_prior`：列端框线残渣记空。表说该空、又是整列物理上第一格或最后一格的「字格」，里面像字的墨行合计不到 0.15 个 period、满宽横线（±3 行）以外的墨占格面积不到 0.03 时改成 blank（产物 flags 记 `layout_frame_junk`）。起因：掩码故意不罚满宽密行，版框横线落进列首／列尾那格时被切成「字」，按 daizhige 算多切一格（vol05 p147 c1、vol06 p18 c6／p69 c2／p63 c1）。列中段的碎墨不碰：卷端页、整页破损页上印断的字（vol09 p164「經部十七」）不能批量判非字。殿本 vol04–09 实测改空 647 格，全部看图是框线、竖线、碎点；比 1.20 逐格多修好 19 列（4／5／6／7／8／9 册各 1／4／6／3／1／4）、改坏 0；穿字格线不变（只改格的类型，不动格线）。开关不开的书不受影响。PATCH；`row_segment` 版本 1.21，`code_hash` d4f420cf47082535 → e82f08017e79c63a。
- Step3 逐列格位先验 `layout_prior`：表的抬头级数与闸（`n_raised_hint`）不一致时，两种格网都切，取格线横穿字少的（打平照旧用表的）。起因：殿本 vol04 产物包对照组／版面先验组（`cv0.4.7-c1-g-82293e-*`）看图——①p84 c5、p65 c8「御」「欽」抬头在版框上方、列图没截到，按表硬设抬头格把首个看得见的字编成 -1，整列格网错一位劈字（84:5 放行错字「一」）；②p127 c1–2 低起列（从第 5 格起），按表压掉闸给的抬头余量后格网上挤半格。一律听闸也不行：书名列首字会被吸进 -1（vol04 实测新坏 10 列）。vol04 全册只有 7 列改走闸的格网（8:8、9:8、65:8、84:5、127:1、127:2、220:1），其余列与 v0.4.7 逐字节相同；穿字格线（对照组 1,810 条）旧版 1,808 → 新版 1,783。Step3 产物 flags 记 `layout_raise_gate`。开关不开的书不受影响。PATCH；`row_segment` 版本 1.20，`code_hash` b72e737b7a45a1df → d4f420cf47082535。
- `guji products diff --images` 看图页：`bbox_page` 是右上原点，原来直接当左上原点裁、画框，除正中那列外都画到镜像位置的另一列（vol04 R1 验收时发现）。现在先 `bbox_tr_to_tl` 再裁。报告数字不受影响。不碰任何 Step，`code_hash` 不变。
- `guji products pack push --label`：标签先在本地按 Worker 的规则校验（ASCII 字母、数字、`_.-`，≤96 字符），中文等不合法标签直接报清楚，不再到 Worker 才报 `bad_path`（重跑 vol04-10 线程 10-20 用「v0.4.6-粗校」撞上）。不碰任何 Step，`code_hash` 不变。

待发分支 `rc/v0.4.8`。

## [0.4.7] - 2026-10-20

### Fixed
- 标点分段（`render/siku_extract.py`、`render/reflow_text.py`，#239）：抬头／平抬／差一格改为软分段，连起来交模型断句后再定。只动渲染出口，不碰任何 Step，`code_hash` 不变。
- 导出（`formats/guji_page_cv.py`）：排除名单格（seg_defect／crop_defect）人已给字（`evidence.human_char`）的，字位 `method=human`、`review=human`，不再记 `pending`、不再标 `lacuna: defect`（文本本来就出这个字）。此前这类格在 pages.json 里仍是 pending（vol02 重跑后 124 格），顺带让待审单、2c 把它们当没裁。只动导出出口，不动任何 Step，`code_hash` 不变。非字、原刻残（damaged）、无人给字的名单格不变。

### Changed
- `guji close-check` 1a（非冻结册）改口径（用户 10-19 定「在跑它的那个版本下新鲜就行，不要求最新版本」）：只因「代码或版本变了」过期、且 manifest 条目记着正式版 `cv_version`（不带 `+N`／`+dirty`）的页算新鲜，过期也不再往下游传；detail 里另报这类页数与本册产物用到的 cv 版本。册配置变、参数变、上游产物变、缺失、失败、显式失效、老条目（没记版本）照旧算 FAIL。新参数 `--strict-cv` 回到旧口径。`Engine.status(code_ok=True)` 是同一件事（缺省 False，`guji status` 不变）。冻结册的 1a 不受影响。PATCH；只动 `core/engine.py`（不在任何 Step 的 `code_deps`）、`ops/close_check.py`、`cli_v2.py`，`code_hash` 不变。

### Added
- 受控重跑三件工具（[doc/受控重跑.md](doc/受控重跑.md)；方法论在 ai-team `domain/CV/规范/受控重跑方法论.md`）。都缺省关，不进任何 Step 的 `code_deps`，17 步 `code_hash` 不变：
  - 册钉字形库 `glyph_pin: N`（`core/glyph_pin.py`）：seed_admit 的人裁、近似字指纹换成 `glyph-gN`，别的对话推上来的人裁不再让本册 seed_admit 过期；号加一才落地新人裁。起因：重跑 vol04–10 时每次 `guji db sync` 都让已过粗校的册判过期、重跑、重做出口检查。不写 = 指纹逐位不变；第一次写上会让该册 seed_admit 过期一次。
  - `guji products diff <册> --a <前> [--b <后>] [--images N]`（`ops/products_diff.py`）：两份产物按位置逐列对比（切分变了也能比），出人审率前后、变了的列（切分／字／状态／框）、逐格翻转（含「放行字变」），`--images` 出原图并排看图页。
  - `guji products pack push|fetch|list` 与 `push-index|fetch-index`（`datastore/packs.py`）：一册 products、生僻字 embedding 索引存进 R2（guji-data Worker 新接口 `/v1/packs`，guji-workspace-data#15），新会话直接取，不再整册现算（云上一册 1.5–2.5 小时）、不再冷建索引（云上单进程约半小时，`--jobs 4` 约 8 分钟；取回 30 MB 约 4 秒）。按名字只增不改，取回先核 sha256。
- 相似字（以字找字，用户 10-19 定）：待审格的近似字（整理本字、上下文字、库前 3…）的异体族——本仓异体表＋部件檢索（新增 `config/variants/charcomp_rt.tsv`，非商业授权、文件头标来源）＋字统网一跳族（按需低频取、缓存在 `$GUJI_DATA_HOME/_shared/zitools/`，不进 git）——按字块图 CNN 余弦排序，每格 ≤30 个。`guji audit alt <册>` 出带 `alt` 的卡片 JSON 交 `pending_list.py`（`proof_fields` 带出 `alt`，网站精校页显示）；`guji audit alt-eval <册>` 人裁后量命中；控制台新路由 `GET /api/rare/alt/...`，定字卡与 Step8「都不对」下加「相似字」行和「以字找字」框。新模块 `clustering/variant_sources.py`、`review/alt_cands.py`；只出候选、不进放行；不碰任何 Step，17 步 `code_hash` 不变。PATCH。runbook S11-b，设计与读数 `doc/research/人审找字-以字找字与异体族按图排序.md`。

### Changed
- Step5-a `glyph_match`：借来的刻例降一档（共享方案 S6）。判 same 的库条目里有本书的，就用本书那条当证据；只有借来的条目（`glyph_lib.borrow` 装进来的，如共享刻例库 `glyphlib-qkp-v1`）判 same 时降成 unsure，字进候选交上下文裁决，记 `via="borrowed:<条目 id>"`，不再走共识升档与近形决胜。新硬参数 `borrow_fingerprint` 自动填被借库的名字，借的库换版本这一步判过期；没借库时是空串、不进参数 dump。**`glyph_match` 的 `code_hash` 变了**（改了 `steps/glyph_match.py` 与 `clustering/match.py`，`MatchResult` 多一个只在内存里用的 `same_hits`）；现在没有书借库，各册判决与参数哈希都不变，按版本号规矩算 PATCH，可以不重算。

### Fixed
- 语料库清单（`guji corpus build`／`init`／`build-base`）里的 `built_with.cv_version` 改读引擎仓 `pyproject.toml`：原来读装包元数据，可编辑安装后升了版本号它不更新，10-19 出的底库 b1 记成了 0.4.4（实为 v0.4.6 发版提交 `0194a152`，以清单里的 `repo_commit` 为准；b1 已发布不可改）。只是记录字段，不碰任何 Step，17 步 `code_hash` 不变。
- `row_segment` 缺省关的新开关（`colgold_prior`／`yolo_*`／`layout_prior` 及其指纹字段）不再进参数 dump（同 `border_detect` 的做法）：v0.4.6 把它们加进 `RowSegmentParams`，所有册的 `params_hash` 都变了，已冻结的册（`freeze:`）用 v0.4.6 跑 close-check 1a 被归成「册配置或参数被改：row_segment N 页」报警，而规矩是代码变只计数不报警。现在关着时参数哈希与 v0.4.5 逐位相同，开着照常进指纹。PATCH；`row_segment` 的 `code_hash` 因改了该模块变一次（对 v0.4.6）。

## [0.4.6] - 2026-10-19

PATCH。中心库拉取省流量与实验分支、借库与两级语料库清单、共享刻例库与升格候选命令；Step1／Step3 的新开关（`column_grid_pages`、`body_pages`、`colgold_prior`、`layout_prior`，缺省全关）；close-check 第 2 项不数重切清单上的格；殿本四联叶拆页表修正。

**`code_hash` 有变（对 v0.4.5，发版时实算）**：`border_detect` e7568862 → d452c5ab、`border_detect_gate` 8c0a7903 → fbc1b48d、`column_gate` 25658f2b → 922057a9、`row_segment` e5572a66 → f773bd3a；其余 13 步不变。新开关缺省关、关着时产物逐字节不变，各册这几步可以不重算；已登记 `freeze:` 的册代码变只计数不报警。

### Changed
- `guji close-check` 第 2 项「待审清零」不再数重切清单（`feedback/lists/<册>-重切清单.tsv`）上的格，detail 里另报「N 格在重切清单上，不计」。起因：vol01 有 66 格待审落在 cv 切不对、book-text 里手拼的列（职名表、p10:7、p196），格 id 与 cv 切分对不上，落不了格事件，永远清不掉；它们的去向由 2c／2d 把关。清单为空时行为不变。PATCH；只动 `ops/close_check.py`，`code_hash` 不变。
- 新机器第一次 `guji db pull` 先从 R2 下工作区快照（殿本约 6–7 MB，R2 下载不收费），库里只要快照之后变了的文件；`pull` 向库要过文件后、`sync` 拉下库里新改动后，把本机与库一致的文本打包存成新快照（只有能写该分支的令牌存得上，存不上不影响拉取）。快照只当缓存，逐文件对库里的 sha，坏了、旧了都退回从库里取。`GUJI_DATA_SNAPSHOT=0` 关掉。要 Worker 的 `/v1/snapshots`（guji-workspace-data#14）。不碰任何 Step，17 步 `code_hash` 不变。
- `guji db pull`／`sync`／借库拉取省 Neon 公网流量：本机已有、整文件 sha 与库里一致的文件直接用本机字节，只向库要变了的文件（按 `src_path` 查）；向库要行只取 `src_path`、`src_line`、`raw`，刻例图清单只取 `instance_id`、`patch_sha`。起因：Neon 免费档每月 5 GiB 公网流量，10-18 建库后 1.6 天用掉 4.75 GB，因为每次 sync 只要库里有新写入就把整个工作区按 `SELECT *` 重读一遍（殿本约 120 MB）。改后小改动的一次 sync 只传变了的那几个文件。要 Worker 认 `cols` 与同列多值（guji-workspace-data#13）；旧 Worker 自动退回整行取、逐值查。新机器第一次拉仍是全量。不碰任何 Step，17 步 `code_hash` 不变。

### Added
- 升格候选命令（共享方案 S7，语料部分）：`guji promote mine -w <工作区>` 只读，从对勘裁决挖形近对、异体对候选，对照引擎仓的形近表、异体表标出已有的，出清单待人审。新文件 `ops/promote.py`，不碰任何 Step，17 步 `code_hash` 不变。
- 共享刻例库命令（共享方案 S5）：`guji glyphlib build -w <来源书> --name glyphlib-<族>-v<N>` 按门槛（人裁在几个不同批次确认过、体检干净、非近似字、每字几张）从一本书精选刻例，出共享刻例库工作区（刻例图逐字节照搬，实例 id 加来源前缀，附升格记录 `feedback/events/promote.jsonl`）；`--push` 以升级脚本身份推进中心库，每版只写一次。新文件 `ops/glyphlib.py`，不碰任何 Step，17 步 `code_hash` 不变。见 `doc/datastore.md` 第六节「共享刻例库」。
- 中心库实验分支能整套用了：`guji db pull/push/sync --branch exp/GUJI-<号>-…`（或 `GUJI_DATA_BRANCH`）把整个工作区换到实验分支，数据目录、glyph.db、products 都放进该分支自己的目录（`$GUJI_DATA_HOME/exp__GUJI-…/<工作区>/`），不碰 main 的副本；push 经 Neon API 找到分支端点，新图进实验桶，拉图时正式桶没有的去实验桶取。新命令 `guji db diff` 逐文件比实验分支与 main。原来 push／sync 只许 main，`pull --branch` 会把实验分支的数据拉进 main 的数据目录。不设分支时行为不变；不碰任何 Step，17 步 `code_hash` 不变。见 `doc/datastore.md` 第六节「实验分支」。
- 两级语料库清单（共享方案 S2）：引擎仓的语料文件登记进底库 `b<M>`（中心库只读工作区 `corpus-base`，`guji corpus build-base` 出、记 `repo_commit`）；书库清单可写 `base: M`，只登记工作区里的文件（`guji corpus build --base latest`，新书 `guji corpus init`）；`db pull`／`sync` 顺带拉底库清单的只读副本。旧的单级清单（殿本 v1）不变。**起跑前硬校验**：册钉了 `corpus: N` 时，读语料的五步开跑前清单里的文件有改动或缺失就拒绝（`GUJI_CORPUS_DRIFT=warn` 临时绕过），新出现的文件只警告；殿本 v1 现在改动 0、缺失 0。改 `core/engine.py`、`core/corpus_pin.py`、`ops/corpus_pack.py`、`datastore/workcopy.py`，17 步 `code_hash` 不变。见 `doc/datastore.md` 第六节「两级语料库清单」。
- 中心库借库（共享方案 S4）：迁过的工作区在 `workspace.yaml` 的 `glyph_lib.borrow` 写被借工作区的名字，`guji db pull`／`db sync` 把它的字形库拉成只读副本（`$GUJI_DATA_HOME/<分支>/.borrowed/<工作区>/`），带上它重建 glyph.db，被借库有新写入才重拉重建；`guji glyph-db rebuild` 也认工作区名。原来配了借库 `db pull` 直接报错。共享层工作区 `corpus-base`、`glyphlib-*` 普通 push／sync 拒绝，只有升级脚本能写，`glyphlib-*` 只写一次。见 `doc/datastore.md` 第六节。不碰任何 Step，17 步 `code_hash` 不变。
- `border_detect_gate` 新参数 `body_pages`（缺省空；空时不进参数 dump、产物逐字节不变）：册配置点名的页不论页型规则判成什么都按正文切，manifest 记 flag `page_type_forced`。起因：殿本 vol06 p88 卷十末叶只有一列小注「部一卷皆附存目」、其余空栏，被判成 cover 整页跳过，丢 7 字；`params: {border_detect_gate: {body_pages: [88]}}` 后整页切出、7 字放行。`border_detect_gate` 的 `code_hash` 变（下游产物逐字节不变，不连带过期）。
- Step1 `border_detect` 新参数 `column_grid_pages`／`grid_col_pitch`（缺省空；空时两项都不进参数 dump、产物逐字节不变）：点名的页竖线走网格模式，其余页照书级配置。起因：殿本 vol05 p55、p123，vol04 p80 界行断续，自由模式挑了假竖线或漏一条界行，整列没切出来（vol05 p55「明王宣撰…」、p123「行故居足之左右…」、vol04 p80「今說易諸書無所偏主…」），现有闸都拦不住；`params: {border_detect: {column_grid_pages: [55, 123], grid_col_pitch: 185}}` 后列距全回到 180–190px，正常页逐位不变。`border_detect` 的 `code_hash` 变。
- `column_grid_pages` 点名页另做一步：最外一列窄于内列中位的 0.8 倍时，把那条外框线按中位列距往外推（记成插值线），只动外框两条。起因：殿本 vol04 p63 右框只下三分之一有墨，探到的「框」落在首列字上，首列只剩 117px、「聖人非因之以作易…」半列丢字；网格模式本身选不到这条残框。正常页不触发（vol04 p62、p80，vol05 p55、p123 逐位不变）。
- Step3（row_segment）加两个开关，**缺省都关，关着时产物与原来逐位相同**（殿本测试 B 100 页实测）（doc/design/19）：`colgold_prior` 读逐列字数金标（daizhige 与 yolo_tool release 两源字数一致的列，`scripts/dzg_import.py colgold` 生成 `corpus/daizhige/colgold.jsonl`），本列切出的字数与金标差 1–2 时按目标格数重切一次，重切后字数对上才采用；`yolo_merge` 用 yolo_tool 原生 ONNX 模型（`model_dir` 指过去，新可选依赖 `pip install -e ".[yolo]"`）提议并格（同一 YOLO 字框覆盖本列相邻两格），两者合用时先 D 后 C；带任何人裁（格数、切点、钉线、强制正文/小注）的列两个开关都不动；开关开着而表或模型不存在时报错。殿本测试 B（900 列）逐列字数 97.0% → 98.44%（修 13 列、新错 0），殿本全书 10 册（现行生产）96.84% → 97.83%（修 149、新错 1）。另加全书评测 `guji eval run column_counts`（金标分片 `char-segmentation/column-counts`，open-guji-dataset）。PATCH；只 `row_segment` 的 `code_hash` 变（e5572a664ad5b088 → a9f270b156c01af1），开关不开的书产物内容不变，但会按指纹判过期一次。
- Step3 逐列格位先验 `row_segment.layout_prior`（缺省关，关时产物逐字节不变）：读 `scripts/dzg_layout.py` 由 daizhige 逐列本生成的逐列格位表（`corpus/daizhige/layout_slots.jsonl`），按表定抬头级数、DP 逐格软罚分（`row_boundaries.fit_row_boundaries(slot_mask=…)`，新函数 `slot_mask_from_occupied`）、两半都有字的夹注格与正文格强制。**与 `colgold_prior`／`yolo_merge` 同列互斥**：表里有的列不跑那两个；带任何人裁（逐列字数、切点、钉线、强制正文/小注）的列三个先验都不碰（人裁按格号记，抬头级数一改就错位；vol01 p40–80 实测修前会动 3 列人裁列）。殿本十册离线：普通正文页逐格全对 95.76% → 98.51%，劈字 19 → 0；vol04/05 同基线下与逐列字数先验对照，字数口径 98.80% vs 98.25%、逐格口径 98.64% vs 94.71%；选法见 `doc/segmentation_v2_pipeline.md`「Step3 结构先验」（`doc/research/切分现状梳理与新方向-2026-10-19.md` §六、§八）。`close-check` 2d 另报「一页 ≥3 列没交代」的页，提示整页进重切清单（只提示，不改判定）。PATCH；**`code_hash` 变：`column_gate` 25658f2bf469a339 → 922057a98646e7d7、`row_segment` a9f270b156c01af1 → f773bd3aa6c4cd11**（`row_boundaries` 是两步的 code_deps），各册从 Step2 交接闸起判过期一次，缺省输出不变。

### Fixed
- 拆页表 `doc/formats/samples/guji_page_v0.2/split_table_siku.json`：殿本 IA 四联叶 vol04 第 216 叶（页 216–218）、vol07 第 128 叶（页 128、130）、vol09 第 258 叶（页 258–261）9 个半叶的裁线没落在版心，右半叶丢一整列或多裁进版心和邻页两列。按原图在版心两条界行 ±8px 处改 x、w（y、h 不变），重裁后每张正好 9 列；guji-workspace 的原图同步替换。拆页算法本身的改进另见 GUJI-625。不碰任何 Step，`code_hash` 不变（图变了，这几页 Step1 起按内容判过期）。

## [0.4.5] - 2026-10-19

PATCH。整理本和语料库清单进中心库；中心库取图不经 Worker；字组第四批与日目组补回；close-check 加 1c、2c、2d；人裁绑定缓存键修正；兼容汉字折成统一汉字。

**`code_hash` 有变（对 v0.4.4，发版时实算）**：`align_ref` e66b1c3f → e3043722、`rare_candidates` 4168770d → 8d081ec3（兼容汉字折叠 #200）、`seed_admit` 50bdd1fb → 52867bcf（#200 与字组 #206 合计）；其余 14 步不变。各册这三步的产物会判过期，重不重算看各册需要（各书重跑现在暂停）。

### Changed
- 中心库取图不再经 Worker（服务端改动，已部署，guji-workspace-data#12）：正式桶挂公开域名 `blob.open-guji.com`，Worker 签下载时回公开地址，各版本客户端都自动生效。从空目录整库拉殿本的 Worker 请求从约 1.85 万次降到 173 次。本仓只改文档与注释（`doc/datastore.md`、`datastore/client.py`），`code_hash` 不变。

### Added
- 补进 #184、#192（它们在 v0.3.5 发版后才合进旧待发分支 rc/v0.3.5，没进 v0.4.x；册配置已开 `xz` `wyu` `yt` `rm`，v0.4.x 跑 seed_admit 报「未登记的字组 'xz'」）。原条目如下：
  - group_flow 第四批形近字组（2026-10-19，sheldon 定）：象彖 `xz`、王玉 `wyu`、圓圖 `yt`，做法同第三批（L1 规则＋逐册 L2 haiku 表，只补放不复核；彖傳／象傳、玉篇／帝王篇、方圓等两可词弃权）。vol04 A/B 组外格 0 变化，放行 +1（该册这三组几乎都已被放行，收益在没放行的册），L1 对整理本零冲突。`seed_admit` 的 `code_hash` f0f2713200ae880e → c3dbd4dac0582b47，其余 16 步不变。报告 [group_flow-4-vol04-报告](doc/exp/group_flow-4-vol04-报告.md)。
  - group_flow：允许组成员重叠＋形近组复核＋日目组 `rm`（2026-10-19，sheldon 定）：①`GroupSpec.overlaps`（须互相声明），`flow.entry` 一个字可属多个组——补放选第一个装得下「分差内全部候选＋整理本字」的组，复核选第一个声明了 `review` 且装得下整理本字的组；日曰 `ry` 与新组日目 `rm`（L1＋L2 haiku 表）共用「日」，日曰候选归 ry、日目候选归 rm、三者混杂留人审。②已放行格复核（只降审、不改字）：`ry wxs ly dt wj zh yh xz wyu yt rm` 打开 `review`（原来只有 jys／rr）。③`seed_admit` 的待审补放通道（witness3／coord_fallback）不再把复核判了 `group_flow_disagree`／`_conflict` 的格放回去（原来降审被 coord_fallback 按整理本字又放行，白降；含 jys／rr 原有的降审）。vol04 A/B：复核降审 8 格（象彖 4、大太 2、問間 1、入人八 1，原来被放回去的那 1 格），无改字；日目 L2 表 57 格答 37；组外格仅 iron 通道 +3（本机重拉字形库后库内容变化所致，与本改动无关）。`seed_admit` `code_hash` c3dbd4dac0582b47 → f0c37eac6214999c，其余 16 步不变。报告 [group_flow-5-vol04-报告](doc/exp/group_flow-5-vol04-报告.md)。
- 整理本和语料库清单进中心库（共享方案 S1）：`corpus/**` 进新表 `corpus_files`（文件进 R2，同锚图做法），清单挪到数据目录 `config/corpus-pack/`（随 `files` 表）。迁过的工作区再跑一次 `guji db migrate` 把工作区根留下的 `corpus/`、`corpus-pack/` 补迁进数据目录，再 `guji db push`。`corpus_path()`／`pack_root()` 先找数据目录。要配合 guji-data Worker 新版（已部署）；旧 Worker 上照常 pull。殿本 10 册 17 步 `self_hash` 搬家前后逐位相同，17 步 `code_hash` 不变。见 `doc/datastore.md` 第六节「整理本与语料库清单」。
- `guji close-check` 加两条放行硬项（用户 10-19 定，GUJI-624；粗校档、终校档都计）：2c「□ 有去向」，导出文本里每个阙文格要在公众待审单（新参数 `--pending <NNN.pending.json>`）或 `feedback/lists/<册>-重切清单.tsv` 上；2d「整理本对不上的列有交代」，align_ref `coord_fallback` 的每一列要在 `feedback/lists/<册>-对不上列交代.tsv`（处理：重切／改字／说明／一致）或重切清单上。`scripts/zhengli/collect_exit.py` 透传 `--pending`（`ops/release_gates.py`）。PATCH；不碰任何 Step，`code_hash` 不变。
- `guji close-check` 加 1c「模型在场」：本机没装 torch 或缺切点裁判／识别权重时 FAIL（这时 1a 是拿「没模型」比「没模型」，照报新鲜）；Step5-b 产物里有字要查却一条 embedding 候选都没出的页也 FAIL（没 torch 跑的 Step5-b 指纹照样新鲜，只能看产物）。D 10-19 云端重跑 vol01 时踩到。PATCH；只动 `ops/close_check.py`，`code_hash` 不变。

### Fixed
- 兼容汉字一律折成统一汉字（如 福 U+FA1B → U+798F，`utils/cjk_compat.py`，#200）：字表、整理本对齐、人裁事件、产物读写都按统一汉字比较。改了 `align_ref`、`rare_candidates`、`seed_admit` 的 `code_hash`（见本节开头）。发版时补记。
- 人裁绑定表（`feedback/bindings.py`）的页缓存键加上字块那一步（`cell_shrink`）的产物 sha，比指纹时字块图也验戳：此前只认 Step3 的 sha，Step3 不变、字块重算了，旧缓存照样采信，行里的指纹是对着旧字块算的，人裁判成 review 不采信。D 10-19 云端整册重跑 vol01 时，10-16 的人裁 100 多格因此丢成 □。缓存版本 6→7，各机绑定缓存下次读时自动重算一遍。`seed_admit` 的指纹仍不含绑定结果，这类丢格靠 close-check 2b（已定字却没出字）兜底，2b 不为 0 的页 `guji step seed_admit … --force`。PATCH；`bindings.py` 不在任何 Step 的 `code_deps` 里，`code_hash` 不变。

## [0.4.4] - 2026-10-18

PATCH。Worker 超资源时自动缩批；借库不再把被借库的人裁算成本书的。17 步 `code_hash` 都不变，不用重算。

### Fixed
- 中心库 Worker 超资源（Cloudflare 1102，客户端看到 503）不再让 `guji db sync|pull` 整次失败（10-19 服务器 siku 拉 4 条新改动时失败）：查表每页 5000 → 2000 条，遇 503 页减半再试（最小 100）；下载签名每批 1000 → 250 张，遇 503 对半拆开；上传签名每批 200 → 40 张（每张要在 Worker 里查一次桶）。10-19 05:00–06:00 UTC 有 65 次 exceededResources。
- 更正 v0.4.1 的说法：取图的签名直链指向 Worker 自己（`/v1/blob/…`），**每张图算一次 Worker 请求**（免费档每天 10 万次）。新机器拉一遍 siku 约 1.8 万次；10-19 05:00 UTC 那一小时用了 7.6 万次。拉过的图在本地缓存里，不重复取。
- 只动 `datastore/`，17 步 `code_hash` 不变。
- 借库（`workspace.yaml` 的 `glyph_lib.borrow` → `rebuild_from_store(extra_stores=...)`）不再把被借库的人裁算成本书的人裁：被借库的 `admissions` 不装，借来实例的 `label_status='human'` 改记 `borrowed_human`；借来的刻例照旧参与匹配。原先人裁通道（`glyph_fp.HUMAN_SQL`）、铁证匹配器、`glyph_match` 共识升档都会把它们当本书人裁：中心库真数据实测全唐文借殿本，人裁查询 2,139 → 5,470 条，共识升档的字 126 → 491 个；修后回到只本书的数（共享方案 3.4 节，S3）。现在没有工作区开着借库。只动 `clustering/glyph_db.py`（不进任何 Step 的 `code_deps`），17 步 `code_hash` 不变。

## [0.4.3] - 2026-10-18

PATCH。push 只上传库里没有的图（只动 `datastore/`），17 步 `code_hash` 不变。

### Fixed
- `guji db push`／`sync` 推送时只把库里没有的图交给上传（先查一次该工作区 `glyph_instances.patch_sha` 与 `anchor_patches_meta.sha256`）。原先每次推都把全部约两万张图逐批签名核对一遍，要十几分钟，期间数据库连接闲置被 Neon 断掉，事务一开就失败（10-19 D 推 vol01 裁决两次失败，库里没有写入）。只动 `datastore/workcopy.py`，17 步 `code_hash` 不变。

## [0.4.2] - 2026-10-18

PATCH。push 删除检查算上锚图（只动 `datastore/`），17 步 `code_hash` 不变。

### Fixed
- `guji db push`／`sync` 推送前的删除检查把锚图（`anchor_patches_meta`）也算进去：v0.4.0 及更早版本 pull 的数据目录里没有锚图，原先会把库里的锚图当本地删掉一并推走（10-19 D 推 vol01 裁决前在 dry-run 里发现，没推）。现在不加 `--allow-delete` 就整次拒绝。只动 `datastore/workcopy.py`，17 步 `code_hash` 不变。

## [0.4.1] - 2026-10-18

PATCH。中心库拉图提速、锚图还原（只动 `datastore/`），17 步 `code_hash` 不变，不用重算。

### Fixed
- `guji db sync|pull|migrate` 拉图提速（10-19 D 反馈：18,481 张刻例图拉了约 20 分钟）：签名本来就每 1000 张批量签，慢在取图一张一次 TLS 握手、只开 8 线程。`WorkerSource.fetch_blobs` 改为每线程留 HTTPS 长连接（走系统代理的 CONNECT 隧道）、缺省 32 线程（`GUJI_DATA_FETCH_WORKERS` 可改），闲置连接被关立刻重连；超过 2000 张时每 2000 张在 stderr 报一次进度。云端实测 3000 张小图：约 30 张/秒 → 约 220 张/秒。取图走签名直链（更正见 0.4.4：直链指向 Worker，每张图算一次 Worker 请求）。
- 锚图（`feedback/anchor_patches/**.png`）只记在 `anchor_patches_meta`、不进 `source_files`，`pull`／`sync` 从没把它们还原到数据目录，`migrate` 则把检出里的每张锚图都报成「与中心库不一致」（服务器 siku-zongmu 报 1946 个）。`_db_manifest` 与 `materialize` 现在把这张表算进来。
- 只动 `datastore/`（不进任何 Step 的 `code_deps`），17 步 `code_hash` 不变。

## [0.4.0] - 2026-10-18

MINOR（用户 2026-10-19 同意：609 改指纹、没冻结的册重算一次）。release note 见 `RELEASES.md`。

### Changed
- 字形库指纹改成「步骤读到的内容」的哈希（GUJI-609，工作包 8.8）。写入切换后 glyph.db 每拉到新字形库就从中心库整库重建，旧指纹的 `(条数, 最大 rowid, 时间戳)` 会随 rowid 重排白白变。新模块 `clustering/glyph_fp.py`（不进任何 Step 的 `code_deps`）：
  - `seed_admit.human_fingerprint` 改取人裁通道真正读的 `(实例 id, 字头)` 排序后的哈希（`h1:<条数>:<哈希>`），与 `_human_shapes` 同一条查询（`glyph_fp.HUMAN_SQL`）。复制、VACUUM、重建、撤了同字重进、机器准入都不变；人裁进库、撤裁、字头改判才变。
  - `rare_candidates` 加参数 `db_font_fingerprint`（字体域清单哈希，自动填，库里没有字体域是 `none`）：中心库重建的 glyph.db 不带字体域，要另跑 `glyph-db import-font`，带不带、导的哪版字体从此看得见。`import-font` 导入时在新表 `font_manifests` 记字体文件 sha256、字表 sha256、渲染数（这张表不导出进账本）；更早导入的退回按实例数。
  - 设计第六节写的是「库版本号 rev」。改用内容哈希：产物在各自机器上，同一份内容在不同机器、不同时候拉到的 rev 不同；本地人裁还没推时没有 rev；推完 rev 变了内容没变会白白再过期一次。精度相同。
  - `glyph_match.db_fingerprint` 不动：它是软参数（只记漂移不判过期），重建后同内容的库戳本来就相同（实测两次重建逐位一致），为它改 `glyph_match` 会让最贵的一步全书重跑。
  - **影响**：`seed_admit`（f0f2713200ae880e → 50bdd1fb5f0bcbd1）、`rare_candidates`（ac757fe8b73ba312 → 4168770d80cbde67）的 `code_hash` 变，参数指纹也变；没冻结的册这两步及其下游重算一次，判决不变（产物里只有指纹字段变）。冻结册按冻结基线比快照，不受影响。其余 15 步不变。

## [0.3.5] - 2026-10-18

PATCH。中心库客户端与写入切换（数据迁出工作区、`guji db sync` 自动合并、每日备份；GUJI-606/608/611），group_flow 第三批形近字组。相对 v0.3.4 只有 `seed_admit` 的 `code_hash` 变（6a4e2bd27c35fa8a → f0f2713200ae880e），其余 16 步不变；没迁进中心库的工作区行为不变。

### Added
- 字组：按字分类的异体组再加 啓啟 厯歴 絕絶（qik lih jue），模板来自 sheldon 10-20「异体对第二批」人裁（vol01、vol04–10），按册留一 0 错。册配置 `group_flow` 点名才生效。
- 字组：两形混用的异体组 叙敘 冊册 教敎（xu ce jiao）走在线 IDS 新判法「按字分类」（`IdsSpec.by_form`）：自动缝切开，取有差别的那段与各字的同段真实刻例比最近邻。模板来自 sheldon 10-20 合审的殿本人裁（vol04–10），按册留一 0 错。册配置 `group_flow` 点名才生效。
- 字组：第三批只看字频的异体组 刊刋 既旣 清淸 顚顛 淄湽 青靑（kan jiw qx dx zx qy；殿本全书人裁只见一形，sheldon 10-20 合审定）。要在册配置 `group_flow` 点名才生效。
- 字频解法阈值 20→10，且主形人裁须来自至少两册（2026-10-20，sheldon 定）：`seed_admit.group_flow_freq_major` 缺省 10、新参数 `group_flow_freq_min_vols` 缺省 2（0＝不查）；字频表新增 `vols`（每个刻形有人裁的册数，旧表没有就不查册数）。现有数据里新放行的只有 變𠮓（17，来自 vol01–03）；彙彚 12 只来自 vol01，仍弃权。`seed_admit` 的 `code_hash` 变，参数哈希变（用 group_flow 的册）。
- `guji db status|pull|branch|import`：中心库客户端（GUJI-606，工作包 8.5）。`pull -w <工作区>` 经 guji-data Worker 把字形库账本按当前版本还原到 `<工作区>/output/central/<分支>/output/glyph_store/`（每个文件核 sha256，刻例图按 sha 从 R2 拉进本地缓存 `GUJI_DATA_CACHE`、去重），再重建 `glyph.db`，等价于 `glyph-db rebuild --no-replay --no-borrow`；git 管着的 `output/glyph_store/` 不动，库旁写 `glyph.db.central.json` 记分支与 rev。`--rev N` 只在该工作区 N 之后没变时放行（中心库不存旧内容），`--with-feedback` 连 feedback/ 一起还原。`branch create|delete` 开删实验分支，`import --from exp/<名>` 把实验分支的事件显式导入正式库（经 Worker `/v1/events`，按事件 id 幂等；写入切换 GUJI-608 前 Worker 不接受写 main）。连接只认 `GUJI_DATA_URL`／`GUJI_DATA_TOKEN`／`GUJI_DATA_BRANCH`。新模块 `datastore/client.py`、`materialize.py`、`pull.py`、`cli_db.py`，不进任何 Step 的 `code_deps`，**17 步 `code_hash` 全部不变**（逐步对照验过）；不用就没有任何影响。`python -m open_guji_cv.datastore r2-plan --via worker` 改为每 200 张调一次 `/v1/assets/sign-batch`（旧版 Worker 退回逐张签）。

- **数据迁出工作区**（GUJI-608，2026-10-19，用户定）：中心库是册 yaml、人裁事件、台账、批次、人工配置、字形库唯一的家，工作区里只留 `workspace.yaml` 和标记 `.central.json`，数据在工作区外的数据目录 `$GUJI_DATA_HOME/<分支>/<工作区 id>/`（缺省 `~/.guji-data`）。`core/workspace` 加 `data_root`／`books_dir`／`ws_config_dir`，见到标记就把数据路径指向数据目录，没有标记照旧；各处从工作区根直拼的路径改走这些函数（`core/book`、`corpus_pin`、`seed_admit`、`groups/freq`、`groups/ids_online`、`collate_consumers`、`snap/*`、`deploy_check`、控制台工作区列表），守卫 `tests/test_central_paths.py`。新命令 `guji db migrate`（核对后挪数据、写标记，glyph.db 不动）、`guji db pull`（中心库 → 数据目录，拉到新字形库才重建 glyph.db）、`guji db push`（拿库锁后先比版本号，别人先写过整次拒绝；只追加台账少行、整个文件丢了也拒绝；glyph.db 改过先导出；新图先经 Worker 传正式桶；连库用 `GUJI_DATA_PG_DSN`，没有就从 `NEON_DATABASE_URL` 自动起 443 桥）。迁过的工作区上 `guji store commit|check` 改为推中心库，close-check 第 8 项改查没推的改动。新模块 `datastore/workcopy.py`、`ops/central_glyph.py`；`importer.import_scans` 从 `import_commit` 拆出（加 `guard` 钩子）；旧的 `db pull` 只读快照（`output/central/`）删掉。**`seed_admit` 的 `code_hash` 变**（50b4c7c96150b33d → f0f2713200ae880e，字组表改从数据目录找；本版字组第三批已经让它变过一次），其余 16 步不变。没迁的工作区行为一字不变。

- `guji db sync -w <工作区> [--dry-run] [--watch 秒]`（GUJI-608 B 块）：拉＋合并＋推一步做完。别人先写过时不再整次拒绝：库里改了本地没改的取库里的，只追加台账（events、consumed、anchors）两边都追加了就把两边的新行都留下，其它文件两边都改了才停（`SyncConflict`，本地不动）。`--watch` 定时反复做，冲突与断网只记日志，用来替代服务器上 30 分钟一次的 `guji-glyph-store-sync.timer`（往 guji-workspace git 提交）。只动 `datastore/workcopy.py`、`cli_db.py`，17 步 `code_hash` 不变。

- 中心库备份与恢复演练（GUJI-611）：`python -m open_guji_cv.datastore backup` 在一个只读快照里把全部表 `COPY` 出来、gzip，附清单（每表列、行数、排序后哈希、序列值、rev），经 Worker `/v1/backups` 存进正式桶 `backup/<日期>/`，清掉超过 30 天的；`restore-check --endpoint <ci 端点>` 取最新一份完整备份恢复到 main 以外的分支（给 main 的端点直接拒绝）并逐表核对。首次实测（10-19，rev 1356）：26 张表 189,964 行，备份 12 MB、31 秒；恢复到 ci 分支 39 秒，逐表行数与哈希全部一致。连库抽成 `datastore/connect.py`。

### Removed
- 往 guji-workspace git 提交数据的旧路径（GUJI-608/611，2026-10-19，用户定「后面这些数据在中心库的就不应该再出现在 workspace 里面」）：删 `scripts/glyph_store_sync.py`（服务器 30 分钟一次的 `guji-glyph-store-sync.timer`，由 `guji db sync --watch` 替代）、`scripts/snapshot_glyph_store.py`、`clustering/store_merge.py`（git 三方合并）、`ops/store_commit.py`（`guji store commit` 的 git 路径）及其测试。`guji store check|commit` 现在只推中心库，没迁的工作区直接提示先 `guji db migrate`；close-check 第 8 项同理。近似字 store 导出与重建的两条用例挪进 `tests/test_approx_store_export.py`。runbook S14、`workspace_layout`、`.claude/CLAUDE.md` 等文档改成中心库口径。17 步 `code_hash` 不变。

### Fixed
- 中心库 push／sync 判「glyph.db 改过要先导出」改用导出签名（`ops/central_glyph.export_signature`，即原 `glyph_store_sync.db_signature`），不再用匹配器库指纹：只标了／撤了近似字、改了实例 label／ids 时匹配器指纹不变，此前这类改动会漏推。
- 中心库客户端与 `r2-plan --via worker` 遇到断流（`http.client.IncompleteRead`）也退避重试，不再整次中断（2026-10-18 正式桶上传时碰到）。
- group_flow 第三批形近不同义字组（2026-10-19，sheldon 定）：論諭 `ly`、大太 `dt`、問間 `wj`、曾會 `zh`、遺還 `yh`，按文意（L1 规则＋haiku 答案表，只收 conf=high，只补放不复核）。注册表加 5 个 `GroupSpec`，配置 `config/groups/{ly,dt,wj,zh,yh}/{rules.yaml,prompt.md}`，扩展脚本 `ext_enum_cells.py`／`ext_make_batches.py` 加 `--groups`。缺省关（书 yaml 的 `group_flow` 点名才生效）。vol04 A/B：组外格逐格不变，放行 +10（曾會，均无强真值可对），报告 `doc/exp/group_flow-3-vol04-报告.md`。PATCH；**`seed_admit` 的 `code_hash` 变**（6a4e2bd27c35fa8a → 50b4c7c96150b33d），其余 16 步不变。
- group_flow 第四批形近字组（2026-10-19，sheldon 定）：象彖 `xz`、王玉 `wyu`、圓圖 `yt`，做法同第三批（L1 规则＋逐册 L2 haiku 表，只补放不复核；彖傳／象傳、玉篇／帝王篇、方圓等两可词弃权）。vol04 A/B 组外格 0 变化，放行 +1（该册这三组几乎都已被放行，收益在没放行的册），L1 对整理本零冲突。`seed_admit` 的 `code_hash` f0f2713200ae880e → c3dbd4dac0582b47，其余 16 步不变。报告 [group_flow-4-vol04-报告](doc/exp/group_flow-4-vol04-报告.md)。
- group_flow 第五批八组（2026-10-19）：目自 `mz`（与日目 `rm` 共用「目」，互相声明 `overlaps`）、一二 `yr`、千干 `qg`、十卜 `sb`、甲申 `js`、而面 `em`、傅傳 `fc`、木本 `mb`，均形近不同义、按文意（L1 规则先行，弃权查 L2 haiku 表，只收 conf=high），补放也复核（只降审不改字）。L1 规则由整理本奇偶册交叉验证生成（两半都不矛盾才收），再手工剔掉「蔡傳」「王宗傳」「草本」类两可词，对 vol02–10 整理本零冲突；一二的 haiku 表对整理本有 5% 分歧，不稳，**一二只用 L1、不挂 L2 表**。vol04 A/B：组内格 0 降审、0 改字，补放 +4（千 1、十 1、傅 1、一 1；其中三格整理本为空，未逐格看图），其余 4000 多个组内格都是「文意与现放行字一致」；原因是这八组在 vol04 几乎都已被基线放对。`seed_admit` `code_hash` f0c37eac6214999c → e05fed6d5f32f4b7，其余 16 步不变。报告 [group_flow-6-vol04-报告](doc/exp/group_flow-6-vol04-报告.md)。
- group_flow：允许组成员重叠＋形近组复核＋日目组 `rm`（2026-10-19，sheldon 定）：①`GroupSpec.overlaps`（须互相声明），`flow.entry` 一个字可属多个组——补放选第一个装得下「分差内全部候选＋整理本字」的组，复核选第一个声明了 `review` 且装得下整理本字的组；日曰 `ry` 与新组日目 `rm`（L1＋L2 haiku 表）共用「日」，日曰候选归 ry、日目候选归 rm、三者混杂留人审。②已放行格复核（只降审、不改字）：`ry wxs ly dt wj zh yh xz wyu yt rm` 打开 `review`（原来只有 jys／rr）。③`seed_admit` 的待审补放通道（witness3／coord_fallback）不再把复核判了 `group_flow_disagree`／`_conflict` 的格放回去（原来降审被 coord_fallback 按整理本字又放行，白降；含 jys／rr 原有的降审）。vol04 A/B：复核降审 8 格（象彖 4、大太 2、問間 1、入人八 1，原来被放回去的那 1 格），无改字；日目 L2 表 57 格答 37；组外格仅 iron 通道 +3（本机重拉字形库后库内容变化所致，与本改动无关）。`seed_admit` `code_hash` c3dbd4dac0582b47 → f0c37eac6214999c，其余 16 步不变。报告 [group_flow-5-vol04-报告](doc/exp/group_flow-5-vol04-报告.md)。

## [0.3.4] - 2026-10-18

PATCH。语料库 corpus-vN（清单、册钉子、补指纹缺口）、group_flow 第二批异体组、清理旧字组代码。相对 v0.3.3 只有 `seed_admit` 的 `code_hash` 变（9d3e5deb232d84f2 → 6a4e2bd27c35fa8a），其余 16 步不变；各册 Step7 本来就要用新字组重算，下面各条自述的中间 `code_hash` 以此为准。没写 `corpus:` 的册其余指纹逐位不变。

### Added
- 册钉了语料库版本（`corpus: N`）后，读语料的 5 步（`glyph_match`、`rare_candidates`、`context_decide`、`align_ref`、`seed_admit`）的指纹整步多带一个 `corpus-vN`（P2，2026-10-18）：补上此前没有内容指纹的输入——形近表（`confusable_*`、`NEVER_MATCH_FAMILIES`）、`context_decide`／`align_ref` 的异体表、`rare_candidates` 的字表与部件库。几何步不受语料库升级影响。名单登记在 `core/corpus_pin.CORPUS_STEPS`（不放进 `StepSpec`，免得改 Step 源码让 `code_hash` 变）。没钉的册指纹逐位不变，17 步 `code_hash` 不变。
- 册 yaml 可钉语料库版本 `corpus: 1`（P1，2026-10-18，sheldon 定）：钉了之后，`params_for` 把参数里的语料类内容指纹（`core/corpus_pin.PIN_FIELDS`：整理本参考文本、证人、用字账、异体表、异体图、夹注词表、铁证形近、group_flow 字频／规则／答案表共 9 个字段）整体换成 `corpus-v1`，**指纹只认版本号，不看内容**；钉的版本没有清单就报错，清单之后文件被改只警告一次。**不写 `corpus:` 的册一字不变**；17 步 `code_hash` 全部不变（逐步对照 rc/v0.3.4 验过）。字形库、人裁排除名单、模型不属语料，指纹照旧。`ops/corpus_pack.py` 的清单读取与扫描挪进 `core/corpus_pin.py`。
- `guji corpus build|verify|list`（P0，2026-10-18，sheldon 定）：语料库 corpus-vN 的清单，登记流程里读的 51 份语料类文件（整理本参考文本、字频表、L2 答案表、规则、IDS、异体表、形近表、字表）的 sha256 和 `NEVER_MATCH_FAMILIES` 哈希，落 `<工作区>/corpus-pack/vN/manifest.json`；版本号递增、不覆盖；`verify` 发现清单之后又被改的文件。**只登记，Step 仍读原位置，指纹不变，17 步 `code_hash` 全部不变。** 方案见 `doc/design/语料库版本化方案.md`。
- group_flow 第二批异体组（2026-10-18，sheldon 定）：即卽（`ji`）、卿𨜊（`qing`）、變𠮓（`bian`）、彙彚（`hui`），只看字频：主形人裁 ≥20 且次形 0 才放行，数据不够送人审，重算字频表后自动放行。缺省关，按册在 `group_flow` 里点名。`seed_admit` 的 `code_hash` 6f24d51db9b8ebcb → 51a72b61d8354196（注册表在其 `code_deps` 里），其余 16 步不变。字形库清了 3 格误标（變 2、旨 1，工作区 events）。A/B 配置 `doc/exp/group_flow-2-vol04.yaml`、`group_flow-2-vol02-vol03.yaml`：vol04、vol02、vol03 三册新增放行共 3 格（都是卿），變 1 格弃权送审，旨㫖字频解封后放行不变，其余格一格没变。

### Removed
- 清理被 `group_flow` 取代、已无调用的旧字组代码（2026-10-18，sheldon 定）：删 `utils/ry_group.py`（日曰 ry-v2 答案表）、`utils/ji_yi_si_clf.suggest`（己已巳旧答案表）、`groups/backends.py` 的 `RyV2TableBackend`／`JysSuggestBackend`、`eval/groups` 的 `suggest:` 后端与 ry-v2 表识别（`table:` 只认 `group_clf/1`），及对应测试、`research/char_groups/{ry/build_cache,jys/build_clf_table}.py`、`scripts/_from_overview` 里量 group_decide 口径的 `ctx_caliber_compare.py`。`seed_admit` 的 `code_hash` 9d3e5deb232d84f2 → 6f24d51db9b8ebcb（改了 `utils/ji_yi_si_clf` 源码，在其 `code_deps` 里），其余 18 步不变。vol04 A/B：旧码 vs 新码，`seed_admit` 产物逐格一致。
- 删 `seed_admit.rare_cp_ctx_review`（罕用码位×context 落审，缺省关，无书在用；2026-10-18 sheldon 定）：参数、`_rare_cp_ctx_pass`、测试 `test_seed_admit_rare_cp_ctx.py` 及 `test_w5_demoted_from` 里的一条。`seed_admit` 的 `code_hash` 6f24d51db9b8ebcb → eba68e984cd2a5ae，其余 18 步不变。

## [0.3.3] - 2026-10-18

PATCH。字组统一流程 group_flow（新 variant-tie）：收编全部旧字组开关、字频与在线 IDS 两个新解法；删 Step5-c／Step6b。

### Added
- 字组统一流程 `seed_admit.group_flow`（新 variant-tie，2026-10-18 sheldon 定，缺省关）：点名注册表里声明了 `flow` 的字组（首批七个异体组 蒙𫎇／點㸃／參㕘叅／讖識䜟／隸𨽾／慎愼／旨㫖，三个形近组 己已巳／日曰／入人八）；没放行的格若库候选（与 top1 分差 <0.03）＋整理本字全在一组，按组声明的解法给字放行（通道 `group_flow`）或留人审，己已巳、入人八另对已放行格复核；每格写 `evidence.group`。新解法「字频」：按人裁刻形冻结每套书一张表（`python -m open_guji_cv.groups.freq <工作区>`），主形 ≥20 且次形为 0 才给字。`groups/registry.py` 新增 `FlowSpec` 与七组（`groups/flow.py`、`groups/freq.py` 进 `seed_admit` 的 `code_deps`）。PATCH；**`seed_admit` 的 `code_hash` 变**（与下面删 5-c 合计 a995ac96→03ad95f1），关时产物不变。
- `group_flow` 的 `ids` 解法接上在线判别（方案 S7，sheldon 10-18 定）：新模块 `groups/ids_online.py`，字块图自动缝一刀 → 决定字的那一段在冻结模板库里最近邻 → margin ≥ 门槛且该类刻例 ≥8 才给字，否则弃权，`evidence.group` 里留 IDS、部件、margin、各部件分数。首批只开 參㕘叅（`can`，门槛 0.04；人标池 74 格留一 59 对／15 弃权／0 错，留一册 57／17／0；叅只 2 例永不给），模板库 `config/groups/can/ids_bank.json` 由 `python -m open_guji_cv.groups.ids_online build can --dataset <dataset>` 从 dataset 人标池建（工作区 `config/groups/ids/<组>.json` 优先）；模板库、判法参数、`ids_override.tsv`、`ids_lv1.txt` 的哈希进 `group_flow_fingerprint`（没有在线 IDS 的组不加，旧指纹不变）。其余组（彝、慎愼、旨㫖…）没有模板库，照旧弃权且不取图。`groups/ids_online`、`ids`、`ids_two`、`ids_parts`、`ids_segment`、`ids_solver` 进 `seed_admit` 的 `code_deps`。PATCH；**`seed_admit` 的 `code_hash` 变**（ce3a31cce2908038→332a5956257e5a6b），关时产物不变。
- `group_flow` 的表路径：相对路径按工作区解释；没给时用工作区 `config/groups/freq.json`、`config/groups/l2/<组>.json`（有才用）。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。
- 字频表计数也认字形库体检的改字／撤库事件（`glyph_audit` relabel／evict），同格按时间取最晚。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。

### Changed
- 字组统一流程 `group_flow` 收编旧 m7 的全部字组（方案 S6，2026-10-18 sheldon 定「旧的都并进来、旧的删掉、每册都开」）：注册表给 土士 `ts`、未末 `wm`（文意＋量横）、戊戌戍 `wxs`（文意）补 `FlowSpec`；`FlowSpec` 加三个旋钮——`review_fix`（复核时文意给了别的字就改字，己已巳用）、`review_abstain`（复核时文意弃权就降审，己已巳用，接替旧 `ji_yi_si_clf` 对规则不命中的 `split_ref` 退役）、`lift_needs`（补放必须有这几路之一给字；入人八要文意，字形分类器不许单独补放）；复核时解法互相冲突也降审；形近护栏（`never_match`／`conflict`／`near_form`）不再挡字组；取上下文窗口时剔除排除名单格（与建 L2 表同一取法）。`always_review` 缺省仍是「己已巳」：vol04 A/B 上留着它比改成空多放 3 格对的、少 2 格错降（报告 `doc/exp/group_flow-S6-vol04-报告.md`）。**没在 `group_flow` 里点名 `jys` 的书，`split_ref` 放行的就是整理本字、不再复核**（旧 `_resolve_ji_yi_si` 删了）。vol04 A/B（旧开关全删＋13 组 vs 现行配置）：组外格逐格不变，放行 +47，强真值上放行 72 对 0 错 → 81 对 0 错，错降 1。PATCH；**`seed_admit` 的 `code_hash` 变**（与下条删旧开关合计，以 S7 之后为底 332a5956257e5a6b → 9d3e5deb232d84f2），各册该步判过期，其余 16 步不变。

### Removed
- 旧字组开关并进 `group_flow` 后删除（方案 S6）：`SeedAdmitParams` 删 `ji_yi_si_review`、`ji_yi_si_ctx_rule`（`_purity`／`_min_n`／`_fingerprint`）、`ji_yi_si_clf`（`_llm`／`_margin`／`_table`／`_fingerprint`）、`ry_group`（`_cache`／`_fingerprint`）、`rr_clf`（`_p`／`_model`／`_fingerprint`）、`m7_groups`／`m7_l2_tables`／`m7_fingerprint`／`m7_bars`、`variant_tie`（`_cov`／`_extra`）共 24 个字段；删 `_resolve_ji_yi_si`、`_ji_yi_si_clf_cell`、`_ctx_known`、`_ry_group_pass`、`_rr_clf_pass`、`_m7_group_pass`、`_variant_tie_ok` 与主循环的 `variant_tie` 通道；删 `groups/m7_pass.py`（`judge`／`fingerprint` 挪进 `groups/flow.py` 为 `ctx_judge`／`ctx_fingerprint`）、`groups/apply.py` 与注册表的 `GroupPolicy`／`GroupSpec.policy`、`utils/ji_yi_si_clf.STRONG_CHANNELS`。`seed_admit` 的 `code_deps` 去掉 `utils.near_form_ctx`、`utils.ry_group`、`groups.m7_pass`、`groups.apply`（`utils/ry_group.py`、`utils/near_form_ctx.py` 只剩离线评测用）。书 yaml 里的旧键读进来被忽略（pydantic 缺省忽略多余字段，不报错），应从十册 yaml 里删掉；`tests/test_group_params_guard.py` 的白名单清空。PATCH；`code_hash` 见上条。
- 删两个不再用的步骤（2026-10-18，sheldon 定）：Step6b `group_decide`（连同产物 `group_decision`、书级 `group_decide:`）与 Step5-c `ocr_candidates`（连同产物种类、书级 `ocr_candidates:`、控制台开关 `PUT /api/books/{book}/ocr_candidates` 与汇总 `GET /api/ocr-candidates/{book}/summary`、前端 5-c 子页）；两条 pipeline yaml 去掉这两步，老 yaml 里的两个键读进来无作用。`align_ref`／`context_decide`／`seed_admit` 不再把 `ocr_candidates` 列为可选上游，OCR 一路恒缺席（等价于原先开关关着，四庫 vol01–10 输出语义不变）。**这三步 `code_hash` 变**（215217611967ce6c→e66b1c3f632c469a、043c75a9ba56ddae→4a12db2db381a543、a995ac964c981e29→03ad95f1c34eb510（连同本版 group_flow）），各册这三步判过期；其余 14 步不变。

## [0.3.2] - 2026-10-17

PATCH。版本护栏、冻结基线、`archive fetch`、`rerun --stale`、规矩文档（没赶上 0.3.1 的 4 个 PR），中心库导入（`datastore`），以及 GUJI-555／622 积下的几个缺省关开关（夹注忽略 rule_bar、遮挡救回、绑定严格档、column_gate 周期先验）。

### Added
- 产物 manifest 每条记 `cv_version`（最近正式 tag，不在 tag 上写 `0.3.0+N`，有未提交改动加 `+dirty`）与 `cv_commit`（完整 sha）；册配置可写 `cv_version`，`guji step`／`pipeline` 发现装的版本不同就拒跑（`--allow-cv-mismatch` 放行），`status`／`progress` 只提醒（GUJI-577，版本号规矩第五节）。PATCH；`core/engine.py`、`core/book.py`、`core/cv_version.py`、`products/manifest.py` 都不在任何 Step 的 `code_deps`，新字段不进 `book_deps`，19 步 `code_hash` 不变。
- 冻结基线（GUJI-601，规矩见 ai-team `domain/CV/规范/冻结基线与重跑分级.md`）：册 yaml 写 `freeze: {at, cv_version, snapshot|manifest}` 后，`guji close-check` 1a 改比快照 manifest 的产物 sha256，不再因 cv 升版、人裁进库报过期；只有产物被改／缺、册配置或参数被改才不过（各步 `_manifest.jsonl` 不比；旧条目分不清代码还是册配置的单列请人核）；另报「基线后新人裁 N 条待落地」（`ops/freeze.py`）。PATCH；`ops/`、`core/book.py` 不在任何 Step 的 `code_deps`，`freeze` 不进 `book_deps`，19 步 `code_hash` 不变。
- 新命令 `guji archive fetch <tag> --out <空目录>`：取回 open-guji-dataset Release 上的归档 tar，按 `--sha256` 或资产自带 digest 核对后安全解包（拒越界路径、设备文件；跟随重定向跨域时去掉 token）（`ops/archive_fetch.py`，GUJI-601）。PATCH（10-18 起新 CLI 命令只算 PATCH）；不碰任何 Step。
- 新命令 `guji rerun --stale <册>`：只重跑 manifest 里显式标了失效（人裁落定等）的页，逐步往下传，只把上游真重算了的页交给下游；上游跳过的页不往下传，因 cv 升版、字形库变化而过期的页不跑（`ops/rerun_stale.py`，GUJI-578，设计 §5.2 第 4 条）；与 pipeline 一样过 cv 版本护栏（`--allow-cv-mismatch` 放行）。PATCH；不碰任何 Step，19 步 `code_hash` 不变。
- 中心库 `open_guji_cv/datastore/`（GUJI-603／605）：Postgres 表结构 `schema.sql`；从 guji-workspace 某个提交幂等导入（`python -m open_guji_cv.datastore import`，按主键比内容哈希、全局 rev、只追加台账的删除护栏）；库与提交逐行核对（`verify`）；刻例图与锚图按 sha256 上 R2 的计划与上传（`r2-plan`，默认只出清单）。新 extra `datastore`（psycopg、boto3、websockets）；只通 443 时用 `datastore.wsbridge` 经 Neon 的 WebSocket 连库。说明见 `doc/datastore.md`。PATCH；新包，19 步 `code_hash` 不变。
- 闸2 `column_gate` 两个周期开关（GUJI-622／GUJI-364，vol01 p196）：`period_prior_pages`（点名页不估页级周期，直接用书级 `period_prior`，记 flag `period_fallback`）与 `period_edge_fallback`（估值贴窗口下界 ≤ int(先验×0.7)+1 时回落先验）。都缺省关，关时不进参数 dump、产物逐字节不变。PATCH；**`column_gate` 的 `code_hash` 变**（8935ff6f → 25658f2b），各册该步判过期，重跑后产物不变、下游不重算。
- 人裁绑定 R1/R3 严格档（环境变量 `GUJI_BINDINGS_STRICT`，缺省关，关时行为逐字节不变；GUJI-555）：补锚 ink 路径 rebound 且上下文核对 `differ`→待审；同页同列整列同量偏移无 ctx 旁证→待审；`human_chars` 同格更晚事件不可用时更早事件不顶上、rebound 落点有更晚原生事件时让位。动 `feedback/`，19 步 `code_hash` 不变（worktree 复算）；开关不进参数指纹，开了要手动重算 seed_admit。
- `seed_admit.nonchar_jiazhu_ignore_rule_bar`（缺省关，方案 A）：开了 `nonchar_gate` 对夹注格不再因 `rule_bar` 撤回放行；关着不进参数哈希（GUJI-555，vol04 p216／p218）。动 `seed_admit` 的 `code_hash`，**seed_admit 及下游步产物判过期**，窗口合并，同 cv#102 只让该步过期一次。
- `seed_admit` 参数 `occluded_rescue_ink`（缺省 0＝关）：遮挡块里格内大块墨占比 ≥ 该值的清楚的字格不算遮挡（GUJI-555，vol04 p130 前 8 格误判 occluded）。`cell_shrink`、`seed_admit` 的 `code_hash` 变（`steps/occlusion.py` 在二者 `code_deps` 里），关着时输出不变。

### Changed
- 版本号规矩（`doc/版本号规矩.md` 第二、三、六节，用户 2026-10-18 定）：任何时候都有一条待发分支 `rc/vX.Y.Z`（缺省 PATCH 加一，CHANGELOG 记在 `## [X.Y.Z] - 待发` 节），功能分支合进它、不直接合 main；合进来的改动缺省关、随时可发，谁都可以发 PATCH；MINOR 收紧为「对大部分册值得重跑一遍」，新增 CLI 命令或参数只算 PATCH。文档改动，PATCH。

### Fixed
- `close-check` 2b「人裁字≠放行字」：字形与放行字互为规范字／异体（埀↔垂 类）的单列 `kind=canon`，不再混进正文一类（GUJI-555）。PATCH；仅 `review/verdict_view`、`cli_v2`，19 步 `code_hash` 不变。

Step 的 `code_hash` 相对 `v0.3.1`：`column_gate`（GUJI-622）、`seed_admit`（夹注忽略 rule_bar、遮挡救回）、`cell_shrink`（`steps/occlusion.py`）3 步变，其余 16 步不变；新开关全部缺省关，关时产物不变。

## [0.3.1] - 2026-10-17

集成分支 `rc/v0.3.1`，M7 扩展（第二阶段）；各功能 PR 合入时在此补条目。

### Added
- M7 上下文路扩展：戊戌戍／未末／土士的 L1 规则与 L2 提示词（`config/groups/{wxs,wm,ts}`）及研究脚本 `research/m7/ctx/ext_*.py`（#118）。**尚未接线**（registry 无对应 GroupSpec），不生效；19 步 `code_hash` 不变。
- M7 量横画法：土士／未末按两横长短取字的研究脚本 `research/m7/bars/` 与结论文档（#119）。仅研究脚本与文档，19 步 `code_hash` 不变。

- 量横长短 ts／wm 接进 `seed_admit`（书级开关 `m7_bars`，缺省关）与 registry 的 wxs／wm／ts 登记（#120、#121）；IDS 两段版 `groups/ids_two.py` 与參㕘叅配置（#117，未接 Step）。

Step 的 `code_hash` 相对 `v0.3.0`：仅 `seed_admit` 变（684cd42c → a60d8f25），其余 18 步不变。vol04 组合 A/B 见 `doc/exp/m7_rc031-vol04-报告.md`：组外差异 0。

### Fixed
- 引擎页级并行（`--jobs>1`）：worker 改由主进程直接传入册、管线、合并后的参数与产物／缓存根目录，不再按 id 重新加载。以前 CLI `--params` 与管线 yaml 的 `params:` 在并行步（`border_detect`、`line_detect`）上全丢，产物按缺省参数算、指纹却记覆盖后的参数；沙箱 `ProductStore` 也被忽略（GUJI-580）。PATCH；`core/engine.py` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。

## [0.3.0] - 2026-10-17

### Added
- Step1 `border_detect`：窄对合并 `merge_narrow_pair`（缺省关，不进参数 dump）：相邻两条内部窄列、宽度和≈一列时用 `expected_cols−1` 重探，去掉把大字列劈成窄条的伪竖线（GUJI-572，vol04 p80／p217）。`border_detect`、`border_detect_gate`、`column_gate` 的 `code_hash` 变，关着时输出逐字节不变。
- M7 形近字优化算法（GUJI-563）的库代码 `open_guji_cv/groups/`：IDS 路（`ids*.py`，彝六字形，通用 IDS 语法、折线切分、字体模板二选一）与上下文路（`context.py`/`ctx_l1.py`/`ctx_l2.py`，日曰／己已巳／入人八，上下各 20 字）；注册表加 `kind`／`solvers`／`config_dir`；`config/groups/<组>/` 规则与提示词。**尚未接进任何 Step**，缺省不生效。
- `seed_admit` 的 M7 接线开关 `m7_groups`／`m7_l2_tables`（缺省关）与 `groups/m7_pass.py`（GUJI-563）；`doc/exp/m7_groups-vol04.yaml`、`doc/exp/跑实验经验.md`。
- 设计与评测：`doc/design/M7-*.md`、`research/m7/`。
- `scripts/zhengli/collect_exit.py`＋`exit_report.py`：对一册自动取粗校出口 R1–R5 的数并拼固定格式报告（GUJI-556）。PATCH；仅 `scripts/`，19 步 `code_hash` 不变。
- `guji close-check --tier rough|final`（缺省 `final`，行为不变）：粗校档第 2 项「待审清零」只报数、不计（GUJI-555）。PATCH；仅 `ops`/`cli_v2`，19 步 `code_hash` 不变。
- `guji pipeline --isolate-steps`：每个 Step 一个独立子进程跑（默认关），整册跑时内存不再逐步叠加（GUJI-555）。PATCH；仅改 `cli_v2`，19 步 `code_hash` 不变。
- `scripts/relanding/`：重落后核对脚本（manifest_cmp／relanding_diff／products_snapshot），从 guji-workspace 的 exports 迁入（GUJI-555）。PATCH；仅 `scripts/`，19 步 `code_hash` 不变。

### Fixed
- `guji snap import` 认 `GUJI_PRODUCTS_DIR`（沙箱），不再无视它写进工作区本体的 `products/`（GUJI-555）。PATCH；`snap/` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。
- 导出（`export format`／`export_guji_page.py`）：看图判错、人还没裁的放行格记 `review: pending`（并带 `vision_flag` 标记），不再当已校对写进 char.json；与 close-check／控制台待审同口径（GUJI-555）。PATCH；`formats`/`feedback` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。

Step 的 `code_hash` 相对 `v0.2.1`：`border_detect`、`border_detect_gate`、`column_gate`、`seed_admit` 4 步变化，其余 15 步不变（实算 `core.engine.code_hash`）；新参数缺省关、关时不进参数 dump。

## [0.2.0] - 2026-10-17

### Added
- guji-proof 0.2 审阅字段模块 `open_guji_cv/review/proof_fields.py`。
- 统一字组接口 `open_guji_cv/groups/` 与统一评测 `open_guji_cv/eval/groups.py`（尚未被任何 Step 引用）。
- 字组参数守卫 `tests/test_group_params_guard.py`：不许再往 `SeedAdmitParams` 加新的字组参数。
- 包分层守卫 `tests/test_architecture.py` 与 `doc/module_map.md`。

### Changed
- 版本号规矩改为 `vX.Y.Z` tag、按 PR 滚动升版。

### Removed
- 旧 exe 发布流水线 `release.yml`（移至 `doc/archive/release.yml.legacy`）。
- 死代码：`steps/step6_signals.py`、v1 桥。

Step 的 `code_hash` 相对 `cv-v0.1.0` 无变化（19 步逐位相同）。
