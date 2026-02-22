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
│  s1~s5 步骤化预处理（每步保存到独立文件夹）                   │
│       ↓                                                      │
│  Phase 3 版面检测 → 版面结构 JSON                            │
└──────────────────────────────────────────────────────────────┘
```

### 统一步骤化管线

| 步骤 | 文件夹 | 名称 | 条件 | 说明 |
|------|--------|------|------|------|
| s0 | — | 书级分析 | 始终 | 分析样本图片 → `profile.json` |
| s1 | `s1_crop_spine/` | 裁书脊 | `has_spine_shadow` | 先定位内容区，再裁切书脊阴影 |
| s2 | `s2_crop_border/` | 裁边框 | 始终 | 裁切到边框外缘，去除页边距 |
| s3 | `s3_deskew/` | 倾斜/透视校正 | 始终 | 透视校正优先，回退投影法旋转 |
| s4 | `s4_split/` | 拆分半页 | `is_uncut` | 沿版心中线拆分为右半页+左半页 |
| s5 | `s5_binarize/` | 二值化 | 始终 | 自适应二值化（黑白/彩色分策略）|

### 执行逻辑

```
current_dir = 原始图片目录 (data/bookX/)

for step in [s1, s2, s3, s4, s5]:
    if step.is_needed(profile):
        step_dir = output/bookX/{step.folder_name}/
        对 current_dir 中每张图执行 step.process()，结果写入 step_dir
        current_dir = step_dir          ← 更新为本步输出
    else:
        跳过，current_dir 不变          ← 下一步自动从上游读取
```

跳过的步骤不产生输出文件夹，下游步骤自动从最近的上游输出读取。

### Phase 3 版面检测

在最终预处理步骤完成后运行（当前通过 `preprocess()` 向后兼容接口调用）：

```
LineDetector (LSD) → BorderDetector → ColumnDetector → 版面结构 JSON
```

详细设计参见各子文档：
- [Phase 1: 书级分析](./phase1_analyzers.md)
- [Phase 2: 图像预处理](./phase2_preprocessors.md)
- [Phase 3: 版面检测](./phase3_detectors.md)
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
├── preprocessors/           # s1~s5: 步骤化预处理器
│   ├── __init__.py          #   StepDef + STEPS 列表 + get_active_steps()
│   ├── base.py              #   BasePreprocessor 抽象基类
│   ├── crop_spine.py        #   s1: 书脊阴影裁剪
│   ├── crop_margin.py       #   s2: 裁切到边框外缘
│   ├── normalize.py         #   s3: 透视校正 + 投影法旋转
│   ├── split_page.py        #   s4: 筒子页拆分
│   └── binarize.py          #   s5: 自适应二值化
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
    ├── content_bounds.py     #   内容区域边界检测（std 算法）
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

    @property
    def is_uncut(self) -> bool           # page_type == "uncut_full"
    @property
    def has_spine_shadow(self) -> bool    # "spine_shadow" in interferences
```

### 4.2 StepDef

预处理步骤定义：

```python
@dataclass
class StepDef:
    number: int                              # 步骤编号 (1~5)
    name: str                                # 步骤名称
    preprocessor_cls: type[BasePreprocessor]  # 预处理器类
    condition: Callable[[BookProfile], bool]  # 执行条件

    @property
    def folder_name(self) -> str             # e.g. "s2_crop_border"
    def is_needed(self, profile) -> bool
    def create_preprocessor(self) -> BasePreprocessor
```

### 4.3 ProcessResult

单张图片（或子图）的处理结果（向后兼容接口）：

```python
@dataclass
class ProcessResult:
    source_path: str             # 原始图片路径
    sub_index: int               # 子图索引（拆分后的第几张）
    preprocessed: np.ndarray     # 预处理后的图像
    layout: dict                 # 版面结构（边框、列等）
    metadata: dict               # 处理过程信息
```

## 5. 步骤化管线详细设计

### s1: 裁书脊阴影 (`crop_spine.py`)

**条件**: `profile.has_spine_shadow == True`

**关键设计**: s1 在 s2（裁边框）之前执行，此时图片还有页边距。为避免被页边距干扰（如 book4 的黑色填充被误认为书脊），s1 内部先调用共享的 `find_content_bounds()` 定位内容区域，然后仅在内容区域内检测书脊阴影。

```python
def process(self, image, profile):
    gray = to_gray(image)
    # 1. 内部定位内容区域（复用 std 算法）
    top, bot, left, right = find_content_bounds(gray)
    content = gray[top:bot+1, left:right+1]
    # 2. 在内容区域内检测书脊（左/右各 15%）
    spine_side, spine_width = self._detect_spine(content)
    # 3. 仅裁切书脊侧（在原图坐标系）
    ...
```

### s2: 裁切到边框 (`crop_margin.py`)

**条件**: 始终执行

**算法**: 利用行/列标准差检测内容区域边界（`find_content_bounds()`）。纯色背景（白/黑）标准差 ≈ 0，内容区（文字+边框）标准差高。自动处理白色扫描背景、黑色填充背景、无页边距等各种情况。

### s3: 倾斜/透视校正 (`normalize.py`)

**条件**: 始终执行

**两种模式**:

1. **透视校正**（首选）：
   - LSD 检测线段 → 共线性聚类（复用 `border_detect.py`）
   - 检测四条边框线（需全部 4 条，每条覆盖率 ≥ 40%）
   - 计算四角交点 → `cv2.getPerspectiveTransform` 映射为矩形
   - 保持原图完整区域（不裁切边框外的版心等内容）
   - **验证**: 校正后用投影法测量残余角度，如果没有改善则放弃

2. **投影法旋转**（回退）：
   - 当边框检测失败时使用
   - 两步搜索：粗搜 ±3°/0.1° → 精搜 ±0.2°/0.02°
   - 原理：旋转到正确角度时水平投影方差最大

**实测效果**: 5 本书平均残余角度从 0.27° 降到 0.07°，改善 46%~85%。

### s4: 拆分半页 (`split_page.py`)

**条件**: `profile.is_uncut == True`（未剪切的筒子页）

**输出**: `list[tuple[str, np.ndarray]]` → `[("right", 右半页), ("left", 左半页)]`

文件命名: `{stem}_right.png`, `{stem}_left.png`

### s5: 二值化 (`binarize.py`)

**条件**: 始终执行

根据 `color_mode` 选择策略：黑白图用 Otsu 全局二值化，彩色图先转灰度再自适应二值化。

## 6. 输出目录结构

```
output/book4/                     # 有书脊、已剪切
  profile.json                    # s0 分析结果
  s1_crop_spine/                  # s1 裁书脊后
    1.png, 2.png, ...
  s2_crop_border/                 # s2 裁到边框后
    1.png, 2.png, ...
  s3_deskew/                      # s3 倾斜/透视校正后
    1.png, 2.png, ...
  (s4_split/ 不存在 — 已剪切不需拆分)
  s5_binarize/                    # s5 二值化后
    1.png, 2.png, ...
  manifest.json                   # 记录哪些步骤执行了

output/book2/                     # 无书脊、未剪切 → 拆分
  profile.json
  (s1 不存在)
  s2_crop_border/
    1.png, 2.png, ...
  s3_deskew/
    1.png, 2.png, ...
  s4_split/                       # 拆分后文件名带后缀
    1_right.png, 1_left.png,
    2_right.png, 2_left.png, ...
  s5_binarize/
    1_right.png, 1_left.png, ...
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
    {"number": 3, "name": "deskew", "folder": "s3_deskew", "images": 10},
    {"number": 5, "name": "binarize", "folder": "s5_binarize", "images": 10}
  ],
  "steps_skipped": [
    {"number": 4, "name": "split", "reason": "page_type=cut_half"}
  ],
  "final_output": "s5_binarize"
}
```

## 7. CLI 用法

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

## 8. 共享工具

### `utils/content_bounds.py` — 内容区域边界检测

供 `crop_margin`（s2）和 `crop_spine`（s1）共用的工具函数：

```python
def find_content_bounds(gray: np.ndarray) -> tuple[int, int, int, int]:
    """利用行/列标准差找到内容区域（边框外缘）的边界。
    Returns: (top, bottom, left, right) 像素坐标
    """
```

算法：纯色背景标准差 ≈ 0，内容区标准差高。两遍扫描：先列标准差定左右，再在内容列内行标准差定上下。参数：`THRESHOLD_RATIO=0.25`, `MIN_STD_THRESHOLD=8.0`, `PADDING=3`。

## 9. 5 本书处理结果

| 古籍 | 执行步骤 | 跳过步骤 | 输出图片 |
|------|---------|---------|---------|
| book1 (bw, cut_half) | s2→s3→s5 | s1(无书脊), s4(已剪切) | 10×3步 |
| book2 (bw, uncut_full) | s2→s3→s4→s5 | s1(无书脊) | 10→10→20→20 |
| book3 (colored, cut_half) | s2→s3→s5 | s1(无书脊), s4(已剪切) | 10×3步 |
| book4 (colored, spine_shadow) | s1→s2→s3→s5 | s4(已剪切) | 10×4步 |
| book5 (bw, white_margin) | s2→s3→s5 | s1(无书脊), s4(已剪切) | 10×3步 |

## 10. 可扩展性设计

### 添加新的分析器

1. 创建 `analyzers/my_analyzer.py`，继承 `BaseAnalyzer`
2. 实现 `analyze(images) -> dict`
3. 在 `analyzers/__init__.py` 的 `ANALYZERS` 列表中注册

### 添加新的预处理步骤

1. 创建 `preprocessors/my_step.py`，继承 `BasePreprocessor`
2. 实现 `is_needed(profile) -> bool` 和 `process(image, profile) -> ndarray | list[tuple[str, ndarray]]`
3. 在 `preprocessors/__init__.py` 的 `STEPS` 列表中添加 `StepDef`（注意编号和顺序）

### 添加新的特征字段

1. 在 `BookProfile` 中添加字段（带默认值）
2. 写对应的 Analyzer 检测它
3. 写对应的 Preprocessor 处理它

## 11. 与现有代码的关系

| 现有文件 | 新框架中的对应 | 关系 |
|---------|--------------|------|
| `lsd_detect.py` | `detectors/lines.py` (LineDetector) | 核心逻辑重新实现为类 |
| `border_detect.py` | `detectors/borders.py` (BorderDetector) | 通过 import 复用核心函数 |
| `border_detect.py` | `preprocessors/normalize.py` | 透视校正复用 `cluster_lines`, `_find_border_pair`, `_intersect_hv` |
| — | `detectors/columns.py` (ColumnDetector) | 新增 |
| — | `utils/content_bounds.py` | 新增，从 crop_margin 提取的共享工具 |

旧脚本保留不动，仍可独立使用。

## 12. 已知局限与后续优化

### 分析精度
- 底色检测将红色/黄色统一识别为 orange，颜色分类精度有待提高

### 倾斜/透视校正
- 透视校正依赖边框检测质量，边框磨损严重时可能回退到旋转法
- 古籍页面本身可能有微小弯曲，四边形到矩形的映射无法完全消除

### 建议改进方向
- Phase 3 可以利用 BookProfile 的先验行数做更强约束
- 支持从中间步骤恢复执行（检测已有的步骤文件夹，跳过已完成的步骤）
- 支持从 README.md 半自动解析 BookProfile 的辅助工具
