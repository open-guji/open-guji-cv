# Open Guji CV - 项目说明

## 语言
- 默认使用中文进行交流

## 项目概述
古籍图像 OCR 分析项目，使用 PaddleOCR 对古籍扫描图片进行逐字识别和位置分析。

---
系统设计 查看 .claude/doc/system_design.md
技术细节： 查看 .claude/doc/technical_learning.md

----
测试数据：
data/ 文件夹下边 有5本古籍 每本古籍有10个截图 和一个read me文件 来介绍它的基本的排版信息

### 环境变量
- `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` — 跳过模型源连接检查，加快启动速度
- `PYTHONIOENCODING=utf-8` — Windows 控制台中文输出必须设置

