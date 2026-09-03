# 一次性脚本存档（v1 时代）

> ⚠️ **已死，仅存档。** 都是 2026-02「欽定四庫全書簡明目錄·文淵閣本」那一轮
> 批处理留下的排障脚本，硬编码 WSL UNC 路径，依赖已退役的 v1 链
> （`detectors/char_grid.py`、`phase3_char_grid` JSON 格式）。

| 脚本 | 当年干什么 | 现在用什么替代 |
|---|---|---|
| `delete_and_rerun.py` | 删指定页 JSON 并重跑 OCR | `guji-cv step <步> <册> --pages …`，且有指纹与 stale 机制 |
| `diag_border.py` | 边框检测诊断，看水平线聚类 | 控制台「产物」视图的叠图 |
| `stats_ce.py` | 统计夹注覆盖率、空页 | `guji-cv eval run`，或直接读 `products/` 的数值产物 |

另有五个 `diag_wei_*.py`（追「緯」字为什么丢的五次尝试）已删——那个 bug 已结案，
根因是 ce01 最后 12 本书 OCR 简繁混杂。
