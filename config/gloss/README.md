# 单字速查释义表（汇编数据，各源授权见下）

`gloss.json` 由 `scripts/build_gloss.py` 分层合并，每条记录带 `s`=来源。
本文件是**汇编**：各源文字保留其原授权，整个文件不宣称单一协议。
再分发本文件即再分发下列各源的片段，须保留本署名清单。

| s | 来源 | 授权 | 收录方式 |
|---|---|---|---|
| `moe` | 教育部《重編國語辭典修訂本》（经 [g0v/moedict-data](https://github.com/g0v/moedict-data)） | **CC BY-ND 3.0 TW**。教育部释义：改作限制仅及文字资料本身，不限制格式转换及后续应用 | 首义项**原文照录，未截短未改写**（截短显示由界面完成）；注音/拼音一并收录 |
| `kangxi` | 《康熙字典》点校文本（《開放康熙》，志攀点校；经 [7468696e6b/kangxiDictText](https://github.com/7468696e6b/kangxiDictText)） | **CC BY-SA 3.0**（原书 1716 年公版，权利仅在点校录入层） | 剥卷页定位前缀，截短到 64 字 |
| `wikt` | 中文维基词典（[kaikki.org](https://kaikki.org/dictionary/) 机器抽取） | **CC BY-SA 4.0** / GFDL 双授权 | 首两义项合并，截短到 64 字 |
| `unihan` | Unicode Unihan `kDefinition` / `kMandarin` / `kFanqie` | Unicode License（类 BSD） | 截短到 64 字 |

明确排除的源及原因：汉典 zdic（CC BY-NC-ND，不可再分发）、chinese-xinhua
（自称 MIT 但新华字典文本版权在商务印书馆，声明无效）、CBETA（NC）。

重建：`python scripts/build_gloss.py`（缓存在 cache/，不入库）。
