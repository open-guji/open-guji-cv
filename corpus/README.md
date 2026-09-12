# 外部整理本語料

> **2026-09-11 起本目錄只存小樣本（各 6000 字），不存全量**——完整語料只在
> `siku-zongmu-workspace` 工作區（`export GUJI_WORKSPACE=/path/to/siku-zongmu-workspace`）。
> 代碼一律走 `core.workspace.corpus_path()` 解析（沒設環境變量退回本目錄樣本，
> 設了就讀工作區真語料），不要再寫死 `"corpus/xxx.txt"` 這種相對路徑字符串——
> 那種寫法靠進程 cwd 解析，曾導致仓内样本与工作区真语料悄悄分叉 4680 行却
> 无人发现（`align_ref` 锚定诊断字段明明很详细，但没人想到是读错了文件）。
> 依赖完整字表覆盖率的统计型测试（如 `test_two_tier_charset_beats_single_table`）
> 用小样本会失真，已加 `skipif` 守卫，不是代码错。

## zongmu_wenyuange_wikisource.txt —— 現役，`align_ref`／`context_decide`／`gold.v2_align` 唯一語料

維基文庫《文淵閣四庫全書》0001-0005冊 ProofreadPage 校對本抽取，經 MediaWiki
API 在線逐頁拉取（本地 dump title-index 對這批 Page: 條目有缺失，09-10 實測
線上有正文而本地索引查不到，故改走在線 API，不依賴本地 dump）。覆蓋《欽定
四庫全書總目》全二百卷：

| 冊 | 內容 | 校對狀態 | 字數 |
|---|---|---|---|
| 0001 | 經部　卷首一至卷首四、卷一至卷四十四 | Progress=C（已完成） | 61.4 萬 |
| 0002 | 史部　卷四十五至卷九十 | Progress=C | 54.0 萬 |
| 0003 | 子部　卷九十一至卷一百四十七 | Progress=C | 73.7 萬 |
| 0004 | 集部（一）　卷一百四十八至卷一百八十五 | Progress=C | 62.9 萬 |
| 0005 | 集部（二）　卷一百八十六至卷二百 | **Progress=OCR（僅機器 OCR，未經人工校對）** | 22.6 萬 |

合計約 275 萬字。0005 冊質量明顯低於前四冊，使用時應區別對待（可能有較多
OCR 原始錯誤未清）。

**雙行小注**（`{{DL|A|B}}` 模板，即 `Template:雙行註文`，本書每條著錄的
「某地／某人採進本」「內府藏本」一類版本來源夾注）保留為 `<AB>` 半角尖括號
包裹，與本倉識典抓取 `lineType=2` 夾注的約定一致。09-10 首版抓取遺漏這個
（被通用 `{{...}}` 模板清除器整條刪掉），09-11 補上——**踩了兩層坑**：
① 先只加了轉換函數但沒接上，漏了調用；② 接上後又被下游的 `TAG_RE`
（通用 HTML 標籤清除器 `<[^>]+>`，用來刪 `<br>`/`<section>`）連帶當成
標籤吃掉，因為它分不清「HTML 標籤」和「剛生成的 `<AB>` 標記」。最終做法：
先把 `{{DL|A|B}}` 換成不含尖括號的佔位符，等 `TAG_RE` 等步驟跑完，最後
一步才替換回 `<AB>`。09-11 三次重抓，五冊合計字數 265→275 萬（+10 萬字，
即找回的雙行小注內容），全量驗證五冊尖括號都配對、無 `{{DL` 殘留、無
佔位符殘留。

## 已退役（保留在目錄裡備查，pipeline 不再讀取）

2026-09-11 起 `align_ref.py`／`context_decide.py`／`gold/v2_align.py` 三處
`DEFAULT_CORPUS` 及 `review/cards.py` 的對齊語料統一改指向上面這份新語料；
舊的兩份語料——`zongmu_wuyingdian_reference.txt`（用戶提供整理本，覆蓋卷首
一~四 + 卷一~二十七，約 34.6 萬字）與 `zongmu_wikisource_reference.txt`
（維基文庫《四庫全書總目提要》wikitext 版，覆蓋卷首一~四 + 卷001~027，約
2026-09-06 抓取）——文件仍留在本目錄，但不再被任何生產代碼默認讀取。
`review/cards.py` 里原有的「維基第二意見」（`ref.wiki` 字段、卡片「維基」
候選按鈕）已一併撤掉，因為新舊語料已合一，「兩份整理本互校」的概念不再
成立。歷史細節見 `variant_strategy.md` §8 09-07（二）及其 09-11 更新註。

## external/ —— 通用古文語料（派生產物）

由 `scripts/prepare_corpus.py` 從殆知閣古代文獻（`garychowcmu/daizhigev20`）
抽樣、opencc 簡→繁轉換而來。入庫是為了讓 `context-correction` 的實測數字
可復現；刪掉也能一條命令重建。

| 檔案 | 來源 | 字數 | 用途 |
|---|---|---|---|
| `daizhige_zhaoling.txt` | 史藏/詔令奏議＋經世文編＋政書＋職官 | 500 萬 | **當前配置**的通用分量（體裁貼近卷首上諭）|
| `daizhige_ru_yi.txt` | 儒藏＋易藏 | 500 萬 | 體裁消融的對照組 |

**體裁比體量重要**（context-correction 實測，同為 500 萬字）：

| 通用語料 | 純通用 | 純本書 | 混合（本書 0.9）|
|---|---|---|---|
| 詔令奏議類 | +1.21% | +1.71% | **+2.14%** |
| 儒藏/易藏（經解）| **+0.00%** | +1.71% | +1.64% |

兩份語料對測試頁金標的 8-gram 洩漏率均為 **0.0**（`prepare_corpus.py
--holdout` 與 `eval_context_correction.py` 各查一次）。

簡→繁是**用可控噪聲換語料量**：opencc 一對多（發→發/髮）必然引入錯誤，
故通用語料只配拿低權重，本書的乾淨語料才拿高權重。詳見
`.claude/doc/charset_and_lm.md`。
