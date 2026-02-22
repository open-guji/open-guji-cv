# Phase 2: 版面结构检测

## 概述

| 阶段 | 输入 | 输出目录 | 源文件 |
|------|------|---------|--------|
| Phase 2 | s6_binarize/ 的最终预处理图 | phase2_layout/ | `detectors/lines.py`, `borders.py`, `columns.py` |

在全部预处理步骤（s1~s6）完成后运行。对每张图检测版面结构：边框位置、列间界栏、列结构。

## 检测流程

```
二值化图像
  │
  ├─ LineDetector.detect()          ← LSD 线段检测
  │    输出: lines[]（线段列表 + 分类统计）
  │
  ├─ BorderDetector.detect()        ← 边框识别
  │    输入: lines[]
  │    输出: outer_frame, inner_frame, column_dividers[]
  │
  └─ ColumnDetector.analyze()       ← 列结构分析
       输入: border_result
       输出: columns[], column_width_stats, is_uniform
```

输出为每张图一个 `*_layout.json` 和一张 `*_annotated.png` 可视化图。

## 1. LineDetector — LSD 线段检测

**文件**: `guji_preprocess/detectors/lines.py`

基于 OpenCV LSD（Line Segment Detector）算法，将图像转为结构化线段列表。

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_length` | 30 | 最小线段长度（像素），低于此值丢弃 |
| `angle_tol` | 10.0 | 判定水平/垂直的角度容差（度） |

### 接口

```python
class LineDetector:
    def __init__(self, min_length: int = 30, angle_tol: float = 10.0)
    def detect(self, image: np.ndarray) -> dict
    def detect_from_file(self, image_path: str) -> dict
```

### 输出格式

```python
{
    "image_size": {"width": int, "height": int},
    "summary": {"total": int, "vertical": int, "horizontal": int, "other": int},
    "lines": [
        {
            "x1": float, "y1": float, "x2": float, "y2": float,
            "length": float,
            "width": float,
            "nfa": float,
            "angle_from_vertical": float,
            "type": "vertical" | "horizontal" | "other"
        }
    ]
}
```

### 角度分类规则

- `angle_from_vertical <= angle_tol` → `"vertical"`
- `angle_from_vertical >= 90 - angle_tol` → `"horizontal"`
- 其余 → `"other"`（被过滤，不参与后续边框检测）

## 2. BorderDetector — 边框识别

**文件**: `guji_preprocess/detectors/borders.py`

消费 LineDetector 输出，通过聚类和合并识别四边外框（可能含双层）和列间界栏。核心算法复用项目根目录 `border_detect.py` 的 `cluster_lines()` 和 `detect_borders()`。

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `pos_tol` | 15 | 位置聚类容差（像素） |
| `max_gap` | 60 | 断续线段合并最大间隙（像素） |
| `min_coverage_ratio` | 0.3 | 边框线最小覆盖比（占边长） |
| `layer_max_dist` | 80 | 双层边框层间最大距离（像素） |

### Profile 自适应

当 `profile.border_wear == "heavy"` 时自动放宽参数：

| 参数 | 调整 |
|------|------|
| `pos_tol` | × 1.3 |
| `max_gap` | × 1.5 |
| `min_coverage` | × 0.7 |

### 接口

```python
class BorderDetector:
    def __init__(self, pos_tol=15, max_gap=60,
                 min_coverage_ratio=0.3, layer_max_dist=80)

    def detect(self, lsd_data: dict, img_width: int, img_height: int,
               profile: BookProfile | None = None) -> dict
```

### 列编号约定

**列编号从右到左，从 1 开始。** 古籍竖排文字从右往左阅读，第 1 列在最右侧，第 N 列在最左侧。

底层 `border_detect.py` 按 x 坐标从左到右生成 0-based 编号，`BorderDetector.detect()` 在返回前通过 `_renumber_columns_rtl()` 将编号反转为从右到左 1-based。列的物理位置（`left_x`, `right_x`）不变，只改 `index`。

### 输出格式

```python
{
    "image_size": {"width": int, "height": int},
    "outer_frame": {
        "top": {"outer": {...}, "inner": {...} | null},
        "bottom": {"outer": {...}, "inner": {...} | null},
        "left": {"outer": {...}, "inner": {...} | null},
        "right": {"outer": {...}, "inner": {...} | null},
    },
    "inner_frame": {
        "top":    {"intercept": float, "slope": float},
        "bottom": {"intercept": float, "slope": float},
        "left":   {"intercept": float, "slope": float},
        "right":  {"intercept": float, "slope": float},
    },
    "column_dividers": [
        {
            "intercept": float, "slope": float,
            "avg_width": float, "coverage": float,
            "segments": [{"start": float, "end": float}],
            "line_count": int,
        }
    ],
    "num_columns": int,
    "columns": [
        {"index": int, "left_x": float, "right_x": float, "width": float}
        # index 从右到左: 1=最右列, N=最左列
    ]
}
```

**参数化直线表示**：每条边框线用 `intercept`（截距）和 `slope`（斜率）描述。

- 水平线：`y = slope * x + intercept`
- 垂直线：`x = slope * y + intercept`

`inner_frame` 取内层边框（有双层时取内层，否则取外层），定义了正文内容区域。

## 3. ColumnDetector — 列结构分析

**文件**: `guji_preprocess/detectors/columns.py`

消费 BorderDetector 输出，分析列宽一致性，在列数不符合先验时尝试修正。

### 接口

```python
class ColumnDetector:
    def analyze(self, border_result: dict,
                profile: BookProfile | None = None) -> dict
```

无构造函数参数。

### 关键阈值

| 阈值 | 值 | 说明 |
|------|----|------|
| 列宽均匀判定 | cv < 0.15 | 变异系数低于 0.15 视为均匀 |
| 列宽拆分触发 | width > expected × 1.5 | 异常宽列触发均分拆分 |

### 输出格式

```python
{
    "columns": [
        {"index": int, "left_x": float, "right_x": float, "width": float}
    ],
    "column_width_stats": {
        "mean": float,
        "std": float,
        "cv": float,   # 变异系数 = std / mean
    },
    "is_uniform": bool,
    # 可选（当 profile 存在且列宽不均时）：
    "columns_corrected": [...]
}
```

### 修正策略

- 检测列数 < 期望列数：将 width > expected_col_width × 1.5 的列均匀拆分
- 检测列数 > 期望列数：暂未实现

## 输出目录

```
output/book1/phase2_layout/
  1_layout.json           # 版面结构数据
  1_annotated.png         # 可视化（边框+列标注）
  2_layout.json
  2_annotated.png
  ...
```

## 典型输出示例（book1 图2）

```json
{
  "lsd_summary": {"total": 186, "vertical": 118, "horizontal": 38, "other": 30},
  "borders": {
    "image_size": {"width": 880, "height": 1291},
    "inner_frame": {
      "top":    {"intercept": 11.46, "slope": 0.005},
      "bottom": {"intercept": 1265.78, "slope": -0.004},
      "left":   {"intercept": 13.38, "slope": -0.001},
      "right":  {"intercept": 804.18, "slope": 0.062}
    },
    "num_columns": 8,
    "columns": [
      {"index": 1, "left_x": 746.8, "right_x": 848.9, "width": 102.1},
      {"index": 2, "left_x": 643.4, "right_x": 746.8, "width": 103.4},
      ...
      {"index": 8, "left_x": 13.4, "right_x": 125.1, "width": 111.7}
    ]
  },
  "columns": {
    "column_width_stats": {"mean": 97.6, "std": 17.4, "cv": 0.178},
    "is_uniform": false
  }
}
```

## 依赖

- OpenCV LSD（`cv2.createLineSegmentDetector`）
- `border_detect.py`（项目根目录，通过 `sys.path` 导入）
