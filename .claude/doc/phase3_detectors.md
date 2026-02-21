# Phase 3: 版面结构检测器

## 概述

Phase 3 对预处理后的图像进行版面结构检测，识别边框、界栏、列结构。

**执行时机**: 每张预处理后的图像运行一次
**输入**: 预处理后的图像 (灰度/二值) + BookProfile
**输出**: `*_layout.json`（版面结构数据）

## 检测流水线

```
预处理后图像
    │
    ├─ [1] LineDetector ────→ LSD 线段检测结果
    │                            │
    ├─ [2] BorderDetector ──→ 边框结构（外框、内框、界栏）
    │                            │
    └─ [3] ColumnDetector ──→ 列结构分析（列宽、一致性）
    │
    v
*_layout.json
```

## 检测器详细设计

---

### 1. LineDetector — LSD 线段检测

**文件**: `guji_preprocess/detectors/lines.py`
**来源**: 从 `lsd_detect.py` 提取核心逻辑

**功能**: 使用 OpenCV LSD 算法检测图像中的直线段。

**算法**:
1. `cv2.createLineSegmentDetector(LSD_REFINE_STD)` 创建检测器
2. `lsd.detect(gray)` 检测所有线段
3. 过滤掉长度 < `min_length` 的线段
4. 按角度分类：垂直线（偏离 90° < 10°）、水平线（偏离 0° < 10°）、其他

**参数**:
- `min_length = 30` — 最小线段长度（像素）
- `angle_tol = 10` — 水平/垂直判定容差（度）

**输出格式**:
```json
{
  "image_size": {"width": 996, "height": 1559},
  "summary": {"total": 277, "vertical": 188, "horizontal": 55, "other": 34},
  "lines": [
    {
      "x1": 159.3, "y1": 249.3, "x2": 163.6, "y2": 1389.4,
      "length": 1140.0, "width": 3.9,
      "type": "vertical",
      "angle_from_vertical": 0.21
    }
  ]
}
```

---

### 2. BorderDetector — 边框检测

**文件**: `guji_preprocess/detectors/borders.py`
**来源**: 复用 `border_detect.py` 的 `cluster_lines()` 和 `detect_borders()` 函数

**功能**: 识别双层外边框和内部列间界栏。

**算法** (详见 `border_detect.py`):
1. 线段聚类：按共线性将线段分组，每组独立拟合参数化直线
2. 双层边框检测：在四个方向（上下左右）的最外/最内侧寻找成对的粗线+细线
3. 界栏检测：内框范围内的垂直线聚类，过滤掉覆盖率低、斜率大的候选

**与 BookProfile 的交互**:
- `border_wear == "heavy"` → 放宽聚类容差（pos_tol × 1.3, max_gap × 1.5）
- 检测到的列数与 `lines_per_page` 不符 → 在结果中标记 `_column_mismatch`

**参数**:
- `pos_tol = 15` — 位置聚类容差（像素）
- `max_gap = 60` — 断续线段合并最大间隙（像素）
- `min_coverage_ratio = 0.3` — 边框线最小覆盖比
- `layer_max_dist = 80` — 双层边框层间最大距离（像素）

**输出格式** (简化):
```json
{
  "image_size": {"width": 996, "height": 1559},
  "outer_frame": {
    "top":    {"outer": {...}, "inner": null},
    "bottom": {"outer": {...}, "inner": null},
    "left":   {"outer": {...}, "inner": null},
    "right":  {"outer": {...}, "inner": null}
  },
  "inner_frame": {
    "top":    {"intercept": 150.1, "slope": 0.0016},
    "bottom": {"intercept": 1403.7, "slope": -0.007},
    "left":   {"intercept": 159.3, "slope": 0.003},
    "right":  {"intercept": 884.9, "slope": 0.002}
  },
  "column_dividers": [
    {"intercept": 263.8, "slope": 0.002, "coverage": 0.964, ...}
  ],
  "num_columns": 7,
  "columns": [
    {"index": 0, "left_x": 159.3, "right_x": 263.8, "width": 104.5}
  ]
}
```

每个边框层的数据结构：
```json
{
  "intercept": 150.1,     // 截距（位置轴上的值）
  "slope": 0.0016,        // 斜率（用于处理形变）
  "avg_width": 4.2,       // 平均线宽
  "total_length": 787.5,  // 总长度
  "line_count": 25,       // 原始线段数
  "segments": [           // 合并后的线段
    {"start": 141.9, "end": 929.4}
  ]
}
```

---

### 3. ColumnDetector — 列结构分析

**文件**: `guji_preprocess/detectors/columns.py`
**来源**: 新增模块

**功能**: 在 BorderDetector 的基础上精细分析列宽一致性，辅助修正异常。

**分析内容**:
1. 计算所有列宽的均值、标准差、变异系数 (CV)
2. CV < 0.15 → 列宽均匀 (`is_uniform = true`)
3. 如果不均匀且有先验行数，尝试修正（拆分过宽的列、合并过窄的列）

**输出格式**:
```json
{
  "columns": [
    {"index": 0, "left_x": 159.3, "right_x": 263.8, "width": 104.5},
    {"index": 1, "left_x": 263.8, "right_x": 368.2, "width": 104.4}
  ],
  "column_width_stats": {
    "mean": 103.65,
    "std": 1.11,
    "cv": 0.011
  },
  "is_uniform": true
}
```

## 完整 layout.json 输出示例

以 book1/1.png 为例：

```json
{
  "lsd_summary": {
    "total": 277,
    "vertical": 188,
    "horizontal": 55,
    "other": 34
  },
  "borders": {
    "image_size": {"width": 996, "height": 1559},
    "outer_frame": {
      "top":    {"outer": {"intercept": 150.1, "slope": 0.002, ...}, "inner": null},
      "bottom": {"outer": {"intercept": 1403.7, "slope": -0.007, ...}, "inner": null},
      "left":   {"outer": {"intercept": 159.3, "slope": 0.003, ...}, "inner": null},
      "right":  {"outer": {"intercept": 884.9, "slope": 0.002, ...}, "inner": null}
    },
    "inner_frame": {
      "top":    {"intercept": 150.1, "slope": 0.002},
      "bottom": {"intercept": 1403.7, "slope": -0.007},
      "left":   {"intercept": 159.3, "slope": 0.003},
      "right":  {"intercept": 884.9, "slope": 0.002}
    },
    "column_dividers": [
      {"intercept": 263.8, "slope": 0.002, "coverage": 0.964, ...},
      {"intercept": 368.2, "slope": 0.003, "coverage": 0.521, ...},
      ...
    ],
    "num_columns": 7,
    "columns": [...],
    "_column_mismatch": {"expected": 8, "detected": 7}
  },
  "columns": {
    "columns": [...],
    "column_width_stats": {"mean": 103.65, "std": 1.11, "cv": 0.011},
    "is_uniform": true
  }
}
```

**关键观察**:
- `num_columns: 7` 但期望 8 → `_column_mismatch` 标记了差异
- `column_width_stats.cv: 0.011` → 非常均匀 (`is_uniform: true`)
- 说明检测到的 7 列结构是正确的（可能第 8 列的界栏磨损严重未检出）

## 各古籍的检测概况

| 古籍 | 检测列数 | 期望列数 | 列宽 CV | 均匀性 | 说明 |
|------|---------|---------|---------|-------|------|
| book1 | 7 | 8 | 0.011 | ✓ | 少检 1 列界栏 |
| book2-sub0 | 4 | 9 | — | — | 只有半页右侧部分 |
| book2-sub1 | 13 | 9 | — | — | 拆分后列检测偏多 |
| book3 | 9 | 8 | — | — | 彩色二值化后多检 1 列 |
| book4 | 1 | 8 | — | — | 彩色+书脊裁剪后界栏未检出 |
| book5 | 11 | 9 | — | — | 含页边距误检 |

**说明**: 列检测精度受 Phase 2 预处理质量影响很大。二值化策略和裁剪精度的改进将直接提升 Phase 3 的检测准确性。
