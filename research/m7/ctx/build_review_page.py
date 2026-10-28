# -*- coding: utf-8 -*-
"""复审页：把「与金标不符／模型之间分歧／haiku 置信不是 high」的强真值格出给 sheldon 重审（2026-10-17 用户要求，不抽查）。
卡上**不显示**金标和任何模型的答案（盲审），只给 前后文＋字块图，选项是组内字＋「其他字」＋「拿不准」。
冻结：cards.jsonl（id、选择理由、金标、各模型答案，都不在页上），重建页时照旧读。
用法：python build_review_page.py <out.html>"""
import base64, collections, json, sys
from pathlib import Path
sys.path.insert(0, "/home/user/open-guji-cv"); sys.path.insert(0, "/home/user/open-guji-cv/.claude/skills/review-artifact/scripts")
import cv2
from common import *
from open_guji_cv.groups.ctx_l3 import parse_output
from review_shell import render

R = Path(__file__).parent / "l2_results"; MODELS = ("opus", "sonnet", "haiku", "muse")
FROZEN = R / "review_cards.jsonl"

def select():
    cards = []
    for g in ("jys", "ry", "rr"):
        fam = set(FAMILY[g]); rows = {r["id"]: r for r in load(g) if r["gold_tier"] in STRONG}
        man = json.load(open(R / f"{g}_manifest.json")); runs = {}
        for m in MODELS:
            d = {}
            for n in man: d.update(parse_output((R / m / f"{n}.json").read_text(encoding="utf-8")))
            runs[m] = d
        for i, r in rows.items():
            v = {m: runs[m].get(i, {}) for m in MODELS}; ch = {m: v[m].get("char") for m in MODELS}
            why = []
            if any(x != r["gold"] for x in ch.values()): why.append("与金标不符")
            if len(set(ch.values())) > 1: why.append("模型分歧")
            if v["haiku"].get("conf") != "high": why.append("haiku置信:" + str(v["haiku"].get("conf")))
            if why:
                l, rr = window(r)
                cards.append(dict(id=i, group=g, left=l, right=rr, gold=r["gold"], gold_src=r.get("gold_src"), why=why,
                                  models={m: [v[m].get("char"), v[m].get("conf")] for m in MODELS}))
    return cards

def crop_uri(g, cid, h=72, q=60):
    p = CG / g / "crops" / (cid.replace(":", "_") + ".png")
    if not p.exists(): return None
    im = cv2.imread(str(p), 0)
    w = max(1, int(im.shape[1] * h / im.shape[0])); im = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()

TITLE = "形近字复审"; KEY = "m7-ctx-review-v1"
CSS = """
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:12px 13px;box-shadow:var(--shadow);}
.card[data-v="other"]{border-left-color:var(--ochre)} .card[data-v="idk"]{border-left-color:var(--faint)} .card[data-v]:not([data-v="other"]):not([data-v="idk"]){border-left-color:var(--ok)}
.grp{font-size:12px;color:var(--muted)} .ctx{font-family:var(--serif);font-size:17px;line-height:1.7;margin:6px 0;word-break:break-all}
.ctx b{background:var(--ochre);color:var(--on-solid);padding:0 4px;border-radius:2px;font-size:20px}
.card img{height:var(--imgh,72px);background:var(--tile);border-radius:2px;display:block;margin:6px 0}
.verdicts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.verdicts button{min-height:44px;min-width:64px;flex:1;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-family:var(--serif);font-size:20px;cursor:pointer}
.verdicts button.s{font-family:var(--sans);font-size:13px}
.verdicts button[aria-pressed="true"]{color:var(--on-solid);border-color:transparent;background:var(--ok)}
.verdicts button.other[aria-pressed="true"]{background:var(--ochre)} .verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
"""
PAGE_JS = """
const BODY = `
<header class="top"><div class="top-in"><span class="brand">形近字复审</span><span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span></div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
 <details class="intro" id="intro" open><summary>怎么审</summary>
 <p>每张卡：黄底的字是要判的那个位置，按前后文（和字块图）选它**应当是哪个字**。选项里「其他字」＝不是这几个字之一（比如口、田、目）；「拿不准」＝上下文看不出。不显示机器答案，也不显示原金标。点错再点一次取消；自动存回本页，右上角看状态。</p></details>
 <div class="ctrl"><div class="seg" id="filter"><button data-f="todo" aria-pressed="true">未审</button><button data-f="all" aria-pressed="false">全部</button><button data-f="done" aria-pressed="false">已审</button></div>
 <div class="seg" id="grp"><button data-g="" aria-pressed="true">全组</button><button data-g="jys" aria-pressed="false">己已巳</button><button data-g="ry" aria-pressed="false">日曰</button><button data-g="rr" aria-pressed="false">入人八</button></div>
 <button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
 <div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>结果</h2><p id="sheet-note"></p><textarea id="sheet-text" readonly></textarea>
<div class="row"><button class="ghost" id="sheet-copy">复制</button><button class="ghost" id="sheet-close">关闭</button></div></div></div>`;
const rowId = r => r.id;
const NAMES = {jys:'己已巳', ry:'日曰', rr:'入人八'};
function card(r){
  const v = verdictOf(r.id);
  const chars = [...r.chars].map(c => `<button class="c" data-v="${c}" aria-pressed="${v===c}">${c}</button>`).join('');
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v}"`:''}>
   <div class="grp">${NAMES[r.group]} · ${esc(r.id)}</div>
   ${r.note?`<div class="grp">${esc(r.note)}</div>`:''}
   <div class="ctx">${esc(r.left)}<b>？</b>${esc(r.right)}</div>
   ${r.img ? `<img data-src="${r.id}" alt="">` : ''}
   <div class="verdicts">${chars}<button class="s other" data-v="other" aria-pressed="${v==='other'}">其他字</button><button class="s idk" data-v="idk" aria-pressed="${v==='idk'}">拿不准</button></div></article>`;
}
let filter='todo', grp='';
function visibleRows(){ return D.rows.filter(r => (!grp || r.group===grp) && (filter==='all' || (!!verdictOf(r.id) === (filter==='done')))); }
document.addEventListener('click', e => {
  let b = e.target.closest('#filter button');
  if (b){ filter=b.dataset.f; [...b.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===b))); draw(); return; }
  b = e.target.closest('#grp button');
  if (b){ grp=b.dataset.g; [...b.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===b))); draw(); }
});
function afterVerdict(){ if (filter!=='all') draw(); }
function payload(){ return D.rows.filter(r=>verdictOf(r.id)).map(r=>JSON.stringify({id:r.id,group:r.group,verdict:verdictOf(r.id)})).join('\\n'); }
"""
def main():
    if FROZEN.exists(): cards = [json.loads(l) for l in FROZEN.open(encoding="utf-8")]
    else:
        cards = select(); FROZEN.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    rng = __import__("random").Random(3); order = cards[:]; rng.shuffle(order)
    rows, imgs = [], {}
    for c in order:
        u = crop_uri(c["group"], c["id"])
        if u: imgs[c["id"]] = u
        rows.append(dict(id=c["id"], group=c["group"], left=c["left"], right=c["right"], chars=FAMILY[c["group"]], img=bool(u), note=c.get("note","")))
    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
    Path(sys.argv[1]).write_text(html, encoding="utf-8")
    print(sys.argv[1], f"{len(html)/1024:.0f} KB", len(rows), collections.Counter(c["group"] for c in cards))
if __name__ == "__main__": main()
