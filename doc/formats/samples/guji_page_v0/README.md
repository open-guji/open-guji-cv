# guji-page v0 样张：四庫總目 vol03 p3、p107

规范：`../../guji_page_v0.md`。全部由真实 CV 产物生成，**不是手写**：

```bash
# 产物：guji-workspace 孤儿分支 snap/96mid1ogzk/vol03/20260928T1708-full（cv 1332c01734）
git clone --depth 1 --single-branch -b snap/96mid1ogzk/vol03/20260928T1708-full --bare \
    https://github.com/open-guji/guji-workspace v03.git && git -C v03.git archive HEAD | tar -x
python scripts/export_guji_page.py --products products --book vol03 --pages 3,107 \
    --meta doc/formats/samples/guji_page_v0/meta.json --out doc/formats/samples/guji_page_v0 \
    --md --iiif https://img.kaiyuanguji.com/iiif
# 校验图（R = guji-workspace 的 96mid1ogzk-…/data_full/zongmu/vol03）
python scripts/render_guji_page_overlay.py doc/…/p0003.guji-page.json $R/3.png check/p0003_w1200.jpg --width 1200
python scripts/render_guji_page_overlay.py doc/…/p0107.guji-page.json $R/_source_defects/105-original-4198x5848.png \
    check/p0107_on_leaf105_w1200.jpg --image-desc source --width 1200
python scripts/render_guji_page_overlay.py doc/…/p0107.guji-page.json $R/107.png check/p0107_on_ws107_w1200.jpg \
    --image-desc canvas --width 1200
```

| 文件 | 内容 |
|---|---|
| `meta.json` | CV 不知道的页级信息：Book ID、册号、IA 原叶、p107 的拆页 region、p3 的人工印章框、p107 网站 Canvas 用的现行图 |
| `pNNNN.guji-page.json` | 本格式 |
| `pNNNN.md` | 由本格式导出的 guji-markdown（与 Step9 `render_page` 逐字相同） |
| `pNNNN.iiif-annotations.json` | 由本格式导出的 W3C 注释（p107 的 target 已换算到工作区现行 107.png） |
| `check/*.jpg` | 1200 px 档校验图。蓝 = 正文，绿 = 夹注右，橙 = 夹注左；淡红底 = 未放行（pending）；灰框 = 留白格；紫框 = 排除·非字；粗红框 = 印章 |

## 看的时候注意

- **p3** 版面上有一方藏书印（1-bit 扫描里成了散点），CV 把 136 格标成 `occluded`，其中坐标对位说是空格的 43 格当非字排除；
  其余照出整理本默认字（`method: cv:occluded_default`，`review: pending`）。印章框是 F1 目测的，CV 没有印章产物。
- **p107** 的 CV 产物建在旧裁法的图（sha `1822ea8f…`，2230×3100）上，工作区现行 `107.png` 已重裁（sha `fbdc696a…`，
  2074×2931）。格式里 `image` 记的是旧图 + 它在 leaf105 上的 region，校验图证明经原叶换算后两张图上都对得准。
  **但这也说明 vol03 p105–108 的产物过期了，应从 Step1 重跑。**
- p107 第 4 列其实是**两列正文**：Step1 漏了「分經合傳…」与「語則又未…」之间那条界行，两列并成一列，Step3 再把它当成
  双行夹注切开（md 里那条很长的 `<…|…>`，校验图里绿/橙两串大字）。这是 CV 切分问题，不是格式问题，格式如实转写；
  也可能与这页产物建在旧裁法的图上有关（重跑后再看）。两页 guji-md 里的大量 `[[]]` 是未放行位（不把机器猜测冒充定字），同 Step9 口径。
