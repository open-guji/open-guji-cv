# Pipeline 主流程

## 概述

`GujiPipeline` 是框架的主入口类，编排 Phase 1 → Phase 2 → Phase 3 的完整流程。

**文件**: `guji_preprocess/pipeline.py`

## 类接口

```python
class GujiPipeline:
    def __init__(self, output_dir: str = "output")

    def analyze(self, book_folder: str, max_samples: int = 10) -> BookProfile
    def preprocess(self, image_path: str, profile: BookProfile) -> list[ProcessResult]
    def process_book(self, book_folder: str, profile: BookProfile = None) -> None
```

## 方法说明

### analyze(book_folder) → BookProfile

Phase 1: 对一本书的样本图片进行特征分析。

**流程**:
1. 在 `book_folder` 中查找图片（最多 `max_samples` 张）
2. 加载为 BGR numpy 数组
3. 按顺序运行所有注册的 Analyzer
4. 合并结果，构建 BookProfile
5. 保存到 `book_folder/profile.json`

**输入输出**:
```
输入: data/book1/ (含 1.png ~ 10.png)
输出: data/book1/profile.json
返回: BookProfile 实例
```

**控制台输出示例**:
```
Phase 1: 分析 10 张样本图片...
  运行分析器: color_mode
  运行分析器: page_layout
  运行分析器: interference
  已保存 BookProfile: data\book1\profile.json
  BookProfile(颜色=bw, 页面=cut_half, 行数=8, 干扰=['spine_shadow'])
```

---

### preprocess(image_path, profile) → list[ProcessResult]

Phase 2 + 3: 对单张图片执行预处理和版面检测。

**流程**:
1. 读取图片
2. 根据 BookProfile 获取需要的预处理器列表
3. 按 priority 顺序执行预处理管线
4. 如果某个预处理器返回 list（如拆分），后续对每张子图分别执行
5. 对每张预处理后的图像执行 Phase 3 版面检测

**输入输出**:
```
输入: data/book2/1.png + BookProfile(page_type=uncut_full)
输出: [
  ProcessResult(sub_index=0, preprocessed=右半页, layout={...}),
  ProcessResult(sub_index=1, preprocessed=左半页, layout={...}),
]
```

**控制台输出示例**:
```
  Phase 2: 预处理 1.png
    启用预处理器: ['split_page', 'crop_spine', 'binarize', 'normalize']
    split_page: 2 张图像
    crop_spine: 2 张图像
    binarize: 2 张图像
    normalize: 2 张图像
  Phase 3: 版面检测 (子图 0)
    ...
  Phase 3: 版面检测 (子图 1)
    ...
```

---

### process_book(book_folder, profile=None) → None

完整流程: 分析 + 处理整本书的所有图片。

**流程**:
1. 检查是否已有 `profile.json`：
   - 参数传入了 profile → 直接使用
   - 目录下有 `profile.json` → 加载
   - 都没有 → 调用 `analyze()` 生成
2. 遍历所有图片，调用 `preprocess()`
3. 保存结果到 `output_dir/book_name/`

**文件查找规则**:
- 支持的扩展名: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`
- 排除后缀: `_lsd`, `_borders`, `_annotated`, `_preprocessed`（避免处理输出文件）

**输出文件**:
```
output/book1/
├── 1_preprocessed.png       # 预处理后图像
├── 1_layout.json            # 版面结构
├── 2_preprocessed.png
├── 2_layout.json
└── ...

output/book2/                # 未剪切页拆分
├── 1_sub0_preprocessed.png  # 右半页
├── 1_sub0_layout.json
├── 1_sub1_preprocessed.png  # 左半页
├── 1_sub1_layout.json
└── ...
```

## CLI 入口

**文件**: `guji_preprocess/__main__.py`

通过 `python -m guji_preprocess` 调用，支持三个子命令：

### analyze

```bash
python -m guji_preprocess analyze data/book1/
```

调用 `pipeline.analyze()`，生成 `profile.json`。

### process

```bash
# 处理整本书
python -m guji_preprocess process data/book1/

# 处理单张图片
python -m guji_preprocess process data/book1/3.png

# 指定 profile
python -m guji_preprocess process data/book1/ --profile path/to/profile.json

# 指定输出目录
python -m guji_preprocess -o my_output process data/book1/
```

处理单张图片时，会自动从同目录查找 `profile.json`，找不到则报错提示先运行 analyze。

### show-profile

```bash
python -m guji_preprocess show-profile data/book1/
# 或
python -m guji_preprocess show-profile data/book1/profile.json
```

以 JSON 格式输出 BookProfile 内容。

## 5 本古籍完整处理结果

```
$ python -m guji_preprocess process data/book1/
============================================================
处理古籍: book1
============================================================
加载已有 BookProfile: data\book1\profile.json
  BookProfile(颜色=bw, 页面=cut_half, 行数=8, 干扰=['spine_shadow'])
--- 1.png ---
  Phase 2: 预处理 1.png
    启用预处理器: ['crop_spine', 'binarize', 'normalize']
  Phase 3: 版面检测 (子图 0)
    版面共 7 列
...
完成！输出目录: output\book1
```

```
$ python -m guji_preprocess process data/book2/
============================================================
处理古籍: book2
============================================================
加载已有 BookProfile: data\book2\profile.json
  BookProfile(颜色=bw, 页面=uncut_full, 行数=9, 干扰=['spine_shadow'])
--- 1.png ---
  Phase 2: 预处理 1.png
    启用预处理器: ['split_page', 'crop_spine', 'binarize', 'normalize']
    split_page: 2 张图像
  Phase 3: 版面检测 (子图 0)
  Phase 3: 版面检测 (子图 1)
...
完成！输出目录: output\book2
```

### 输出文件统计

| 古籍 | 输入图片 | 输出文件数 | 说明 |
|------|---------|----------|------|
| book1 | 10 | 20 | 10 × (1 png + 1 json) |
| book2 | 10 | 40 | 10 × 2 子图 × (1 png + 1 json) |
| book3 | 10 | 20 | 10 × (1 png + 1 json) |
| book4 | 10 | 20 | 10 × (1 png + 1 json) |
| book5 | 10 | 20 | 10 × (1 png + 1 json) |
| **合计** | **50** | **120** | |

## ProcessResult 数据结构

```python
@dataclass
class ProcessResult:
    source_path: str             # 原始图片路径，如 "data/book1/1.png"
    sub_index: int = 0           # 子图索引 (0=完整页/右半, 1=左半)
    preprocessed: np.ndarray     # 预处理后的图像数组
    layout: dict                 # 版面结构 (参见 phase3_detectors.md)
    metadata: dict               # 处理过程信息

# metadata 示例:
{
    "preprocessors_applied": ["crop_spine", "binarize", "normalize"],
    "original_size": {"width": 996, "height": 1559},
    "processed_size": {"width": 950, "height": 1559}
}
```
