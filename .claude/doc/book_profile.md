# BookProfile 数据结构

## 概述

`BookProfile` 是整个预处理框架的核心数据结构，描述一本古籍的版式特征。它由 Phase 1 分析器自动生成，也可以手动编辑修正。

**文件位置**: `guji_preprocess/profile.py`
**存储格式**: JSON (`data/bookN/profile.json`)

## 字段定义

### 颜色相关

| 字段 | 类型 | 默认值 | 说明 | 取值范围 |
|------|------|--------|------|---------|
| `color_mode` | str | `"bw"` | 颜色模式 | `"bw"` (黑白), `"colored"` (彩色) |
| `background_color` | str\|None | `None` | 底色 | `None`, `"red"`, `"yellow"`, `"orange"` |
| `text_color` | str | `"black"` | 文字颜色 | `"black"` |
| `border_color` | str | `"black"` | 边框颜色 | `"black"`, `"red"`, `"orange"` |

### 页面布局

| 字段 | 类型 | 默认值 | 说明 | 取值范围 |
|------|------|--------|------|---------|
| `page_type` | str | `"cut_half"` | 页面类型 | `"cut_half"` (已剪切半页), `"uncut_full"` (未剪切整页) |
| `lines_per_page` | int | `8` | 每半页行数 | 通常 `8` 或 `9` |

### 边框

| 字段 | 类型 | 默认值 | 说明 | 取值范围 |
|------|------|--------|------|---------|
| `border_style` | str | `"double"` | 边框样式 | `"double"` (双层：外粗内细), `"single"` |
| `border_wear` | str | `"medium"` | 磨损程度 | `"light"`, `"medium"`, `"heavy"` |

### 干扰项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `interferences` | list[str] | `[]` | 干扰项列表，可叠加 |

干扰项取值：
- `"spine_shadow"` — 书脊阴影（页面侧边的纵向暗条纹）
- `"white_margin"` — 白色页边距（内容区外的高亮度空白）
- `"stains"` — 污渍（背景上的异常色块）
- `"page_number"` — 页码（页面底部的数字）

### 文字

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `chars_per_line` | int\|None | `21` | 每行字数，`None` 表示不固定 |
| `has_marginal_notes` | bool | `False` | 是否有夹注（小字注释） |

### 元信息

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `auto_detected` | bool | `True` | `True`=自动检测, `False`=手动填写 |
| `detection_confidence` | dict | `{}` | 各项检测的置信度 (0.0~1.0) |

## 便利属性

BookProfile 提供以下只读属性，用于条件判断：

```python
profile.is_colored       # color_mode == "colored"
profile.is_uncut         # page_type == "uncut_full"
profile.has_spine_shadow # "spine_shadow" in interferences
profile.has_white_margin # "white_margin" in interferences
profile.has_stains       # "stains" in interferences
```

## JSON 示例

### book1 (黑白、已剪切、8行)

```json
{
  "color_mode": "bw",
  "background_color": null,
  "text_color": "black",
  "border_color": "black",
  "page_type": "cut_half",
  "lines_per_page": 8,
  "border_style": "double",
  "border_wear": "medium",
  "interferences": ["spine_shadow"],
  "chars_per_line": 21,
  "has_marginal_notes": false,
  "auto_detected": true,
  "detection_confidence": {
    "color_mode": 1.0,
    "page_type": 1.0,
    "lines_per_page": 0.5,
    "spine_shadow": 0.998
  }
}
```

### book2 (黑白、未剪切整页、9行)

```json
{
  "color_mode": "bw",
  "background_color": null,
  "text_color": "black",
  "border_color": "black",
  "page_type": "uncut_full",
  "lines_per_page": 9,
  "border_style": "double",
  "border_wear": "medium",
  "interferences": ["spine_shadow"],
  "chars_per_line": 21,
  "has_marginal_notes": false,
  "auto_detected": true,
  "detection_confidence": {
    "color_mode": 1.0,
    "page_type": 1.0,
    "lines_per_page": 0.5,
    "spine_shadow": 0.975
  }
}
```

### book3 (彩色红底、已剪切、有污渍)

```json
{
  "color_mode": "colored",
  "background_color": "orange",
  "text_color": "black",
  "border_color": "orange",
  "page_type": "cut_half",
  "lines_per_page": 8,
  "border_style": "double",
  "border_wear": "medium",
  "interferences": ["stains"],
  "chars_per_line": 21,
  "has_marginal_notes": false,
  "auto_detected": true,
  "detection_confidence": {
    "color_mode": 1.0,
    "page_type": 1.0,
    "lines_per_page": 0.5,
    "stains": 0.914
  }
}
```

### book4 (彩色黄底、有书脊阴影)

```json
{
  "color_mode": "colored",
  "background_color": "orange",
  "text_color": "black",
  "border_color": "orange",
  "page_type": "cut_half",
  "lines_per_page": 8,
  "border_style": "double",
  "border_wear": "medium",
  "interferences": ["spine_shadow"],
  "chars_per_line": 21,
  "has_marginal_notes": false,
  "auto_detected": true,
  "detection_confidence": {
    "color_mode": 1.0,
    "page_type": 1.0,
    "lines_per_page": 0.5,
    "spine_shadow": 1.0
  }
}
```

### book5 (黑白、白色页边距)

```json
{
  "color_mode": "bw",
  "background_color": null,
  "text_color": "black",
  "border_color": "black",
  "page_type": "cut_half",
  "lines_per_page": 8,
  "border_style": "double",
  "border_wear": "medium",
  "interferences": ["spine_shadow", "white_margin"],
  "chars_per_line": 21,
  "has_marginal_notes": false,
  "auto_detected": true,
  "detection_confidence": {
    "color_mode": 1.0,
    "page_type": 1.0,
    "lines_per_page": 0.5,
    "spine_shadow": 0.900,
    "white_margin": 0.596
  }
}
```

## 自动检测 vs 手动修正

BookProfile 支持三种使用方式：

1. **全自动**: `python -m guji_preprocess analyze data/bookN/` 自动生成
2. **自动 + 手动修正**: 自动生成后手动编辑 `profile.json` 中不准确的字段
3. **全手动**: 直接创建 `profile.json`，设置 `"auto_detected": false`

建议流程：先自动分析，查看结果，对不准确的字段手动修正。

## 5 本古籍的检测精度对比

| 古籍 | color_mode | page_type | lines | interferences | 总体 |
|------|-----------|-----------|-------|--------------|------|
| book1 | bw ✓ | cut_half ✓ | 8 ✓ | spine_shadow ✗ (实际无) | 部分 |
| book2 | bw ✓ | uncut_full ✓ | 9 ✓ | spine_shadow (实际 page_number) | 部分 |
| book3 | colored ✓ | cut_half ✓ | 8 ✓ | stains ✓ | ✓ |
| book4 | colored ✓ | cut_half ✓ | 8 ✓ | spine_shadow ✓ (缺 stains) | 大部分 |
| book5 | bw ✓ | cut_half ✗ (实际 uncut) | 8 ✗ (实际 9) | white_margin ✓ | 部分 |

**说明**：颜色模式和页面类型（宽高比明显的）检测很准确，干扰项检测是目前的主要薄弱环节。
