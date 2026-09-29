"""S#266 版心 / p49 假竖线：Step1 改前改后整页 A/B 盲评（5 页）。"""
import sys, json, random, base64, os, cv2, numpy as np
from pathlib import Path
S = Path(os.environ.get("S266_DIR", "."))
ROOT = Path("/home/user/open-guji-cv") if not (Path(__file__).resolve().parents[3] / "open_guji_cv").exists() else Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".claude/skills/review-artifact/scripts"))
from review_shell import render
RAW = os.environ["GUJI_WORKSPACE"] + "/data_full/zongmu/vol03/{}.png"
TITLE = "vol03 版心与竖线 A/B"
KEY = "s266-banxin-vline-ab-v1"
VERDICTS = [("A", "A 对", "ok"), ("B", "B 对", "ok"), ("same", "一样", "ochre"), ("bad", "都不对", "zhu"), ("idk", "拿不准", "faint")]
NOTES = {49: "Step1 假竖线", 105: "按版心中线重切", 106: "按版心中线重切", 107: "按版心中线重切", 108: "按版心中线重切"}
def uri(img, q=70):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q]); return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
def draw(pg, prod):
    if prod == "resplit":
        return draw_resplit(pg)
    im = cv2.imread(RAW.format(pg)); H, W = im.shape[:2]
    li = json.load(open(prod / "vol03" / "border_detect" / f"p{pg:04d}.json"))["line_index"]
    bd = json.load(open(prod / "vol03" / "border_detect" / f"p{pg:04d}.json"))["borders"]
    g = json.load(open(prod / "vol03" / "column_gate" / f"p{pg:04d}.json"))["gate_manifest"]
    adm = {c["col"]: c["admitted"] for c in g["columns"]}
    ov = im.copy()
    for l in li["lines"]:
        x0r, x1r = int(W - 1 - l["x1"]), int(W - 1 - l["x0"])
        y0, y1 = int(l["y0"]), int(l["y1"])
        col = (60, 160, 60) if adm.get(l["col"]) and l["kind"] == "body" else (150, 150, 150)
        cv2.rectangle(ov, (x0r + 4, y0), (x1r - 4, y1), col, -1)
    im = cv2.addWeighted(ov, 0.22, im, 0.78, 0)
    for v in bd["verticals"]:
        for y in range(0, H, 3):
            cv2.circle(im, (int(W - 1 - (v["x_at_top"] + v["slope"] * y)), y), 3, (30, 30, 220), -1)
    for l in li["lines"]:
        xm = int(W - 1 - (l["x0"] + l["x1"]) / 2)
        cv2.putText(im, str(l["col"]), (xm - 18, int(l["y0"]) - 25), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (200, 40, 40), 5)
    s = 520 / H
    return cv2.resize(im, (int(W * s), 520), interpolation=cv2.INTER_AREA)
def draw_resplit(pg):
    """按 crop_recipe_v2 重切后的图 + 现役 Step1（不含任何版心代码）的分列。"""
    sys.path.insert(0, str(ROOT))
    from open_guji_cv.core.book import load_book
    from open_guji_cv.utils.border_geometry import detect_borders
    bk = load_book("vol03")
    im = cv2.imread(str(S / "resplit" / "out" / f"{pg}.png")); H, W = im.shape[:2]
    r = detect_borders(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), expected_cols=bk.expected_cols, book_bottom_gap=bk.bottom_gap,
                       top_band_frac=bk.top_band_frac, bottom_band_frac=bk.bottom_band_frac)
    y0 = int(r.top.y_at(0.0)); y1 = int(r.bottom.y_at(0.0))
    ov = im.copy(); xs = [v.x_at_top for v in r.verticals]
    for k, (a, b) in enumerate(zip(xs, xs[1:])):
        cv2.rectangle(ov, (int(W - 1 - b) + 4, y0), (int(W - 1 - a) - 4, y1), (60, 160, 60), -1)
    im2 = cv2.addWeighted(ov, 0.22, im, 0.78, 0)
    for v in r.verticals:
        for y in range(0, H, 3):
            cv2.circle(im2, (int(W - 1 - v.x_at(y)), y), 3, (30, 30, 220), -1)
    for k, (a, b) in enumerate(zip(xs, xs[1:])):
        cv2.putText(im2, str(k + 1), (int(W - 1 - (a + b) / 2) - 18, y0 - 25), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (200, 40, 40), 5)
    s_ = 520 / H
    return cv2.resize(im2, (int(W * s_), 520), interpolation=cv2.INTER_AREA)
cards_path = S / "s266_s1_cards.jsonl"
frozen = {json.loads(l)["id"]: json.loads(l) for l in cards_path.read_text().splitlines()} if cards_path.exists() else {}
rng = random.Random(2662)
rows, imgs, cards_out = [], {}, []
for pg in (49, 105, 106, 107, 108):
    cid = f"vol03:{pg}"
    for tag, prod in (("base", S / "products_base"), ("new", "resplit" if pg in (105, 106, 107, 108) else S / "products_s1")):
        imgs[f"pg{pg}_{tag}"] = uri(draw(pg, prod))
    swap = frozen[cid]["a_is"] == "new" if cid in frozen else rng.random() < 0.5
    a, b = ("new", "base") if swap else ("base", "new")
    rows.append({"id": cid, "title": f"第 {pg} 页", "note": NOTES[pg], "A": f"pg{pg}_{a}", "B": f"pg{pg}_{b}"})
    cards_out.append({"id": cid, "a_is": a})
if not cards_path.exists():
    cards_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in cards_out) + "\n")
CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n' for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px;}
.card .tag{font-size:12px; color:var(--muted); margin-left:6px}
.ab{display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:8px; margin-top:8px}
.side{min-width:0; border:1px solid var(--rule); border-radius:3px; padding:4px; background:var(--tile)}
.side b{font-family:var(--serif); font-size:16px}
.side img{width:100%; display:block; margin-top:2px; background:#fff}
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
    <p>49 页：Step1 竖线修复前后。105~108 页：原「1 切 4」（每张带着一整条版心）与按版心中线重切（版心一切为二）后的分列。每张卡 A / B 是两种分列（左右随机，不告诉你哪边是新的）。红点是找到的竖线，绿底是要切字、要识别的列，灰底是被拒掉、不识别的列，红字是列号。</p>
    <p>看的是：版心（「欽定四庫全書總目」「卷五」那一条）有没有被当成一列；每一列是不是恰好一行正文、没有被劈成两半或两列并成一列。点开图可以放大看。裁决自动存回本页。</p>
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
    <h3>${esc(r.title)}${r.note ? `<span class="tag">${esc(r.note)}</span>` : ''}</h3>
    <div class="ab"><div class="side"><b>A</b><img data-src="${r.A}" alt=""></div><div class="side"><b>B</b><img data-src="${r.B}" alt=""></div></div>
    <div class="verdicts">${VERDICTS.map(btn).join('')}</div>
  </article>`;
}
let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
document.addEventListener('click', e => {
  const b = e.target.closest('#filter button'); if (!b) return;
  filter = b.dataset.f;
  [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  draw();
});
document.addEventListener('click', e => {
  const im = e.target.closest('.side img'); if (!im || !im.src) return;
  const w = window.open(); if (w) w.document.write('<img src="' + im.src + '" style="max-width:none">');
});
function afterVerdict(){ if (filter !== 'all') draw(); }
function payload(){
  return D.rows.filter(r => verdictOf(r.id))
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id)})).join('\\n');
}
""".replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in VERDICTS], ensure_ascii=False)).replace("__TITLE__", TITLE)
out = Path(sys.argv[1])
SEED = {"vol03:49": {"v": "B", "t": 1790647105792}}  # 49 画面未变，沿用用户已裁；105–108 换了重切图，旧裁决不沿用
html = render(TITLE, KEY, verdicts=SEED, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
out.write_text(html, encoding="utf-8")
print(out, f"{len(html)/1024:.0f} KB", len(rows), "cards")
