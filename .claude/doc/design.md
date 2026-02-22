# 古籍图像预处理框架设计文档

## 1. 项目目标

对古籍扫描图片进行**预处理**，目标不是识别文字，而是：

1. 排除图片中的噪音和干扰项（书脊阴影、白色页边距、污渍等）
2. 对古籍排版建立基本认知（颜色模式、页面类型、边框结构、列结构等）
3. 为后续 OCR 逐字识别提供干净、结构化的输入

核心设计理念是**自学习**：系统先分析一本书的样本图片，自动检测该书的版式特征，然后根据特征自适应地选择预处理策略。

## 2. 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                       GujiPipeline                           │
│                                                              │
│  s0 书级分析 → BookProfile (profile.json)                    │
│       ↓                                                      │
│  s1~s6 步骤化预处理（每步保存到独立文件夹）                   │
│       ↓                                                      │
│  Phase 2 版面检测 → 版面结构 JSON (边框+列)                  │
│       ↓                                                      │
│  Phase 3 字符网格 → 字符位置 JSON (投影分割+OCR)             │
└──────────────────────────────────────────────────────────────┘
```

### 统一步骤化管线

| 步骤 | 文件夹 | 名称 | 条件 | 说明 | 详细文档 |
|------|--------|------|------|------|----------|
| s0 | — | 书级分析 | 始终 | 分析样本图片 → `profile.json` | [book_profile.md](./book_profile.md) |
| s1 | `s1_crop_spine/` | 裁书脊 | `has_spine_shadow` | 检测并裁切书脊阴影 | [s1_crop_spine.md](./s1_crop_spine.md) |
| s2 | `s2_crop_border/` | 裁边框 | 始终 | 裁切到边框外缘 | [s2_crop_border.md](./s2_crop_border.md) |
| s3 | `s3_enhance_lines/` | 直线增强 | 始终 | 长直线断续补全+线宽统一 | [s3_enhance_lines.md](./s3_enhance_lines.md) |
| s4 | `s4_deskew/` | 倾斜/透视校正 | 始终 | 透视校正优先，回退投影法旋转 | [s4_deskew.md](./s4_deskew.md) |
| s5 | `s5_split/` | 拆分半页 | `is_uncut` | 沿版心中线拆分为右半页+左半页 | [s5_split.md](./s5_split.md) |
| s6 | `s6_binarize/` | 二值化 | 始终 | 自适应二值化（黑白/彩色分策略）| [s6_binarize.md](./s6_binarize.md) |

### 执行逻辑

```
current_dir = 原始图片目录 (data/bookX/)

for step in [s1, s2, s3, s4, s5, s6]:
    if step.is_needed(profile):
        step_dir = output/bookX/{step.folder_name}/
        对 current_dir 中每张图执行 step.process()，结果写入 step_dir
        current_dir = step_dir          ← 更新为本步输出
    else:
        跳过，current_dir 不变          ← 下一步自动从上游读取
```

跳过的步骤不产生输出文件夹，下游步骤自动从最近的上游输出读取。

### Phase 2 版面检测

在最终预处理步骤完成后运行：

```
LineDetector (LSD) → BorderDetector → ColumnDetector → 版面结构 JSON
```

**列编号约定**：从右到左，从 1 开始（古籍竖排阅读顺序）。第 1 列在最右侧，第 N 列在最左侧。

### Phase 3 字符网格检测

在 Phase 2 版面检测完成后运行：

```
投影法分割 + PaddleOCR 识别 → CharGridDetector → 字符网格 JSON
```

三种格子类型：`char`（字符）、`empty`（空白）、`margin`（边距），严格不重叠。

详细设计参见：
- [Phase 1: 书级分析](./phase1_analyzers.md)
- [Phase 2: 版面检测](./phase2_detectors.md)
- [Phase 3: 字符网格](./phase3_char_grid.md)
- [Pipeline 主流程](./pipeline.md)

## 3. 目录结构

```
guji_preprocess/
├── __init__.py              # 包入口，导出 BookProfile, GujiPipeline
├── __main__.py              # CLI 入口 (python -m guji_preprocess)
├── pipeline.py              # 主 Pipeline 编排 (GujiPipeline 类)
├── profile.py               # BookProfile 数据类 + JSON 序列化
│
├── analyzers/               # s0: 书级特征分析器
│   ├── __init__.py          #   注册表 ANALYZERS + get_all_analyzers()
│   ├── base.py              #   BaseAnalyzer 抽象基类
│   ├── color_mode.py        #   颜色模式检测
│   ├── page_layout.py       #   页面布局检测
│   └── interference.py      #   干扰项检测
│
├── preprocessors/           # s1~s6: 步骤化预处理器
│   ├── __init__.py          #   StepDef + STEPS 列表 + get_active_steps()
│   ├── base.py              #   BasePreprocessor 抽象基类
│   ├── crop_spine.py        #   s1: 书脊阴影裁剪
│   ├── crop_margin.py       #   s2: 裁切到边框外缘
│   ├── enhance_lines.py     #   s3: 长直线增强
│   ├── normalize.py         #   s4: 透视校正 + 投影法旋转
│   ├── split_page.py        #   s5: 筒子页拆分
│   └── binarize.py          #   s6: 自适应二值化
│
├── detectors/               # Phase 2~3: 版面结构与字符检测器
│   ├── __init__.py
│   ├── lines.py             #   Phase 2: LSD 线段检测
│   ├── borders.py           #   Phase 2: 边框检测（复用 border_detect.py）
│   ├── columns.py           #   Phase 2: 列结构分析
│   ├── ocr_detector.py      #   Phase 3: PaddleOCR 封装（延迟加载）
│   └── char_grid.py         #   Phase 3: 字符网格检测（投影+OCR）
│
└── utils/
    ├── __init__.py
    ├── image_io.py           #   imread/imwrite（支持中文路径）
    ├── content_bounds.py     #   内容区域边界检测（std 算法）
    └── viz.py                #   可视化绘制辅助
```

## 4. 核心数据结构

### 4.1 BookProfile

详细定义参见 [BookProfile 数据结构](./book_profile.md)。

```python
@dataclass
class BookProfile:
    color_mode: str              # "bw" | "colored"
    background_color: str | None # None, "red", "yellow", "orange"
    text_color: str              # "black"
    border_color: str            # "black", "red", "orange"
    page_type: str               # "cut_half" | "uncut_full"
    lines_per_page: int          # 每半页行数 (8 或 9)
    border_style: str            # "double" | "single"
    border_wear: str             # "light" | "medium" | "heavy"
    interferences: list[str]     # ["spine_shadow", "stains", "white_margin", ...]
    chars_per_line: int | None   # 每行字数，None=不固定
    has_marginal_notes: bool     # 是否有夹注
```

### 4.2 StepDef

预处理步骤定义：

```python
@dataclass
class StepDef:
    number: int                              # 步骤编号 (1~6)
    name: str                                # 步骤名称
    preprocessor_cls: type[BasePreprocessor]  # 预处理器类
    condition: Callable[[BookProfile], bool]  # 执行条件

    @property
    def folder_name(self) -> str             # e.g. "s3_enhance_lines"
    def is_needed(self, profile) -> bool
    def create_preprocessor(self) -> BasePreprocessor
```

## 5. 输出目录结构

```
output/book4/                     # 有书脊、已剪切
  profile.json                    # s0 分析结果
  s1_crop_spine/                  # s1
  s2_crop_border/                 # s2
  s3_enhance_lines/               # s3
  s4_deskew/                      # s4
  (s5_split/ 不存在 — 已剪切不需拆分)
  s6_binarize/                    # s6
  phase2_layout/                  # Phase 2 版面检测
    1_layout.json, 1_annotated.png, ...
  phase3_char_grid/               # Phase 3 字符网格
    1_char_grid.json, 1_annotated.png, ...
  manifest.json

output/book2/                     # 无书脊、未剪切 → 拆分
  profile.json
  (s1 不存在)
  s2_crop_border/
  s3_enhance_lines/
  s4_deskew/
  s5_split/                       # 拆分后文件名带后缀
    1_right.png, 1_left.png, ...
  s6_binarize/
    1_right.png, 1_left.png, ...
  phase2_layout/
  phase3_char_grid/
  manifest.json
```

### manifest.json 格式

```json
{
  "book": "book4",
  "profile": "profile.json",
  "steps_executed": [
    {"number": 1, "name": "crop_spine", "folder": "s1_crop_spine", "images": 10},
    {"number": 2, "name": "crop_border", "folder": "s2_crop_border", "images": 10},
    {"number": 3, "name": "enhance_lines", "folder": "s3_enhance_lines", "images": 10},
    {"number": 4, "name": "deskew", "folder": "s4_deskew", "images": 10},
    {"number": 6, "name": "binarize", "folder": "s6_binarize", "images": 10}
  ],
  "steps_skipped": [
    {"number": 5, "name": "split", "reason": "page_type=cut_half"}
  ],
  "final_output": "s6_binarize"
}
```

## 6. CLI 用法

```bash
# 分析一本书的版式特征
python -m guji_preprocess analyze data/book1/

# 处理整本书（自动分析 + 全步骤预处理）
python -m guji_preprocess process data/book1/

# 指定输出目录
python -m guji_preprocess -o my_output process data/book1/

# 查看 BookProfile
python -m guji_preprocess show-profile data/book1/
```

## 7. 共享工具

### `utils/content_bounds.py`

供 s1 和 s2 共用的内容区域边界检测。算法：行/列标准差扫描，纯色背景 std≈0，内容区 std 高。

### `border_detect.py`

项目根目录的独立脚本，提供核心函数被 s3 和 s4 复用：
- `cluster_lines()` — 共线性聚类
- `_find_border_pair()` — 双层边框检测
- `_intersect_hv()` — 水平/垂直线交点

## 8. 可扩展性设计

### 添加新的预处理步骤

1. 创建 `preprocessors/my_step.py`，继承 `BasePreprocessor`
2. 实现 `is_needed(profile)` 和 `process(image, profile)`
3. 在 `preprocessors/__init__.py` 的 `STEPS` 列表中添加 `StepDef`（注意编号和顺序）
4. Pipeline 自动识别新步骤，无需修改 `pipeline.py`

### 添加新的分析器

1. 创建 `analyzers/my_analyzer.py`，继承 `BaseAnalyzer`
2. 实现 `analyze(images) -> dict`
3. 在 `analyzers/__init__.py` 的 `ANALYZERS` 列表中注册

## 9. 与现有独立脚本的关系

| 现有文件 | 框架中的对应 | 关系 |
|---------|--------------|------|
| `lsd_detect.py` | `detectors/lines.py` | 核心逻辑重新实现为类 |
| `border_detect.py` | `detectors/borders.py` + s3/s4 | 通过 import 复用核心函数 |

旧脚本保留不动，仍可独立使用。
