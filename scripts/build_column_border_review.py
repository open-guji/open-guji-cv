# -*- coding: utf-8 -*-
"""Step2 上下版框残墨的金标标注页（`char-segmentation/column-warp` 的第二部分）。

    python scripts/build_column_border_review.py -o output/column_border_review.html

侧界行那一页定的是**竖直**方向的文字带；这一页定**水平**方向的：矫正图的
上下两端常常带进一截版框线（`column_bounds` 取页面右端 x=0 锚点，落点未必
正好压在版框上），得在 Step2 就削掉。

**金标只记类别，不记坐标**（用户 2026-08-31 定：「如果确认了属于哪一类，
基本很好切分」）。所以卡上没有可拖的线、也不显示算法打算削几行——印上去会
把人的判断带偏，而我们要量的正是"人怎么分类"。一列出两张卡（上端 / 下端），
每张卡 = 该端的裁剪图 + 沿水平方向的投影曲线，人只需要点一个类别：

  * `clean` 有版框残墨，且跟首字之间**有间隙**（对应算法的 a/d 档）
  * `glued` 有版框残墨，但**跟首字粘连**、找不到间隙（b 档）
  * `none`  这一端**压根没有**版框残墨（c 档）
  * `idk`   拿不准

裁剪图按 `clean_column` 的定版顺序做出来：**先在原始矫正图上定文字带 → 抹掉
两侧界行 → 只在文字带宽度内算水平投影**。顺序错了投影就不准——抹白之后再定
带会拿到整幅宽度，带外那片白把整条曲线稀释约 9%，`ink_eps` 之类的阈值全部失准。

列图取 `output/<book>/step2_columns/<page>/c<N>.png`（`regen_step2_columns.py`
产的定版输入）。**换输入口径之后这一页的裁决一律作废、不能带**：新窗口逐列算
上下界、故意把主版框线放在列图第 0 行，两端有什么东西是被口径决定的——实测
上端 `c`（没残墨）从 24 列掉到 6 列，旧的 `none` 是被口径作废的，不是噪声。
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "review-artifact" / "scripts"))

from open_guji_cv.utils.column_projection import (  # noqa: E402
    column_row_profile,
    column_text_band,
    denoise_column,
    strip_column_rules,
)
from review_shell import render  # noqa: E402

GOLD = ROOT.parent / "open-guji-dataset" / "char-segmentation" / "column-warp" / "samples"
STEP2_COLUMNS = ROOT / "output" / "{book}" / "step2_columns" / "{page}"
CARDS = ROOT / "output" / "column_warp_cards.jsonl"   # 列表跟侧界行那页一致

TITLE = "单列矫正·上下版框核校"
KEY = "column-warp-border-v1"       # 换页必须换 key
CROP_ROWS = 220                       # 每端裁多少行给人看（约 2 个字格，够看到首字）

VERDICTS = [("clean", "有间隙", "ok"), ("glued", "粘连", "zhu"),
            ("none", "没残墨", "indigo"), ("idk", "拿不准", "faint")]


def build_rows() -> tuple[list[dict], dict[str, str]]:
    """列表跟侧界行那页共用冻好的卡集，两页说的是同一批列。"""
    rows, imgs = [], {}
    wins: dict[tuple[str, str], dict[int, dict]] = {}
    for line in CARDS.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        card = json.loads(line)
        book, page, col = card["book"], card["page"], card["col"]
        if (book, page) not in wins:
            wf = Path(str(STEP2_COLUMNS).format(book=book, page=page)) / "windows.json"
            if not wf.exists():
                raise SystemExit(f"{wf} 不存在——先跑 scripts/regen_step2_columns.py")
            wins[(book, page)] = {c["col"]: c
                                   for c in json.loads(wf.read_text(encoding="utf-8"))["columns"]}
        win = wins[(book, page)][col]
        img_path = Path(str(STEP2_COLUMNS).format(book=book, page=page)) / win["file"]
        # 定版顺序：原图定带 -> 抹侧界行 -> 只在带宽内算水平投影（见 clean_column）
        denoised = denoise_column(cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE))
        band = column_text_band(denoised)
        no_rules = strip_column_rules(denoised)
        core = no_rules[:, band[0]:band[1]]
        prof = column_row_profile(no_rules, band)
        h = core.shape[0]
        raised = bool(win["raised"])
        tags = [t for t in card["tags"] if t != "抬头列"] + (["抬头列"] if raised else [])

        for end in ("top", "bot"):
            # 两端都按「从该端往里」的朝向裁，人看到的永远是"版框在上、字在下"
            crop = core[:CROP_ROWS] if end == "top" else core[h - CROP_ROWS:][::-1]
            pslice = prof[:CROP_ROWS] if end == "top" else prof[h - CROP_ROWS:][::-1]
            cid = f"{book}_{page}_c{col}_{end}"
            ok, buf = cv2.imencode(".png", crop, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            assert ok
            imgs[cid] = "data:image/png;base64," + base64.b64encode(buf).decode()
            rows.append(dict(
                id=cid, book=book, page=page, col=col, end=end,
                tags=sorted(tags), raised=raised,
                w=int(core.shape[1]), rows=CROP_ROWS,
                prof=base64.b64encode(
                    bytes(int(round(float(v) * 255)) for v in pslice)).decode()))
    return rows, imgs


CSS = """
.card{background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid transparent; border-radius:3px; padding:12px 13px;
  box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n'
              for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px;}
.card h3 em{font-style:normal; font-family:var(--mono); font-size:11px;
  color:var(--muted); font-weight:400; margin-left:7px;}
.tags{margin:5px 0 0; display:flex; flex-wrap:wrap; gap:5px;}
.tags span{font-size:11px; padding:1px 6px; border-radius:2px;
  background:var(--sunk); color:var(--muted);}
.tags span.end{background:var(--indigo-soft); color:var(--indigo); font-weight:600;}
.tags span.raise{background:var(--ochre-soft); color:var(--ochre)}

.pair{display:flex; gap:6px; margin:10px auto 0; align-items:flex-start;}
.stage{flex:0 1 auto; background:var(--tile);
  border:1px solid var(--rule-hard); border-radius:2px; overflow:hidden;}
.stage img{display:block; width:100%; height:auto; image-rendering:pixelated;}
.prof{flex:0 0 54px; align-self:stretch; background:var(--ground);
  border:1px solid var(--rule); border-radius:2px;}
.prof path{fill:var(--indigo); fill-opacity:.5; stroke:none}
.edge{position:absolute; left:0; right:0; top:0; height:2px; background:var(--indigo);
  opacity:.55; pointer-events:none;}

.verdicts{display:grid; grid-template-columns:repeat(NCOL,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-family:var(--sans);
  font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
""".replace("NCOL", str(len(VERDICTS))) + "".join(
    f'.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n'
    for v, _, c in VERDICTS)


PAGE_JS = r"""
const VERDICTS = __VERDICTS__;

const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么标</summary>
    <p>一张卡是<b>一列的一端</b>（上端或下端）。图已经把两侧界行清掉了、只留文字带那一段宽度，
       并且<b>一律转成「版框在上、字在下」</b>——下端的卡是翻过来给你看的，别被字倒了吓到。
       右边那条是<b>沿水平方向的投影</b>：每一行的墨占比。</p>
    <p><b>只需要点一个类别，不用标坐标</b>——类别定了，切在哪一行算法自己能算准。</p>
    <div class="rubric">
      <div><b style="background:var(--ok-soft);color:var(--ok)">有间隙</b>
        <span>有版框残墨，而且它跟首字之间看得到空白。（版框贴着边、或者往里缩了一截都算。）</span></div>
      <div><b style="background:var(--zhu-soft);color:var(--zhu)">粘连</b>
        <span>有版框残墨，但跟首字连成一片、找不到间隙——只能少削一点，宁可留残框也别切字。</span></div>
      <div><b style="background:var(--indigo-soft);color:var(--indigo)">没残墨</b>
        <span>这一端根本没带进版框，什么都不用削。</span></div>
      <div><b style="background:var(--sunk);color:var(--faint)">拿不准</b>
        <span>看不清，或这一端另有毛病。</span></div>
    </div>
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
  <h2>标注结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;
/* page_js 整段跑在壳之前，`D` 还在暂时性死区里——索引必须懒建 */
let _idx = null;
const rowOf = id => (_idx || (_idx = Object.fromEntries(D.rows.map(r => [r.id, r]))))[id];

function unpackProf(s){
  const bin = atob(s), out = new Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i) / 255;
  return out;
}

function profSvg(r){
  const p = unpackProf(r.prof), n = p.length;
  /* 横躺的投影：y 是行号（跟左边的图对齐），x 是墨占比。按本卡峰值归一，
     峰值原值写不出来也无所谓——这一页只判类别，看的是形状不是数值。 */
  const pmax = Math.max(...p, 0.02);
  let d = 'M0,0';
  for (let i = 0; i < n; i++){ const x = p[i] / pmax * 96;
    d += ` L${x},${i} L${x},${i + 1}`; }
  d += ` L0,${n} Z`;
  return `<svg class="prof" viewBox="0 0 100 ${n}" preserveAspectRatio="none">
    <path d="${d}"></path></svg>`;
}

function card(r){
  const v = verdictOf(r.id);
  const btn = ([k, txt]) => `<button class="${k}" data-v="${k}" aria-pressed="${v === k}">${txt}</button>`;
  const tag = s => `<span${s === '抬头列' ? ' class="raise"' : ''}>${esc(s)}</span>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${r.book}/${r.page} 第 ${r.col} 列<em>${r.end === 'top' ? '上端' : '下端（已翻转）'}</em></h3>
    <div class="tags"><span class="end">${r.end === 'top' ? '上' : '下'}</span>${
      r.tags.map(tag).join('')}</div>
    <div class="pair" style="max-width:${r.w * 2 + 60}px">
      <div class="stage" style="position:relative; flex-basis:${r.w * 2}px">
        <img data-src="${r.id}" alt=""><div class="edge"></div>
      </div>
      ${profSvg(r)}
    </div>
    <div class="verdicts">${VERDICTS.map(btn).join('')}</div>
  </article>`;
}

document.addEventListener('click', e => {
  const fb = e.target.closest('#filter button'); if (!fb) return;
  filter = fb.dataset.f;
  [...fb.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === fb)));
  draw();
});

let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
function afterVerdict(){ if (filter !== 'all') draw(); }

function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r =>
    JSON.stringify({id: r.id, book: r.book, page: r.page, col: r.col,
                     end: r.end, verdict: verdictOf(r.id)})).join('\n');
}
""".replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in VERDICTS], ensure_ascii=False)) \
   .replace("__TITLE__", TITLE)


def load_existing(path: str | None, drop: set[str] | None = None) -> dict:
    """把读回来的页里已有的裁决带上——重发一律先 read 再 build，否则覆盖掉
    用户还没收割的标注（规矩见 artifacts/README.md）。`#trim` 那批键是上一版
    可拖动界面的遗留，本版金标只记类别，丢掉。`drop` 里的卡 id（几何漂了、
    标注已失效）连同它的裁决一起清掉，回到"未裁"——跟姊妹脚本
    `build_column_warp_review.py` 的 `--drop` 同一条规矩。"""
    if not path:
        return {}
    html = Path(path).read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit("这份 HTML 里没有 #data")
    st = json.loads(m.group(1).replace("<\\/", "</")).get("verdicts", {})
    drop = drop or set()
    return {k: v for k, v in st.items() if not k.endswith("#trim") and k not in drop}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="output/column_border_review.html")
    ap.add_argument("--cards", default="output/column_border_cards.jsonl")
    ap.add_argument("--carry", help="读回来的旧页 HTML，把已有裁决带过来")
    ap.add_argument("--only", default="",
                    help="逗号分隔的卡 id（如 vol01_47_c2_top）：只放这些卡，"
                         "要重标时用，别让人在一堆已裁的卡里翻那几张")
    ap.add_argument("--drop", default="",
                     help="逗号分隔的卡 id，几何漂了、标注已失效，清掉裁决重标"
                          "（不加 --only 就仍然显示这张卡，只是打回未裁状态）")
    args = ap.parse_args()

    rows, imgs = build_rows()
    only = {x for x in args.only.split(",") if x}
    drop = {x for x in args.drop.split(",") if x}
    if only:
        rows = [r for r in rows if r["id"] in only]
        if not rows:
            raise SystemExit(f"--only 里的 id 一个都没匹配上：{sorted(only)}")
        imgs = {r["id"]: imgs[r["id"]] for r in rows}
    existing = load_existing(args.carry, drop)
    if only:
        existing = {k: v for k, v in existing.items() if k in only}
    cards = Path(args.cards)
    cards.parent.mkdir(parents=True, exist_ok=True)
    cards.write_text("\n".join(
        json.dumps({k: v for k, v in r.items() if k != "prof"}, ensure_ascii=False)
        for r in rows) + "\n", encoding="utf-8")

    html = render(TITLE, KEY, verdicts=existing, css=CSS, page_js=PAGE_JS,
                   payload={"rows": rows, "imgs": imgs})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{len(rows)} 张卡（{len(rows) // 2} 列 × 上下两端）"
          f"，带过来 {len(existing)} 条已有裁决 -> {out} "
          f"({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
