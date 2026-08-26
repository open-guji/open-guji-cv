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
| [char_clustering_design.md](doc/char_clustering_design.md) | 刻本字符切分与聚类的完整设计与实测记录（最厚的一份）|
| [charset_and_lm.md](doc/charset_and_lm.md) | 字表标准（字体 cmap + Unihan）与语言模型混合（通用低权重 + 本书高权重）|
| [glyph_db_expansion_research.md](doc/glyph_db_expansion_research.md) | 字形库扩展：开源字形/异体字数据地图、分层扩库路线（P0 异体字关系层 + P1 字体字形已实现）与**字体字形匹配力实测**（§6）|
| [glyph_canonical_format.md](doc/glyph_canonical_format.md) | 字形图块统一存储格式（256×256 灰度、只缩不放、质心居中）与迁移记录 |
| [review_feedback_loops.md](doc/review_feedback_loops.md) | **审阅反馈三环总入口**：切分回流 / 匹配回流 / 准入规则标定（含短笔画被咬的三源修复记录）|
| [glyph_match_stack.md](doc/glyph_match_stack.md) | **字形相似度匹配栈交接**：四层算法链 + glyph-match/triplets 测试集 + 回归护栏 + 已知失败形态（匹配优化专题从这进）|
| [glyph_match_research.md](doc/glyph_match_research.md) | 匹配算法调研：我们这层在文献谱系里的位置（IDM 零阶形变模型）+ 四条改进路线与引用文献 |
| [design.md](doc/design.md) | 预处理框架（s0~s6 + Phase 2/3）总体设计 |
| [phase2_detectors.md](doc/phase2_detectors.md) | 版面检测（边框/列）|
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

