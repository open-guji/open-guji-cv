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

## 环境变量

```bash
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export PYTHONIOENCODING=utf-8
```

## CLI 命令总览

```
python -m src [-o OUTPUT] <command> [args]

命令:
  analyze        Phase 1:   分析版式特征 → profile.json
  preprocess     Phase 1.5: 预处理 s1~s6
  detect-layout  Phase 2:   版面检测（边框/列）
  detect-grid    Phase 3:   字符网格检测
  run            完整管线:   Phase 1 → 1.5 → 2 → 3
  show-profile   工具:       显示 BookProfile
```

### 全局选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-o, --output` | `output` | 输出根目录 |

### 通用选项（preprocess / detect-layout / detect-grid / run）

| 选项 | 说明 |
|------|------|
| `--profile PATH` | 指定 profile.json 路径（默认自动查找） |
| `--range RANGE` | 指定处理的图片范围，如 `3-6`、`1,3,5`、`003-006` |

---

## 各阶段命令

### analyze — Phase 1: 分析版式特征

```bash
python -m src analyze <book_folder>
python -m src analyze data/book1/
```

对文件夹内的样本图片（最多10张）运行自动分析，生成 `profile.json`。

输出：`<book_folder>/profile.json`

### preprocess — Phase 1.5: 预处理

```bash
# 整本书模式：执行 s1~s6 步骤化预处理
python -m src preprocess data/book1/
python -m src preprocess data/book1/ --profile path/to/profile.json

# 只处理第 3~6 张
python -m src preprocess data/book1/ --range 3-6

# 单图模式：预处理 + Phase 2 版面检测
python -m src preprocess data/book1/3.png

# 指定输出目录
python -m src -o my_output preprocess data/book1/
```

**整本书模式** 执行 s1~s6 步骤化预处理，输出到 `output/<book_name>/`。

**单图模式** 执行预处理 + Phase 2 版面检测，保存预处理图片和 layout JSON。

> `process` 是 `preprocess` 的向后兼容别名，用法完全相同。

### detect-layout — Phase 2: 版面检测

```bash
# 整本书模式：读取预处理输出，批量检测版面
python -m src detect-layout data/book1/
python -m src detect-layout data/book1/ --range 1-5

# 单图模式：对一张图片直接做版面检测
python -m src detect-layout output/book1/s6_binarize/1.png
```

**整本书模式** 从 `output/<book_name>/` 中读取最终预处理结果（通常是 `s6_binarize/`），输出到 `phase2_layout/`：
- `{stem}_layout.json` — 边框和列结构数据
- `{stem}_annotated.png` — 可视化标注图

**单图模式** 对指定图片执行版面检测，输出到 `output/<parent_name>/`。

**前置条件**：需要先运行 `preprocess`。

### detect-grid — Phase 3: 字符网格检测

```bash
# 整本书模式：读取 Phase 2 结果，批量检测字符网格
python -m src detect-grid data/book1/
python -m src detect-grid data/book1/ --range 3-6

# 单图模式：需要指定 layout JSON
python -m src detect-grid output/book1/s6_binarize/1.png --layout output/book1/phase2_layout/1_layout.json
```

**整本书模式** 从 `output/<book_name>/phase2_layout/` 和预处理输出读取，输出到 `phase3_char_grid/`：
- `{stem}_char_grid.json` — 字符网格数据
- `{stem}_annotated.png` — 可视化标注图

**前置条件**：需要先运行 `preprocess` + `detect-layout`。

### run — 完整管线

```bash
# 从头到尾执行所有阶段
python -m src run data/book1/

# 只处理第 3~6 张图片
python -m src run data/book1/ --range 3-6

# 合并输出为单个 JSON
python -m src run data/book1/ --format combined

# 完成后清理中间文件
python -m src run data/book1/ --clean

# 全部选项
python -m src run data/book1/ --range 3-6 --format combined --clean
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--profile` | 自动检测 | 指定 profile.json 路径 |
| `--range` | 全部 | 指定处理的图片范围（如 `3-6` 或 `1,3,5`） |
| `--format` | `char_grid` | 输出格式：`char_grid`（分页）或 `combined`（合并为 `book_result.json`） |
| `--clean` | 不清理 | 完成后删除中间文件夹 |

**`run` 每张图片输出三个最终文件到 `results/`：**

| 文件 | 说明 |
|------|------|
| `{stem}.json` | 标准格式检测结果（对齐 guji_layout，含 border、columns、characters） |
| `{stem}_preprocessed.png` | 预处理后的二值化图片（供后续 OCR 使用） |
| `{stem}_annotated.png` | 合并标注图（边框 + 列线 + 字符格子 + 序号） |

### show-profile — 显示 BookProfile

```bash
python -m src show-profile data/book1/
python -m src show-profile data/book1/profile.json
```

以 JSON 格式输出 BookProfile 内容。

---

## 阶段与命令对应关系

| 阶段 | 命令 | 输入 | 输出 |
|------|------|------|------|
| Phase 1 | `analyze` | 原始图片文件夹 | `profile.json` |
| Phase 1.5 | `preprocess` | 原始图片文件夹 | `s1~s6` 步骤文件夹 + `manifest.json` |
| Phase 2 | `detect-layout` | 预处理后图片 | `phase2_layout/`（JSON + 标注图） |
| Phase 3 | `detect-grid` | 预处理图片 + layout JSON | `phase3_char_grid/`（JSON + 标注图） |
| 全部 | `run` | 原始图片文件夹 | `results/`（JSON + 预处理图 + 标注图） |

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

## 输出目录结构

```
output/<book_name>/
├── profile.json              # BookProfile 副本
├── manifest.json             # 执行记录（哪些步骤执行/跳过）
├── s2_crop_border/           # 步骤输出（跳过的步骤不生成文件夹）
├── s3_enhance_lines/
├── s4_deskew/
├── s6_binarize/              # 最终二值化图像
├── phase2_layout/            # Phase 2 版面检测结果
│   ├── {stem}_layout.json
│   └── {stem}_annotated.png
├── phase3_char_grid/         # Phase 3 字符网格检测结果
│   ├── {stem}_char_grid.json
│   └── {stem}_annotated.png
├── results/                  # run 命令最终输出（每张图 3 个文件）
│   ├── {stem}.json               # char_grid 结果
│   ├── {stem}_preprocessed.png   # 预处理图片
│   └── {stem}_annotated.png      # 合并标注图
└── book_result.json          # --format combined 时生成
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
  "skip_pages": [1, 2],            // 跳过的页码（按文件名末尾数字匹配），如书名页、作者页
  "chars_per_line": 21,            // 每行字数，null 表示不固定
  "has_marginal_notes": false,
  "auto_detected": true,
  "detection_confidence": {}
}
```

关键字段对预处理的影响：
- `page_type == "uncut_full"` → 执行 s5 拆分
- `"spine_shadow" in interferences` → 执行 s1 裁切书脊
- `skip_pages` → 预处理和分析时跳过指定页码（如书名页 [1]、作者页 [2]）
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

# Phase 1.5: 预处理整本书（s1~s6）
pipeline.process_book("data/book1/", profile=profile)

# Phase 1.5: 只处理指定图片
pipeline.process_book("data/book1/", profile=profile,
                      name_filter={"v01_003", "v01_004"})

# Phase 2: 版面检测（批量）
pipeline.detect_layout_book("book1", profile=profile)

# Phase 3: 字符网格（批量）
pipeline.detect_char_grid("book1", profile=profile)

# 完整管线
pipeline.run_all("data/book1/", output_format="combined", clean=True)

# 完整管线：只处理指定图片
pipeline.run_all("data/book1/",
                 name_filter={"v01_003", "v01_004", "v01_005", "v01_006"})

# 手动创建 profile
profile = BookProfile(
    page_type="cut_half",
    lines_per_page=8,
    chars_per_line=21,
    interferences=[],
)
profile.save("my_profile.json")
```
