# Backlog

> 状态：低优先级 (2026-02-22)

## 集成与测试

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

---

## 全册运行

（等夹注功能完成后再考虑恢复）

- [ ] 对《欽定四庫全書簡明目錄》vol01 图片运行完整 pipeline
- [ ] OCR 结果存放到 `03_信息提取/ocr/vol01/`
- [ ] 跳过前两页（书名页、作者信息页）
