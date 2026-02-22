# s2: 裁切到边框 (crop_border)

## 概述

| 项目 | 说明 |
|------|------|
| 编号 | s2 |
| 文件夹 | `s2_crop_border/` |
| 源文件 | `guji_preprocess/preprocessors/crop_margin.py` |
| 类名 | `CropMarginPreprocessor` |
| 执行条件 | 始终执行 |
| 输入 | s1 输出（或原始图片） |
| 输出 | 裁切到边框外缘的图片 |

## 背景

古籍扫描图片通常包含边框外的多余区域：白色扫描背景、黑色填充背景、页边距等。这些区域对 OCR 没有价值，还会干扰后续的线段检测和校正。

## 算法

核心委托给共享工具 `find_content_bounds()`：

```
1. 将图像转为灰度
2. 计算每列的标准差（col_stds）
   - 纯色背景列：std ≈ 0
   - 内容列（有文字/边框）：std 高
3. 自适应阈值 = max(中间区域std中位数 × 0.25, 8.0)
4. 从两端向内扫描，找到 std > 阈值的首列 → 左右边界
5. 在已确定的左右范围内，对行做同样处理 → 上下边界
6. 向外扩展 3px padding（保护边框线）
7. 裁切
```

### 安全检查

- 图像尺寸 < 100px → 不裁切
- 裁切后内容区域 < 原图 30% → 不裁切（防止误裁）

## 适用场景

| 书籍特征 | 效果 |
|----------|------|
| 白色扫描背景（book1/2/5） | 裁掉白色页边距 |
| 黑色填充背景（book4） | 裁掉黑色填充 |
| 无明显页边距（book3） | 几乎不裁切 |

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MIN_CONTENT_RATIO` | 0.3 | 裁切后最小保留比例 |
| `MIN_DIMENSION` | 100 | 最小输入尺寸 |
| `THRESHOLD_RATIO` | 0.25 | std 阈值系数（在 content_bounds.py 中） |
| `MIN_STD_THRESHOLD` | 8.0 | std 绝对最小阈值 |
| `PADDING` | 3 | 边界外扩像素数 |

## 依赖

- `utils/content_bounds.py` → `find_content_bounds()`
