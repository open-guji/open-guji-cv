> **2026-10-23 说明**：本 README 保留的是早期的安装与功能概述。现行入口：`.claude/CLAUDE.md`（先看哪份文档、改代码规矩）、`doc/runbook/整理一册书.md`（整理一册书）、`doc/datastore.md`（中心库）、`doc/版本号规矩.md`（分支与发版）。环境用 uv 建 `.venv`，见 `.claude/CLAUDE.md`「环境」。

# Open Guji CV

古籍图像 OCR 分析工具包：对古籍扫描图片进行逐字识别、版面检测与字符网格定位。

---

## 功能概述

- **版式自动分析**：自动识别古籍排版特征（边框类型、行列数、筒子页/半页、书脊阴影等）
- **步骤化预处理**：裁书脊 → 裁边框 → 直线增强 → 倾斜校正 → 拆分半页 → 二值化
- **版面检测**：检测边框（双层/单层）和列结构，输出带标注的可视化图
- **字符网格检测**：逐列定位每个字符的边界框，输出结构化 JSON
- **OCR 识别**：基于 PaddleOCR，支持 CPU 和 GPU 两种模式
- **表格识别**：针对古籍中的表格页面，提取行列结构与单元格文字

---

## 安装

### 前置要求

- Python 3.10+
- （可选）CUDA 12.x + NVIDIA GPU（RTX 3080 实测约 1.5 秒/页）

### 1. 克隆仓库并创建虚拟环境

```bash
git clone https://github.com/your-org/open-guji-cv.git
cd open-guji-cv
python -m venv venv
```

### 2a. CPU 模式安装

```bash
venv/Scripts/pip install -e ".[cpu]"   # Windows
# 或
venv/bin/pip install -e ".[cpu]"        # Linux/macOS
```

### 2b. GPU 模式安装（推荐，速度约 7-8x）

**Windows：**
```bat
install_gpu.bat
```

**Linux：**
```bash
bash install_gpu.sh
```

或手动执行：
```bash
# 安装 GPU 版 PaddlePaddle（适配 CUDA 12.x）
pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu123/
pip install -e ".[gpu]"
```

### 3. 设置环境变量（推荐）

```bash
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True   # 跳过模型源连接检查，加快启动
export PYTHONIOENCODING=utf-8                         # Windows 控制台中文输出必须设置
```

---

## 快速开始

管线是 v2 切分链（`keben_body_v2`），由 `guji` 命令驱动。v1 的 `analyze / preprocess / extract / run` 已于 2026-10-06 退役删除。

```bash
export PYTHONIOENCODING=utf-8
export GUJI_WORKSPACE=<册所在的工作区>   # 册定义（books/*.yaml）从这里读

guji pipeline keben_body_v2 <册> --pages all -w <工作区>   # 跑一册
guji status <册> -w <工作区>                                # 看各步进度
```

链上前两步与页型相关：

| 步骤 | 作用 |
|------|------|
| Step0 `page_survey` / `invert_detect` | 页面尺寸预检；反色带候选（只送审，不自动修） |
| Step1 `border_detect` | 版框、界行、抬头框与列类型；出口闸判页型（`page_type` / 网格策略） |

页型判别的口径、评测与局限见 `doc/pipeline_handbook.md`（§「怎么筛正文页」与 P0/P2 段）；整册操作流程见 `doc/runbook/整理一册书.md`。

---

## Python API

```python
from open_guji_cv.pipeline import GujiPipeline
from open_guji_cv.profile import BookProfile

pipeline = GujiPipeline(output_dir="output")

# 版式分析
profile = pipeline.analyze("data/book1/")

# 预处理
pipeline.process_book("data/book1/", profile=profile)

# 版面检测
pipeline.detect_layout_book("book1", profile=profile)

# 字符网格检测
pipeline.detect_char_grid("book1", profile=profile)

# 完整管线（一步到位）
pipeline.run_all("data/book1/", output_format="combined", clean=True)
```

---

## 测试数据

`data/` 目录下包含 7 本古籍各 10 张样本图片，每本附有 `README.md` 描述排版特征：

| 目录 | 内容 |
|------|------|
| `data/book1/` | 手写体，双层边框，每行 21 字 |
| `data/book2/` | ~ |
| `data/book3/` | ~ |
| `data/book4/` | ~ |
| `data/book5/` | ~ |
| `data/book6/` | ~ |
| `data/book7/` | 含表格页面（历法表格） |

---

## 性能参考

| 模式 | 配置 | 每页速度 |
|------|------|----------|
| CPU | — | ~11.4 秒/页 |
| GPU | RTX 3080, CUDA 12.x | ~1.5 秒/页（首页约 8 秒含模型加载） |

---

## 版本与历史

- 版本号规则见 [`doc/版本号规矩.md`](doc/版本号规矩.md)（`vMAJOR.MINOR.PATCH`，git tag 名加 `cv-` 前缀，rc 仅用于窗口候选）。
- 基线 `v0.1.0`（tag `cv-v0.1.0`）= main `26657f84`。
- 历史于 2026-10-16 分 7 段重写，旧历史见备份分支 `archive/pre-compress-2026-10`（同树瘦身备份）和 Owen 的 bundle。

---

## 许可证

详见 [LICENSE](LICENSE)。
