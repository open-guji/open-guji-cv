---
name: review-artifact
description: 出「给人裁一批样本」的交互网页（Artifact）——卡片式、手机能点、裁决用颜色标出来、**点完自动存回页面本身**，事后一条命令把结果收回来。用户说「出个审查页」「让我审一批」「做个标注页面」「把这些发给我看/裁」「人工确认一下」，或者你自己需要人来裁样本（挑错例、验金标、扩测试集、查库里的坏数据）时，都用这个 skill，不要从零手写 HTML——从零写十有八九会漏掉自存，人裁完一小时结果丢了。
---

# 人裁审查页（review-artifact）

人裁是这类项目里最贵的一种资源：一次五十张卡，用户在手机上点二十分钟。
**这二十分钟的产出必须自动回到你手里。** 靠「点完复制粘贴给我」会掉链子——
页面刷新一次、手滑一下、剪贴板被别的东西顶掉，二十分钟就白花了。这套壳的
全部意义就在这：裁决一边点一边写回页面自己，你事后 `Artifact action:"read"`
读回来即可。

## 三个动作

```bash
S=.claude/skills/review-artifact/scripts

python $S/example_review.py /tmp/demo.html   # 1. 照着这个改出你的建页脚本
python $S/check_fixedpoint.py your.html      # 2. 验：页面重发自己是定点
                                             # 3. Artifact 工具发布（见下）
python $S/harvest_verdicts.py read_back.html -o verdicts.jsonl   # 4. 收回
```

发布用 `Artifact` 工具，`capabilities` 里必须声明 `artifact`——**这是自存的
开关**，漏了页面就只能存在人家浏览器本地：

```
Artifact(file_path="your.html", title="…裁决台", favicon="🔎",
         capabilities={"artifact": {}})
```

**同一批人裁的复审要重发到同一个 URL**（传 `url=`），别每轮新开一个——
用户手机上开着的那一份才是活的那份。发布前先加载 `artifact-capabilities`
skill 确认当前 `capabilities` 的写法。

收回：`Artifact(action="read", url=…)` 拿到 HTML（大页会落成本地文件），
再喂 `harvest_verdicts.py`。看到 `0 / N 已裁` 先别急着怪用户——多半是自存
没生效，去查 references/autosave.md 的「排查」。

## 壳与页的契约

`review_shell.render(title, key, verdicts, css, page_js, payload)` 拼出整页。
壳管状态 / 自存 / 复制 / 进度 / 图片懒加载；你只写 `css` 和 `page_js`。

`page_js` 必须定义这几个（`example_review.py` 里都有现成的）：

| 名字 | 作用 |
|---|---|
| `BODY` | 整个界面的 HTML 字符串，壳会塞进 `#app` |
| `rowId(r)` | 一行的稳定 id |
| `card(r)` | 一张卡的 HTML，根元素 `<article class="card" data-id="…">`，裁决按钮放 `.verdicts` 里、带 `data-v` |
| `visibleRows()` | 当前该画哪些行（筛选档在这里实现）|
| `payload()` | 「复制」按钮吐什么（建议 JSONL）|
| `afterVerdict()` | 可选。裁完一张之后做什么（比如「未裁」档下重画）|

`BODY` 里必须有这些 id，壳按 id 找：`save` `count` `prog` `intro` `list`
`copy` `reset` `sheet` `sheet-text` `sheet-note` `sheet-copy` `sheet-close`。

两条最容易踩的：

1. **`page_js` 跑在 BODY 进 DOM 之前**。控制条的事件一律挂到 `document` 上
   做委托（`e.target.closest('#filter button')`），`getElementById('filter')
   .addEventListener` 会当场 null 崩掉，然后整页空白。
2. **换一张页必须换 `key`**（localStorage 键）。同 key 的两张页会互相灌
   裁决，而且是静悄悄的。

图片走 `payload["imgs"] = {键: dataURI}`，卡里只写 `<img data-src="键">`，
壳有 IntersectionObserver 在滚到跟前时才塞 `src`——一页几百张缩略图也不卡。
缩略图要**压狠一点**（128px、16 级灰足够看形状），整页控制在几 MB 内；
页面每存一次就要把自己整个重发一遍，页越大存得越慢越容易被限流。

## 颜色：让人一眼看出裁到哪了

细节在 [references/color.md](references/color.md)，要点三条：

- **语义固定**：绿 `--ok` = 通过 / 朱红 `--zhu` = 有问题 / 土黄 `--ochre` =
  另说 / 灰 `--faint` = 拿不准。别拿绿色表示「有问题」，人会点反。
- **两处上色**：卡片左边一条 3px 竖条（`.card[data-v="ok"]`）给出滚动时的
  全局观感；被选中的按钮用**填充**而不是描边（`button[aria-pressed="true"]`），
  手机上单手扫过去，填充才一眼看得出点没点过。
- **主题三态**：亮色写在裸 `:root`，暗色同时写
  `@media (prefers-color-scheme:dark){:root:not([data-theme="light"])}` 和
  `:root[data-theme="dark"]`。少写一处，用户切主题时页面就半明半暗。
  壳的 `TOKENS` 已经把这套写好了，直接用令牌，别自己写死颜色。

## 自存：怎么做到「点完就存上了」

细节和排查在 [references/autosave.md](references/autosave.md)，要点：

- 页面声明 `artifact` 能力后，用 **files 形式** `publish({'index.html': …})`
  重发自己——files 形式**不重载当前视图**，用户可以一路点下去；html 形式会
  重载，只当兜底。
- **头一次存放到 2 秒**，之后 6 秒防抖。存不上这件事要当场露出来，而不是
  等用户裁完 50 张才发现右上角一直是「仅存本机」。
- 状态牌子要把**错误码**显出来（`只读·capability_disabled`）。用户截个图
  发过来你就知道是哪一档失败，不用猜。
- localStorage 永远同时写一份，并且**开页就比一次**：本机比页里嵌的那份新，
  说明上一轮没推上去，立刻补推。这一条救回过一整轮人裁。
- 复制按钮和底部抽屉留着——所有自存路子都断了的时候，那是最后的退路。

`check_fixedpoint.py` 验的是「页面重建自己」是定点：v3 逐字节等于 v2。
不是定点的话每存一次页面就漂一点，最后自己把自己拆了。改了
`renderIndex()`、改了拼装顺序、往 `#data` 加了字段，都跑一遍再发布。

## 出题的纪律（这决定了裁决值不值钱）

页做得再顺手，题出歪了裁决也是废的。这几条是踩出来的：

- **别把机器的判断印在卡上**。你想量的是「人怎么看」，卡上写了
  `cov=0.997 疑似错标`，人就顺着你点了，测出来的是你自己。要复核机器判定的
  时候，把判定藏起来、把顺序打散。
- **分层抽样并且记下权重**。全按可疑度排序抽出来的一批，只能告诉你「可疑
  的里面有多少真问题」，回答不了「全库有多大比例有问题」。每条带上
  `stratum` 和 `stratum_weight`，事后才估得出总体。
- **id 要冻住**。卡的 id 落一份 JSONL 存盘（`*_cards.jsonl`），重建页面时
  照旧读——否则重出一版页，id 一变，上一轮的裁决就对不上号了。
- **给「拿不准」留一档**。逼人二选一，得到的是噪声。实测里「拿不准」那一档
  本身就是信号：它扎堆的地方，往往是上游切分或数据有问题。
- **一次别超过百来张**。人裁到后面会累，累出来的标比没有还糟。

## 已有的实例

`scripts/build_glyph_evict_review.py`（分层质检）、
`scripts/build_label_suspect_review.py`（三栏对照 + 筛选档）是本仓库里跑通过
的两页，仓库里的 `scripts/_review_shell.py` 是同一个壳。要出新页，
挑最像的那个抄。发布过的页都登记在 `artifacts/README.md`。
