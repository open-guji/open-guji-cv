# open-guji-cv 近期任务

> 来源：overview 项目下发 (2026-02-22)

## 优先：夹注（双列小字）检测功能

> 设计文档：`.claude/doc/jiazhu_detection.md`
> 测试数据：`data/book6/`（10 张图片，含大量夹注列）

### Phase 1: 夹注区域检测（支持多段）

- [x] 实现 `_detect_jiazhu_regions(col_gray, regions, col_width, theoretical_char_h)` 方法
  - 逐区域分析垂直投影（双峰检测）
  - 找出所有连续的双峰区域段（每段 >= 3 个区域）
  - **返回多段**：`[(start1, end1), (start2, end2), ...]`，空列表表示无夹注
  - 支持一列内正文和夹注多次交替
  - 额外边缘裁剪 + 峰宽检查防止界行线误判
- [x] 用 book6 的 v01_024-026 手动验证检测准确性
- [x] book1 回归测试（10 页全部无误判）

### Phase 2: 子列拆分

- [ ] 实现 `_split_jiazhu_subcols(col_gray, jiazhu_y_top, jiazhu_y_bottom, col_width)` 方法
  - 在中间区域找垂直投影最小值作为分割线
  - 返回左右两个子列图像
- [ ] 可视化分割结果（标注图上画分割线）

### Phase 3: 子列 OCR + 网格构建（多段合并）

- [ ] 实现 `_segment_column(regions, jiazhu_ranges)` 方法
  - 将区域分为交替的正文段和夹注段
- [ ] 实现 `_build_jiazhu_column()` 方法
  - 遍历每个段：正文段用现有 `_build_char_grid()`，夹注段拆分子列分别处理
  - 全局 `slot_idx` 递增，保证多段 index 连续不冲突
  - 合并结果，标记 `type="jiazhu"` 和 `sub_col`
- [ ] 列数据增加 `has_jiazhu` 标记


---

## 延后：集成测试与全量管线运行

以下任务已移至 `.claude/backlog.md`，目前重点在于完成夹注核心算法。

- Phase 4: 集成与测试
- 后续：对《欽定四庫全書簡明目錄》第一册运行完整管线
