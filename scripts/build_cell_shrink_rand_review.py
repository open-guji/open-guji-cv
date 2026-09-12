# -*- coding: utf-8 -*-
"""Step4（字框收缩）随机层裁决台：给 R4 立一把真人核校过的尺子。

    PYTHONPATH=. python scripts/build_cell_shrink_rand_review.py \
        --sample output/cell_shrink_rand_r1.json --out artifacts/cell_shrink_rand_review.html

## 为什么要这一页

Step4 现在报 R4 = 0.51%（10/1953），但没有人工核校的独立基准说这个数对不对。
手上的金标都不能拿来验收：`instances` 777 条和 `recrop` 都是定向富集的缺陷样本，
读不出全书比例；`self_assess_r1~r4` 虽然叫 `stratum=rand`，但 `label_origin`
全是 `model`——算法标自己，循环论证。

这一页出的候选是 `scripts/sample_cell_shrink_rand.py` 从全书（现有 cell_shrink
产物范围内）正文页字格里**等概率随机**抽的，不看任何旗标。

## 卡上不叠算法判断

卡片只给两张图：**语境图**（原图裁一块，红框=紧裁框）回答「这个框圈的是不是
恰好一个整字」；**成品图块**回答「下游拿到的是什么」。不显示 `flags`、不显示
任何判据结论——印上去人就会顺着点，测出来的是算法自己（`head-raise-presence`
那批的教训）。

## 裁决

    clean        框准、字全、没有污染——可用
    truncated    字被切掉一部分（缺笔画/缺偏旁/框太紧）
    contaminated 框里混进了不该有的东西（邻字残留/界行线/版框条/墨渍）
    not_text     这一格根本不是一个字（空白/半个字被误切成独立格/图注等）

裁决自动存回页面（`artifact` 能力），`Artifact action:"read"` 读 `#data` 的
`verdicts` 回收。回收后走事件 → `gold_add` 落 `char-segmentation/instances`，
`stratum` 标 `rand_human`，与既有的 `self_assess` 系列（`label_origin=model`）
和其余定向层分开，报数时不能合并算。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.core.anchor import x_tr_to_tl  # noqa: E402
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402

TITLE = "Step4 随机层裁决台"
PAD = 28
TILE_H = 200
MAX_W = 260


def png_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def fit(img: np.ndarray, h: int, w: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    s = min(h / max(1, ih), w / max(1, iw))
    out = cv2.resize(img, (max(1, round(iw * s)), max(1, round(ih * s))))
    if out.shape[0] < h:
        pad = h - out.shape[0]
        val = (245, 245, 245) if out.ndim == 3 else 245
        out = cv2.copyMakeBorder(out, 0, pad, 0, 0, cv2.BORDER_CONSTANT, value=val)
    return out


class PageCache:
    def __init__(self):
        self._pages: dict[tuple[str, int], np.ndarray | None] = {}

    def get(self, book: str, page: int) -> np.ndarray | None:
        k = (book, page)
        if k not in self._pages:
            f = load_book(book).raw_path(page)
            self._pages[k] = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None
        return self._pages[k]


def context_thumb(pages: PageCache, r: dict) -> str | None:
    """`bbox_page` 是 raw_page_px@top-right（右上原点、x 向左）；cv2 读的图是
    左上原点、x 向右——照 render/overlay.py::overlay 的 cell_shrink 分支转换。"""
    img = pages.get(r["book"], r["page"])
    if img is None:
        return None
    h, w = img.shape
    bx0, by0, bx1, by1 = r["bbox_page"]
    x0, x1 = x_tr_to_tl(bx1, w), x_tr_to_tl(bx0, w)
    y0, y1 = by0, by1
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    cx0, cy0 = max(0, x0 - PAD), max(0, y0 - PAD)
    cx1, cy1 = min(w, x1 + PAD), min(h, y1 + PAD)
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    c = cv2.cvtColor(img[cy0:cy1, cx0:cx1], cv2.COLOR_GRAY2BGR)
    cv2.rectangle(c, (x0 - cx0, y0 - cy0), (x1 - cx0 - 1, y1 - cy0 - 1), (0, 0, 255), 1)
    return png_b64(fit(c, TILE_H, MAX_W))


def patch_thumb(ic: ImageCache, r: dict) -> str | None:
    f = ic.get(r["book"], "char_patch", r["patch_key"])
    if f is None:
        return None
    p = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
    if p is None:
        return None
    return png_b64(fit(p, TILE_H, MAX_W))


CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  box-shadow:var(--shadow); padding:12px 12px 11px; border-left:3px solid var(--rule-hard);}
.card[data-v="clean"]{border-left-color:var(--ok)}
.card[data-v="truncated"]{border-left-color:var(--ochre)}
.card[data-v="contaminated"]{border-left-color:var(--zhu)}
.card[data-v="not_text"]{border-left-color:var(--indigo)}
.ch{display:flex; align-items:center; gap:9px; margin-bottom:9px;}
.cid{font-family:var(--mono); font-size:11px; color:var(--faint);}
.two{display:grid; grid-template-columns:1fr 1fr; gap:10px;}
.two figure{margin:0; display:grid; gap:5px; justify-items:center;}
.tile{width:100%; aspect-ratio:1; background:var(--tile); border:1px solid var(--rule);
  border-radius:2px; overflow:hidden; display:grid; place-items:center;}
.tile img{width:100%; height:100%; object-fit:contain; display:block;}
.cap{font-size:10.5px; letter-spacing:.04em; color:var(--faint);}
.verdicts{display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:11px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--muted); cursor:pointer;
  font-family:var(--sans); font-size:13px; font-weight:500; padding:0 4px;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.clean[aria-pressed="true"]{background:var(--ok)}
.verdicts button.truncated[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.contaminated[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.not_text[aria-pressed="true"]{background:var(--indigo)}
.k-clean b{color:var(--ok); background:var(--ok-soft)}
.k-truncated b{color:var(--ochre); background:var(--ochre-soft)}
.k-contaminated b{color:var(--zhu); background:var(--zhu-soft)}
.k-not_text b{color:var(--indigo); background:var(--indigo-soft)}
"""

PAGE_JS = r"""
const BODY = `
<header class="top">
  <div class="top-in">
    <span class="brand">Step4 随机层裁决台</span>
    <span class="save" id="save" data-s="idle">本机</span>
    <span class="count" id="count">—</span>
  </div>
  <div class="bar"><i id="prog"></i></div>
</header>
<main class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>左边是<b>语境图</b>（原图裁一块，红框=紧裁框），回答「这个框圈的是不是
       恰好一个整字」；右边是<b>成品图块</b>，回答「下游拿到的是什么」。
       这批候选是从全书正文页字格里<b>等概率随机</b>抽的，卡片不叠任何算法
       判断——判的时候只看图，不用管这一格「按理说」该是什么。</p>
    <div class="rubric">
      <div class="k-clean"><b>clean</b><span>框准、字全、没有污染——可用</span></div>
      <div class="k-truncated"><b>truncated</b><span>字被切掉一部分（缺笔画/缺偏旁/框太紧）</span></div>
      <div class="k-contaminated"><b>contaminated</b><span>框里混进了不该有的东西（邻字残留/界行线/版框条/墨渍）</span></div>
      <div class="k-not_text"><b>not_text</b><span>这一格根本不是一个字（空白/被误切的半字/图注等）</span></div>
    </div>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter" role="group" aria-label="筛选">
      <button data-f="all" aria-pressed="true">全部</button>
      <button data-f="todo" aria-pressed="false">未裁</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
  </div>
  <div class="ctrl">
    <button class="ghost" id="copy" style="flex:1">复制裁决</button>
    <button class="ghost" id="reset">清空</button>
  </div>
  <div class="list" id="list"></div>
</main>
<div class="sheet" id="sheet" hidden>
  <div class="sheet-in">
    <h2>裁决 JSONL</h2>
    <p id="sheet-note">长按选中全文复制，或用下面的按钮。</p>
    <textarea id="sheet-text" readonly spellcheck="false"></textarea>
    <div class="row">
      <button class="ghost" id="sheet-copy">复制到剪贴板</button>
      <button class="ghost" id="sheet-close">关闭</button>
    </div>
  </div>
</div>`;

const rowId = r => r.id;
let filter = 'all';
function visibleRows(){
  return D.rows.filter(r => filter === 'all' ? true
    : filter === 'done' ? !!verdictOf(r.id) : !verdictOf(r.id));
}
function card(r){
  const v = verdictOf(r.id);
  const btn = (k, t) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v}"`:''}>
    <div class="ch">
      <span class="cid">${esc(r.book)} ${r.page}:${r.col}</span>
    </div>
    <div class="two">
      <figure><span class="tile"><img data-src="c:${r.id}" alt="语境图" decoding="async"></span>
        <span class="cap">语境图</span></figure>
      <figure><span class="tile"><img data-src="p:${r.id}" alt="成品图块" decoding="async"></span>
        <span class="cap">成品图块</span></figure>
    </div>
    <div class="verdicts">${btn('clean','clean')}${btn('truncated','truncated')}${btn('contaminated','contaminated')}${btn('not_text','not_text')}</div>
  </article>`;
}
function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => JSON.stringify({
    id: r.id, book: r.book, page: r.page, col: r.col, patch_key: r.patch_key,
    stratum: r.stratum, verdict: verdictOf(r.id)
  })).join('\n');
}
let afterVerdict = () => { if (filter !== 'all') setTimeout(draw, 180); };
document.addEventListener('click', e => {
  const f = e.target.closest('#filter button'); if (!f) return;
  filter = f.dataset.f;
  [...f.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === f)));
  draw();
});
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", default="artifacts/cell_shrink_rand_review.html")
    ap.add_argument("--verdicts", default="artifacts/cell_shrink_rand_verdicts.jsonl")
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _review_shell import render  # noqa: E402

    rows = json.loads(Path(a.sample).read_text(encoding="utf-8"))

    ic = ImageCache()
    pages = PageCache()
    imgs: dict[str, str] = {}
    kept = []
    for r in rows:
        c = context_thumb(pages, r)
        p = patch_thumb(ic, r)
        if c is None or p is None:
            continue
        imgs[f"c:{r['id']}"] = c
        imgs[f"p:{r['id']}"] = p
        kept.append(r)

    import random
    random.Random(1).shuffle(kept)

    verdicts = {}
    vpath = Path(a.verdicts)
    if vpath.exists():
        for line in vpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                verdicts[d["id"]] = {"v": d["verdict"], "t": 1}

    payload = {"rows": kept, "imgs": imgs, "verdicts": verdicts}
    html = render(TITLE, "guji-cellshrink-rand-v1",
                  {"clean": "clean", "truncated": "truncated",
                   "contaminated": "contaminated", "not_text": "not_text"},
                  CSS, PAGE_JS, payload)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"卡 {len(kept)}（丢了 {len(rows)-len(kept)} 条图缺失）  图 {len(imgs)}")
    print(f"→ {a.out}  ({Path(a.out).stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
