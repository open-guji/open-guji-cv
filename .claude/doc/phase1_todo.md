# Phase 1 分析器优化 TODO

## 检测结果对比（2026-02-21 运行）

### Book 1
| 特征 | 检测结果 | README 真实值 | 判定 |
|------|---------|-------------|------|
| color_mode | `bw` | 黑白 | ✅ 正确 |
| background_color | `null` | 无 | ✅ 正确 |
| page_type | `cut_half` | 已剪切 | ✅ 正确 |
| lines_per_page | `8` | 8行 | ✅ 正确 |
| interferences | `["spine_shadow"]` | **无干扰** | ❌ 误报书脊阴影 |

> spine_shadow 每张图得分均接近 1.0，但 README 明确说"无干扰"。黑白图像边缘天然有亮度梯度（扫描边缘效应），算法过于敏感。

### Book 2
| 特征 | 检测结果 | README 真实值 | 判定 |
|------|---------|-------------|------|
| color_mode | `bw` | 黑白 | ✅ 正确 |
| page_type | `uncut_full` | 未剪切 | ✅ 正确 |
| lines_per_page | `9` | 每半页9行 | ✅ 正确 |
| interferences | `["spine_shadow"]` | **偶数页下方有页码** | ❌ 误报书脊 + 漏检页码 |

> spine_shadow 全部得分 >= 0.75，但实际干扰是页码（page_number），书脊阴影是误报。page_number 检测功能尚未实现。

### Book 3
| 特征 | 检测结果 | README 真实值 | 判定 |
|------|---------|-------------|------|
| color_mode | `colored` | 彩色 | ✅ 正确 |
| background_color | `orange` | **淡红色** | ⚠️ 偏差（应为 red） |
| border_color | `orange` | **深红色** | ❌ 错误（应为 red） |
| page_type | `cut_half` | 已剪切 | ✅ 正确 |
| lines_per_page | `8` | 8行 | ✅ 正确 |
| interferences | `["stains"]` | 污渍 | ✅ 正确 |

> 颜色识别偏差：淡红色底 → 检测为 orange，深红色框 → 也检测为 orange。HSV 中淡红色（低饱和度的红色）容易落入 H=10-25 的 orange 区间。

### Book 4
| 特征 | 检测结果 | README 真实值 | 判定 |
|------|---------|-------------|------|
| color_mode | `colored` | 彩色 | ✅ 正确 |
| background_color | `orange` | **淡黄色** | ⚠️ 偏差（应为 yellow） |
| border_color | `orange` | **黑色** | ❌ 错误（应为 black） |
| page_type | `cut_half` | 已剪切 | ✅ 正确 |
| lines_per_page | `8` | 8行 | ✅ 正确 |
| interferences | `["spine_shadow"]` | **书脊阴影 + 污渍** | ⚠️ 部分正确（漏检污渍） |

> 1. 颜色：淡黄色检测为 orange（黄/橙边界问题）
> 2. border_color 逻辑有 bug：代码中 `border_color = bg_color if bg_color != "yellow" else "black"`，硬编码规则无法正确处理
> 3. stains 平均分 0.4，刚好未过 0.5 阈值，漏检

### Book 5
| 特征 | 检测结果 | README 真实值 | 判定 |
|------|---------|-------------|------|
| color_mode | `bw` | 黑白 | ✅ 正确 |
| page_type | `cut_half` | **未剪切（有白色页边距的整页）** | ❌ 错误 |
| lines_per_page | `8` | **9行** | ❌ 错误（受 page_type 连锁影响） |
| interferences | `["spine_shadow", "white_margin"]` | **白色页边距** | ⚠️ 部分正确（书脊误报） |

> 1. page_type 误判：宽高比 0.666 < 0.9，被判为 cut_half，但实际是未剪切整页 + 大面积白色页边距
> 2. lines_per_page 连锁错误：因为 page_type 错了，默认给了 8 而不是 9
> 3. white_margin 检测正确
> 4. spine_shadow 又是误报（score=0.9）

---

## 干扰检测详细分值

### 每张图的 spine / margin / stain 得分

**Book 1**（README: 无干扰）
```
File        Spine   Margin    Stain
1.png       1.000    0.000    0.000
10.png      1.000    0.000    1.000
2.png       1.000    0.643    0.000
3.png       1.000    0.584    0.000
4.png       1.000    0.000    0.000
5.png       1.000    0.000    0.000
6.png       1.000    0.000    1.000
7.png       0.976    0.000    0.000
8.png       1.000    0.000    1.000
9.png       1.000    0.000    0.000
AVG         0.998    0.123    0.300
```

**Book 2**（README: 偶数页下方有页码）
```
File        Spine   Margin    Stain
1.png       1.000    0.720    0.000
10.png      1.000    0.000    0.000
2.png       1.000    0.000    0.000
3.png       1.000    0.672    0.000
4.png       1.000    0.000    0.000
5.png       1.000    0.648    0.000
6.png       1.000    0.000    0.000
7.png       1.000    0.611    0.000
8.png       0.750    0.000    0.000
9.png       1.000    0.505    0.000
AVG         0.975    0.316    0.000
```

**Book 3**（README: 底色上有污渍）
```
File        Spine   Margin    Stain
1.png       0.209    0.000    1.000
10.png      0.225    0.000    1.000
2.png       0.217    0.000    1.000
3.png       0.185    0.000    1.000
4.png       0.177    0.000    1.000
5.png       0.119    0.000    0.868
6.png       0.170    0.000    0.267
7.png       0.221    0.000    1.000
8.png       0.159    0.000    1.000
9.png       0.246    0.000    1.000
AVG         0.193    0.000    0.914
```

**Book 4**（README: 书脊阴影 + 污渍）
```
File        Spine   Margin    Stain
1.png       1.000    0.000    1.000
10.png      1.000    0.000    0.000
2.png       1.000    0.000    1.000
3.png       1.000    0.000    1.000
4.png       1.000    0.000    1.000
5.png       1.000    0.000    0.000
6.png       1.000    0.000    0.000
7.png       1.000    0.000    0.000
8.png       1.000    0.000    0.000
9.png       1.000    0.000    0.000
AVG         1.000    0.000    0.400
```

**Book 5**（README: 白色页边距）
```
File        Spine   Margin    Stain
1.png       0.701    0.664    0.000
10.png      1.000    0.516    1.000
2.png       1.000    0.688    0.000
3.png       0.687    0.750    0.000
4.png       1.000    0.651    0.000
5.png       0.959    0.705    0.000
6.png       1.000    0.684    0.000
7.png       0.820    0.657    0.000
8.png       1.000    0.647    0.000
9.png       0.831    0.000    1.000
AVG         0.900    0.596    0.200
```

---

## 图片宽高比参考

| 书籍 | 样例尺寸 | 宽高比 | 判定 | 真实 |
|------|---------|--------|------|------|
| book1 | 1155×1559 | 0.741 | cut_half | cut_half ✅ |
| book2 | 2481×1738 | 1.428 | uncut_full | uncut_full ✅ |
| book3 | 2572×4658 | 0.552 | cut_half | cut_half ✅ |
| book4 | 3213×5811 | 0.553 | cut_half | cut_half ✅ |
| book5 | 3446×5171 | 0.666 | cut_half | **uncut_full** ❌ |

---

## 问题清单

| 编号 | 分析器 | 问题 | 影响书籍 | 严重度 | 状态 |
|------|--------|------|---------|--------|------|
| P1 | InterferenceAnalyzer | **spine_shadow 严重误报** — 旧算法只看单步梯度跳变，扫描边缘就能触发 | book1, book2, book5 | 🔴 高 | ✅ 已修复 |
| P2 | PageLayoutAnalyzer | ~~**book5 page_type 误判**~~ — 经核实 book5 README 明确标注"已剪切"，检测结果 cut_half 是正确的 | book5 | ~~🔴 高~~ | ✅ 非问题 |
| P3 | ColorModeAnalyzer | **background_color 偏差** — 淡红→orange，淡黄→orange，HSV 色调映射边界不准 | book3, book4 | 🟡 中 | 待修 |
| P4 | ColorModeAnalyzer | **border_color 逻辑简陋** — 没有独立检测边框区域颜色，用硬编码规则 `bg_color if bg_color != "yellow" else "black"` | book3, book4 | 🟡 中 | 待修 |
| P5 | InterferenceAnalyzer | **stains 漏检** — book4 平均分 0.4 未过 0.5 阈值 | book4 | 🟡 中 | 待修 |
| P6 | InterferenceAnalyzer | **page_number 检测缺失** — 没有页码检测功能 | book2 | 🟢 低 | 待修 |
| P7 | PageLayoutAnalyzer | **lines_per_page 硬编码** — 没有真实检测行数，依赖 Phase 3 修正 | 全部 | 🟢 低 | 待修 |

---

## 修正方案

### 🔴 高优先级

#### P1: spine_shadow 误报修正 ✅ 已完成
**文件**: `guji_preprocess/analyzers/interference.py` — `_detect_spine_shadow()`

**根因**: 旧算法只检测"边缘区域任意相邻两列的最大亮度差"，扫描背景→纸张的过渡（跳变 50-105）远超阈值 40，导致 book1/book2/book5 全部误报。

**修复方案**: 基于"书脊阴影从顶到底贯穿，边框上下有空白"的核心区分特征，重写为分段贯穿检测算法：
1. 将边缘条带沿垂直方向分成 5 个水平段（band）
2. 在每段内独立检测是否存在连续暗带（亮度低于中值 - 25 灰度级）
3. 要求顶部段和底部段都存在暗带（贯穿性）
4. 要求至少 4/5 段有暗带，且暗带位置一致（中心偏移 < 20%）

**修复后结果**:
| 书籍 | 旧结果 | 新结果 | README 真实值 | 判定 |
|------|-------|-------|-------------|------|
| book1 | spine_shadow (avg=0.998) | 无 (avg=0.300) | 无干扰 | ✅ 修正 |
| book2 | spine_shadow (avg=0.975) | 无 (avg=0.400) | 页码（非书脊） | ✅ 修正 |
| book3 | 无 (avg=0.193) | 无 (avg=0.100) | 无书脊 | ✅ 不变 |
| book4 | spine_shadow (avg=1.000) | spine_shadow (avg=1.000) | 有书脊阴影 | ✅ 正确保留 |
| book5 | spine_shadow (avg=0.900) | 无 (avg=0.000) | 白色页边距（非书脊） | ✅ 修正 |

#### P2: book5 page_type 误判 ✅ 非问题
经核实 book5 的 README 明确标注"筒子页剪切：已剪切 奇数页为右半页 偶数页为左半页"。
原始分析中错误地认为 book5 是未剪切整页，实际检测结果 `cut_half` 是**正确的**。
证据：book5 的左右白色页边距在奇偶页之间交替（奇数页右侧宽、左侧窄；偶数页相反），
这是典型的已剪切筒子页特征。

#### P0: 页边距裁切预处理 ✅ 已完成
**文件**: `guji_preprocess/preprocessors/crop_margin.py`

**需求**: 所有后续分析和预处理都应在去除页边距/扫描背景后进行，否则边缘特征（边框检测、颜色分析等）会被干扰。

**算法**: 利用行/列标准差区分"内容区"（高方差）和"背景区"（低方差），裁剪到内容区外边界（即边框外缘）。
1. 计算每列的像素标准差，自适应阈值（中间1/3区域中位数×0.25，最低8）
2. 从两端向内扫描，找到标准差超过阈值的位置 → 左右边界
3. 在内容列范围内计算每行标准差 → 上下边界
4. 加 3px padding 保护边框不被裁切

**改动**:
- `crop_margin.py`: 重写算法，`is_needed()` 改为始终返回 True
- `preprocessors/__init__.py`: CropMargin 移到 SplitPage 之前（先裁切再拆页）

**测试结果**:
| 书籍 | 裁切情况 | 判定 |
|------|---------|------|
| book1 | 四周 ~137px 白色扫描背景去除，边框完整 | ✅ |
| book2 | 左右 ~240-320px 白色背景去除，上下因页而异 | ✅ |
| book3 | 几乎不裁（0-5px），无页边距正确保持原样 | ✅ |
| book4 | 三面 ~120px 黑色填充去除，剪切侧保留(left=0) | ✅ |
| book5 | 三面大白色背景去除，奇偶页左右交替正确 | ✅ |

### 🟡 中优先级

#### P3: background_color 偏差修正
**文件**: `guji_preprocess/analyzers/color_mode.py` — `_hue_to_color_name()`

**方案**:
1. 缩窄 orange 范围：当前 10-25，改为 15-22
2. 扩大 red 范围：当前 0-10 + 170-180，改为 0-15 + 165-180
3. 扩大 yellow 范围：当前 25-35，改为 22-40
4. 考虑加入饱和度维度：低饱和度的橙色偏向"淡红"或"淡黄"

#### P4: border_color 独立检测
**文件**: `guji_preprocess/analyzers/color_mode.py` — `_identify_colors()`

**方案**:
1. 提取图像边缘区域（四边各 5%）作为边框候选区
2. 对边框区域做独立的 HSV 色调分析
3. 如果边框区域饱和度很低，判定为 black；否则用色调映射

#### P5: stains 阈值调整
**文件**: `guji_preprocess/analyzers/interference.py` — `_detect_stains()`

**方案**:
1. 降低判定阈值从 0.5 → 0.35
2. 或者对有书脊阴影的图片，先去除阴影区域后再做污渍检测

### 🟢 低优先级

#### P6: page_number 检测（新功能）
暂缓，影响面小，可作为后续独立特性。

#### P7: lines_per_page 精确检测
当前 Phase 3 边框检测会修正，暂不改动 Phase 1 的粗略估计。
