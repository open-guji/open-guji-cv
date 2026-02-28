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

```bash
# 第一步：分析版式特征
python -m open_guji_cv analyze data/book1/

# 第二步：图像预处理（裁剪 → 增强 → 二值化）
python -m open_guji_cv preprocess data/book1/

# 第三步：版面 + 字符检测，输出结构化 JSON
python -m open_guji_cv extract data/book1/

# 一键运行全部流程
python -m open_guji_cv run data/book1/
```

---

## CLI 命令参考

### 全局选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-o, --output` | `output` | 输出根目录 |

### 通用选项（preprocess / extract / run）

| 选项 | 说明 |
|------|------|
| `--profile PATH` | 指定 profile.json 路径（默认自动查找） |
| `--range RANGE` | 处理范围，如 `3-6` 或 `1,3,5` |

---

### `analyze` — 第一步：版式分析

```bash
python -m open_guji_cv analyze data/book1/
```

对文件夹内样本图片（最多 10 张）自动分析，生成 `data/book1/profile.json`。

检测内容：边框类型（双层/单层）、页面类型（半页/筒子页）、行列数、书脊阴影等。

---

### `preprocess` — 第二步：图像预处理

```bash
python -m open_guji_cv preprocess data/book1/
python -m open_guji_cv preprocess data/book1/ --range 3-6   # 只处理第 3~6 张
```

按顺序执行 s1~s6，输出到 `output/book1/`：

| 步骤 | 名称 | 条件 |
|------|------|------|
| s1 | 裁书脊阴影 | `spine_shadow` 在干扰项中 |
| s2 | 裁边框 | 始终执行 |
| s3 | 直线增强 | 始终执行 |
| s4 | 倾斜校正 | 始终执行 |
| s5 | 拆分筒子页 | `page_type == "uncut_full"` |
| s6 | 二值化 | 始终执行 |

---

### `extract` — 第三步：版面与字符检测

```bash
python -m open_guji_cv extract data/book1/                    # 两步全做（默认）
python -m open_guji_cv extract data/book1/ --steps layout     # 只做版面检测
python -m open_guji_cv extract data/book1/ --steps grid       # 只做字符网格
python -m open_guji_cv extract data/book1/ --range 1-5
```

| `--steps` | 说明 |
|-----------|------|
| `all`（默认） | Phase 2 版面检测 + Phase 3 字符网格，全部执行 |
| `layout` | 只做版面检测（边框 + 列结构） |
| `grid` | 只做字符网格定位（需先有 layout 结果） |

输出到 `output/book1/phase2_layout/` 和 `output/book1/phase3_char_grid/`：
- `{stem}_layout.json` / `{stem}_char_grid.json` — 结构化数据
- `{stem}_annotated.png` — 可视化标注图

---

### `run` — 一键完整管线

```bash
python -m open_guji_cv run data/book1/                        # 全部图片
python -m open_guji_cv run data/book1/ --range 3-6            # 指定范围
python -m open_guji_cv run data/book1/ --format combined       # 合并为单个 JSON
python -m open_guji_cv run data/book1/ --clean                 # 完成后删除中间文件
```

依次执行 analyze → preprocess → extract 三步，最终输出到 `output/book1/results/`：

| 文件 | 说明 |
|------|------|
| `{stem}.json` | 检测结果（边框、列、字符位置与文字） |
| `{stem}_preprocessed.png` | 预处理后的二值化图片 |
| `{stem}_annotated.png` | 合并标注图 |

---

### `show-profile` — 查看版式配置

```bash
python -m open_guji_cv show-profile data/book1/
```

---

## 输出目录结构

```
output/<book_name>/
├── profile.json              # BookProfile（版式配置）
├── manifest.json             # 执行记录
├── s2_crop_border/
├── s3_enhance_lines/
├── s4_deskew/
├── s6_binarize/              # 最终二值化图像
├── phase2_layout/            # 版面检测结果
├── phase3_char_grid/         # 字符网格结果
└── results/                  # 最终输出
    ├── {stem}.json
    ├── {stem}_preprocessed.png
    └── {stem}_annotated.png
```

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

## 许可证

详见 [LICENSE](LICENSE)。
