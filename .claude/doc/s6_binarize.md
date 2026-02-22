# s6: 二值化 (binarize)

## 概述

| 项目 | 说明 |
|------|------|
| 编号 | s6 |
| 文件夹 | `s6_binarize/` |
| 源文件 | `guji_preprocess/preprocessors/binarize.py` |
| 类名 | `BinarizePreprocessor` |
| 执行条件 | 始终执行 |
| 输入 | s5 输出（或 s4/s3 输出，取决于 s5 是否执行） |
| 输出 | 二值化图像（文字黑色，背景白色） |

## 背景

二值化是 OCR 前的最后一步预处理，将灰度/彩色图像转为纯黑白图像，突出文字轮廓、消除背景噪声。

## 策略选择

根据 `profile.color_mode` 分两个分支：

### 黑白图像 (`color_mode == "bw"`)

使用 **自适应高斯阈值**：

```python
cv2.adaptiveThreshold(gray, 255, ADAPTIVE_THRESH_GAUSSIAN_C,
                      THRESH_BINARY, blockSize=31, C=10)
```

自适应阈值对古籍扫描中常见的光照不均更稳健（相比 Otsu 全局阈值）。

### 彩色图像 (`color_mode == "colored"`)

根据底色类型在 HSV 空间提取文字掩码：

| 底色 | 策略 |
|------|------|
| 红底 (`background_color == "red"`) | 文字 = 低饱和度(S<80) + 低亮度(V<150) |
| 黄底 (`background_color == "yellow"`) | 文字 = 低饱和度(S<60) + 低亮度(V<160) |
| 其他 | 回退到灰度 + 自适应阈值 |

提取文字掩码后做 2×2 矩形核的**闭运算**（填充小孔），再反转为标准格式（文字黑/背景白）。

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `blockSize` | 31 | 自适应阈值的邻域大小（黑白模式） |
| `C` | 10 | 自适应阈值的常数偏移 |
| 饱和度/亮度阈值 | 见上表 | 彩色模式下的文字提取阈值 |

## 适用场景

| 书籍 | 模式 | 策略 |
|------|------|------|
| book1/2/5 | bw | 自适应高斯阈值 |
| book3 | colored (red) | HSV 饱和度+亮度提取 |
| book4 | colored (yellow) | HSV 饱和度+亮度提取 |
