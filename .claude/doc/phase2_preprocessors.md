# Phase 2: 图像预处理器

## 概述

Phase 2 根据 BookProfile 自动选择并执行预处理器链，将原始扫描图片转化为干净的、适合版面检测的图像。

**执行时机**: 每张图片运行一次
**输入**: 单张 BGR 图像 + BookProfile
**输出**: 预处理后的图像（可能是多张，如筒子页拆分后）

## 预处理管线

```
原始图像
  │
  ├─ [1] SplitPagePreprocessor    (priority=10, if uncut_full)
  │      → 拆分为右半页 + 左半页
  │
  ├─ [2] CropMarginPreprocessor   (priority=20, if white_margin)
  │      → 裁剪白色页边距
  │
  ├─ [3] CropSpinePreprocessor    (priority=25, if spine_shadow)
  │      → 裁剪书脊阴影
  │
  ├─ [4] BinarizePreprocessor     (priority=50, 始终执行)
  │      → 二值化（黑白用自适应阈值，彩色先提取文字通道）
  │
  └─ [5] NormalizePreprocessor    (priority=60, 始终执行)
         → 倾斜校正
         │
         v
    预处理完成 → *_preprocessed.png
```

**重要**: 如果 SplitPage 将一张图拆分为多张子图，后续所有预处理器对每张子图分别执行。

## 各古籍实际启用的预处理器

| 古籍 | 启用的预处理器 | 输出子图数 |
|------|-------------|----------|
| book1 | crop_spine, binarize, normalize | 1 |
| book2 | **split_page**, crop_spine, binarize, normalize | **2** |
| book3 | binarize, normalize | 1 |
| book4 | crop_spine, binarize, normalize | 1 |
| book5 | crop_spine, crop_margin, binarize, normalize | 1 |

## 基类接口

**文件**: `guji_preprocess/preprocessors/base.py`

```python
class BasePreprocessor(ABC):
    name: str          # 预处理器标识名
    priority: int      # 执行优先级（越小越先执行）

    @classmethod
    @abstractmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        """根据 BookProfile 判断是否需要执行。"""

    @abstractmethod
    def process(self, image: np.ndarray, profile: BookProfile
                ) -> np.ndarray | list[np.ndarray]:
        """处理图像。返回 list 表示拆分为多张子图。"""
```

## 预处理器详细设计

---

### 1. SplitPagePreprocessor — 筒子页拆分

**文件**: `guji_preprocess/preprocessors/split_page.py`
**触发条件**: `profile.page_type == "uncut_full"`
**优先级**: 10（最先执行）

**功能**: 将未剪切的完整筒子页沿中线拆分为左右两半页。

**算法**:
1. 转为灰度图
2. 计算垂直投影（每列的平均亮度）
3. 在图像中央 30%~65% 区域搜索最暗的纵向带（版心界栏）
4. 用滑动窗口平滑后取最小值位置作为中线
5. 左半裁切：`image[:, :center_x]`
6. 右半裁切：`image[:, center_x:]`

**输出**: `[右半页, 左半页]` — 右半页在前（古籍从右往左读）

**输入输出示例** (book2/1.png):
```
输入: 1.png (1520 × 1057, 完整筒子页)
  ↓ SplitPagePreprocessor
输出: [右半页 (760 × 1057), 左半页 (760 × 1057)]
  文件: 1_sub0_preprocessed.png (右半页)
        1_sub1_preprocessed.png (左半页)
```

---

### 2. CropMarginPreprocessor — 页边距裁剪

**文件**: `guji_preprocess/preprocessors/crop_margin.py`
**触发条件**: `"white_margin" in profile.interferences`
**优先级**: 20

**功能**: 裁剪图像外部的白色/浅色空白区域。

**算法**:
1. 灰度 → Otsu 反二值化
2. 形态学闭运算连接前景区域（20×20 矩形核）
3. `findNonZero` + `boundingRect` 获取前景包围盒
4. 添加 5px padding 后裁剪

**输入输出示例** (book5/1.png):
```
输入: 灰度图 (2479 × 1947)
  ↓ CropMarginPreprocessor
输出: 裁剪后图像 (约 2200 × 1600, 去除白色页边距)
```

---

### 3. CropSpinePreprocessor — 书脊阴影裁剪

**文件**: `guji_preprocess/preprocessors/crop_spine.py`
**触发条件**: `"spine_shadow" in profile.interferences`
**优先级**: 25

**功能**: 检测并裁剪页面左/右侧的书脊阴影条纹。

**算法**:
1. 取图像左/右各 15% 区域
2. 计算每列平均亮度
3. 找到最暗位置（书脊阴影）
4. 计算暗度差异 vs 边缘正常区域
5. 差异 > 20 灰度级 → 找到阴影结束边界
6. 裁剪阴影部分（取得分更高的一侧）

**关键参数**:
- `EDGE_SEARCH_RATIO = 0.15` — 搜索区域宽度比例
- `DARKNESS_THRESHOLD = 20` — 暗度差异阈值

---

### 4. BinarizePreprocessor — 自适应二值化

**文件**: `guji_preprocess/preprocessors/binarize.py`
**触发条件**: 始终执行
**优先级**: 50

**功能**: 将图像二值化，分离文字和背景。

**策略**:

#### 黑白图像 (`color_mode == "bw"`)
- 使用 `cv2.adaptiveThreshold` 自适应高斯阈值
- `blockSize=31, C=10`
- 对光照不均匀的古籍扫描更稳健

#### 彩色图像 (`color_mode == "colored"`)
根据 `background_color` 分策略：
- **红底 / 橙底**: 在 HSV 空间中，文字（黑色）具有低饱和度 + 低亮度
  - `text_mask = (S < 80) & (V < 150)`
- **黄底**: 类似，阈值略低
  - `text_mask = (S < 60) & (V < 160)`
- **其他**: 回退到灰度 + 自适应阈值

**输入输出示例** (book3/1.png, 彩色红底):
```
输入: 彩色图像 (淡红色底，深红色边框，黑色文字)
  ↓ BinarizePreprocessor (colored, orange 策略)
输出: 二值图像 (白底黑字，红色边框被部分保留)
```

---

### 5. NormalizePreprocessor — 倾斜校正

**文件**: `guji_preprocess/preprocessors/normalize.py`
**触发条件**: 始终执行
**优先级**: 60（最后执行）

**功能**: 检测并校正图像的整体倾斜。

**算法**:
1. Canny 边缘检测
2. HoughLinesP 霍夫变换检测直线
3. 收集接近水平的线段（偏离 0° < 15°）的角度
4. 取角度中位数作为倾斜角度
5. 仿射变换旋转校正

**保护机制**:
- 角度 < 0.3° → 不校正（太小不值得）
- 角度 > 5.0° → 不校正（太大可能是误检）

## 注册与扩展

在 `preprocessors/__init__.py` 中维护注册表：

```python
PREPROCESSORS = [
    SplitPagePreprocessor,     # priority=10
    CropMarginPreprocessor,    # priority=20
    CropSpinePreprocessor,     # priority=25
    BinarizePreprocessor,      # priority=50
    NormalizePreprocessor,     # priority=60
]
```

**顺序很重要**：先裁剪/拆分，再二值化，最后矫正。

添加新预处理器只需：
1. 新建 `preprocessors/my_pp.py`，继承 `BasePreprocessor`
2. 实现 `is_needed()` 和 `process()`
3. 设置合适的 `priority`
4. 将类插入 `PREPROCESSORS` 列表的合适位置
