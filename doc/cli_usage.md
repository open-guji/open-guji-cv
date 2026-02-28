# CLI 使用文档

## 包结构

```
open_guji_cv/            # Python 包（通过 python -m open_guji_cv 调用）
├── __init__.py          # 导出 BookProfile, GujiPipeline
├── __main__.py          # CLI 入口
├── pipeline.py          # GujiPipeline 主管线
├── profile.py           # BookProfile 数据类
├── analyzers/           # 版式分析器
├── detectors/           # 版面 / 字符 / OCR 检测器
├── preprocessors/       # s1~s6 预处理步骤
└── utils/               # 工具函数（image_io, viz）

border_detect.py         # 边框聚类核心函数（被内部模块依赖，不可删除）
```

## 环境变量

```bash
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True   # 跳过模型源连接检查
export PYTHONIOENCODING=utf-8                         # Windows 中文输出必须设置
```

## 命令总览

```
python -m open_guji_cv [-o OUTPUT] <command> [args]

三大步骤：
  analyze    <folder>           分析版式特征 → profile.json
  preprocess <folder>           图像预处理（裁剪 / 增强 / 二值化）
  extract    <folder>           版面 + 字符检测，输出结构化 JSON

一键运行：
  run        <folder>           依次执行以上三步

工具：
  show-profile <folder|json>   显示 BookProfile
```

### 全局选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-o, --output` | `output` | 输出根目录 |

### 通用选项（preprocess / extract / run）

| 选项 | 说明 |
|------|------|
| `--profile PATH` | 指定 profile.json 路径（默认自动查找） |
| `--range RANGE` | 指定处理的图片范围，如 `3-6`、`1,3,5` |

---

## 第一步：analyze — 版式分析

```bash
python -m open_guji_cv analyze data/book1/
```

对文件夹内样本图片（最多 10 张）自动分析排版特征，生成 `profile.json`。

**输出**：`data/book1/profile.json`

**检测内容**：边框类型（双层/单层）、页面类型（半页/筒子页）、行列数、
书脊阴影、颜色模式、是否有夹注等。

---

## 第二步：preprocess — 图像预处理

```bash
python -m open_guji_cv preprocess data/book1/
python -m open_guji_cv preprocess data/book1/ --range 3-6     # 只处理第 3~6 张
python -m open_guji_cv preprocess data/book1/ --profile path/to/profile.json
```

按顺序执行 s1~s6，输出到 `output/book1/`：

| 步骤 | 名称 | 文件夹 | 条件 |
|------|------|--------|------|
| s1 | 裁书脊阴影 | `s1_crop_spine/` | `spine_shadow` 在干扰项中 |
| s2 | 裁边框 | `s2_crop_border/` | 始终执行 |
| s3 | 直线增强 | `s3_enhance_lines/` | 始终执行 |
| s4 | 倾斜校正 | `s4_deskew/` | 始终执行 |
| s5 | 拆分筒子页 | `s5_split/` | `page_type == "uncut_full"` |
| s6 | 二值化 | `s6_binarize/` | 始终执行 |

跳过的步骤不产生文件夹，下游步骤自动从最近的上游输出读取。

**前置条件**：建议先运行 `analyze`（无 profile.json 时自动触发分析）。

---

## 第三步：extract — 版面与字符检测

```bash
python -m open_guji_cv extract data/book1/                        # 两步全做（默认）
python -m open_guji_cv extract data/book1/ --steps layout         # 只做版面检测
python -m open_guji_cv extract data/book1/ --steps grid           # 只做字符网格
python -m open_guji_cv extract data/book1/ --range 1-5            # 指定范围
```

| `--steps` 值 | 说明 |
|--------------|------|
| `all`（默认）| Phase 2 版面检测 + Phase 3 字符网格，全部执行 |
| `layout` | 只做 Phase 2：检测边框和列结构 |
| `grid` | 只做 Phase 3：字符网格定位（需先有 layout 结果） |

**Phase 2 输出**（`output/book1/phase2_layout/`）：
- `{stem}_layout.json` — 边框和列结构数据
- `{stem}_annotated.png` — 可视化标注图

**Phase 3 输出**（`output/book1/phase3_char_grid/`）：
- `{stem}_char_grid.json` — 字符网格（含 OCR 文字）
- `{stem}_annotated.png` — 可视化标注图

**前置条件**：需要先运行 `preprocess`。

---

## run — 一键完整管线

```bash
python -m open_guji_cv run data/book1/
python -m open_guji_cv run data/book1/ --range 3-6
python -m open_guji_cv run data/book1/ --format combined    # 合并为单个 JSON
python -m open_guji_cv run data/book1/ --clean              # 完成后删除中间文件
```

依次执行 analyze → preprocess → extract 三步。

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--format` | `char_grid` | `char_grid`（分页 JSON）或 `combined`（合并为 `book_result.json`） |
| `--clean` | 不清理 | 完成后删除中间文件夹（s1~s6） |

**最终输出**（`output/book1/results/`，每张图 3 个文件）：

| 文件 | 说明 |
|------|------|
| `{stem}.json` | 检测结果（边框、列、字符位置与文字） |
| `{stem}_preprocessed.png` | 预处理后的二值化图片 |
| `{stem}_annotated.png` | 合并标注图 |

---

## show-profile — 查看版式配置

```bash
python -m open_guji_cv show-profile data/book1/
python -m open_guji_cv show-profile data/book1/profile.json
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
├── phase2_layout/            # extract --steps layout 输出
│   ├── {stem}_layout.json
│   └── {stem}_annotated.png
├── phase3_char_grid/         # extract --steps grid 输出
│   ├── {stem}_char_grid.json
│   └── {stem}_annotated.png
└── results/                  # run 命令最终输出
    ├── {stem}.json
    ├── {stem}_preprocessed.png
    └── {stem}_annotated.png
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
  "lines_per_page": 8,
  "border_style": "double",        // "double" | "single"
  "border_wear": "medium",         // "light" | "medium" | "heavy"
  "interferences": [],             // ["spine_shadow", "stains", ...]
  "skip_pages": [1, 2],
  "chars_per_line": 21,
  "has_marginal_notes": false,
  "auto_detected": true
}
```

关键字段影响：
- `page_type == "uncut_full"` → 执行 s5 拆分筒子页
- `"spine_shadow" in interferences` → 执行 s1 裁书脊
- `skip_pages` → 预处理和分析时跳过（如书名页 `[1]`）
- `chars_per_line` → Phase 3 每列网格槽位数

---

## Python API 快速参考

```python
from open_guji_cv.pipeline import GujiPipeline
from open_guji_cv.profile import BookProfile

pipeline = GujiPipeline(output_dir="output")

# 版式分析
profile = pipeline.analyze("data/book1/")

# 图像预处理（s1~s6）
pipeline.process_book("data/book1/", profile=profile)

# 版面检测（Phase 2）
pipeline.detect_layout_book("book1", profile=profile)

# 字符网格检测（Phase 3）
pipeline.detect_char_grid("book1", profile=profile)

# 完整管线（一步到位）
pipeline.run_all("data/book1/", output_format="combined", clean=True)

# 只处理指定图片
pipeline.run_all("data/book1/",
                 name_filter={"v01_003", "v01_004", "v01_005"})

# 手动创建 profile
profile = BookProfile(
    page_type="cut_half",
    lines_per_page=8,
    chars_per_line=21,
    interferences=[],
)
profile.save("my_profile.json")
```
