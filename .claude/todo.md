# open-guji-cv 近期任务

> 来源：overview 项目下发 (2026-02-23)
> 背景：新方案 — 用 OCR 位置 + 网络文字合并，自动化第 2-10 册数字化

## 目标

完成 OCR pipeline 全部功能，对欽定四庫全書簡明目錄全部 10 册图片运行 OCR，输出每页的**字符位置和识别文字** JSON，供下游合并器使用。

不要求 OCR 文字完全准确（会用网络文字纠正），但要求**位置信息尽可能准确**，尤其是：
- 每列的边界
- 夹注区域的检测和子列拆分
- 每个字符在列中的相对位置（第几行）

## Phase 5: 全 10 册 OCR 运行（下一步）

### 输出格式要求

cell type `"jiazhu"` 示例：
```json
{"type": "jiazhu", "index": 8, "sub_col": 1, "y_top": 490, "y_bottom": 530, "text": "舊", "confidence": 0.85}
```

列级别增加：`"has_jiazhu": true`

## Phase 5: 全 10 册 OCR 运行

完成夹注功能后，对全部 10 册运行 OCR pipeline。

图片位置：`\\wsl.localhost\Ubuntu\home\lishaodong\workspace\guji-resource\欽定四庫全書簡明目錄·文淵閣本\01_初始化\images\`
- 06064237.cn ~ 06064246.cn（对应册 1-10，每册约 90 张图）

### 执行步骤

- [ ] 对册 1 (06064237.cn) 运行完整 pipeline，验证输出质量
- [ ] 跳过每册前几页（封面、书名页、空白页 — 参考 `ce0X_page_layout.json` 的页面分类）
- [ ] OCR 结果以 JSON 格式存放，每页一个文件
- [ ] 输出路径：`guji-resource/.../03_信息提取/ocr/ce0X/pageNNN.json`
- [ ] 确认输出质量后，批量处理册 2-10

### OCR 输出 JSON 格式（供合并器使用）

每页输出一个 JSON，包含：
```json
{
  "page_index": 23,
  "columns": [
    {
      "index": 0,
      "left_x": 100,
      "right_x": 200,
      "has_jiazhu": false,
      "jiazhu_ranges": [],
      "ocr_text": "易類一舊本題...",
      "cells": [
        {"type": "char", "index": 0, "y_top": 50.0, "y_bottom": 75.5, "text": "易", "confidence": 1.0},
        {"type": "jiazhu", "index": 8, "sub_col": 1, "y_top": 490, "y_bottom": 530, "text": "舊", "confidence": 0.85}
      ]
    }
  ]
}
```

---

## 已完成

- [x] Phase 1: 夹注区域检测（支持多段）
  - `_detect_jiazhu_regions()` 已实现
  - book6 v01_024-026 验证通过
  - book1 回归测试通过
- [x] Phase 2: 子列拆分
  - `_split_jiazhu_subcols()` 在中间 30% 范围找垂直投影最小值
  - 可视化：标注图上画橙色分割线（虚线）
- [x] Phase 3: 子列 OCR + 网格构建
  - `_segment_column()` 分正文/夹注交替段
  - `_build_jiazhu_column()` 多段合并，全局 slot_idx 递增
  - `_ocr_subcol()` 子列投影分割 + OCR + 逐区域匹配
  - 输出 `type="jiazhu"` + `sub_col` + `has_jiazhu`
- [x] Phase 4: 集成测试
  - `detect()` 集成夹注处理流程
  - book6 v01_023-025 端到端测试通过
  - book1 回归测试通过（无夹注误判）
  - 标准输出格式正确输出 jiazhu type + sub_col
