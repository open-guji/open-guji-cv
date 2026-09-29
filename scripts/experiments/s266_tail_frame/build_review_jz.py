"""S#266 补查：雙行小注在 Step4 被整格发成正文——改前/改后盲评页（18 格）。"""
import sys, json, random, base64, os, cv2
from pathlib import Path
S = Path(os.environ.get("S266_DIR", "."))
ROOT = Path(__file__).resolve().parents[3] if (Path(__file__).resolve().parents[3] / "open_guji_cv").exists() else Path("/home/user/open-guji-cv")
sys.path.insert(0, str(ROOT / ".claude/skills/review-artifact/scripts")); sys.path.insert(0, str(ROOT))
from review_shell import render
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.core.spec import column_key
from open_guji_cv.products import kinds as _k  # noqa
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

TITLE = "vol03 小注拆分 A/B"
KEY = "s266-jiazhu-split-ab-v1"
VERDICTS = [("A", "A 好", "ok"), ("B", "B 好", "ok"), ("same", "一样", "ochre"), ("bad", "都不对", "zhu"), ("idk", "拿不准", "faint")]
REPORTED = set("42:3:8 62:4:8 69:5:7 69:5:8 69:5:9 89:5:8 108:8:11".split())
ids = json.loads((S / "jz_changed.json").read_text()) + ["69:5:10"]   # 49:3:15–16 已撤（用户 09-29：那是两列正文，Step1 切错），见 HANDOFF 7.6
ctx = RunContext(load_book("vol03"), ProductStore(), ImageCache(), log=lambda s: None)
def uri(img, q=60):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q]); return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
def recs(tag, pg, col, slot):
    c = next(c for c in json.loads((S / f"cs_{tag}" / f"p{pg:04d}.json").read_text())["columns"] if c["col"] == col)
    return {r["sub"]: r for r in c["chars"] if r["slot"] == slot}
def patch(tag, key):
    im = cv2.imread(str(S / f"cache_{tag}" / "vol03" / "char_patch" / f"{key}.png"), 0)
    s = 80 / im.shape[0]; return cv2.resize(im, (max(1, int(im.shape[1] * s)), 80), interpolation=cv2.INTER_AREA)
cards_path = S / "s266_jz_cards.jsonl"
frozen = {json.loads(l)["id"]: json.loads(l) for l in cards_path.read_text().splitlines()} if cards_path.exists() else {}
rng = random.Random(2661)
rows, imgs, cards_out = [], {}, []
for cid in ids:
    pg, col, slot = map(int, cid.split(":"))
    new_tag = "a" if pg in (49, 69) else "j1"
    img = ctx.image("column_image", column_key(pg, col))
    ro = recs("j0", pg, col, slot); rn = recs(new_tag, pg, col, slot)
    anyr = next(iter(rn.values()))
    y0 = max(0, int(anyr["bbox_col"][1]) - 130); y1 = min(img.shape[0], int(anyr["bbox_col"][3]) + 130)
    ctxim = cv2.cvtColor(img[y0:y1], cv2.COLOR_GRAY2BGR)
    cv2.rectangle(ctxim, (0, int(anyr["bbox_col"][1]) - y0 - 4), (ctxim.shape[1] - 1, int(anyr["bbox_col"][3]) - y0 + 4), (40, 90, 220), 2)
    s = 110 / ctxim.shape[1]; ctxim = cv2.resize(ctxim, (110, int(ctxim.shape[0] * s)), interpolation=cv2.INTER_AREA)
    imgs[f"ctx{pg}_{col}_{slot}"] = uri(ctxim)
    sides = {}
    for tag, rr, name in (("j0", ro, "base"), (new_tag, rn, "new")):
        pats = []
        for sub in ("a", "b", None):
            r = rr.get(sub)
            if r and r["patch_key"]:
                k = f"p{pg}_{col}_{slot}{sub or ''}_{name}"; imgs[k] = uri(patch(tag, r["patch_key"]))
                pats.append({"k": k, "label": {"a": "右行", "b": "左行", None: "整格"}[sub]})
        sides[name] = pats
    swap = frozen[f"vol03:{cid}"]["a_is"] == "new" if f"vol03:{cid}" in frozen else rng.random() < 0.5
    a, b = ("new", "base") if swap else ("base", "new")
    rows.append({"id": f"vol03:{cid}", "title": f"第 {pg} 页 第 {col} 列 第 {slot} 格", "ctx": f"ctx{pg}_{col}_{slot}",
                 "A": sides[a], "B": sides[b], "reported": cid in REPORTED})
    cards_out.append({"id": f"vol03:{cid}", "a_is": a, "reported": cid in REPORTED})
if not cards_path.exists():
    cards_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in cards_out) + "\n")

CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n' for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px;}
.card .tag{font-size:12px; color:var(--muted); margin-left:6px}
.body{display:grid; grid-template-columns:110px minmax(0,1fr); gap:10px; margin-top:8px}
.body .ctx{width:110px; display:block; border:1px solid var(--rule)}
.ab{display:grid; gap:8px; min-width:0}
.side{min-width:0; border:1px solid var(--rule); border-radius:3px; padding:6px; background:var(--tile)}
.side b{font-family:var(--serif); font-size:16px}
.pats{display:flex; flex-wrap:wrap; gap:6px; margin-top:4px}
.pats figure{margin:0; text-align:center; font-size:10px; color:var(--muted)}
.pats img{max-height:80px; max-width:100%; width:auto; height:auto; display:block; background:#fff; border:1px solid var(--rule)}
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
    <p>每张卡是一格（左边小图是它在列里的位置，蓝框圈出）。A / B 是这一格送去识别的字块的两种切法（左右随机，不告诉你哪边是新的）。</p>
    <p>看的是：这一格是不是雙行小注、字块是不是一字一块、读序（右行先、左行后）对不对。哪边好点哪边；差不多点「一样」；两边都不对点「都不对」。裁决自动存回本页。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="rep" aria-pressed="false">曾报错</button>
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
function side(name, pats){
  return `<div class="side"><b>${name}</b><div class="pats">${pats.map(p =>
    `<figure><img data-src="${p.k}" alt=""><figcaption>${esc(p.label)}</figcaption></figure>`).join('')}</div></div>`;
}
function card(r){
  const v = verdictOf(r.id);
  const btn = ([k, t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.title)}${r.reported ? '<span class="tag">曾报错</span>' : ''}</h3>
    <div class="body"><img class="ctx" data-src="${r.ctx}" alt=""><div class="ab">${side('A', r.A)}${side('B', r.B)}</div></div>
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
SEED = {json.loads(l)["id"]: {"v": json.loads(l)["verdict"], "t": json.loads(l)["t"]} for l in open(os.environ["S266_SEED"])} if os.environ.get("S266_SEED") else {}
html = render(TITLE, KEY, verdicts=SEED, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
out.write_text(html, encoding="utf-8")
print(out, f"{len(html)/1024:.0f} KB", len(rows), "cards", sum(r["reported"] for r in rows), "reported")
