# Phase 3: 字符网格检测 (char_grid)

## 概述

| 阶段 | 输入 | 输出目录 | 源文件 |
|------|------|---------|--------|
| Phase 3 | phase2_layout/*.json + s6_binarize/*.png | phase3_char_grid/ | `detectors/char_grid.py`, `detectors/ocr_detector.py` |

在 Phase 2 版面检测完成后运行。对每列内部定位每个字符的位置，结合投影法分割和 PaddleOCR 文字识别，生成字符网格。

## 检测流程

```
对每张图片：
  加载 layout JSON → 获取列结构 + inner_frame 边界
  加载 s6_binarize/ 二值图
  │
  对每一列 (col_top ~ col_bottom, left_x ~ right_x)：
  │
  ├─ 1. 投影法分割
  │    裁切列区域 → 水平投影 → 找连续文字区域
  │    过滤噪点(< 10px) → 二次分割过大区域(> 1.6 × 理论字高)
  │    输出: regions[] — 每个字符的 (y_top, y_bottom)
  │
  ├─ 2. OCR 文字识别
  │    裁切列区域 → PaddleOCR predict → 取整列文字字符串
  │    输出: ocr_text — 整列识别文字（如 "通查各省進到之書…"）
  │
  └─ 3. 网格构建
       融合 regions + ocr_text + 先验(chars_per_line=21)
       输出: cells[] — 三种类型的格子列表
```

## 核心算法

### 投影法分割

对列区域的灰度图做水平投影（每行黑色像素数），找出连续文字区域：

1. 二值化（阈值 128）
2. 逐行统计黑色像素数 → 投影数组
3. 投影值 > `PROJ_THRESHOLD`(2) 的行标记为文字
4. 找连续 True 区域 → 原始字符区域
5. 过滤：高度 < `MIN_CHAR_HEIGHT`(10px) 的区域丢弃
6. 二次分割：高度 > 理论字高 × `SPLIT_RATIO`(1.6) 的区域，在投影最低点处切割

### OCR 文字识别

PaddleOCR 对竖排古籍的行为：将整列文字识别为一个长文本行。因此：
- 对每列裁切区域调用 `OcrDetector.detect_chars()`
- 取置信度最高的结果的 `.text` 作为整列文字
- 文字按顺序逐个对应到投影分割的区域

### 网格构建 — 三种格子类型

```
┌─────────────┐
│   margin    │  ← 列顶边距（不占字符数）
├─────────────┤
│   empty     │  ← 空白字符格（等高、连续无缝隙）
├─────────────┤
│   empty     │
├─────────────┤
│   char "通"  │  ← 字符格（来自投影分割）
├─ ─ ─ ─ ─ ─ ┤     ↑ char 之间可有缝隙
│   char "查"  │
├─ ─ ─ ─ ─ ─ ┤
│    ...      │
├─────────────┤
│   empty     │
├─────────────┤
│   margin    │  ← 列底边距
└─────────────┘
```

**三种类型的规则：**

| 类型 | 含义 | 占字符编号 | 相邻关系 |
|------|------|----------|---------|
| `char` | 有文字的字符格 | 是 | 彼此之间可有缝隙，不重叠 |
| `empty` | 空白字符格 | 是 | 连续等高、无缝隙 |
| `margin` | 列首/列尾边距 | 否 | 与相邻格子无缝隙 |

**铁律**：任何两个相邻格子之间不重叠。margin + empty + char 合起来填满 `[col_top, col_bottom]`（char 之间的缝隙除外）。

### 字高估算

1. 理论字高：`theoretical = (col_bottom - col_top) / chars_per_line`
2. 实际字高：取相邻投影区域中心距的中位数
3. 约束：实际字高 clamp 到理论值的 70%~130%

## 1. CharGridDetector

**文件**: `guji_preprocess/detectors/char_grid.py`

### 参数

| 常量 | 值 | 说明 |
|------|----|------|
| `PROJ_THRESHOLD` | 2 | 水平投影最小黑色像素数 |
| `MIN_CHAR_HEIGHT` | 10 | 最小字符区域高度（像素） |
| `SPLIT_RATIO` | 1.6 | 触发二次分割的高度比率 |
| `CHAR_HEIGHT_MIN_RATIO` | 0.7 | 字高下界（×理论值） |
| `CHAR_HEIGHT_MAX_RATIO` | 1.3 | 字高上界（×理论值） |

### 接口

```python
class CharGridDetector:
    def __init__(self, ocr_detector: OcrDetector | None = None)

    def detect(self, image: np.ndarray, layout: dict,
               profile: BookProfile) -> dict
```

### 输出格式

```python
{
    "image_size": {"width": int, "height": int},
    "chars_per_line": 21,
    "char_height_estimated": 58.5,   # 全局平均字高
    "columns": [
        {
            "index": 1,           # 列编号: 从右到左, 1=最右列
            "left_x": 746.8,
            "right_x": 848.9,
            "ocr_text": "通查各省進到之書其一人而收藏百種以上者可",
            "cells": [
                {"type": "margin", "y_top": 11.46, "y_bottom": 94.0},
                {"type": "char", "index": 0, "y_top": 94.0, "y_bottom": 153.0,
                 "text": "通", "confidence": 1.0},
                {"type": "char", "index": 1, "y_top": 163.0, "y_bottom": 215.0,
                 "text": "查", "confidence": 1.0},
                ...
                {"type": "margin", "y_top": 1245.0, "y_bottom": 1265.78}
            ]
        },
        ...
    ]
}
```

### cell 字段说明

**margin**:
```python
{"type": "margin", "y_top": float, "y_bottom": float}
```

**empty**:
```python
{"type": "empty", "index": int, "y_top": float, "y_bottom": float,
 "text": null, "confidence": 0.0}
```

**char**:
```python
{"type": "char", "index": int, "y_top": float, "y_bottom": float,
 "text": "字" | null, "confidence": float}
```

`index` 是字符编号，char 和 empty 共享同一编号序列，margin 没有 index。

## 2. OcrDetector — PaddleOCR 封装

**文件**: `guji_preprocess/detectors/ocr_detector.py`

### 特性

- **延迟初始化**：首次调用 `detect_chars()` 时才加载 PaddleOCR 模型，避免 import 时的重量级初始化
- **PaddleOCR 3.x API**：使用 `ocr.predict()` 而非已废弃的 `ocr.ocr()`

### PaddleOCR 初始化参数

| 参数 | 值 |
|------|-----|
| `use_doc_orientation_classify` | False |
| `use_doc_unwarping` | False |
| `use_textline_orientation` | False |
| `lang` | "ch" |
| `text_det_thresh` | 0.3 |
| `text_det_box_thresh` | 0.5 |

### 接口

```python
@dataclass
class CharBox:
    polygon: list[list[float]]   # 4 点多边形
    text: str
    confidence: float
    center_x: float
    center_y: float
    width: float
    height: float

class OcrDetector:
    def __init__(self)
    def detect_chars(self, image: np.ndarray) -> list[CharBox]
```

`detect_chars()` 返回按 `center_y` 升序排列的 CharBox 列表。

### 竖排文字行为

PaddleOCR 对竖排古籍做**文本行级别检测**：整列文字被识别为一个大框。因此 `CharGridDetector` 不依赖 OCR 做逐字切分，而是：
- OCR 负责获取文字内容（整列字符串）
- 投影法负责定位每个字符的 y 坐标

## 输出目录

```
output/book1/phase3_char_grid/
  1_char_grid.json        # 字符网格数据
  1_annotated.png         # 可视化（绿=char, 灰=empty, 蓝=margin）
  2_char_grid.json
  2_annotated.png
  ...
```

## Pipeline 调用

```python
pipeline = GujiPipeline(output_dir="output")
pipeline.detect_char_grid("book1")
```

在 `GujiPipeline.detect_char_grid()` 中：
1. 加载 profile.json
2. 遍历 phase2_layout/*.json
3. 对每张图创建 CharGridDetector 执行检测
4. 保存 JSON + 可视化 PNG

## 依赖

- PaddleOCR 3.x（`paddlepaddle==3.2.2` + `paddleocr==3.4.0`）
- OpenCV（二值化、灰度转换）
- NumPy（投影计算、统计）

### 环境变量

| 变量 | 值 | 说明 |
|------|-----|------|
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | True | 跳过模型源连接检查 |
| `PYTHONIOENCODING` | utf-8 | Windows 中文输出 |
