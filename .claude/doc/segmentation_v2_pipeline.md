# 切分管线重定义（v2：四步）

## 背景

现有切分链路是 Phase 2（`border_detect.py` 版面检测）+ Phase 3
（`grid_segment.py` 字符网格）糊在一起的老设计，两步内部各自有很多特例
判据（详见 `phase2_detectors.md`/`phase3_char_grid.md`/`char_clustering_design.md`）。
这一轮探索出的两个独立新算法——`peak_line_search.py`（半高宽匹配度 + 位置
角度联合搜索找边框/界行）、`row_boundaries.py`（弹性DP切字格）——分别在
vol02/133、vol02/135、vol01/33、vol01 133~142 等页上验证过比现有算法更准
（详见各自设计文档），但都还只是"跟生产并存的独立工具"，没有正式取代
生产管线。

这次要做的是**把整条切分链路重新切成四个边界清晰的步骤**，每步有严格的
输入输出格式和独立的金标测试集，可以逐步开发、逐步验证、逐步替换生产，
而不是像现在这样版面检测和网格切分内部揉在一起改。

**这份文档只整理四步的总体框架**，细节（尤其 Step 1）下一轮再深入。

## 坐标系约定（新，四步统一遵守）

跟旧管线（`phase2_layout`/`phase3_char_grid` 现有产物）不一样，这是这次
明确要改的：

- **原点在页面右上角**（旧管线是左上角）。
- 列号、格号等一切"第几个"的计数**从 1 开始**，不是从 0 开始（旧
  `phase3_char_grid` 的 `cells[].index` 是 0 开始，新管线不再沿用）；
  列号从右到左递增（第 1 列在最右侧），跟古籍阅读顺序一致——这一点旧
  `design.md` 里其实已经这么约定，只是从来没有贯彻到坐标系本身，新管线
  要坐标原点和计数方向都对齐这个阅读顺序，不再是"计数从右到左、坐标
  原点却在左上角"这种拧巴状态。
- y 轴仍是向下递增（从页面顶端往下数，不用跟着列号一起反）。
- 具体到某一步内部数组下标要不要也跟着从 1 开始（比如某条曲线的采样点
  序号），还是只有对外的"第几列/第几格"这种业务字段从 1 开始——留到细化
  Step 1 时定，本文档先占位。

## 四步总览

每步一节，格式统一：定义 / 输入 / 输出 / 现有实现 / 测试集现状。

### Step 1：边框探测

**定义**：从原始扫描图上找出版框（上下内外边框）和界行（列间分隔线），
显式处理倾斜和模糊/磨损；有抬头列的页面额外定位抬头框。

**输入**：原图（未去噪、未矫正的单页扫描图）。

**输出**（已定版，`open_guji_cv/utils/border_geometry.py`）：

```python
@dataclass
class HLine:               # 水平线(上/下版框)
    y_at_right: float       # 该线在页面右端(新坐标系x=0处)的y值
    slope: float             # dy/dx，x向左递增
    kind: str                 # "top" | "bottom"

@dataclass
class VLine:                # 竖直线(外边框/界行)
    x_at_top: float          # 该线在页面顶端(y=0处)的x值
    slope: float             # dx/dy

@dataclass
class HeadRaiseBorder:      # 某一抬头列自己的内外上边框(局部量，非整页一条线)
    col: int                  # 列号，从右到左、从1开始
    inner_y: float
    outer_y: float

@dataclass
class BorderDetectionResult:
    width: int
    height: int
    top: HLine
    bottom: HLine
    verticals: list[VLine]           # 从右到左排列：[0]=第1列外边框(最右)
    head_raise: list[HeadRaiseBorder]  # 目前恒为空列表，见下

def detect_borders(gray, expected_cols: int) -> BorderDetectionResult: ...
```

一般水平线只有 top/bottom 两条；本版没有把"2~4条"这个更宽的口子做成
数据结构（只固定了 top+bottom），抬头框的纵坐标改用专门的 `HeadRaiseBorder`
承载，不是塞进"水平线"字段——每个抬头列的抬头框是**局部量**（只影响这
一列，不贯穿整页），跟贯穿全页的版框线放在同一个"水平线列表"里语义
不一致，拆开更清楚。

**现有实现**：`open_guji_cv/utils/peak_line_search.py` 提供底层探测算法
（半高宽匹配度找峰 + 位置角度联合搜索），跟生产 `border_detect.py`/
`detectors/borders.py` 并存，未接入生产管线。`border_geometry.py` 是新加
的坐标系转换层——`peak_line_search.py` 内部完全不用改，仍按标准图像坐标
（左上角原点、x向右）工作，`detect_borders()` 探测完之后做一次坐标转换
（`_hline_to_new`/`_vline_to_new`，含把 `peak_line_search` 内部"锚点在
页面中心"的约定重新锚定到"页面顶端/右端"），包成新约定的输出。

**抬头框探测**：`detect_borders()` 的 `head_raise` 字段目前恒为空
列表——**没有可靠的自动探测算法**（试过"扫描墨量占比"，会把普通列的
装饰花边也误判成抬头，见 `row_boundaries_design.md`「抬头列」节），
需要人工标注补上，见下面「测试集」。

**测试集**：**标注中**。现有测试集（`text-band`、`page-crop` 等）测的
是边框探测出错之后下游的症状（窗口太小丢字、裁切吃掉整列），不是直接
拿人工核校的边框/界行坐标做金标比对；单测 `tests/test_border_geometry.py`
只验证坐标转换数学本身是对的，也不能替代真实页面的金标。第一批标注页面
已发布（见 `artifacts/README.md`「Step1边框探测金标标注」）：2 普通页
（vol01/137、138）+ 3 抬头页（vol01/32、33、49——32/49 是这轮新确认的
真实抬头页，此前只深入分析过 33），种子取自 `peak_line_search` 自动
探测，等人工拖拽核校完导出即为金标（导出后按标准像素坐标两端点，用
`VLine.from_endpoints`/`HLine.from_endpoints` 转成本文档定义的新坐标系）。

### Step 2：单列射影变换 + 去噪

**定义**：给定 Step 1 里某一列的左右两条边线，把这一列做射影变换矫正成
竖直矩形，并去掉噪点（书斑、墨渍等非文字干扰）。

**输入**：原图 + Step 1 输出中该列的左右边线 `(position, slope)`。

**输出**：该列去透视后的竖直矩形灰度图（去噪后）。

**现有实现**：`row_boundaries.py`/`peak_line_search.py` 探索时都各自写过
一次性的射影矫正代码（`cv2.getPerspectiveTransform` + `warpPerspective`，
只用两条边线的 position+slope，取满页高不按上下版框裁），但没有沉淀成
独立、可复用的函数，也没有做"去噪"这一部分。

**测试集**：**目前没有**。

### Step 3：单列文字切分

**定义**：把 Step 2 输出的单列矩形图切成一个个字格，包括正常字、空白格、
抬头字、双行小注（a/b 两半）。

**输入**：Step 2 输出的单列矩形灰度图。

**输出**：字格边界列表，每格标注类型（字/空白/抬头/夹注a/夹注b）。

**现有实现**：`row_boundaries.py`（弹性DP：候选=波谷+页面共享周期先验+
三层硬约束）是"切普通字格"这部分的现成实现，vol02/135、vol01/33 两页
验证过；`top_slack` 参数解决了"抬头但格数不变"的情况，"抬头到多一个字"
的情况还没解决（见 `row_boundaries_design.md`）。**双行小注还完全没有
接进这条新链路**——生产 `grid_segment.py` 里有夹注 a/b 拆分的逻辑
（`jiazhu-tail` 等分片专门测这个），但那是旧管线的实现，没有迁移到
`row_boundaries.py` 这条新链路上。

**测试集**：`open-guji-dataset/char-segmentation/row-boundaries`
（vol02/135 普通页 + vol01/33 含 4 个抬头列，抬头列里"多一字" vs "不多字"
两种都有金标）——覆盖普通字格切分和部分抬头场景，**双行小注没有专门
测试集**（`jiazhu-tail` 测的是生产旧管线的段端修复，不是新链路）。

### Step 4：字框收缩

**定义**：把 Step 3 给出的粗字格（矩形）收缩成贴合字身墨迹的最小矩形框。

**输入**：Step 3 的字格粗框 + 原图（或 Step 2 的矫正图）。

**输出**：每个字格对应的最小外接矩形框。

**现有实现**：生产 `open_guji_cv/clustering/extractor.py::CharExtractor.
extract_page`（连通体归属 + 清边 + 弯曲界行处理等一整套已经调好的逻辑）。
这一步用户已经确认"可以直接复用旧算法"，vol01 十页抽查（133~142）验证过
效果——配合 Step 1 用新算法但要注意**逐列单独去斜**，不能像最初尝试那样
拿全页共享一个 shear 喂给它（会在残余倾角偏离页面中位数较大的列上把
相邻字的连通体判串，细节见 `artifacts/README.md`「vol01 新算法逐字框选」
条目）。

**测试集**：`open-guji-dataset/char-segmentation/instances`（`clean`/
`contaminated`/`truncated`/`not_text` 四分类）和 `cells`（合成数据、像素级
金标）是现有最接近的测试集——测的是"图块干不干净/完不完整"，跟"框是不是
最小矩形"角度略有差异（该数据集原则是"多裁一点空白不算失败，只看墨对不
对"），可以先复用，够不够精确覆盖"最小矩形"这个具体要求，留到细化这一步
时再看。

## 下一步

先细化 Step 1（边框探测）的严格算法/接口定义，并建金标测试集——普通页
一批 + 抬头页专项一批（抬头框内外边框坐标目前完全是空白，优先级最高）。
