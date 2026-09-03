# Open Guji CV - 项目说明

## 语言
- 默认使用中文进行交流

## 项目概述
古籍图像 OCR 分析项目，使用 PaddleOCR 对古籍扫描图片进行逐字识别和位置分析。

## 当前策略（2026-08 起）
**只优化正文页。** 目录、职名、序跋、牌记等非正文版式先放着——各有各的
排版规矩，混在一起调参会互相牵扯。指标一律按「正文/非正文」分开报。
正文页由 `open-guji-dataset/page-type` 金标里 `page_type == "body"` 筛出
（vol01 **108** 页 / vol02 **全书 186 页**——vol01 全书 206 页只标了 108 页
正文，其余是目录 47/职名 44/空白 3/等；旧文档一直写"296"，2026-09-02 查证
是错的，已更正）；管线自己目前**分不出来**
（`classify_page_type` 把 roster/toc/edict 都归 body），这本身是待办。

---
## 文档

**先看这份 → [.claude/doc/pipeline_handbook.md](doc/pipeline_handbook.md)**
分步现状、各步的测试集在哪、哪些步骤能并行、以及踩过的坑。接手任何一步
之前都应该先读它。

| 文档 | 内容 |
|---|---|
| [pipeline_handbook.md](doc/pipeline_handbook.md) | **总入口**：分步现状 / 并行分工 / 量法 / 踩过的坑 |
| [console_architecture.md](doc/console_architecture.md) | **总体架构（2026-09-03 overview 下发）**：Step / Product / Gold / Event 四个抽象 + 本地控制台 + 存储分层 + 分阶段落地（P0 骨架 → P4 扩展）；实现控制台、数据集抽象、反馈路由前先读；任务清单在 `.claude/todo.md` |
| [console_manual.md](doc/console_manual.md) | **控制台使用手册**：怎么跑管线 / 看产物 / 收人裁 / 跑评测；典型工作流与排错。**要用这套东西干活先看这份**，架构为什么这么设计再看上一行 |
| [segmentation_v2_pipeline.md](doc/segmentation_v2_pipeline.md) | **切分管线重定义（进行中）**：边框探测/单列射影变换/单列文字切分/字框收缩四步，每步严格输入输出+测试集现状；坐标系改为右上角原点+从1计数。Step1（边框探测）已定版含内外边框+抬头框，金标 14 页 `open-guji-dataset/border-detection`；**外边框自动探测 `detect_outer_borders()` 已接入**（口径=外延；先测竖直外框拿 `abs(v_outer_offset)` 当页级间距先验、按边校正后在其 ±16px 里找）。**用户判据「内外间距全页一致」已修正为「只在同一条边上成立」**——四边不等距，清楚页同页实测竖直外延间距比 top 大 10.8±4.5px、比 bottom 大 5.9±4.2px（n=5）；原先看着「全页一致」是取样偏差（只量了竖直和抬头框，都属竖直一族）。按边校正后对真墨外延 top 1.6→1.2px、bottom 5.6→0.9px（`v_outer_side` 14/14、`v_outer_offset` 2.9px）。**这一项必须拿真墨当基准**：top 对金标反而「变差」3.3→5.5px，是金标错——vol01/14 金标 38.6px、真墨外延 21.2px、算法 20.5px。**上下外框有一半不该报数**、一律 None（降门槛凑覆盖率是负结果，弱档 6 例里 3 例超 10px）。**版框几何常数**（`scripts/measure_frame_geometry.py` 抽 90 页、106 条清楚边实测，px 均值±标准差，口径=内框线心为 0 向外）：上框 线宽 5.8±0.7 / 外条宽 16.3±5.5 / 近沿 19.6±4.6 / 外延 35.9±6.6；下框 5.7±0.6 / 16.4±3.3 / 17.8±2.4 / 34.3±3.7；竖直 4.5±0.6 / 19.6±2.1 / 20.4±2.3 / 40.1±3.1。**四边不等距**：同页配对差 竖直外延比上框大 4.2±6.5（中位 3.6, n=23）、比下框大 6.3±3.9（中位 6.8, n=12）。**负结果：这两个差不能用小样本拟**——头一版拿 5 页拟出 top=−10.8/bottom=−5.9，扩到 90 页后 top 差了 2.5 倍（真值 −4.2），而 14 页金标评测在 −3~−10.8 之间分辨不出来（都 1.2~1.3px），挑不出对的值，只能直接量。「清楚」这道闸必须含**内框线宽 ≤10px**，否则末行字的墨会混进来（下框外延 34.3±3.7 会被拉成 30.3±9.8）。**负结果：外条近沿不可用**（外条从内侧磨掉，近沿 +15→+34 漂，远沿只 +33→+45），只有远沿可用来反推。**vol01/137/138/141 的 `bottom_inner` 金标是对的**（一度误判为脱靶）——两个量法教训：旧 `eval_border_hlines_vs_ink` 只拿金标当脊线种子、结构上不可能输，它报的「47 top 差 23.9px」「51 bottom 差 15.5px」都是假象（换中立量法后 28 条边 23 条本来就重合）；判「有没有线」不能用绝对墨门槛，要用**相对本底的局部峰 + 空间相干性**（本底 0.000，金标处 0.02~0.10 已是 8~39 倍；清楚页 250~450 倍，是连续衰减谱）。算法在这三页反而都错（咬末行字 / 落在外条上）。审查页 artifacts/README.md 有台账；`find_horizontal_border` 窄窗口第二候选修复 + `find_vertical_lines` 精修去重bug修复均已落地（top 1.9px、bottom 7.0px、竖直线 2.7px 均值）。**抬头框自动探测 `detect_head_raise()` 已定版并接入**（13/13 可观测金标全中、8 页普通页零误报、**inner 0.6px / outer 0.4px**——原本报 6.9px / 3.3px，金标按真墨重拟后双双降到亚像素，那几个 px 全是标注口径的差）——关键在于先把 18 个金标的墨占比/半高宽逐个量出来再设计判据：outer 有"粗满墨条"和"整条没印上"两种形态所以不能要求内外成对（v3 那版召回崩到 28%），墙线检查必须是块级不是列级。真抬头判据也踩过坑——"边框上方有字凸出"不可靠，正确判据是"边框线本身有台阶"。**Step2 已扩为「射影变换+去噪+界行清除+上下版框清除」并收了真实页面金标**（`char-segmentation/column-warp`）：新增 `clean_column` 固化收尾顺序（原来"先抹白再定文字带"会把水平投影稀释 9%，负结果已记）。金标**按输入口径拆成两套**（`samples/`=算法边线+逐列窗口，端到端 17 列命中 30/34、切字 0 列；`legacy-page-anchor/`=人工金标边线+页级锚点，隔离 Step1 误差 25 列命中 43/50）——两条链路边线差 0.76~27.6px、列图宽差 38px，不能混比。金标已被上游改动作废过三轮，**复核必须对全部原始标注跑**（有 2 条上一轮失效、这一轮又有效）——这套复核已固化成 `scripts/migrate_column_warp_gold.py`：文字带按"人标点处墨量还≈0 吗"留用、上下版框按**端裁剪图的指纹**留用（**不拿算法一致性当判据，那是循环论证**），主判据是**图像指纹**「人当时看的那张图还在不在」、零墨只当 clean 列的补救通道（拿零墨当主判据会把 mixed 列全误报成失效，已修）；两页各 32 列/64 条端裁决**全部标完**，文字带命中 58/64、上下版框类别一致 60/63；「先清左右再做上下」漏过一种界行（弯界行只在列的一端探进带里，整列一个带看不见）——已改分横条 + 补内缩档，负结果：内缩条只看峰值分不开（字身腹地峰 0.533 vs 界行条 0.40）；`border_class` 因窗口口径变更**一条都不能迁**（新窗口故意把版框线放在第 0 行，上端"没残墨"从 24 列掉到 6）；判据改过一版（旧的"体+裙边"两头翻车：糊掉的界行漏判、淡竖痕啃穿 21px），现在是"扫到窗口最低点"。上下版框按用户给的 a/b/c 三档实现、实测补出第四档 d「内缩版框」（x=0 锚点越过真实版框的后果），金标**只记类别不记坐标**、已收 23 条端裁决**一致 22/22**；「行墨占比当判据」是负结果（字身行最高 0.747 跟版框线完全重叠，只能靠"墨段厚度"分：版框线 3~13 行 vs 首字 91~121 行）。`out_w=max` 会不会压扁内容已查清=不会（射影映射把每行都归一到 out_w，max/min 只改整体分辨率）。**Step3（单列文字切分）已定版**：输出格式冻结成带类型的字格（字/空白/抬头/夹注a/夹注b + 列内读序，`row_boundaries.segment_column`），生产的双行小注 a/b 拆分已迁移进新链路（`jiazhu_split.py`，逐条保留原阈值 + 漂移护栏单测）；新链路独有的坑是列图两侧压着界行会让夹注跨度判据整体失效，已加 `find_content_window` 剥墙。vol02 40 页对照生产标注：Step1 把列切对的 26 页里 29 个夹注列 27 列逐格全对、1 列差一格相位、1 列比生产多检出一格（目视是生产漏了）。顺带用金标复测推翻了「抬头列多一格修不好」的旧结论——根因只是 `top_slack=1×period` 不够，开到列图顶端后误差 88.2px→12.3px。**vol01/47「竖直线系统偏斜」已查明是假问题**：金标是人工拖的直线、界行本身是弯的，用真墨脊线当第三方基准重量，**算法比人工金标更贴真墨、没有一页反过来**（47 上贴近 3.25px），原定的「挖抬头墙线」修法作废。**金标已按真墨重拟并入库**（用户授权；140 条改 119 条，金标离真墨 2.20→1.41px、天花板 1.28px，现在 14/14 页金标都比算法贴；人工原值留档 `verticals_inner_manual`，脚本 `open-guji-dataset/scripts/refit_border_vlines.py --apply` 幂等）。**抬头框同样重拟并定版了坐标口径**：`inner_y`=线心（13 例，原值全部同号偏低 4~11px、根本不在墨上）、`outer_y`=外延（11 例；探测器也一并改成外延，否则带 +2~4px 系统偏差），金标新增 `inner_observed`/`outer_observed` 标注每个坐标是不是量出来的（vol01/51 c2/c8 外框根本没印上）。坑在于墨占比门槛必须是绝对值，外框满墨时相对门槛会把浅的内框整批杀掉。两个教训：目视叠加图只能说明两条线不一样、不能说明谁对；量法本身要先验证——第一版脊线提取太松（窗口 ±50px、无亚像素、无剔外点、含最外两条），把距离和弯曲幅度一起虚高了约 3 倍。**Step2→Step3 交接闸已落地**（`scripts/export_step3_input.py`）：三级准入L1 页级(Step1 切对列) / L2 列级自检(两侧找得到零墨边界) / L3 人裁金标，vol01 126 列推出 24 列 12 页、`segment_column` 24/24 有解；页级 `period`/`ref_w` **用该页全部 9 列算**（准入闸管的是推哪些列去切，不是谁参与算页级先验），`content_x` 必须随图传（图是抹白不裁切的，Step3 的 `find_content_window` 在上面一堵墙都找不到、24 列全返回整幅宽，宽 9.6%）。**负结果：除 L1 外没有第二条经过验证的列级筛选力**——「清理后带内残墨」是循环论证（mixed 列 0.008 反而低于 clean 列的 0.088）、「带宽偏离页中位数」区分不出来、L2 现用的「两侧最低墨」clean 上限 0.0109 vs mixed 下限 0.0136 只差 24% 且 mixed 只有 n=2、实测一列都没多筛掉。下一步：**专门去标 mixed 形态的列**把 L2 真正标定出来 / **Step1 列探测已用 60 页人裁直接量过：正确率 56/60 = 93.3%**（ok 56 / 线压在字上 2 / 有缝漏切 2 / 拿不准 0；等距抽样 page_type==body，不是按可疑度挑的，95% 区间约 84~98%）——**这推翻了此前一直沿用的「40 页里 13 页没把列切对」（67%）**，那个数字来自另一条链路的间接统计、不是直接人裁，却被当成「准确率的封顶因素」用了很久，**封顶因素需要重新找**。金标 `open-guji-dataset/border-detection/column-split/`。**弯页已换三段折线**（用户方案，已落地）：`VLine` 从 (x,k) 扩成 (x,k1,k2,k3)+折点 y1/y2，`k2 is None` 即直线、下游只调 `x_at()` 的代码不用改；整页统一（`vline_segments`），直线拟合下 w80 中位≥**7** 或单条≥24 才切（7 是量出来的：7~9 档 18/18 页强制折线后全降到 4~5，切约 31% 的页）。拟合直接搜四个折点 x（不按 k1→k2→k3 贪心，误差会下传），目标=相邻段墨落在线上的加权行数（三角核 {0:3,±1:2,±2:1}，±1 硬窗口在 5px 宽的线上有平台定不到线心）。Step2 `warp_column` 按折点分带射影再拼。真页：vol01/151 w80 16.5→5、47 14→5、vol02/95 18→5、119 21→7、11 9→4。**量改前必须用 `verticals_straight`**（拟合前留下的直线）——三段页的 `x_at_top/slope` 是第一段外推值，拿它当原直线量出来的改前数全偏（151 曾报 20、47 报 25）。**三段折线的表达上限已记死**：每段都是直线，只能吃「整条平滑弯曲」（151/47/95 型全修到 w80 4~5）；吃不住**段内还带曲率**的——vol01/119 L1 真线是「直—弯—直」，中间那段用直线表示不了，用户裁定**不增段就调不动、按现状收金标**，别再往 KNOT_SEARCH/窗口上使劲。另：**有些线墨少到指标量不出来**（vol01/11 L1 很虚，算法线和人工金标线的 w80 都是 null，靠人拖定位、`gold_origin=human`）——**拿 w80 自动评测要排除 null 的线**，否则当成回归失败。折线金标 `open-guji-dataset/border-detection/vline-polyline/`（3 页 90 段，approved 83/90）。**行过滤必须有局部一致性闸**（相邻 9 行 x 中位差 >3px 剔）：vol02/3 曾被判最弯（w80 36）其实是直线断处混进笔画碎片。**界行「直不直」已有指标**（用户给的判据）：整条界行投到 x 轴，越直峰越高越窄；用 `w80`（装下 80% 墨的最窄 x 跨度），`scripts/measure_gutter_straightness.py`。200 页实测（加一致性闸、用拟合前直线量）**w80 中位 6.0px**（75 分位 7.0 / 90 分位 10.0 / 最大 17），门槛 7 切 **35%** 的页；最弯：vol01/119 (21.0)、vol02/95 (17.0)、vol01/151 (16.5)、vol01/69 (16.0)、vol01/47 (13.0)。**旧榜单 20+ 的数字是错的**（拿三段线第一段外推当原直线量的），vol02/3 (曾报 36) 其实是直线。**必须同时看 `w80_max`**——vol02/3 峰值 0.827 却宽 20，vol01/11 页级中位仅 9.5 但单条 `w80_max` 到 64，这种「一条线跑飞」看中位会漏。该指标独立复核了旧结论「vol01/47 是界行本身弯、不是算法偏斜」。**外框「条外必须是纸」闸已落地**（`_paper_beyond`，门槛 0.11 由 108 条人裁标定）：健康页外条之外行墨恒为 0.000，而 vol02/153、vol02/75 的 bottom 一直 0.126~0.178——根因是 bottom 内框线没落在下版框上、外框探测在正文里挑了最黑一段，线直接穿过文字；**门槛压不到更低因为抬头页是真例外**（抬头框就在上框外，vol01/52/49/58/134 有 0.028~0.094 且人裁 ok）。已知两种坏形态（用户实审点名）：vol01/151 界行**S 形弯**、端到端偏离直线约 30px（清楚页 3.6px），线上墨 0.44~0.57 vs 印得好的 0.79~0.99，直线 VLine 模型跟不上；vol01/11 界行**顶端向右勾**约 20px，另有第 10 条是**落在正文笔画上的假线**（线上墨 0.162、末档列距 155px vs 其余 179~187px）。**图源确认干净**：`rebuild_src/vol02` 与下载源 `data_zongmu/zongmu_v01` **187/187 字节相同**，没跑过任何预处理；`peak_line_search.py`/`border_geometry.py` 里一个 cv2 调用都没有，不存在直线增强。看着「像增强过」是因为**扫描件本身就是 1-bit 双值 TIFF（CCITT G4）**，全库没有灰度原图可退。扩大抬头框金标（现仅 6 页 18 例，形态常数有过拟合风险） |
| [char_clustering_design.md](doc/char_clustering_design.md) | 刻本字符切分与聚类的完整设计与实测记录（最厚的一份）|
| [charset_and_lm.md](doc/charset_and_lm.md) | 字表标准（字体 cmap + Unihan）与语言模型混合（通用低权重 + 本书高权重）|
| [glyph_db_expansion_research.md](doc/glyph_db_expansion_research.md) | 字形库扩展：开源字形/异体字数据地图、分层扩库路线（P0 异体字关系层 + P1 字体字形已实现）与**字体字形匹配力实测**（§6）|
| [glyph_canonical_format.md](doc/glyph_canonical_format.md) | 字形图块统一存储格式（256×256 灰度、只缩不放、质心居中）与迁移记录 |
| [review_feedback_loops.md](doc/review_feedback_loops.md) | **审阅反馈三环总入口**：切分回流 / 匹配回流 / 准入规则标定（含短笔画被咬的三源修复记录）|
| [glyph_match_stack.md](doc/glyph_match_stack.md) | **字形相似度匹配栈交接**：四层算法链 + glyph-match/triplets 测试集 + 回归护栏 + 已知失败形态（匹配优化专题从这进）|
| [glyph_match_research.md](doc/glyph_match_research.md) | 匹配算法调研：我们这层在文献谱系里的位置（IDM 零阶形变模型）+ 四条改进路线与引用文献 |
| [design.md](doc/design.md) | 预处理框架（s0~s6 + Phase 2/3）总体设计 |
| [phase2_detectors.md](doc/phase2_detectors.md) | 版面检测（边框/列）|
| [peak_line_search.md](doc/peak_line_search.md) | 投影峰匹配找版框线（半高宽匹配度 + 位置角度联合搜索）：跟 `border_detect.py` 并存的实验性替代方案，5 页试跑 + 已知局限（抬头页/职名页）+ 意外发现 vol02/133 底边框偏差 41px，**未接入生产管线** |
| [row_boundaries_design.md](doc/row_boundaries_design.md) | 列内字格纵向边界（弹性DP，候选=波谷+页面共享周期先验+三层硬约束）：vol02/135、vol01/33 两页验证，均值误差2.5~4.2px；含抬头列 `top_slack` 修法与已知局限；记录十几版失败尝试各自的坑（整段滑格/独立snap漏选/自估周期偏差），**未接入生产管线，作为并行算法落地** |
| [phase3_char_grid.md](doc/phase3_char_grid.md) | 字符网格切分 |
| [technical_learning.md](doc/technical_learning.md) | PaddleOCR 版本/环境坑 |
| s1~s6_*.md | 各预处理步骤 |
| [jiazhu_detection.md](doc/jiazhu_detection.md) / [edge_border_analysis.md](doc/edge_border_analysis.md) | 夹注检测 / 边框分析 |
| [segmentation_border_feedback.md](doc/segmentation_border_feedback.md) | 进库实审回流给切分层的反馈：边框混入四个惯犯位置 + 重切 bbox 金标 |
| [../artifacts/README.md](../artifacts/README.md) | **Artifact 登记处**：各审查页的 URL 台账 + HTML 快照 + 再生方法（更新必须重发布到同一 URL）|

数据集与评测在隔壁仓库 `open-guji-dataset`，入口见其
`doc/making-datasets.md`（怎么定义和准备一个测试集）。

----
测试数据：
data/ 文件夹下边 有5本古籍 每本古籍有10个截图 和一个read me文件 来介绍它的基本的排版信息

### 字形库
跨书字形库真源在 `glyph_store/`（随仓库提交），SQLite 索引可重建：
```bash
python -m open_guji_cv glyph-db rebuild        # 刻本字形（真源在 glyph_store/）
python -m open_guji_cv glyph-db import-font --jobs 4   # 字体字形（约 10 分钟）
```
字体字形不进 Git，由 `fonts/` 里的字体档 + 字表确定性重建，详见
[fonts/README.md](../fonts/README.md) 与 glyph_db_expansion_research.md §6。

### 环境变量
- `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` — 跳过模型源连接检查，加快启动速度
- `PYTHONIOENCODING=utf-8` — Windows 控制台中文输出必须设置

### 本机环境（2026-09-03）
- 仓里的 `venv/` 指向已卸载的 Store Python 3.13，**是死的**。用 `.venv/`（uv 建，Python 3.12）：
  `uv venv .venv --python 3.12 && uv pip install -e . pytest fastapi uvicorn pydantic pyyaml opencc-python-reimplemented`
- pytest 在本机会吞掉终端输出，要结果就加 `--junitxml=…` 再解析。

### 四个抽象（v2）快速上手
```bash
.venv/Scripts/python -m open_guji_cv pipeline keben_body_v2 vol01            # dev_set 12 页，Step1→Step4
.venv/Scripts/python -m open_guji_cv step border_detect vol01 --pages 24,42   # 只跑一步
.venv/Scripts/python -m open_guji_cv status vol01                            # 各步各页 新鲜/过期/缺失
.venv/Scripts/python -m open_guji_cv console                                 # http://127.0.0.1:8640/
```
产物在 `products/<book>/<step>/p0024.json`（只有数值），列图 / 字块在 `cache/`，任务记录在 `runs/`。

