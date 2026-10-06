# yolo_tool 的 YOLO 模型在四庫 vol03 上的探针（F1，2026-10-02）

结论与解读见 `doc/yolo_tool_segmentation_review.md`。本目录只放可复现的东西：

| 文件 | 内容 |
|---|---|
| `probe.py` | 跑 yolo_tool `model/{type,slide}/best.onnx`（onnxruntime，不装 torch），与 guji-page 样张里的 CV 列框/字框比 IoU |
| `result_vol03_p3_p107.json` | 输出：版面框（类别、置信、xywh）；逐列 CV 字框数、排除数、YOLO 框数、IoU≥0.5 命中数 |
| `vol03_p3_yolo_vs_cv.jpg`、`vol03_p107_yolo_vs_cv.jpg` | 1200 px 叠图：蓝粗框 = YOLO 正文列条、绿粗框 = YOLO 夹注/版心、红 = YOLO 单字、浅蓝 = CV 字框 |

```bash
pip install onnxruntime
python research/yolo_tool_probe/probe.py <yolo_tool 仓> <工作区 data_full/zongmu/vol03> <出图目录> > result.json
```

p107 的 CV 框按 `meta.json` 的 `canvas_image` 换算到工作区现行 `107.png` 上比（产物建在旧裁法的图上，见 guji-page 样张 README）。

## 第二轮：分场景扩测（2026-10-02，用户追加）

`probe2.py`（两种喂法、按场景打标签算命中）→ `inkcheck.py`（墨被谁的框漏掉）/ `framecheck.py`（压版框线）/
`sheets.py`（分歧拼图，左 CV 蓝、右 YOLO 红）。vol03 27 页 + vol02 11 页，产物取自 guji-workspace 快照
`snap/96mid1ogzk/vol03/20260928T1708-full` 与 `vol02/20260929T1023|1024|20260930T0339`，guji-page 用 `export_guji_page.py` 先导出。
`r2/` 是输出与挑出来的拼图；解读见 `doc/yolo_tool_segmentation_review.md` §四。
