# 夹注（双列小字）检测设计

> 2026-02-22 | overview 项目下发

## 背景

古籍中常见"夹注"排版：一列内有两列小字并排排列（占原列宽度一半），用于书目注释、引用来源等。当前 `CharGridDetector` 假设每列为单列等宽文字，无法处理夹注。

测试数据：`data/book6/`（《欽定四庫全書簡明目錄·文淵閣本》第一册）

## 目标

在现有 char_grid 检测管线中增加夹注识别能力：
1. 检测列中是否存在夹注区域
2. 定位夹注区域的起止行
3. 将夹注区域拆分为左右两个子列
4. 分别 OCR 两个子列
5. 输出符合 guji_layout 格式的 jiazhu cell

## 一、夹注的视觉特征

基于 book6 图片观察，**一列中正文和夹注可以交替出现**：

```
┌──────────┐
│ 易       │  row 0   ← 正文段 A（大字，占满列宽）
│ 類       │  row 1
│ 一       │  row 2
│ 舊│流    │  row 3   ← 夹注段 1（双列小字）
│ 本│傳    │  row 4
│ 題│已    │  row 5
│ 卜│久    │  row 6
│ 子│今    │  row 7
│ ...│...  │  ...
│ 周       │  row 13  ← 正文段 B（大字）
│ 易       │  row 14
│ 鄭│元    │  row 15  ← 夹注段 2（双列小字）
│ 康│撰    │  row 16
│ ...│...  │  ...
└──────────┘
```

**关键特征**：
1. 字符宽度突然减小（约为正文的 50%-70%）
2. 水平方向上有两个墨迹峰（垂直投影呈双峰分布）
3. 两个子列之间有明显的纵向间隙
4. 夹注字符高度通常也略小于正文
5. **正文和夹注可以多次交替**——不能假设一列只有一段夹注

## 二、检测算法

### 2.1 总体流程

在 `CharGridDetector.detect()` 的现有流程中插入夹注检测步骤：

```
现有流程：
  对每列 → 投影分割 → OCR → 构建网格

新流程：
  对每列 → 投影分割 → 【逐区域夹注检测】→ 按段分组：
    ├── 正文段 → 现有 OCR + 网格构建
    └── 夹注段 → 拆分子列 → 各自 OCR + 网格构建
    最终合并所有段的 cells
```

**关键：支持一列内正文和夹注多次交替。**

### 2.2 Step 1: 夹注区域检测（多段）

**方法：逐区域垂直投影分析**

对列中每个投影区域，分析其垂直投影（水平方向的墨迹分布）。
正常行呈单峰（一个字占满列宽），夹注行呈双峰（两个字各占半列宽）。

```python
def _detect_jiazhu_regions(self, col_gray, regions, col_width, theoretical_char_h):
    """检测列中的所有夹注区域（支持多段）。

    对每个投影区域分析垂直投影是否呈双峰分布。
    连续的双峰区域构成一个夹注段。

    Returns:
        list of (start_region_idx, end_region_idx)
        空列表表示无夹注
    """
    mid_x = col_width // 2
    gap_zone = (int(mid_x * 0.7), int(mid_x * 1.3))  # 中间 30% 区域

    is_dual = []
    for r_top, r_bot in regions:
        region_img = col_gray[r_top:r_bot, :]
        v_proj = np.sum(region_img < 128, axis=0)

        mid_proj = v_proj[gap_zone[0]:gap_zone[1]]
        left_proj = v_proj[:gap_zone[0]]
        right_proj = v_proj[gap_zone[1]:]

        has_gap = (np.mean(mid_proj) < np.mean(v_proj) * 0.3)
        has_left = (np.max(left_proj) > threshold)
        has_right = (np.max(right_proj) > threshold)

        is_dual.append(has_gap and has_left and has_right)

    # 找所有连续 True 段（每段 >= MIN_JIAZHU_ROWS 个区域）
    MIN_JIAZHU_ROWS = 3
    jiazhu_ranges = []
    i = 0
    while i < len(is_dual):
        if is_dual[i]:
            start = i
            while i < len(is_dual) and is_dual[i]:
                i += 1
            end = i  # exclusive
            if end - start >= MIN_JIAZHU_ROWS:
                jiazhu_ranges.append((start, end - 1))  # inclusive
        else:
            i += 1

    return jiazhu_ranges
```

**辅助判据**：
- 字符高度：夹注区域的投影区域间距明显小于正文
- 列宽利用率：正文字符占列宽 80%+，夹注每个子列只占 40%-50%
- 连续性：夹注至少连续 3 个以上投影区域
- 单行偶尔双峰（如 "三" 字）不应误判——要求连续多行

### 2.3 Step 2: 分段处理

根据检测结果，将投影区域分成交替的正文段和夹注段：

```python
# 例: regions 有 21 个区域，夹注检测返回 [(3, 12), (15, 19)]
# 则分段为:
#   正文段:  regions[0:3]    → index 0-2
#   夹注段1: regions[3:13]   → index 3-12
#   正文段:  regions[13:15]  → index 13-14
#   夹注段2: regions[15:20]  → index 15-19
#   正文段:  regions[20:21]  → index 20 (如果有)

def _segment_column(self, regions, jiazhu_ranges):
    """将区域分为正文段和夹注段的交替序列。

    Returns:
        list of (seg_type, region_indices)
        seg_type: "normal" | "jiazhu"
    """
    segments = []
    prev_end = 0
    for jz_start, jz_end in sorted(jiazhu_ranges):
        if prev_end < jz_start:
            segments.append(("normal", list(range(prev_end, jz_start))))
        segments.append(("jiazhu", list(range(jz_start, jz_end + 1))))
        prev_end = jz_end + 1
    if prev_end < len(regions):
        segments.append(("normal", list(range(prev_end, len(regions)))))
    return segments
```

### 2.4 Step 3: 子列拆分

在夹注区域内，沿垂直方向将列图像一分为二：

```python
def _split_jiazhu_subcols(self, col_gray, jiazhu_y_top, jiazhu_y_bottom, col_width):
    """将夹注区域图像拆分为左右两个子列。

    找到最佳的垂直分割线（墨迹最少的纵向位置）。
    """
    jiazhu_img = col_gray[jiazhu_y_top:jiazhu_y_bottom, :]
    v_proj = np.sum(jiazhu_img < 128, axis=0)

    # 在列宽中间 30% 范围内找投影最小值
    mid = col_width // 2
    search_start = int(mid * 0.7)
    search_end = int(mid * 1.3)
    split_x = search_start + np.argmin(v_proj[search_start:search_end])

    right_sub = col_gray[jiazhu_y_top:jiazhu_y_bottom, :split_x]   # sub_col=1 (右)
    left_sub = col_gray[jiazhu_y_top:jiazhu_y_bottom, split_x:]    # sub_col=2 (左)

    return right_sub, left_sub, split_x
```

> 注意：在古籍竖排中，"右"是先读的（sub_col=1），"左"是后读的（sub_col=2）。但由于图片坐标系中 x 从左到右，在图片中 sub_col=1（右子列）实际在图片的**右侧**（x 值较大），sub_col=2（左子列）在图片的**左侧**（x 值较小）。需根据实际排版方向确认。

### 2.5 Step 4: 子列 OCR

对每个子列图像，复用现有的 `_projection_segment` + `_ocr_column_words` + `_build_char_grid`：

```python
# 对右子列
right_regions = self._projection_segment(right_sub_gray, jiazhu_char_h)
right_text, right_words = self._ocr_column_words(right_sub_img, y_offset)
right_cells, _ = self._build_char_grid(right_regions, right_text, right_words, ...)

# 对左子列
left_regions = self._projection_segment(left_sub_gray, jiazhu_char_h)
left_text, left_words = self._ocr_column_words(left_sub_img, y_offset)
left_cells, _ = self._build_char_grid(left_regions, left_text, left_words, ...)
```

**夹注子列的 expected_chars**：
- 夹注区域占 N 个行位，每个子列的 expected_chars = N
- 字高 `jiazhu_char_h` = 正文字高 × 0.7（因为夹注字更小）

### 2.6 Step 5: 多段合并

按段顺序合并所有正文段和夹注段的 cells：

```python
def _build_jiazhu_column(self, col_gray, col_image, regions,
                         jiazhu_ranges, col_top, col_bottom,
                         expected_chars, theoretical_char_h, y_offset):
    """处理含夹注的列（支持多段交替）。"""
    segments = self._segment_column(regions, jiazhu_ranges)
    final_cells = []
    slot_idx = 0  # 全局行号

    for seg_type, region_indices in segments:
        seg_regions = [regions[i] for i in region_indices]

        if seg_type == "normal":
            # 正文段：用现有逻辑处理
            seg_ocr, seg_words = self._ocr_column_words(...)
            seg_cells, _ = self._build_char_grid(
                seg_regions, seg_ocr, seg_words, ...)
            for cell in seg_cells:
                cell["index"] = slot_idx
                slot_idx += 1
                final_cells.append(cell)

        else:  # jiazhu
            # 夹注段：拆分子列，分别处理
            jz_y_top = seg_regions[0][0]
            jz_y_bottom = seg_regions[-1][1]
            right_sub, left_sub, split_x = self._split_jiazhu_subcols(
                col_gray, jz_y_top, jz_y_bottom, col_width)

            right_cells = ...  # 右子列 OCR + 网格
            left_cells  = ...  # 左子列 OCR + 网格

            n_rows = max(len(right_cells), len(left_cells))
            for i in range(n_rows):
                idx = slot_idx + i
                if i < len(right_cells) and right_cells[i]["type"] == "char":
                    right_cells[i].update(type="jiazhu", index=idx, sub_col=1)
                    final_cells.append(right_cells[i])
                if i < len(left_cells) and left_cells[i]["type"] == "char":
                    left_cells[i].update(type="jiazhu", index=idx, sub_col=2)
                    final_cells.append(left_cells[i])
            slot_idx += n_rows

    return final_cells, has_jiazhu=True
```

**关键**：`slot_idx` 全局递增，保证正文和多段夹注的 index 不冲突且连续。

## 三、集成到现有管线

### 3.1 CharGridDetector 改动

在 `detect()` 方法的列循环中：

```python
for col in columns_info:
    # ... 现有的列裁剪代码 ...

    # Step 1: 投影法分割（现有）
    regions = self._projection_segment(col_gray, theoretical_char_h)
    regions = [(y1 + r_top, y1 + r_bot) for r_top, r_bot in regions]

    # 【新增】Step 1.5: 夹注检测（返回多段）
    jiazhu_ranges = self._detect_jiazhu_regions(
        col_gray, regions, x2 - x1, theoretical_char_h)

    if jiazhu_ranges:
        # 含夹注的列：按段处理（支持正文/夹注多次交替）
        cells, char_h = self._build_jiazhu_column(
            col_gray, image[y1:y2, x1:x2],
            regions, jiazhu_ranges,
            col_top, col_bottom, expected_chars,
            theoretical_char_h, y1)
        has_jiazhu = True
    else:
        # 普通列处理（现有逻辑不变）
        ocr_text, word_boxes = self._ocr_column_words(col_image, y1)
        cells, char_h = self._build_char_grid(...)
        has_jiazhu = False

    result_columns.append({
        "index": col_idx,
        "left_x": left_x,
        "right_x": right_x,
        "has_jiazhu": has_jiazhu,
        "ocr_text": ocr_text,
        "cells": cells,
    })
```

### 3.2 BookProfile 扩展

在 `profile.py` 中，可选地记录此书是否有夹注：

```python
@dataclass
class BookProfile:
    # ... 现有字段 ...
    has_jiazhu: bool = False  # 已存在但未使用，现在启用
```

在 Phase 1 分析阶段，可以通过抽样检测是否有列呈现双峰投影来设置此标记。
但 Phase 3 的夹注检测应该是逐列独立判断的，不依赖 profile。

## 四、输出格式

完全符合 `guji_layout` 定义的 char_grid 格式（见 `guji-platform/.claude/doc/jiazhu_ocr_design.md`）。

## 五、测试计划

### 5.1 用 book6 测试

```bash
# 完整管线
python -m src run data/book6/ --format combined --clean

# 或仅 Phase 3
python -m src detect-grid data/book6/
```

验证点：
- [ ] v01_023: 中间列（含"子夏易傳十一卷"后的注释）应检测到夹注
- [ ] v01_024: 多列含夹注文字应正确识别
- [ ] 纯正文列（如书名列）不应误判为夹注
- [ ] 夹注 cell 的 sub_col 赋值正确（右=1, 左=2）
- [ ] 夹注 cell 的 index 与正文 cell 的 index 连续
- [ ] JSON 输出可被 guji_layout from_ocr_result() 正确解析

### 5.2 回归测试

确保 book1-book5（无夹注）的输出不受影响：
```bash
python -m src detect-grid data/book1/
# 所有列 has_jiazhu 应为 false，cells 无 type="jiazhu"
```

## 六、实现优先级

1. **先做检测**：`_detect_jiazhu_region()` — 能判断有/无夹注
2. **再做拆分**：`_split_jiazhu_subcols()` — 确定分割线
3. **最后做 OCR**：子列的投影+OCR+网格构建
4. **集成测试**：book6 端到端验证

## 七、已知局限

1. 三列小字（极少见）暂不支持
2. 夹注区域内的空行（正文留白后继续夹注）可能误判
3. 夹注开始/结束的精确行号可能偏差 1 行
4. 子列分割线如果穿过文字笔画可能不准确
