# tests/fixtures —— 冻结的测试数据

这里的东西是**测试的输入常量**，跟代码里的魔数同级。改它等于改所有用到它的
测试的前提，所以：

> **默认不动。** 要新形态就新加一份，别改现有的。

## 为什么要有（2026-09-20）

在这之前，测试直接读三种**活数据**：隔壁测试集仓 `../open-guji-dataset`、
某本书的工作区（`GUJI_WORKSPACE` 下的原图/产物/缓存/字形库）、以及引擎仓里
跟着跑批变的 `output/` `corpus/` `data/`。于是：

- 跑一次批、导一次金标，测试就红——它断言的是「当下产物长什么样」，不是代码行为；
- 换台机器（云端、CI）数据不在，整条 `skip`——94 条静默跳过，绿得毫无意义。

口径改成：**测试只依赖本仓库，且只依赖 `tests/` 下这份冻结数据。**
单元测试自己在测试文件里造数据；确实要真图像的少数集成测试用这里的样本。

## 内容

```
workspace/                 一个最小的工作区（布局同 core/workspace.py 那张图）
  books/keben.yaml         刻本半页，八列二十一字，配着下面三张真页
  books/folio.yaml         筒子页刻本（只有册属性，没配图）
  books/modern.yaml        现代印刷竖排（frame: none，列数由探测给，没配图）
  raw/keben/{1,2,3}.png    **真扫描页**，从 data/book1 复制（四庫全書簡明目錄，
                           黑白、已剪切半页、双层版框有界行、八列二十一字）
  corpus/reference.txt     17 KB 小语料，从 corpus/ 复制
```

为什么复制而不是直接指 `data/` 和 `corpus/`：那两个是生产数据，会换批、会
重建；测试数据跟着它们变，就又回到「数据一变测试就红」。复制过来一共 1.2 MB，
换来的是这批测试十年不动。

`keben.yaml` 里的 `bottom_gap: 188.0` / `period_prior: 56.0` 是拿这三张图实测的
（`find_horizontal_border` 逐页量下版框，页高减下框 y 取中位；版框内高 ÷ 21 字），
不是抄别的书的——换书必须重标，见 `core/book.py` 对应字段的注释。

## 怎么用

`tests/conftest.py` 里的 fixture，别自己拼路径：

| fixture | 给你什么 |
|---|---|
| `ws` | 一个**可写**的隔离工作区（这份 fixture 复制进 tmp），`GUJI_WORKSPACE` 已指好 |
| `keben_book` | `load_book("keben")` |
| `fixture_page` / `fixture_page_path` | 冻结样页 1 的灰度图 / 路径（**只读**） |
| `gold_root` + `write_gold_shard()` | 空金标根，分片内容测试自己写 |

没有 fixture 覆盖到的，就在测试文件里自己造——产物都是 pydantic 模型，
`Borders(...)`、`PageCells(...)` 直接构造，不要去扫 `products/` 看碰巧有什么。

`tests/test_suite_hygiene.py` 会扫测试源码，拦住重新长出来的仓外依赖。
