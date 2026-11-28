# open-guji-cv 文档

这里只写**事实**：步骤、产物 schema、参数、规矩。介绍、教程、怎么用看 [GitHub Wiki](https://github.com/open-guji/open-guji-cv/wiki)；跑批、人审、中心库、出版本这些操作在 [guji-manager](https://github.com/open-guji/guji-manager)。

cv 只做 guji-manager 第二步 `pipeline` 里的「跑 CV 管线」，管线分四大步：

| 大步 | 命令里写 | 原来的步 | 目录 |
|---|---|---|---|
| 1 版面 | `layout` | Step0–1：页面预检、版框界行、印章（只认位置、判类型） | [1-版面/](1-版面/README.md) |
| 2 切字 | `cut` | Step2–4：单列拉直、逐字切分、字框收缩（拉直与字框分离 2026-11-22 起归这里） | [2-切字/](2-切字/README.md) |
| 3 识字 | `read` | Step5-a/b：字形库匹配、生僻字候选（只从字块图取证） | [3-识字/](3-识字/README.md) |
| 4 定字 | `decide` | Step5-d、Step6–7：整理本对位、上下文、放行（整理本对位 2026-11-22 起归这里） | [4-定字/](4-定字/README.md) |

原第 8 步入库归 manager 第二步，原第 9 步排版输出归 manager 第五步 `output`。

cv 自己的命令行入口是 `guji-cv`（`python -m open_guji_cv` 同）；guji-manager 通过总入口 `guji pipeline …` 调同一批命令。大步工具可带前缀：`guji-cv layout preclean …`、`guji-cv read rare …`。

```bash
guji-cv pipeline keben_body_v2 vol04 -w <工作区> --pages 9 --from layout --to cut   # 跑一段，可写大步名或步骤 id
guji-cv step row_segment vol04 -w <工作区> --pages 9                       # 只跑一步
guji-cv status vol04 -w <工作区> --pages all                               # 各步新鲜／过期／缺失
guji-cv version --json                                                           # 装着的 cv 版本与契约版本
```

每个大步目录里有一份 `步骤与产物.md`，由 `scripts/gen_stage_docs.py` 从代码生成（测试 `tests/test_stage_docs.py` 守着它不过时）。

## 公共

| 文档 | 内容 |
|---|---|
| [验收标准.md](验收标准.md)、[bench登记表.md](bench登记表.md) | 每个大步、小步要达到的标准（接口、文档、可控、可测试，2026-11-28 用户定）；各小步 benchmark 与测试集登记 |
| [版本号规矩.md](版本号规矩.md) | 分支、发版、tag、Wiki 随 MINOR 重改 |
| [开关登记表.md](开关登记表.md) | 每个开关的证据与负责人 |
| [参考/字格永久编号u.md](参考/字格永久编号u.md) | 字格永久编号 u：cv 读什么（裁定按 u 查、身份账只读）、`ruling_by_u` 怎么开、各版本线、换单导出带 u、字形库为什么不改键 |
| [参考/契约.md](参考/契约.md) | cv 与 manager 的接口：命令、`--json`、退出码、磁盘 schema |
| [参考/module_map.md](参考/module_map.md) | 包分层与依赖方向（守卫 `tests/test_architecture.py`） |
| [参考/切分代码结构.md](参考/切分代码结构.md) | `seg/` 原语、`impl/` 版式、书仓 `code/` |
| [参考/datastore.md](参考/datastore.md)、[参考/data-taxonomy.md](参考/data-taxonomy.md)、[参考/workspace_layout.md](参考/workspace_layout.md) | 数据放在哪、工作区布局 |
| [参考/受控重跑.md](参考/受控重跑.md)、[参考/性能统计.md](参考/性能统计.md)、[参考/longrun.md](参考/longrun.md) | 重跑分级、耗时、断点续跑 |
| [参考/exp_framework.md](参考/exp_framework.md)、[参考/cloud_eval.md](参考/cloud_eval.md) | A/B 实验与评测 |
| [参考/modern_print_pipeline.md](参考/modern_print_pipeline.md) | 现代排印链 |
| [formats/](formats/README.md) | guji-page、pages.json、裁定事件等格式 |

## 其他

- [经验/](经验/)：踩坑、量法、负结果（改算法前先看）。
- [design/](design/README.md)：各项设计与决定的来由；[research/](research/)：调研与基准；[exp/](exp/)：实验配置与报告。
- [archive/](archive/)：退役文档（旧 runbook、控制台手册、交接单等），只供查阅。
