# -*- coding: utf-8 -*-
"""人裁审查页的公共壳：设计令牌 + 状态/自存/复制/进度那一套。

各审查页只需要给出「一张卡怎么画」和自己的控制条，壳负责：

- 三态主题令牌（bare `:root` 亮 / `prefers-color-scheme` 暗 / `[data-theme]` 覆盖）；
- 裁决状态 `{id:{v,t}}`：localStorage 即时兜底 + 页里嵌的那份按时间戳合并；
- **自存**：声明 `artifact` 能力，改动 6 秒防抖后用 files 形式把 index.html
  重发一版（files 形式不重载本视图，可以一路点下去），裁决嵌在 `#data` 里，
  `Artifact action:"read"` 直接读得到。能力拿不到时退回本机 + 复制按钮；
- 页面靠读自己的 `#css`/`#js` 重建完整文档，是**定点**（重发一版再重发，
  字节相同）——这条别改坏了：坏了就会每存一次页面漂一点。

用法见 `build_glyph_evict_review.py`。`build_match_inversion_review.py` 是
这套东西的第一版，还没迁过来（迁移会改动它的定点，等那一轮人裁收工再动）。
"""
from __future__ import annotations

import json

TOKENS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light dark;
  --ground:#EBE8DF; --surface:#F8F6F1; --sunk:#E3DFD3; --tile:#DBD6C6;
  --ink:#1C1B16; --muted:#6B6659; --faint:#948E7E;
  --rule:#D6D1C3; --rule-hard:#BCB5A2;
  --indigo:#2C4C76; --indigo-soft:#DEE6F1;
  --zhu:#A8342A; --zhu-soft:#F4E2DE;
  --ok:#39684A; --ok-soft:#DFEBE2;
  --ochre:#856418; --ochre-soft:#F0E8D2;
  --on-solid:#FBFAF6;
  --shadow:0 1px 0 rgba(28,27,22,.04),0 2px 10px rgba(28,27,22,.055);
  --sans:"Archivo","Noto Sans SC",system-ui,-apple-system,sans-serif;
  --serif:"Noto Serif SC",Songti SC,SimSun,serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#161612; --surface:#20201A; --sunk:#2A2923; --tile:#B7B2A3;
    --ink:#E9E5D9; --muted:#9A9486; --faint:#7A7568;
    --rule:#32312A; --rule-hard:#4A483E;
    --indigo:#8FB3DE; --indigo-soft:#22303F;
    --zhu:#E28C80; --zhu-soft:#3A2521;
    --ok:#84BA93; --ok-soft:#1E2C23;
    --ochre:#CBA652; --ochre-soft:#302819;
    --on-solid:#14140F;
    --shadow:0 1px 0 rgba(0,0,0,.3),0 2px 10px rgba(0,0,0,.28);
  }
}
:root[data-theme="dark"]{
  --ground:#161612; --surface:#20201A; --sunk:#2A2923; --tile:#B7B2A3;
  --ink:#E9E5D9; --muted:#9A9486; --faint:#7A7568;
  --rule:#32312A; --rule-hard:#4A483E;
  --indigo:#8FB3DE; --indigo-soft:#22303F;
  --zhu:#E28C80; --zhu-soft:#3A2521;
  --ok:#84BA93; --ok-soft:#1E2C23;
  --ochre:#CBA652; --ochre-soft:#302819;
  --on-solid:#14140F;
  --shadow:0 1px 0 rgba(0,0,0,.3),0 2px 10px rgba(0,0,0,.28);
}
body{margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--sans); font-size:15px; line-height:1.55;
  -webkit-text-size-adjust:100%;}
.wrap{max-width:34rem; margin:0 auto; padding:0 14px 96px;}

.top{position:sticky; top:0; z-index:20; background:var(--ground);
  background:color-mix(in srgb,var(--ground) 88%,transparent);
  backdrop-filter:blur(10px) saturate(1.2); border-bottom:1px solid var(--rule);}
.top-in{max-width:34rem; margin:0 auto; padding:9px 14px 0;
  display:flex; align-items:baseline; gap:9px;}
.brand{font-family:var(--serif); font-weight:700; font-size:16px; letter-spacing:.02em;}
.save{font-size:10.5px; letter-spacing:.03em; padding:1px 6px; border-radius:2px;
  color:var(--muted); background:var(--sunk); white-space:nowrap;}
.save[data-s="saved"]{color:var(--ok); background:var(--ok-soft)}
.save[data-s="busy"],.save[data-s="wait"]{color:var(--indigo); background:var(--indigo-soft)}
.save[data-s="local"],.save[data-s="ro"]{color:var(--ochre); background:var(--ochre-soft)}
.count{margin-left:auto; font-family:var(--mono); font-size:12px; color:var(--muted);
  font-variant-numeric:tabular-nums; white-space:nowrap;}
.bar{height:3px; background:var(--sunk); margin-top:8px;}
.bar i{display:block; height:100%; background:var(--indigo); width:0; transition:width .25s ease;}

.intro{margin:18px 0 0; padding:14px 15px; background:var(--surface);
  border:1px solid var(--rule); border-radius:3px; box-shadow:var(--shadow);}
.intro summary{cursor:pointer; font-weight:600; font-size:14px; letter-spacing:.01em;}
.intro summary::marker{color:var(--faint)}
.intro p{margin:10px 0 0; font-size:13.5px; color:var(--muted); line-height:1.65;}
.intro code{font-family:var(--mono); font-size:12px; color:var(--ink);
  background:var(--sunk); padding:1px 4px; border-radius:2px;}
.rubric{margin:12px 0 0; padding:0; display:grid; gap:7px;}
.rubric div{display:grid; grid-template-columns:auto 1fr; gap:9px; align-items:baseline;
  font-size:13px; color:var(--muted);}
.rubric b{font-weight:600; font-size:12.5px; padding:1px 6px; border-radius:2px; white-space:nowrap;}

.ctrl{display:flex; gap:8px; margin:14px 0 4px; align-items:center;}
.seg{display:flex; background:var(--sunk); border-radius:3px; padding:2px; flex:1;
  overflow-x:auto;}
.seg button{flex:1 0 auto; min-height:36px; padding:0 10px; border:0; background:none;
  color:var(--muted); font-family:var(--sans); font-size:13px; font-weight:500;
  border-radius:2px; cursor:pointer; white-space:nowrap;}
.seg button[aria-pressed="true"]{background:var(--surface); color:var(--ink);
  box-shadow:var(--shadow);}
.ghost{min-height:38px; padding:0 13px; border:1px solid var(--rule-hard);
  background:var(--surface); color:var(--ink); border-radius:3px; cursor:pointer;
  font-family:var(--sans); font-size:13px; font-weight:500; white-space:nowrap;}
.ghost:active{background:var(--sunk)}
.ghost:focus-visible,.seg button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}

.list{display:grid; gap:12px; margin-top:12px;}
.empty{padding:34px 10px; text-align:center; color:var(--faint); font-size:13.5px;}

.sheet{position:fixed; inset:0; z-index:40; background:rgba(20,19,15,.5);
  display:grid; place-items:end center;}
.sheet[hidden]{display:none}
.sheet-in{width:100%; max-width:34rem; background:var(--surface); border-radius:6px 6px 0 0;
  padding:14px 14px calc(14px + env(safe-area-inset-bottom)); display:grid; gap:10px;
  max-height:82vh;}
.sheet h2{margin:0; font-size:14px; font-weight:600;}
.sheet p{margin:0; font-size:12.5px; color:var(--muted)}
.sheet textarea{width:100%; height:38vh; resize:none; font-family:var(--mono);
  font-size:11px; line-height:1.5; padding:9px; color:var(--ink);
  background:var(--ground); border:1px solid var(--rule); border-radius:3px;}
.sheet .row{display:flex; gap:8px}
.sheet .row .ghost{flex:1; min-height:44px}

@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
"""


def head_tags(title: str) -> str:
    return (f"<title>{title}</title>\n"
            '<meta name="viewport" content="width=device-width, initial-scale=1, '
            'viewport-fit=cover">\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
            "family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&"
            'family=Noto+Serif+SC:wght@500;700&display=swap">')


SHELL_JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const HEAD = __HEAD__, KEY = __KEY__, V = __VERDICTS__;

/* ---------- 裁决状态：{id:{v,t}}，与页里嵌的那份按时间戳合并 ---------- */
function readLocal(){ try { return JSON.parse(localStorage.getItem(KEY) || '{}'); }
                      catch(e){ return {}; } }
function mergeState(a, b){
  const out = {...a};
  for (const k in b) if (!(k in out) || (b[k].t||0) > (out[k].t||0)) out[k] = b[k];
  return out;
}
let state = mergeState(D.verdicts || {}, readLocal());
const verdictOf = id => (state[id] || {}).v || '';
const doneCount = () => D.rows.filter(r => verdictOf(rowId(r))).length;
function persist(){
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){}
  queueSave();
}
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

document.getElementById('app').innerHTML = BODY;

/* ---------- 列表 ---------- */
const listEl = document.getElementById('list');
let flashT = 0;
function flash(msg){
  const el = document.getElementById('count');
  el.textContent = msg; clearTimeout(flashT); flashT = setTimeout(tally, 2200);
}
function tally(){
  const done = doneCount(), n = D.rows.length;
  document.getElementById('count').textContent = `${done} / ${n} 已裁`;
  document.getElementById('prog').style.width = (done / n * 100) + '%';
}
function draw(){
  const rows = visibleRows();
  listEl.innerHTML = rows.length ? rows.map(card).join('')
    : `<p class="empty">这一档里没有卡片了。</p>`;
  listEl.querySelectorAll('img[data-src]').forEach(i => io.observe(i));
  tally();
}
const io = new IntersectionObserver(es => {
  for (const e of es) if (e.isIntersecting){
    const img = e.target, k = img.dataset.src;
    if (k && D.imgs[k]) img.src = D.imgs[k];
    img.removeAttribute('data-src'); io.unobserve(img);
  }
}, {rootMargin: '700px 0px'});

listEl.addEventListener('click', e => {
  const b = e.target.closest('.verdicts button'); if (!b) return;
  const art = b.closest('.card'), id = art.dataset.id, v = b.dataset.v;
  if (verdictOf(id) === v) delete state[id]; else state[id] = {v, t: Date.now()};
  persist();
  const now = verdictOf(id);
  art.querySelectorAll('.verdicts button').forEach(x =>
    x.setAttribute('aria-pressed', String(now === x.dataset.v)));
  if (now) art.dataset.v = now; else art.removeAttribute('data-v');
  tally();
  if (afterVerdict) afterVerdict();
});

/* ---------- 自存：把自己重发一版 ---------- */
const saveEl = document.getElementById('save');
const SAVE_TEXT = {idle:'本机', wait:'待存', busy:'存中…', saved:'已存',
                   local:'仅存本机', ro:'只读'};
function setSave(s, extra){ saveEl.dataset.s = s; saveEl.textContent = extra || SAVE_TEXT[s] || s; }
let ns = null, canPub = false, timer = 0, inflight = false, dirty = false;
/* 头一次存**快**（2 秒），好让「存不了」这件事当场露出来而不是等到最后；
   之后 6 秒防抖。html 兜底模式下会重发整页并重载本视图，所以放慢到 30 秒。 */
let delay = 2000, mode = 'files';

function renderIndex(){
  const css = document.getElementById('css').textContent;
  const js  = document.getElementById('js').textContent;
  const data = JSON.stringify({...D, verdicts: state}).split('</').join('<\\/');
  return '<!doctype html>\n<html lang="zh-Hans">\n<head>\n<meta charset="utf-8">\n'
    + HEAD + '\n<style id="css">' + css + '</style>\n</head>\n<body>\n'
    + '<div id="app"></div>\n'
    + '<script type="application/json" id="data">' + data + '<\/script>\n'
    + '<script id="js">' + js + '<\/script>\n</body>\n</html>\n';
}
function queueSave(){
  dirty = true;
  if (!canPub){ setSave('local'); return; }
  setSave('wait'); clearTimeout(timer); timer = setTimeout(save, delay);
}
async function publishNow(html){
  /* files 形式不重载本视图，是首选；它在有些视图上根本不开放（capability_disabled），
     那就退回 html 形式——会重载本视图，但裁决在 localStorage 里，重载回来还在。 */
  if (mode === 'files'){
    try { return await ns.publish({'index.html': html}); }
    catch (e){
      if ((e && e.code) !== 'capability_disabled') throw e;
      mode = 'html';
    }
  }
  return await ns.publish(html);
}
async function save(){
  if (!canPub || !dirty || inflight) return;
  inflight = true; setSave('busy');
  const snap = JSON.stringify(state);
  try {
    await publishNow(renderIndex());
    dirty = JSON.stringify(state) !== snap;
    delay = mode === 'files' ? 6000 : 30000;
    setSave(dirty ? 'wait' : 'saved');
    if (dirty) timer = setTimeout(save, delay);
  } catch (err){
    const code = (err && err.code) || 'upstream_error';
    if (code === 'conflict') setSave('busy', '别处已改');
    else if (['not_writer','not_granted','not_declared','capability_disabled',
              'capability_removed','consent_required'].includes(code)){
      canPub = false; setSave('ro', '只读·' + code);
    } else if (code === 'too_large' || code === 'invalid_content'){
      canPub = false; setSave('local', '仅存本机·' + code);
    } else if (code === 'rate_limited'){
      delay = Math.min(Math.max(delay, 6000) * 2, 60000);
      setSave('wait'); timer = setTimeout(save, delay);
    } else { setSave('wait', '重试中·' + code); timer = setTimeout(save, 8000); }
  } finally { inflight = false; }
}
function flush(){ if (canPub && dirty){ clearTimeout(timer); save(); } }
addEventListener('visibilitychange', () => { if (document.hidden) flush(); });
addEventListener('pagehide', flush);
/* 开页就比一次：本机比页里嵌的那份新，说明上一轮的裁决还没推上去
   （能力当时没拿到、或者关得太快）——立刻补推，别等下一次点击。 */
const behind = JSON.stringify(state) !== JSON.stringify(D.verdicts || {});
if (window.claude && typeof window.claude.use === 'function'){
  setSave('idle');
  window.claude.use('artifact').then(x => {
    ns = x; canPub = !!x;
    if (!canPub){ setSave('local'); return; }
    if (dirty || behind){ dirty = true; setSave('wait');
                          clearTimeout(timer); timer = setTimeout(save, delay); }
    else setSave('saved');
  }).catch(() => setSave('local'));
} else setSave('local');

/* ---------- 复制（自存拿不到时的退路） ---------- */
const sheet = document.getElementById('sheet'), sheetText = document.getElementById('sheet-text');
document.getElementById('copy').addEventListener('click', async () => {
  const txt = payload();
  if (!txt){ flash('还没有裁决可复制。'); return; }
  sheetText.value = txt; sheet.hidden = false;
  try { await navigator.clipboard.writeText(txt);
        document.getElementById('sheet-note').textContent = '已复制到剪贴板。下面是全文，可再手动选。'; }
  catch(e){ document.getElementById('sheet-note').textContent = '长按选中全文复制，或用下面的按钮。'; }
});
document.getElementById('sheet-copy').addEventListener('click', async () => {
  sheetText.focus(); sheetText.select();
  try { await navigator.clipboard.writeText(sheetText.value);
        document.getElementById('sheet-note').textContent = '已复制。'; }
  catch(e){ document.getElementById('sheet-note').textContent = '复制没成功，请长按选中。'; }
});
document.getElementById('sheet-close').addEventListener('click', () => sheet.hidden = true);
sheet.addEventListener('click', e => { if (e.target === sheet) sheet.hidden = true; });
const resetBtn = document.getElementById('reset');
let armed = 0;
resetBtn.addEventListener('click', () => {
  if (!armed){ armed = 1; resetBtn.textContent = '确认清空？';
               setTimeout(() => { armed = 0; resetBtn.textContent = '清空'; }, 3000); return; }
  armed = 0; resetBtn.textContent = '清空';
  state = {}; persist(); draw(); flash('已清空。');
});
const intro = document.getElementById('intro');
try { if (localStorage.getItem(KEY + '-intro') === 'shut') intro.open = false; } catch(e){}
intro.addEventListener('toggle', () => {
  try { localStorage.setItem(KEY + '-intro', intro.open ? 'open' : 'shut'); } catch(e){}
});
draw();
"""


def render(title: str, key: str, verdicts: dict[str, str], css: str, page_js: str,
           payload: dict) -> str:
    """页面 js = page_js（定义 BODY / rowId / card / visibleRows / payload …）+ 公共壳。"""
    head = head_tags(title)
    js = page_js + SHELL_JS.replace("__HEAD__", json.dumps(head)) \
                           .replace("__KEY__", json.dumps(key)) \
                           .replace("__VERDICTS__", json.dumps(verdicts, ensure_ascii=False))
    blob = json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")
    return (head + '\n<style id="css">' + TOKENS + css + "</style>\n"
            + '<div id="app"></div>\n'
            + '<script type="application/json" id="data">' + blob + "</script>\n"
            + '<script id="js">' + js + "</script>\n")
