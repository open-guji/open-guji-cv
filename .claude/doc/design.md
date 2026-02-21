# 古籍图像预处理框架设计文档

## 1. 项目目标

对古籍扫描图片进行**预处理**，目标不是识别文字，而是：

1. 排除图片中的噪音和干扰项（书脊阴影、白色页边距、污渍等）
2. 对古籍排版建立基本认知（颜色模式、页面类型、边框结构、列结构等）
3. 为后续 OCR 逐字识别提供干净、结构化的输入

核心设计理念是**自学习**：系统先分析一本书的样本图片，自动检测该书的版式特征，然后根据特征自适应地选择预处理策略。

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                     GujiPipeline                         │
│                                                          │
│  ┌──────────────┐   ┌───────────────┐   ┌─────────────┐│
│  │   Phase 1    │──>│   Phase 2     │──>│   Phase 3   ││
│  │  书级分析    │   │  图像预处理   │   │  版面检测   ││
│  │  (一次/书)   │   │  (一次/图)    │   │  (一次/图)  ││
│  └──────┬───────┘   └───────┬───────┘   └──────┬──────┘│
│         │                   │                   │        │
│         v                   v                   v        │
│    BookProfile         预处理图像          版面结构JSON  │
│    (profile.json)      (*_preprocessed.png) (*_layout.json)│
└─────────────────────────────────────────────────────────┘
```

### 三阶段流程

| 阶段 | 运行频率 | 输入 | 输出 | 说明 |
|------|---------|------|------|------|
| Phase 1 书级分析 | 每本书一次 | 样本图片（10张） | `profile.json` | 多个 Analyzer 各自检测一个特征维度 |
| Phase 2 图像预处理 | 每张图一次 | 单张图 + BookProfile | 预处理后的图像 | 根据 Profile 自动选择预处理器 |
| Phase 3 版面检测 | 每张预处理图一次 | 预处理图 + BookProfile | 版面结构 JSON | 线段检测 → 边框检测 → 列分析 |

详细设计参见各子文档：
- [Phase 1: 书级分析](./phase1_analyzers.md)
- [Phase 2: 图像预处理](./phase2_preprocessors.md)
- [Phase 3: 版面检测](./phase3_detectors.md)

## 3. 目录结构

```
guji_preprocess/
├── __init__.py              # 包入口，导出 BookProfile, GujiPipeline
├── __main__.py              # CLI 入口 (python -m guji_preprocess)
├── pipeline.py              # 主 Pipeline 编排 (GujiPipeline 类)
├── profile.py               # BookProfile 数据类 + JSON 序列化
│
├── analyzers/               # Phase 1: 书级特征分析器
│   ├── __init__.py          #   注册表 ANALYZERS + get_all_analyzers()
│   ├── base.py              #   BaseAnalyzer 抽象基类
│   ├── color_mode.py        #   颜色模式检测
│   ├── page_layout.py       #   页面布局检测
│   └── interference.py      #   干扰项检测
│
├── preprocessors/           # Phase 2: 图像预处理器
│   ├── __init__.py          #   注册表 PREPROCESSORS + get_preprocessors(profile)
│   ├── base.py              #   BasePreprocessor 抽象基类
│   ├── split_page.py        #   筒子页拆分
│   ├── crop_margin.py       #   页边距裁剪
│   ├── crop_spine.py        #   书脊阴影裁剪
│   ├── binarize.py          #   自适应二值化
│   └── normalize.py         #   倾斜校正
│
├── detectors/               # Phase 3: 版面结构检测器
│   ├── __init__.py
│   ├── lines.py             #   LSD 线段检测
│   ├── borders.py           #   边框检测（复用 border_detect.py）
│   └── columns.py           #   列结构分析
│
└── utils/
    ├── __init__.py
    ├── image_io.py           #   imread/imwrite（支持中文路径）
    └── viz.py                #   可视化绘制辅助
```

## 4. 核心数据结构

### 4.1 BookProfile

详细定义参见 [BookProfile 数据结构](./book_profile.md)。

BookProfile 是整个框架的核心数据结构，描述一本古籍的版式特征：

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
    auto_detected: bool          # 是否自动检测
    detection_confidence: dict   # 各项置信度
```

### 4.2 ProcessResult

单张图片（或子图）的处理结果：

```python
@dataclass
class ProcessResult:
    source_path: str             # 原始图片路径
    sub_index: int               # 子图索引（拆分后的第几张）
    preprocessed: np.ndarray     # 预处理后的图像
    layout: dict                 # 版面结构（边框、列等）
    metadata: dict               # 处理过程信息
```

## 5. Pipeline 主流程

```python
class GujiPipeline:
    def analyze(self, book_folder) -> BookProfile
    def preprocess(self, image_path, profile) -> list[ProcessResult]
    def process_book(self, book_folder, profile=None) -> None
```

### analyze 流程

```
加载样本图片 (最多10张)
    │
    ├── ColorModeAnalyzer.analyze(images) → color_mode, background_color, border_color
    ├── PageLayoutAnalyzer.analyze(images) → page_type, lines_per_page
    └── InterferenceAnalyzer.analyze(images) → interferences
    │
    v
合并结果 → BookProfile → 保存 profile.json
```

### preprocess 流程

```
读取图片
    │
    ├── [if uncut] SplitPagePreprocessor → 拆分为2张子图
    ├── [if white_margin] CropMarginPreprocessor → 裁剪页边距
    ├── [if spine_shadow] CropSpinePreprocessor → 裁剪书脊阴影
    ├── [always] BinarizePreprocessor → 二值化
    └── [always] NormalizePreprocessor → 倾斜校正
    │
    v
对每张子图执行 Phase 3:
    LineDetector → BorderDetector → ColumnDetector
    │
    v
保存 *_preprocessed.png + *_layout.json
```

## 6. CLI 用法

```bash
# 分析一本书的版式特征，生成 profile.json
python -m guji_preprocess analyze data/book1/

# 处理整本书（如果没有 profile.json 会先自动分析）
python -m guji_preprocess process data/book1/

# 处理单张图片（需要同目录有 profile.json）
python -m guji_preprocess process data/book1/3.png

# 查看 BookProfile
python -m guji_preprocess show-profile data/book1/

# 指定输出目录
python -m guji_preprocess -o my_output process data/book2/

# 使用指定的 profile 处理
python -m guji_preprocess process data/book1/ --profile data/book1/profile.json
```

## 7. 输出文件结构

```
output/
├── book1/                          # 已剪切半页 → 每张图1个输出
│   ├── 1_preprocessed.png
│   ├── 1_layout.json
│   ├── 2_preprocessed.png
│   ├── 2_layout.json
│   └── ...                         # 共20个文件 (10张 × 2)
│
├── book2/                          # 未剪切筒子页 → 每张图拆分为2个子图
│   ├── 1_sub0_preprocessed.png     # 右半页
│   ├── 1_sub0_layout.json
│   ├── 1_sub1_preprocessed.png     # 左半页
│   ├── 1_sub1_layout.json
│   └── ...                         # 共40个文件 (10张 × 2子图 × 2)
│
├── book3/                          # 彩色已剪切 → 二值化处理
│   ├── 1_preprocessed.png
│   ├── 1_layout.json
│   └── ...
│
├── book4/                          # 彩色+书脊阴影
│   └── ...
│
└── book5/                          # 黑白+白色页边距
    └── ...
```

## 8. 可扩展性设计

### 添加新的分析器

1. 创建 `analyzers/my_analyzer.py`，继承 `BaseAnalyzer`
2. 实现 `analyze(images) -> dict`
3. 在 `analyzers/__init__.py` 的 `ANALYZERS` 列表中注册

### 添加新的预处理器

1. 创建 `preprocessors/my_preprocessor.py`，继承 `BasePreprocessor`
2. 实现 `is_needed(profile) -> bool` 和 `process(image, profile) -> ndarray`
3. 在 `preprocessors/__init__.py` 的 `PREPROCESSORS` 列表中注册（注意顺序）

### 添加新的特征字段

1. 在 `BookProfile` 中添加字段（带默认值）
2. 写对应的 Analyzer 检测它
3. 写对应的 Preprocessor 处理它

## 9. 与现有代码的关系

| 现有文件 | 新框架中的对应 | 关系 |
|---------|--------------|------|
| `lsd_detect.py` | `detectors/lines.py` (LineDetector) | 核心逻辑重新实现为类 |
| `border_detect.py` | `detectors/borders.py` (BorderDetector) | 通过 import 复用核心函数 |
| — | `detectors/columns.py` (ColumnDetector) | 新增 |

旧脚本保留不动，仍可独立使用。

## 10. 已知局限与后续优化

### 分析精度
- `InterferenceAnalyzer` 的书脊阴影检测存在误报（如 book1 实际无书脊阴影但被检测到）
- book5 因白色页边距导致宽高比接近 1:1，`PageLayoutAnalyzer` 将其误判为 cut_half
- 底色检测将红色/黄色统一识别为 orange，颜色分类精度有待提高

### 建议改进方向
- Phase 1 分析器可以引入多特征交叉验证（如先裁剪页边距再判断宽高比）
- Phase 2 预处理器执行顺序可以更灵活（目前是固定顺序）
- Phase 3 可以利用 BookProfile 的先验行数做更强约束
- 支持从 README.md 半自动解析 BookProfile 的辅助工具
