# Open Guji CV - 项目说明

## 语言
- 默认使用中文进行交流

## 项目概述
古籍图像 OCR 分析项目，使用 PaddleOCR 对古籍扫描图片进行逐字识别和位置分析。

## 当前策略（2026-08 起）
**只优化正文页。** 目录、职名、序跋、牌记等非正文版式先放着——各有各的
排版规矩，混在一起调参会互相牵扯。指标一律按「正文/非正文」分开报。
正文页由 `open-guji-dataset/page-type` 金标里 `page_type == "body"` 筛出
（vol01 296 页 / vol02 **全书 186 页**）；管线自己目前**分不出来**
（`classify_page_type` 把 roster/toc/edict 都归 body），这本身是待办。

---
## 文档

**先看这份 → [.claude/doc/pipeline_handbook.md](doc/pipeline_handbook.md)**
分步现状、各步的测试集在哪、哪些步骤能并行、以及踩过的坑。接手任何一步
之前都应该先读它。

| 文档 | 内容 |
|---|---|
| [pipeline_handbook.md](doc/pipeline_handbook.md) | **总入口**：分步现状 / 并行分工 / 量法 / 踩过的坑 |
| [segmentation_v2_pipeline.md](doc/segmentation_v2_pipeline.md) | **切分管线重定义（进行中）**：边框探测/单列射影变换/单列文字切分/字框收缩四步，每步严格输入输出+测试集现状；坐标系改为右上角原点+从1计数。Step1（边框探测）已定版含内外边框+抬头框，金标 14 页 `open-guji-dataset/border-detection`；`find_horizontal_border` 窄窗口第二候选修复 + `find_vertical_lines` 精修去重bug修复均已落地（top 1.9px、bottom 7.0px、竖直线 2.7px 均值）。**抬头框自动探测 `detect_head_raise()` 已定版并接入**（13/13 可观测金标全中、8 页普通页零误报、inner 6.9px / outer 3.3px）——关键在于先把 18 个金标的墨占比/半高宽逐个量出来再设计判据：outer 有"粗满墨条"和"整条没印上"两种形态所以不能要求内外成对（v3 那版召回崩到 28%），墙线检查必须是块级不是列级。真抬头判据也踩过坑——"边框上方有字凸出"不可靠，正确判据是"边框线本身有台阶"。Step2（单列射影变换+去噪）`column_projection.py` 已定版（合成图单测覆盖，真实页面金标待建）。**Step3（单列文字切分）已定版**：输出格式冻结成带类型的字格（字/空白/抬头/夹注a/夹注b + 列内读序，`row_boundaries.segment_column`），生产的双行小注 a/b 拆分已迁移进新链路（`jiazhu_split.py`，逐条保留原阈值 + 漂移护栏单测）；新链路独有的坑是列图两侧压着界行会让夹注跨度判据整体失效，已加 `find_content_window` 剥墙。vol02 40 页对照生产标注：Step1 把列切对的 26 页里 29 个夹注列 27 列逐格全对、1 列差一格相位、1 列比生产多检出一格（目视是生产漏了）。顺带用金标复测推翻了「抬头列多一格修不好」的旧结论——根因只是 `top_slack=1×period` 不够，开到列图顶端后误差 88.2px→12.3px。**vol01/47「竖直线系统偏斜」已查明是假问题**：金标是人工拖的直线、界行本身是弯的，用真墨脊线当第三方基准重量，**算法比人工金标更贴真墨、没有一页反过来**（47 上贴近 3.25px），原定的「挖抬头墙线」修法作废。**金标已按真墨重拟并入库**（用户授权；140 条改 119 条，金标离真墨 2.20→1.41px、天花板 1.28px，现在 14/14 页金标都比算法贴；人工原值留档 `verticals_inner_manual`，脚本 `open-guji-dataset/scripts/refit_border_vlines.py --apply` 幂等）。两个教训：目视叠加图只能说明两条线不一样、不能说明谁对；量法本身要先验证——第一版脊线提取太松（窗口 ±50px、无亚像素、无剔外点、含最外两条），把距离和弯曲幅度一起虚高了约 3 倍。下一步：**修 Step1 的列探测**（40 页里 13 页没把列切对，下游全部连坐，现在是准确率的封顶因素）/ 扩大抬头框金标（现仅 6 页 18 例，形态常数有过拟合风险） |
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

