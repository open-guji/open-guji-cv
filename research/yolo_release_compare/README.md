# yolo_release_compare：yolo_tool 切分 release vs CV 切分（2026-10-19）

结论见 [doc/research/yolo_release_comparison.md](../../doc/research/yolo_release_comparison.md)。

| 文件 | 内容 |
|---|---|
| `evaluate.py` | 主入口：`dzg` / `make-ws-a` / `make-ws-b` / `test-a` / `test-b` / `prior`，用法见文件头 |
| `run_yolo.py` + `yolo_headless.py` | 无 GUI 复现 yolo_tool 原生推理（版面 → 裁条 → 单字 → 阅读序），逐行对照 `core/workers.py` |
| `their.py` | 读 release `format_version 2`（逐卷 `text.jsonl.gz`，x/y 为左上角） |
| `ours_prod.py` / `ours_md.py` | 读我们的 `cell_shrink` 产物（右上原点 → 左上）与整册报告 `volNN.md` |
| `colcount.py` / `boxeval.py` | 逐列字数（YOLO 按版面框水平重叠聚列、轻清理）与贪心 IoU 匹配 |
| `dzg_eval.py` / `cmp_md.py` | 对 daizhige 逐列本的列边界吻合；我们的整册报告 ↔ release 页面对齐 |
| `results/` | 抽样页表、YOLO 原始输出（`y*.jsonl.gz`）、release 逐卷对 daizhige 的结果 |
