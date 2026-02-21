# Phase 1: 书级特征分析器

## 概述

Phase 1 对一本书的样本图片（通常 10 张）进行分析，自动检测该书的版式特征，生成 `BookProfile`。

**执行时机**: 每本书运行一次
**输入**: 样本图片文件夹（如 `data/book1/`）
**输出**: `profile.json`（保存到同目录）

## 架构

```
样本图片 (10张 BGR)
    │
    ├── ColorModeAnalyzer ──→ color_mode, background_color, border_color
    ├── PageLayoutAnalyzer ─→ page_type, lines_per_page
    └── InterferenceAnalyzer → interferences
    │
    v
合并结果 → BookProfile → profile.json
```

所有分析器继承自 `BaseAnalyzer`，互相独立，可以单独添加/移除。

## 基类接口

**文件**: `guji_preprocess/analyzers/base.py`

```python
class BaseAnalyzer(ABC):
    name: str  # 分析器标识名

    @abstractmethod
    def analyze(self, images: list[np.ndarray]) -> dict:
        """分析样本图片，返回检测到的特征字典。

        返回格式示例:
        {
            "color_mode": "bw",
            "_confidence": {"color_mode": 0.95}
        }
        以 '_' 开头的 key 为元信息，不映射到 BookProfile 字段。
        """
```

## 分析器详细设计

---

### 1. ColorModeAnalyzer — 颜色模式检测

**文件**: `guji_preprocess/analyzers/color_mode.py`

**检测目标**: 黑白 vs 彩色，底色颜色，边框颜色

**算法**:
1. 将每张图转为 HSV 色彩空间
2. 计算饱和度（S 通道）的分布
3. 高饱和度像素（S > 30）占比超过 8% → 判定为彩色
4. 如果是彩色，提取高饱和度区域的色调（H 通道）直方图
5. 找到色调直方图的峰值，映射为颜色名称

**关键参数**:
- `SATURATION_THRESHOLD = 30` — 饱和度阈值
- `COLOR_RATIO_THRESHOLD = 0.08` — 彩色像素占比阈值

**输出字段**:
- `color_mode`: `"bw"` 或 `"colored"`
- `background_color`: `None`, `"red"`, `"orange"`, `"yellow"`, ...
- `border_color`: 同上

**色调映射表**:
| HSV H 范围 | 颜色名 |
|-----------|--------|
| 0-10, 170-180 | red |
| 10-25 | orange |
| 25-35 | yellow |
| 35-80 | green |
| 80-130 | blue |
| 130-170 | purple |

**实际检测结果**:
| 古籍 | 检测 color_mode | 检测 background_color | 实际 | 是否正确 |
|------|----------------|---------------------|------|---------|
| book1 | bw | None | 黑白 | ✓ |
| book2 | bw | None | 黑白 | ✓ |
| book3 | colored | orange | 淡红色底 | 接近 (红/橙边界) |
| book4 | colored | orange | 淡黄色底 | 接近 (黄/橙边界) |
| book5 | bw | None | 黑白 | ✓ |

---

### 2. PageLayoutAnalyzer — 页面布局检测

**文件**: `guji_preprocess/analyzers/page_layout.py`

**检测目标**: 已剪切半页 vs 未剪切整页，每半页行数

**算法**:
1. 计算每张图的宽高比（width / height）
2. 宽高比 > 1.1 → 未剪切整页（横向）
3. 宽高比 < 0.9 → 已剪切半页（纵向）
4. 0.9~1.1 之间的模糊地带，用中线对称性辅助判断

**中线对称性检测**:
- 取图像中央纵向条带（宽度为图像宽度的 5%）
- 左右两侧条带做翻转比较
- 计算归一化差异作为对称性得分

**行数估计**:
- 当前采用简单规则：未剪切页默认 9 行，已剪切页默认 8 行
- 后续由 Phase 3 边框检测精确确定

**关键参数**:
- `UNCUT_ASPECT_RATIO_MIN = 1.1`
- `CUT_ASPECT_RATIO_MAX = 0.9`

**实际检测结果**:
| 古籍 | 实际宽高比 | 检测 page_type | 实际 | 是否正确 |
|------|----------|---------------|------|---------|
| book1 | ~0.64 | cut_half | 已剪切 | ✓ |
| book2 | ~1.48 | uncut_full | 未剪切 | ✓ |
| book3 | ~0.56 | cut_half | 已剪切 | ✓ |
| book4 | ~0.52 | cut_half | 已剪切 | ✓ |
| book5 | ~0.78 | cut_half | **未剪切** | ✗ |

**book5 误判原因**: 图片有大面积白色页边距，导致宽高比接近正方形，低于 1.1 阈值。

**改进方向**: 可先用 CropMarginPreprocessor 裁剪页边距，再判断宽高比。

---

### 3. InterferenceAnalyzer — 干扰项检测

**文件**: `guji_preprocess/analyzers/interference.py`

**检测目标**: 书脊阴影、白色页边距、污渍

**算法**:

#### 书脊阴影检测 (`_detect_spine_shadow`)
1. 取图像左/右各 15% 区域
2. 计算每列的平均亮度
3. 检测亮度梯度的最大跳变
4. 跳变幅度 > 40 灰度级 → 置信度 1.0

#### 白色页边距检测 (`_detect_white_margin`)
1. 取图像四个边缘条带（上、下、左、右）
2. 计算边缘平均亮度 vs 中心区域平均亮度
3. 亮度差 > 30 → 判定有白色页边距

#### 污渍检测 (`_detect_stains`)
1. 用大核高斯模糊估计背景
2. 计算原图与背景的差异
3. 阈值化差异图，统计异常像素比例
4. 比例在 1%~15% 之间 → 判定有污渍

**实际检测结果**:
| 古籍 | 检测到 | 实际 | 是否正确 |
|------|--------|------|---------|
| book1 | spine_shadow | 无干扰 | ✗ 误报 |
| book2 | spine_shadow | page_number | 部分 (漏检页码) |
| book3 | stains | 污渍 | ✓ |
| book4 | spine_shadow | 书脊阴影+污渍 | 部分 (漏检污渍) |
| book5 | spine_shadow, white_margin | 白色页边距 | 部分 (误报书脊) |

**已知问题**: 书脊阴影检测过于敏感，对边缘亮度变化的阈值需要调高。

## 注册与扩展

在 `analyzers/__init__.py` 中维护注册表：

```python
ANALYZERS = [
    ColorModeAnalyzer,
    PageLayoutAnalyzer,
    InterferenceAnalyzer,
]
```

添加新分析器只需：
1. 新建 `analyzers/my_analyzer.py`，继承 `BaseAnalyzer`
2. 实现 `analyze()` 方法
3. 将类添加到 `ANALYZERS` 列表
