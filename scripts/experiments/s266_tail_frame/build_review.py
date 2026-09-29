"""S#266 列尾下版框 改前/改后 盲评审查页。"""
import sys, json, random, base64, cv2, numpy as np
from pathlib import Path
import os
S = Path(os.environ.get("S266_DIR", "."))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / ".claude/skills/review-artifact/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from review_shell import render
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.core.spec import column_key
from open_guji_cv.products import kinds as _k  # noqa
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

TITLE = "vol03 列尾版框 A/B"
KEY = "s266-tail-frame-ab-v1"
VERDICTS = [("A", "A 好", "ok"), ("B", "B 好", "ok"), ("same", "一样", "ochre"), ("bad", "都不对", "zhu"), ("idk", "拿不准", "faint")]
M = {'char': '字', 'blank': '空', 'jiazhu_a': '注a', 'jiazhu_b': '注b', 'jiazhu_solo': '注'}
TARGETS = set("11:1:21 17:1:21 17:3:21 17:7:21 18:4:21 18:7:21 25:1:21 25:2:21 25:4:21 28:1:20 28:1:21 42:4:21 43:3:21 43:4:20 43:4:21 43:7:20 43:7:21 47:1:21 48:6:21 64:7:21 70:6:20 72:2:21 80:5:21 88:2:21 89:8:21 104:8:21 110:1:21".split())

ctx = RunContext(load_book("vol03"), ProductStore(), ImageCache(), log=lambda s: None)
def colrec(tag, pg, col):
    d = json.loads((S / tag / f"p{pg:04d}.json").read_text()); return next(c for c in d["columns"] if c["col"] == col)
def uri(img, q=55):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q]); return "data:image/jpeg;base64," + base64.b64encode(buf).decode()

cmp_cols = [tuple(map(int, l.split()[:2])) for l in (S / "cmp.txt").read_text().splitlines()[2:]]
diff = json.loads((S / "cell_diff.json").read_text())
by_col = {}
for d in diff:
    pg, col = map(int, d["id"].split(":")[:2]); by_col.setdefault((pg, col), []).append(d)
cols = sorted(set(cmp_cols) | set(by_col))
cards_path = S / "s266_cards.jsonl"
frozen = {}
if cards_path.exists():
    for l in cards_path.read_text().splitlines():
        r = json.loads(l); frozen[r["id"]] = r
rng = random.Random(266)
rows, imgs, cards_out = [], {}, []
for pg, col in cols:
    cid = f"vol03:{pg}:{col}"
    swap = frozen[cid]["a_is"] == "new" if cid in frozen else rng.random() < 0.5
    img = ctx.image("column_image", column_key(pg, col))
    cb, cn = colrec("run_base", pg, col), colrec("run_new", pg, col)
    ba, bn = cb["boundaries"], cn["boundaries"]
    mv = [i for i, (x, y) in enumerate(zip(ba, bn)) if abs(x - y) > 2]
    first = min(mv) if mv else len(ba) - 2
    y0 = int(max(0, min(ba[max(0, first - 1)], bn[max(0, first - 1)]) - 8))
    y1 = img.shape[0]
    sides = {}
    for tag, c in (("base", cb), ("new", cn)):
        v = cv2.cvtColor(img[y0:y1], cv2.COLOR_GRAY2BGR)
        for cell in c["cells"]:
            if cell["kind"] == "jiazhu_b": continue
            ya = int(round(cell["y0"])) - y0
            if ya >= 0:
                cv2.line(v, (0, ya), (v.shape[1], ya), (40, 90, 220), 2)
        yl = int(round(c["cells"][-1]["y1"])) - y0
        cv2.line(v, (0, yl), (v.shape[1], yl), (40, 90, 220), 2)
        s = 110 / v.shape[1]; v = cv2.resize(v, (110, max(1, int(v.shape[0] * s))), interpolation=cv2.INTER_AREA)
        key = f"c{pg}_{col}_{tag}"; imgs[key] = uri(v)
        tail = [f"{x['slot']}{M[x['kind']]}" for x in c["cells"] if x["y1"] > y0 + 5]
        pats = []
        for d in by_col.get((pg, col), [])[:4]:
            r = d[tag]
            if r and r.get("patch"):
                f = S / f"cache_{tag}" / "vol03" / "char_patch" / f"{r['patch']}.png"
                p = cv2.imread(str(f), 0)
                if p is not None:
                    sc = 72 / max(p.shape); p = cv2.resize(p, (max(1, int(p.shape[1] * sc)), max(1, int(p.shape[0] * sc))), interpolation=cv2.INTER_AREA)
                    pk = f"p{pg}_{col}_{d['id'].split(':')[2]}_{tag}"; imgs[pk] = uri(p, 60)
                    pats.append({"k": pk, "slot": d["id"].split(":")[2]})
            elif r is None or not r.get("patch"):
                pats.append({"k": None, "slot": d["id"].split(":")[2]})
        sides[tag] = {"img": key, "kinds": " ".join(tail[-6:]), "patches": pats}
    a, b = ("new", "base") if swap else ("base", "new")
    is_target = any(f"{pg}:{col}:{s}" in TARGETS for s in (20, 21))
    rows.append({"id": cid, "title": f"第 {pg} 页 第 {col} 列（列尾）", "A": sides[a], "B": sides[b], "reported": is_target})
    cards_out.append({"id": cid, "a_is": a, "reported": is_target})
if not cards_path.exists():
    cards_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in cards_out) + "\n")

CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n' for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px;}
.card .tag{font-size:12px; color:var(--muted); margin-left:6px}
.ab{display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:10px; margin-top:8px}
.side{min-width:0; border:1px solid var(--rule); border-radius:3px; padding:6px; background:var(--tile)}
.side b{font-family:var(--serif); font-size:16px}
.side .col{width:110px; max-width:100%; display:block; margin:4px auto 0}
.side .k{font-size:11px; color:var(--muted); margin-top:4px; word-break:break-all}
.pats{display:flex; flex-wrap:wrap; gap:4px; margin-top:6px}
.pats figure{margin:0; text-align:center; font-size:10px; color:var(--muted)}
.pats img{max-height:72px; max-width:100%; width:auto; height:auto; display:block; background:#fff; border:1px solid var(--rule)}
.pats .none{height:72px; width:40px; display:flex; align-items:center; justify-content:center; border:1px dashed var(--rule)}
.verdicts{display:grid; grid-template-columns:repeat(auto-fit,minmax(56px,1fr)); gap:6px; margin-top:10px;}
.verdicts button{min-width:0; min-height:44px; border:1px solid var(--rule-hard); border-radius:3px; background:var(--surface);
  color:var(--ink); font-family:var(--sans); font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
""" + "".join(f'.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n' for v, _, c in VERDICTS)

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
    <p>每张卡是同一列的列尾，左右两种切法 A / B（左右随机，不告诉你哪边是新的）。
       蓝线是格线；下面一排小图是这一列里<b>两种切法下不一样的字块</b>（Step4 实际送去识别的图），空框表示那一边这一格没有字块。</p>
    <p>看的是：字块里有没有混进<b>版框横条</b>、字有没有被<b>切掉笔画</b>、格线有没有<b>切进字里</b>、字的格号是否对得上。
       哪边好点哪边；差不多点「一样」；两边都有毛病点「都不对」。裁决自动存回本页。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="rep" aria-pressed="false">曾报错的列</button>
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
function side(name, s){
  const pats = s.patches.map(p => p.k ? `<figure><img data-src="${p.k}" alt=""><figcaption>${esc(p.slot)}</figcaption></figure>`
                                      : `<figure><div class="none">无</div><figcaption>${esc(p.slot)}</figcaption></figure>`).join('');
  return `<div class="side"><b>${name}</b><img class="col" data-src="${s.img}" alt="">
    <div class="k">${esc(s.kinds)}</div><div class="pats">${pats}</div></div>`;
}
function card(r){
  const v = verdictOf(r.id);
  const btn = ([k, t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.title)}${r.reported ? '<span class="tag">曾报错</span>' : ''}</h3>
    <div class="ab">${side('A', r.A)}${side('B', r.B)}</div>
    <div class="verdicts">${VERDICTS.map(btn).join('')}</div>
  </article>`;
}
let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  if (filter === 'rep') return D.rows.filter(r => r.reported);
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
document.addEventListener('click', e => {
  const b = e.target.closest('#filter button'); if (!b) return;
  filter = b.dataset.f;
  [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  draw();
});
function afterVerdict(){ if (filter === 'todo' || filter === 'done') draw(); }
function payload(){
  return D.rows.filter(r => verdictOf(r.id))
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id)})).join('\\n');
}
""".replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in VERDICTS], ensure_ascii=False)).replace("__TITLE__", TITLE)

out = Path(sys.argv[1])
html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
out.write_text(html, encoding="utf-8")
print(out, f"{len(html)/1024:.0f} KB", len(rows), "cards", sum(r["reported"] for r in rows), "reported")
