# CLI 使用文档

## 包结构

```
src/                     # Python 包（包名通过 python -m src 调用）
├── __init__.py          # 导出 BookProfile, GujiPipeline
├── __main__.py          # CLI 入口
├── pipeline.py          # GujiPipeline 主管线
├── profile.py           # BookProfile 数据类
├── analyzers/           # Phase 1 分析器
├── detectors/           # Phase 2/3 检测器（borders, columns, char_grid, ocr）
├── preprocessors/       # s1~s6 预处理步骤
└── utils/               # 工具函数（image_io, viz）

border_detect.py         # 边框聚类核心函数（被 src 内部模块依赖，不可删除）
```

## CLI 命令

通过 `python -m src` 调用，需要先设置环境变量：

```bash
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export PYTHONIOENCODING=utf-8
```

### analyze — 分析版式特征

```bash
python -m src analyze <book_folder>
python -m src analyze data/book1/
```

对文件夹内的样本图片（最多10张）运行自动分析，生成 `profile.json`。

输出：`<book_folder>/profile.json`

### process — 预处理整本书

```bash
# 处理整本书（自动加载或生成 profile）
python -m src process data/book1/

# 指定 profile
python -m src process data/book1/ --profile path/to/profile.json

# 指定输出目录
python -m src -o my_output process data/book1/

# 处理单张图片（需要同目录有 profile.json）
python -m src process data/book1/3.png
```

**整本书模式** 执行 s1~s6 步骤化预处理，输出到 `output/<book_name>/`。

**单图模式** 执行预处理 + Phase 2 版面检测，返回 ProcessResult。

### show-profile — 显示 BookProfile

```bash
python -m src show-profile data/book1/
python -m src show-profile data/book1/profile.json
```

以 JSON 格式输出 BookProfile 内容。

---

## 全局选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-o, --output` | `output` | 输出根目录 |

---

## 预处理步骤（s1~s6）

`process_book()` 按顺序执行以下步骤，跳过的步骤不产生文件夹：

| 步骤 | 名称 | 文件夹 | 条件 | 说明 |
|------|------|--------|------|------|
| s1 | crop_spine | `s1_crop_spine/` | `spine_shadow` in interferences | 裁切书脊阴影 |
| s2 | crop_border | `s2_crop_border/` | 始终执行 | 裁到边框范围 |
| s3 | enhance_lines | `s3_enhance_lines/` | 始终执行 | 长直线增强（断续补全） |
| s4 | deskew | `s4_deskew/` | 始终执行 | 倾斜校正 |
| s5 | split | `s5_split/` | `page_type == "uncut_full"` | 拆分未剪切筒子页为左右半页 |
| s6 | binarize | `s6_binarize/` | 始终执行 | 二值化（Otsu 阈值） |

跳过的步骤不产生输出，下游步骤自动从最近的上游输出读取。

---

## Phase 2 — 版面检测

Phase 2 检测边框和列结构，目前 **没有独立的 CLI 命令**，需要通过 Python API 调用：

```python
import sys; sys.path.insert(0, '.')
from src.pipeline import GujiPipeline

pipeline = GujiPipeline(output_dir="output")

# 方式 1：通过 preprocess() 自动执行（含预处理 + 版面检测）
from src.profile import BookProfile
profile = BookProfile.load("data/book1/profile.json")
results = pipeline.preprocess("output/book1/s6_binarize/1.png", profile)
# results[0].layout 包含版面结构

# 方式 2：直接调用内部方法
from src.utils.image_io import imread
image = imread("output/book1/s6_binarize/1.png")
layout = pipeline._detect_layout(image, profile)
```

输出结构（layout dict）：

```json
{
  "lsd_summary": { ... },
  "borders": {
    "inner_frame": { "top": {...}, "bottom": {...}, "left": {...}, "right": {...} },
    "columns": [...]
  },
  "columns": {
    "columns": [
      {"index": 1, "left_x": 751.9, "right_x": 851.8},
      ...
    ]
  }
}
```

## Phase 3 — 字符网格检测

**前置条件**：需要 `output/<book>/s6_binarize/` 和 `output/<book>/phase2_layout/` 目录。

```python
from src.pipeline import GujiPipeline

pipeline = GujiPipeline(output_dir="output")
pipeline.detect_char_grid("book1")
```

读取 `phase2_layout/` 中的 layout JSON 和 `s6_binarize/` 中的图片，输出到 `phase3_char_grid/`：
- `{stem}_char_grid.json` — 字符网格数据
- `{stem}_annotated.png` — 可视化标注图

---

## 输出目录结构

```
output/<book_name>/
├── profile.json              # BookProfile 副本
├── manifest.json             # 执行记录（哪些步骤执行/跳过）
├── s2_crop_border/           # 步骤输出（跳过的步骤不生成文件夹）
├── s3_enhance_lines/
├── s4_deskew/
├── s6_binarize/              # 最终二值化图像
├── phase2_layout/            # 版面检测结果
│   ├── 1_layout.json
│   └── 1_annotated.png
└── phase3_char_grid/         # 字符网格检测结果
    ├── 1_char_grid.json
    └── 1_annotated.png
```

---

## BookProfile 字段

```json
{
  "color_mode": "bw",              // "bw" | "colored"
  "background_color": null,        // null | "red" | "yellow"
  "text_color": "black",
  "border_color": "black",         // "black" | "red"
  "page_type": "cut_half",         // "cut_half" | "uncut_full"
  "lines_per_page": 8,             // 每半页行数
  "border_style": "double",        // "double" | "single"
  "border_wear": "medium",         // "light" | "medium" | "heavy"
  "interferences": [],             // ["spine_shadow", "stains", "white_margin", "page_number"]
  "chars_per_line": 21,            // 每行字数，null 表示不固定
  "has_marginal_notes": false,
  "auto_detected": true,
  "detection_confidence": {}
}
```

关键字段对预处理的影响：
- `page_type == "uncut_full"` → 执行 s5 拆分
- `"spine_shadow" in interferences` → 执行 s1 裁切书脊
- `chars_per_line` → Phase 3 每列的网格槽位数

---

## Python API 快速参考

```python
import sys; sys.path.insert(0, '.')
from src.pipeline import GujiPipeline
from src.profile import BookProfile

pipeline = GujiPipeline(output_dir="output")

# Phase 1: 分析
profile = pipeline.analyze("data/book1/")

# 预处理整本书（s1~s6）
pipeline.process_book("data/book1/", profile=profile)

# Phase 3: 字符网格（需要先有 phase2_layout/）
pipeline.detect_char_grid("book1", profile=profile)

# 手动创建 profile
profile = BookProfile(
    page_type="cut_half",
    lines_per_page=8,
    chars_per_line=21,
    interferences=[],
)
profile.save("my_profile.json")
```
