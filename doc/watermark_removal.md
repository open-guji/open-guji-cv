# 水印去除算法

## 概述

本模块处理古籍扫描图片中**固定位置、固定形状**的水印。水印由黑色和白色线条组成，每页位置几乎相同，形状大小固定。

**代码位置**: `open_guji_cv/preprocessors/remove_watermark.py`
**触发条件**: `profile.json` 中 `interferences` 包含 `"watermark"`
**Pipeline 步骤**: `s1_remove_watermark`（在所有其他预处理之前执行）

## 算法总览

```
多页图片 ──→ p90 堆叠 ──→ 水印区域定位 ──→ 线条像素检测 ──→ 逐页 inpaint
              │                │                  │                 │
         文字消失          连通域+凸包         top-hat          只修复线条
         水印保留          排除边框            黑线+白线        周围取色填充
```

整体分两个阶段：

| 阶段 | 方法 | 输入 | 输出 |
|------|------|------|------|
| setup（一次） | p90 堆叠 + 区域定位 + 线条检测 | 全部页面 | 线条掩码 |
| process（每页） | cv2.inpaint | 单页图片 + 掩码 | 去水印图片 |

## 阶段一：setup — 构建水印线条掩码

### 步骤 1：p90 百分位堆叠

将所有页面（通常 10 页）逐像素取第 90 百分位值。

```python
stack = np.array([...])  # shape: (N, H, W, 3)
p90 = np.percentile(stack, 90, axis=0).astype(np.uint8)
```

**原理**: 水印在每页的相同位置 → 堆叠后保留；文字在每页不同位置 → 被"投票"消除（只有 ≤10% 的页面在某位置有文字，取 p90 就跳过了）。

**结果**: 一张"只有水印、没有文字"的模板图。

**为什么用 p90 而不是中值**: 中值（p50）会保留更多文字残影（50% 的页面在某位置有笔画就能留下来），p90 更激进地消除文字。

### 步骤 2：水印区域定位（粗定位）

目的是找到水印的大致位置，排除边框线等干扰。

```
p90 灰度图
    ↓
高斯模糊（201×201, σ=70）→ 平滑背景估计
    ↓
|p90 - 背景| → 绝对差值
    ↓
阈值化（>25）→ 二值图
    ↓
膨胀 + 闭合 → 连接断裂线条
    ↓
连通域分析 → 过滤
    ↓
凸包 + 膨胀 70px → 水印区域掩码
```

**连通域过滤规则**:
- 面积 ≥ 图像面积的 0.5%（排除小噪声）
- 宽 **且** 高不能同时超过图像的 50%（排除边框线连成的大区域）

**凸包 + 膨胀 70px**: 凸包确保覆盖水印内部空间，膨胀确保覆盖白色外框线（白线在黑线检测区域外面）。

**典型结果**: 检测到 2 个水印区域（左右页各一个），覆盖约 24% 像素。

### 步骤 3：精确线条检测

在水印区域内，用形态学 top-hat 从 p90 模板精确检测线条像素。

```python
k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))

# 黑线检测（Black top-hat = closing - original）
black_tophat = cv2.morphologyEx(p90_gray, cv2.MORPH_BLACKHAT, k)

# 白线检测（White top-hat = original - opening）
white_tophat = cv2.morphologyEx(p90_gray, cv2.MORPH_TOPHAT, k)
```

**Black top-hat 原理**: `closing` 操作用 15×15 的核填充比核小的暗特征（黑线约 5px 宽 < 15px 核），得到"假设没有黑线"的图像。与原图做差就提取出了黑线。

**White top-hat 原理**: `opening` 操作用 15×15 的核去除比核小的亮特征（白线），得到"假设没有白线"的图像。原图与之做差就提取出了白线。

**阈值**: top-hat 值 > 8 的像素视为线条。

**关键设计：不膨胀掩码**。p90 模板中，因为各页水印位置有微小偏移（1-3px），线条已经比实际略粗。如果再膨胀，就会覆盖到文字笔画。

**限制在水印区域内**:
```python
line_mask = cv2.bitwise_and(line_mask, region_mask)
```
避免把边框线、页面边缘等也当成水印线条。

**典型结果**: 掩码覆盖约 2.8% 像素（只有线条本身）。

## 阶段二：process — 逐页 inpaint

```python
result = cv2.inpaint(image, line_mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)
```

**cv2.inpaint** 的工作方式：对掩码标记的每个像素，从周围未标记像素取色填充。相当于"用旁边的颜色画上去"。

**inpaintRadius=2**: 小半径确保只从最近邻取色，避免引入远处的颜色。

**效果**: 黑线处被周围的背景色（米黄色）填充，白线处同样被背景色填充。文字如果和线条交叉，inpaint 会从文字笔画两侧取色，基本保持文字形状。

## 参数一览

| 参数 | 值 | 作用 |
|------|-----|------|
| `_BG_BLUR_KSIZE` | 201 | 背景估计高斯核大小 |
| `_BG_BLUR_SIGMA` | 70 | 背景估计高斯 σ |
| `_COARSE_THRESH` | 25 | 粗检测阈值 |
| `_CONNECT_KSIZE` | 11 | 连通域连接核大小 |
| `_MIN_AREA_RATIO` | 0.005 | 最小面积比（排除噪声） |
| `_MAX_DIM_RATIO` | 0.5 | 最大尺寸比（排除边框） |
| `_HULL_EXPAND_RADIUS` | 70 | 凸包膨胀半径（px） |
| `_TOPHAT_KSIZE` | 15 | top-hat 核大小（需 > 线条宽度） |
| `_LINE_THRESH` | 8 | 线条检测阈值 |
| `_INPAINT_RADIUS` | 2 | inpaint 取色半径 |

## 适用条件

- 水印位置在每页**基本固定**（允许 1-3px 偏移）
- 水印由**线条**组成（黑线和/或白线），非大面积半透明覆盖
- 至少 **3 页**以上的图片（用于 p90 堆叠消除文字）
- 页面越多效果越好（10 页以上最佳）

## 使用方法

在 `profile.json` 的 `interferences` 中添加 `"watermark"`：

```json
{
  "interferences": ["spine_shadow", "watermark"],
  ...
}
```

运行预处理：
```bash
python -m open_guji_cv preprocess data/book8/ --keep-intermediate
```

## 调试

如果效果不理想，可调整的关键参数：

| 问题 | 调整方向 |
|------|---------|
| 水印区域没检测到 | 降低 `_COARSE_THRESH`（如 20）或 `_MIN_AREA_RATIO`（如 0.002） |
| 边框线被当成水印 | 降低 `_MAX_DIM_RATIO`（如 0.4） |
| 线条没检测到 | 降低 `_LINE_THRESH`（如 5），但可能引入噪声 |
| 文字被损伤 | 提高 `_LINE_THRESH`（如 10-12） |
| 白线没覆盖到 | 增大 `_HULL_EXPAND_RADIUS`（如 90） |

## 被排除的方案

开发过程中测试了多种方案，最终选择当前方案的原因：

| 方案 | 问题 |
|------|------|
| HSV 颜色过滤 | 水印是灰色线条，不是彩色，HSV 无法区分 |
| 加法亮度补偿 | 黑线效果好，但白线补偿方向错误（inpaint 背景估计偏高） |
| 补偿 + opening | opening 会模糊水印区域内的文字 |
| 乘法校正 | p90 模板中的文字残影被放大，产生光晕 |
| 补偿 + inpaint | inpaint 在修复线条时把下面的文字也模糊了 |
| 逐页 top-hat | 单页上无法区分水印线条和文字笔画 |
| p90 掩码 + 膨胀 | 膨胀后覆盖文字，且页间偏移让掩码变胖 |
