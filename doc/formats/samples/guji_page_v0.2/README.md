# guji-page v0.2 样张：四庫總目 vol03 p3、p107

规范：`../../guji_page_v0.2.md`（v0、v0.1 样张在 `../guji_page_v0/`、`../guji_page_v0.1/`）。全部由真实 CV 产物生成：

```bash
# 产物：guji-workspace 孤儿分支 snap/96mid1ogzk/vol03/20260928T1708-full（cv 1332c01734）
python scripts/export_guji_page.py --products products --book vol03 --pages 3,107 \
    --meta doc/formats/samples/guji_page_v0.2/meta.json --out doc/formats/samples/guji_page_v0.2 \
    --md --iiif --index --split-table doc/formats/samples/guji_page_v0.2/split_table_siku.json
# 校验图（R = guji-workspace 的 96mid1ogzk-…/data_full/zongmu/vol03）
python scripts/render_guji_page_overlay.py …/p0003.guji-page.json $R/3.png check/p0003_w1200.jpg --width 1200
python scripts/render_guji_page_overlay.py …/p0107.guji-page.json $R/107.png check/p0107_canvas0105c_w1200.jpg --width 1200
python scripts/render_guji_page_overlay.py …/p0107.guji-page.json $R/_source_defects/105-original-4198x5848.png \
    check/p0107_on_leaf105_w1200.jpg --image-desc source --width 1200
```

| 文件 | 内容 |
|---|---|
| `meta.json` | CV 不知道的页级信息（Book ID、册号、IA item、p107 跑批那张图在原叶上的 region、p3 人工印章框） |
| `split_table_siku.json` | 整理总管落盘的合扫拆页裁剪框表（overview `项目进展/新书整理/书/四庫合扫拆页-裁剪框.json`，`73d3b4be`）的副本 |
| `pNNNN.guji-page.json` | 本格式 v0.2（阙文「□」+ `lacuna`；字框 `cand`/`channel`） |
| `pNNNN.md` | 导出的 guji-markdown（与 Step9 `render_page`、与 v0/v0.1 样张逐字相同） |
| `pNNNN.iiif-annotations.json` | W3C 注释，target = `<canvas id>#xywh=` |
| `pNNNN.iiif-canvas.json` | canvas 骨架；p107 带 `source.selector`（原叶 105 上 `xywh=2101,2913,2074,2931`） |
| `index.json` | 册级索引样例（`chapters` 留空，等文本一侧对齐时填） |
| `check/*.jpg` | 1200 px 档校验图（几何与 v0.1 相同，直接沿用 v0.1 的三张）（颜色同 v0：蓝正文、绿夹注右、橙夹注左、淡红底未放行、粗红框印章） |

**p107 看点**：CV 产物建在 09-27 首版裁法的图上（原叶 `1945,2743,2230,3100`），canvas `0105c` 是 09-29 按版心中线重切的块
（`2101,2913,2074,2931`）。导出器经原叶把全部几何平移 (−156, −170) 搬到 canvas 上；第 9 列版心条里的「五」整块落在新块之外，
`box` 置 null 并记在 `warnings`。校验图直接画在工作区现行 `107.png`（就是 canvas 那张图）上，对得准。

**v0.2 看点**：p3 阙文 8 位、p107 21 位，`text` 里都是「□」并记进 `lacuna`；每个字框带 `channel` 与 `cand`（快照没有 OCR 产物，
`cand.ocr` 全缺）。p107 的阙文位候选多是形近对（乾/軋、西/酉、權/榷/𣙜），正好是校对模式要看的。
