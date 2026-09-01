# 颜色：让裁决状态一眼可见

审查页是**扫**着看的：拇指往下滑，眼睛要在半秒内答出「这张裁过没有、裁成
什么了」。颜色是唯一能这么快回答的通道。

## 语义固定，别临时发挥

壳的 `TOKENS` 里有四组语义色，各带一个 `-soft` 的浅底版本：

| 令牌 | 颜色 | 语义 |
|---|---|---|
| `--ok` / `--ok-soft` | 绿 | 通过、没问题、保留 |
| `--zhu` / `--zhu-soft` | 朱红 | 有问题、要改、出库 |
| `--ochre` / `--ochre-soft` | 土黄 | 另说、都不是、待定 |
| `--faint` | 灰 | 拿不准 |
| `--indigo` / `--indigo-soft` | 靛 | 中性强调：进度条、焦点圈、「存中」|

**语义在页与页之间要一致**。同一个人这周裁三张页，绿在这页是「通过」、在那页
是「有问题」，他一定会点反，而且反了自己不知道。

## 两处上色，各管一件事

**卡片左边一条 3px 竖条**——管「滚动时的全局观感」。滑过去一眼看出哪几张裁
过、裁成了什么、还剩哪几张空着：

```css
.card{border-left:3px solid transparent}
.card[data-v="ok"]  {border-left-color:var(--ok)}
.card[data-v="bad"] {border-left-color:var(--zhu)}
.card[data-v="idk"] {border-left-color:var(--faint)}
```

`data-v` 由壳在点击时写到 `<article>` 上，取消裁决时移除。

**选中的按钮用填充**——管「这一张我点没点」。描边在手机上、在阳光下、在
暗色主题下都太弱：

```css
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent}
.verdicts button.ok[aria-pressed="true"] {background:var(--ok)}
.verdicts button.bad[aria-pressed="true"]{background:var(--zhu)}
```

用 `aria-pressed` 而不是 class：读屏软件能读出来，样式又照上。

顺带两条手感：按钮 `min-height:44px`（拇指的最小靶面），四档以内一行铺开
（`grid-template-columns:repeat(N,1fr)`），别折行——折行以后人点着点着就
串档了。

## 主题三态，一处都不能少

页面在用户的主题里渲染，有三种状态：显式亮、显式暗、跟随系统。所以暗色要
写两遍：

```css
:root{ --ok:#39684A; … }                       /* 亮：写在裸 :root */
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){ --ok:#84BA93; … }   /* 跟随系统 */
}
:root[data-theme="dark"]{ --ok:#84BA93; … }    /* 显式切暗 */
```

`:root:not([data-theme="light"])` 那个 `:not` 是关键：用户显式选了亮色但系统
是暗的时候，没有它页面会被媒体查询按暗色渲染。

还有两条：`body` 必须显式给 `background:var(--ground)`——宿主在页面底下自己
铺了一层底，body 透明的话会借到宿主的主题；任何一个颜色都不能**只**定义在
媒体查询或 `[data-theme]` 块里，不然另一半状态下它就是空的。

这一套壳的 `TOKENS` 已经写全了。你自己的 CSS 只用令牌，别写死 `#39684A`。

## 状态牌子也上色

右上角那个自存牌子按状态换底色，用的是同一套语义：

```css
.save[data-s="saved"]{color:var(--ok);     background:var(--ok-soft)}
.save[data-s="busy"] {color:var(--indigo); background:var(--indigo-soft)}
.save[data-s="local"]{color:var(--ochre);  background:var(--ochre-soft)}
```

绿=存上了，靛=在存，土黄=只存在本机（要人管一下）。用户不用读字，扫一眼
颜色就知道自己这二十分钟安不安全。
