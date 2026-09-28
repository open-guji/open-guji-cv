# 即/歷异码位逐处核（P 道，2026-09-28）

任务书：overview `项目进展/图片初步数字化/进度/字形库/任务书-P-光盘版即歷异码位逐处核.md`
结果：overview `项目进展/图片初步数字化/进度/inbox/P-即歷逐处核/20260928-0006-done.md`

`classify_positions.py`：在光盘版 `corpus/zongmu_wenyuange_wikisource.txt` 里用精确的
`^欽定四庫全書總目卷N` 标题行（不是粗糙的 `^卷N`，那会把书内引用别的著作的「卷一/卷二」
和目录页的逐卷罗列行都误判成本书标题）切出每卷的行区间，定位「即/歷/卽/厯」各处出现的
行号、卷号、上下文，并按 `books/volNN.yaml` 的覆盖表判断是否落在已扫描范围内。

跑法：`python classify_positions.py`（需要 `GUJI_WORKSPACE` 指到本书工作区，脚本内写死了
绝对路径，换环境要改 `CORPUS` 常量）。

后续如果要对落在 vol01–vol10 范围内的候选做真实锚定+截图，用现成 CLI：
```
guji step border_detect vol09 --pages <估算窗口> -w <ws>
guji step column_warp/row_segment/cell_shrink/glyph_match/align_ref 同上
# 再用 ProductStore 读 align_ref 产物找 align_char 匹配目标字的位置，
# core.anchor.crop_patch() 按 char_index 产物的 bbox_page 截图。
```
