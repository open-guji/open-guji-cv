# open-guji-cv 近期任务

> 来源：overview 项目下发 (2026-02-22)

## 优先：夹注（双列小字）检测功能

> 设计文档：`.claude/doc/jiazhu_detection.md`
> 测试数据：`data/book6/`（10 张图片，含大量夹注列）

### Phase 1: 夹注区域检测（支持多段）

- [ ] 实现 `_detect_jiazhu_regions(col_gray, regions, col_width, theoretical_char_h)` 方法
  - 逐区域分析垂直投影（双峰检测）
  - 找出所有连续的双峰区域段（每段 >= 3 个区域）
  - **返回多段**：`[(start1, end1), (start2, end2), ...]`，空列表表示无夹注
  - 支持一列内正文和夹注多次交替
- [ ] 用 book6 的 v01_023 和 v01_024 手动验证检测准确性

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

### Phase 4: 集成与测试

- [ ] 修改 `CharGridDetector.detect()` 集成夹注检测流程
- [ ] book6 全部 10 张图片端到端测试
- [ ] book1-book5 回归测试（无夹注，不应误判）
- [ ] 输出 JSON 用 guji_layout `from_ocr_result()` 验证可解析

### 输出格式要求

cell type `"jiazhu"` 示例：
```json
{"type": "jiazhu", "index": 8, "sub_col": 1, "y_top": 490, "y_bottom": 530, "text": "舊", "confidence": 0.85}
```

列级别增加：`"has_jiazhu": true`

约束：唯一 index 数 = chars_per_line（夹注同一 index 可有 sub_col=1 和 sub_col=2 两个 cell）

---

## 后续：对《欽定四庫全書簡明目錄》第一册运行完整管线

（等夹注功能完成后再执行）

- [ ] 对 vol01 图片运行完整 pipeline
- [ ] OCR 结果存放到 `03_信息提取/ocr/vol01/`
- [ ] 跳过前两页（书名页、作者信息页）
