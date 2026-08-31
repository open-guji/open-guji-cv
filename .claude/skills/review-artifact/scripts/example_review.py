# -*- coding: utf-8 -*-
"""最小可跑的审查页：抄这个开头，别从零拼。

    python example_review.py out.html

它把 3 张假卡片渲成一页完整 HTML。真页面要改的只有四处：`ROWS`（喂什么）、
`VERDICTS`（几档裁决、什么颜色）、`card()`（一张卡怎么画）、`payload()`
（裁决怎么导出）。壳负责状态 / 自存 / 复制 / 进度 / 懒加载。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from review_shell import render  # noqa: E402

TITLE = "示例审查页"
KEY = "example-review-v1"          # 换页必须换 key，否则两页的裁决串味

# 裁决档：(值, 按钮文案, 颜色令牌)。颜色令牌来自壳里的调色板：
# ok=绿 / zhu=朱红 / ochre=土黄 / faint=灰。语义固定：绿=通过，朱红=有问题，
# 土黄=需要人再看一眼，灰=拿不准。别拿绿色表示「有问题」，人会点反。
VERDICTS = [("ok", "没问题", "ok"), ("bad", "有问题", "zhu"), ("idk", "拿不准", "faint")]

CSS = """
.card{background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid transparent; border-radius:3px; padding:12px 13px;
  box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n'
              for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px;}
.card p{margin:6px 0 0; font-size:13px; color:var(--muted);}
.card img{width:100%; max-width:160px; image-rendering:pixelated;
  background:var(--tile); border-radius:2px; display:block; margin:8px 0 0;}
.verdicts{display:grid; grid-template-columns:repeat(NCOL,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-family:var(--sans);
  font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
/* 选中态是**填充**，不是描边——手机上单手扫过去，填充才一眼看得出点没点过 */
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
""".replace("NCOL", str(len(VERDICTS))) + "".join(
    f'.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n'
    for v, _, c in VERDICTS)

PAGE_JS = """
const VERDICTS = __VERDICTS__;

const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>一张卡一裁，点错再点一次取消。裁决自动存回本页，
       状态看右上角的小牌子；存不上会显示<code>仅存本机</code>，
       那就用「复制」把结果贴回对话。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="all"  aria-pressed="false">全部</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
    <button class="ghost" id="copy">复制</button>
    <button class="ghost" id="reset">清空</button>
  </div>
  <div class="list" id="list"></div>
</div>
<div class="sheet" id="sheet" hidden><div class="sheet-in">
  <h2>裁决结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;

function card(r){
  const v = verdictOf(r.id);
  const btn = ([k, t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.title)}</h3>
    <p>${esc(r.note)}</p>
    ${r.img ? `<img data-src="${r.img}" alt="">` : ''}
    <div class="verdicts">${VERDICTS.map(btn).join('')}</div>
  </article>`;
}

let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
/* page_js 跑在壳把 BODY 塞进 #app **之前**，这会儿 #filter 还不存在——
   所以控制条一律用 document 上的事件委托，别 getElementById 直接挂。 */
document.addEventListener('click', e => {
  const b = e.target.closest('#filter button'); if (!b) return;
  filter = b.dataset.f;
  [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  draw();
});
/* 「未裁」档下裁完一张就该让它消失，否则人不知道自己走到哪了 */
function afterVerdict(){ if (filter !== 'all') draw(); }

function payload(){
  return D.rows.filter(r => verdictOf(r.id))
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id)})).join('\\n');
}
""".replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in VERDICTS],
                            ensure_ascii=False)).replace("__TITLE__", TITLE)

ROWS = [{"id": f"s{i:03d}", "title": f"样本 {i}", "note": "这里放判据要用的上下文。",
         "img": None} for i in range(1, 4)]


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "review.html")
    # verdicts 传上一轮已收回的裁决即可续裁；imgs 是 {键: data URI}，
    # 卡里写 data-src=键，壳会在滚到跟前时才塞进 img.src。
    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS,
                  payload={"rows": ROWS, "imgs": {}})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB  {len(ROWS)} 卡")


if __name__ == "__main__":
    main()
