# 表格 Cell 输出格式规范

> 用于古籍表格页 OCR 识别结果的结构化输出。

## 概述

古籍中包含大量表格（如历法、天文数据表），需要：
1. 检测表格网格线（水平线 + 垂直线）
2. 构建 cell 网格
3. 将 OCR 识别结果映射到对应 cell
4. 输出结构化 JSON

## JSON 输出格式

```json
{
  "image": "path/to/image.png",
  "image_size": [1217, 1650],

  "table": {
    "rows": 9,
    "cols": 9,
    "h_lines": [145, 290, 326, 495, 660, 824, 992, 1153, 1318, 1500],
    "v_lines": [150, 265, 364, 462, 560, 655, 752, 847, 942, 1037]
  },

  "cells": [
    {
      "row": 0,
      "col": 0,
      "row_span": 1,
      "col_span": 1,
      "bbox": [150, 145, 265, 290],
      "size": [115, 145],
      "text": "九百三十年",
      "confidence": 0.74,
      "char_count": 5,
      "chars": [
        {
          "char": "九",
          "bbox": [183, 175, 247, 199],
          "confidence": 0.95
        }
      ]
    }
  ]
}
```

## 字段说明

### table 对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `rows` | int | 表格行数 |
| `cols` | int | 表格列数 |
| `h_lines` | int[] | 水平分隔线 y 坐标（rows+1 个值） |
| `v_lines` | int[] | 垂直分隔线 x 坐标（cols+1 个值） |

### cell 对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `row` | int | 行索引（0-based） |
| `col` | int | 列索引（0-based，从左到右） |
| `row_span` | int | 跨行数，默认 1 |
| `col_span` | int | 跨列数，默认 1 |
| `bbox` | [x1,y1,x2,y2] | cell 在原图中的像素坐标 |
| `size` | [w, h] | cell 像素尺寸 |
| `text` | string | 合并后的文本（竖排从上到下） |
| `confidence` | float | 平均 OCR 置信度 (0-1) |
| `char_count` | int | 识别到的字符数 |
| `chars` | object[] | 逐字详情列表 |

### char 对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `char` | string | 单个字符 |
| `bbox` | [x1,y1,x2,y2] | 字符在原图中的像素坐标 |
| `confidence` | float | 单字 OCR 置信度 (0-1) |

## 坐标约定

- 所有坐标均为**原图像素坐标**
- bbox 格式: `[x_min, y_min, x_max, y_max]`
- 行列索引: 0-based
- 列方向: **从左到右**（注意古籍阅读顺序是从右到左，col=0 是图像最左列）
- cell 内文字顺序: **从上到下**（竖排文本自然顺序）

## 表格线检测方法

1. OTSU 二值化
2. 形态学开操作提取水平/垂直线
3. 投影统计提取线位置
4. 合并相近线（< 25px）

## 数据来源

- 测试数据: `data/book7/` — 《四库全书》历法表格页
- 来源: https://archive.org/details/06054854.cn
