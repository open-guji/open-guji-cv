# -*- coding: utf-8 -*-
"""扩展字组（戊戌戍／未末／土士）复审页：L1+haiku 弃权或与整理本不符的格出给 sheldon 裁（不抽查）。改自 build_review_page.py。
卡上**不显示**金标和任何模型的答案（盲审），只给 前后文＋字块图，选项是组内字＋「其他字」＋「拿不准」。
冻结：cards.jsonl（id、选择理由、金标、各模型答案，都不在页上），重建页时照旧读。
用法：python build_review_page.py <out.html>"""
import base64, collections, json, sys
from pathlib import Path
sys.path.insert(0, "/home/user/open-guji-cv"); sys.path.insert(0, "/home/user/open-guji-cv/.claude/skills/review-artifact/scripts")
import cv2
from review_shell import render

FAMILY = {"wxs": "戊戌戍", "wm": "未末", "ts": "土士"}
FROZEN = Path(__file__).parent / "l2_results" / "ext_review_cards.jsonl"

def crop_uri(cid, ws, prods, h=72, q=60):
    """按 cell_shrink 的 bbox_page 从原图裁字块（外扩 12%）。找不到格或裁不出返回 None。"""
    from open_guji_cv.core.anchor import crop_patch
    vol, page = cid.split(":")[:2]
    f = Path(prods) / vol / "cell_shrink" / f"p{int(page):04d}.json"
    if not f.exists(): return None
    for col in json.load(open(f, encoding="utf-8"))["char_index"]["columns"]:
        for c in col["chars"]:
            if c["id"] == cid:
                x0, y0, x1, y1 = c["bbox_page"]; dx, dy = (x1 - x0) * .12, (y1 - y0) * .12
                im = cv2.imread(str(Path(ws) / "data_full/zongmu" / vol / f"{page}.png"), 0)
                p = crop_patch(im, [x0 - dx, y0 - dy, x1 + dx, y1 + dy])
                if p is None: return None
                w = max(1, int(p.shape[1] * h / p.shape[0])); p = cv2.resize(p, (w, h), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", p, [cv2.IMWRITE_JPEG_QUALITY, q])
                return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    return None

TITLE = "形近字复审·戊未土"; KEY = "m7-ctx-ext-review-v1"
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
 <div class="seg" id="grp"><button data-g="" aria-pressed="true">全组</button><button data-g="wxs" aria-pressed="false">戊戌戍</button><button data-g="wm" aria-pressed="false">未末</button><button data-g="ts" aria-pressed="false">土士</button></div>
 <button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
 <div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>结果</h2><p id="sheet-note"></p><textarea id="sheet-text" readonly></textarea>
<div class="row"><button class="ghost" id="sheet-copy">复制</button><button class="ghost" id="sheet-close">关闭</button></div></div></div>`;
const rowId = r => r.id;
const NAMES = {wxs:'戊戌戍', wm:'未末', ts:'土士'};
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
    """用法：python ext_build_review.py <out.html> <review.json> <工作区> <产物目录>
    review.json＝ext_ingest 的 decisions 中需复审的行（id/group/left/right/…）；首次运行时冻结成 ext_review_cards.jsonl。"""
    out, rev, ws, prods = sys.argv[1:5]
    if FROZEN.exists(): cards = [json.loads(l) for l in FROZEN.open(encoding="utf-8")]
    else:
        cards = [dict(id=r["id"], group=r["group"], left=r["left"][-20:], right=r["right"][:20], why=("弃权" if r["final"] is None else "与整理本不符")) for r in json.load(open(rev, encoding="utf-8"))]
        FROZEN.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    order = cards[:]; __import__("random").Random(3).shuffle(order)
    rows, imgs = [], {}
    for c in order:
        u = crop_uri(c["id"], ws, prods)
        if u: imgs[c["id"]] = u
        rows.append(dict(id=c["id"], group=c["group"], left=c["left"], right=c["right"], chars=FAMILY[c["group"]], img=bool(u), note="" if u else "（无字块图，只看上下文）"))
    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
    Path(out).write_text(html, encoding="utf-8")
    print(out, f"{len(html)/1024:.0f} KB", len(rows), "有图", len(imgs), collections.Counter(c["group"] for c in cards))
if __name__ == "__main__": main()
