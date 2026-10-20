# hanzi 库 B1 验收读数（2026-10-19 晚，洛杉矶）

> 总设计：[汉字字形与关系库-总设计.md](汉字字形与关系库-总设计.md) §7。本文只贴读数，结论回写总设计 §10。
> 机器：云会话容器（4 核 CPU），Python 3.13，SQLite 3.45。

## 复现

```bash
python scripts/build_hanzi_db.py --fetch                       # 下载原始文件到 $GUJI_DATA_HOME/_shared/hanzi/src/，再构建
python scripts/build_hanzi_db.py --zi-dir $GUJI_DATA_HOME/_shared/zitools --check --report check.json
python -m pytest tests/test_hanzi_db.py -s -p no:cacheprovider
```

## 版本与规模

版本 `hanzi-adf47e89a8be`：Unihan 18.0.0；带字统网 61 字的派生族。构建 37.5 秒，打开库 0.5 ms。

| 表 | 行数 |
|---|---|
| sources | 25 |
| chars | 101,997 |
| forms（未编码形，IDS 键） | 2,697 |
| edges | 147,990 |
| ids（yi-bai lv0/1/2、BabelStone、cjkvi-ids） | 601,763 |
| comps（部件闭包，深度 ≤ 6） | 2,180,259 |
| near（两张形近对表） | 81,105 |

边按「来源|关系」分：

| 来源 | 关系 | 条数 |
|---|---|---|
| twedu | variant | 24,741 |
| hydzd | variant／simp | 26,883／2,260 |
| hydzd-borrowed | borrow | 3,198 |
| dypytz | variant | 1,051 |
| cjkvi-simplified | simp | 5,905 |
| yitizi | variant | 8,688 |
| unihan（Semantic／Specialized／Z／简繁两向／Spoofing） | variant／variant_partial／z／simp／spoof | 2,181／304／90／6,924＋6,924／183 |
| charcomp:rt（部件檢索） | variant／related | 12,179／46,211 |
| zi（字统网，针对性查 61 字） | variant | 213 |
| local:keben | variant | 1 |
| local:never | distinct | 54 |

体积：tsv 55 MB，sqlite 164 MB（大头是 comps）。对外分发前要瘦身，记到 B7。

## A1 重放现役关系表：过

1. **同一份上游文件**：用现役 `scripts/build_variants.py` 在同一份 Unihan、cjkvi、yitizi 上重建一份 `variants.json`，和新库的 `export_variants_json()` 比，**逐条相同**：
   - `pairs` 47,538 = 47,538；
   - `directed` 43,481 = 43,481。
2. **对仓里现役的 `config/variants/variants.json`**：
   - pairs：旧 88,110 个（对, 标签），新库少 16 个、多 751 个；
   - directed：旧 73,774 个，少 16 个、多 740 个。
   - 差异全部是 Unihan 的边，归因于上游版本：本机下到的是 18.0.0，仓里那份是更早的版本构建的。
     - 少的：如 录→錄，18.0 改指 U+9332；线 的繁体改为 綫；
     - 多的：主要是 18.0 新增扩展 J 字的简繁对，如 䙰/褵、䛅/𲂆。
   - 本仓手工边 `local:keben` 一条不少（`local_missing: []`）。

## A2 覆盖：过

| 靶子 | 新库 | 对照 |
|---|---|---|
| 414 条 (p,g)：p 的族里有 g | **414/414**（只用现役来源也是 414；只用部件檢索 379） | 现役 414，rt 379（`coverage_result.json`） |
| N 档 76 条（现役表无边的 oov/unseen）：新库给出族 | 不带字统网 **50**；带上针对性查的 61 字 **70** | 原报告 rt 67、zi 63/74 |

- N 档口径说明：原报告的「rt 67」把部件檢索里的私用区未编码形也算成了族。按只收已编码汉字的口径（本仓 `charcomp_rt.tsv` 也是这个口径），rt 是 50。
- 补上的 20 条全靠字统网的族。剩下 6 条（如 㒊、瑞、璐）两边都没有族。
- `pool()` 与现役 `variant_sources.family_pool()` 对比：在 互、亙、旨、歷、注 上池子逐字相同；狼 多出的 9 个字是字统网派生边，现役调用没带缓存。

## A3 可复现：过

- 同一份 `src/`＋同一 commit 构建两次，`content_sha` 都是 `adf47e89a8be`。
- 单元测试 `test_build_is_reproducible` 也守着这一条。

## A4 速度：查族过，部件检索达到交互线

按码位每 50 字抽 2,000 字：

| 查询 | p50 | p99 | 最大 |
|---|---|---|---|
| `family()` | 0.027 ms | 0.135 ms | 0.26 ms |
| `pool()`（含形近前 5） | 0.031 ms | 0.153 ms | 0.23 ms |
| `by_components(该字前两个部件)` | 0.33 ms | 62 ms | 233 ms |

`by_components` 慢在两个常见部件（如 口＋木）相交，结果有上千字。交互线 200 ms 内，没到「<10 ms」那一档，B3 接控制台时再看要不要预先截断。

## A5 测试：过

- `tests/test_hanzi_db.py` 9 条，全部自造小数据：构建可复现、方向与关系类型、族剔除通假／钓鱼形近／distinct、未编码形、部件闭包与折叠、`pool` 形状、导出、缺源跳过。
- `tests/test_architecture.py`（`hanzi` 登记为 L0）与 `tests/test_suite_hygiene.py` 都过。

## 字统网针对性补查（B4 的预演）

- 用现役 `ZiCache(fetch=True)` 查 N 档的 61 个金标字，3 秒间隔，约 3 分钟，全部取到。
- 缓存只存派生的族（`{q, fam, ts}`），不存页面、图、释义。
- 族的噪声如需求所说偏大，例如 芳 的族只有 房，衍 的族里有 演 延。所以库里标 `zi` 来源，`pool()` 里单列 `zi`，排序照旧靠字块图。
