# 自存：让裁决自己回来

审查页的成败就在这一件事上。下面是实测踩出来的整条链路，实现见
`scripts/review_shell.py` 的 `SHELL_JS`。

## 链路

1. 发布时 `capabilities={"artifact": {}}`。**漏了这一句，后面全都不成立**。
2. 页面里 `await window.claude.use('artifact')` 拿到命名空间 `ns`。
   拿不到（旧视图、能力被关）就退回本机 + 复制按钮，并把牌子打成「仅存本机」。
3. 有改动 → 防抖 → `renderIndex()` 重建一份完整文档 → `ns.publish(...)`。
4. 事后 `Artifact action:"read"` 把 HTML 读回来，从 `#data` 里取 `verdicts`。

## files 形式 vs html 形式

```js
if (mode === 'files'){
  try { return await ns.publish({'index.html': html}); }
  catch (e){ if ((e && e.code) !== 'capability_disabled') throw e; mode = 'html'; }
}
return await ns.publish(html);          // 兜底：会重载当前视图
```

- `publish({'index.html': …})`——**不重载当前视图**。用户正裁到第 30 张，
  页面在背后悄悄存了一版，滚动位置、展开状态全都不动。这是首选。
- `publish(html)`——会重载视图。裁决在 localStorage 里，重载回来还在，
  但滚动位置没了，人裁的节奏被打断。所以只在 files 形式被
  `capability_disabled` 拒了之后才退到这一档，并且把防抖从 6 秒放到 30 秒。

## 时序

```
首存 2000ms → 之后 6000ms 防抖（html 兜底档 30000ms）
visibilitychange(hidden) / pagehide → 立刻 flush
开页时 localStorage 比 #data 新 → 立刻补推
```

**首存故意快**。「存不上」是必须当场暴露的故障：2 秒后右上角还是「仅存本机」，
用户当场就问你了；要是等到 6 秒防抖 × 裁完 50 张才发现，那一轮已经废了。

**开页补推**（`behind`）救回过一整轮人裁：上一轮能力没拿到、或者用户裁完
直接关了页，裁决只留在本机；下次打开一比时间戳就发现本机更新，立刻推上去。

## 错误码怎么处理

牌子上要**带着错误码显示**（`只读·capability_disabled`），用户截图一发你就
定位到了，不用来回猜。

| 码 | 含义 | 处置 |
|---|---|---|
| `conflict` | 别处已经改过这版 | 牌子提示「别处已改」，下一轮防抖会带上最新状态重发 |
| `not_writer` / `not_granted` / `not_declared` / `capability_disabled` / `capability_removed` / `consent_required` | 这个视图根本不让写 | 停掉自存，打「只读」，让复制按钮接管 |
| `too_large` / `invalid_content` | 页太大 / 内容不合法 | 停掉自存，打「仅存本机」；下一版要把图压小 |
| `rate_limited` | 存太勤 | 防抖翻倍（封顶 60 秒）后重试 |
| 其它 | 上游抖动 | 8 秒后重试，牌子打「重试中·<码>」 |

## 定点：页面重建自己这件事必须收敛

`renderIndex()` 读自己的 `#css`/`#js` 的 textContent，拼回一份完整文档：

```js
const data = JSON.stringify({...D, verdicts: state}).split('</').join('<\\/');
return '<!doctype html>…<style id="css">' + css + '</style>…'
     + '<script type="application/json" id="data">' + data + '<\/script>'
     + '<script id="js">' + js + '<\/script>…';
```

两处容易坏：

- **`</` 的转义**。JSON 里出现 `</script` 会当场把 script 标签截断，页面从
  那儿开始就是一团乱码。所以嵌之前一律把 `</` 换成 `<\/`；读回来解析时反着
  换一次（`harvest_verdicts.py` 里做了）。
- **骨架不对称**。Python 端 `render()` 出的是**片段**（宿主会裹上
  doctype/head/body），JS 端 `renderIndex()` 出的是**整份文档**。这两边不必
  逐字节相同，但 `renderIndex()` 必须是自己的定点：它的输出再过一次
  `renderIndex()` 要**逐字节不变**。不然每存一次漂一点，存到第三次页面就
  自己散了。

`check_fixedpoint.py` 干的就是这件事：装页 → 点一个裁决 → `renderIndex()` 出
v2 → 换个干净上下文（localStorage 空的）装 v2 → 再 `renderIndex()` 出 v3 →
要求 `v3 == v2`，并且 v2 里确实嵌上了刚才那个裁决。

## 排查：读回来 0 条

按这个顺序查，基本一次到底：

1. 发布时 `capabilities` 里有没有 `artifact`？——最常见的一条。
2. 读回来的 HTML 里 `#data` 的 `verdicts` 是不是 `{}`？是的话页面从没存上；
   不是的话是你的解析写错了。
3. 让用户看右上角那个牌子：「已存」= 存上了；「只读·<码>」= 查上表；
   「仅存本机」= 能力没拿到，让他点「复制」，这一轮先用剪贴板兜住。
4. 页太大（几十 MB）会撞 `too_large`。把缩略图压小重发一版。
