// ── 定字裁决（C2）：审查搬进控制台 ──────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。
// 卡片来自 /api/review/cards（admit_decide 产物），裁决直接 POST /api/events，
// 再走既有的路由 → glyphdb_admit。**不新造协议**。
//
// 一条口径（用户 2026-09-04 定）：**先读字形，文本录入按文意，记录转换**。
// 所以每张卡收两个值：shape（图上刻的形，默认取候选）与 reading（文意，
// 默认等于 shape）。两者不同的那些正是已/巳、卽/即 这类，事件里都带上，
// 下游按 GlyphDB 的 shape/char 分岔存（charset_and_lm.md §四）。
import { $, api } from '../api.js';
import { needsReading, readingOf, consumedMsg } from '../shared/domain.js';

export const id = 'review';

let _onSubmitted = () => {};

export let RV = { cards: [], cur: 0, verdicts: {}, seen: {}, rare: {}, rareFly: new Set() };

export function mount(root, deps = {}) {
  if (deps.onSubmitted) _onSubmitted = deps.onSubmitted;
  $('#rv_load').onclick = rvLoad;
  $('#rv_cards').addEventListener('click', (ev) => {
    const b = ev.target.closest('.rvrarebtn');
    if (b) rvFetchRare(+b.dataset.i, true);
    const cb = ev.target.closest('.rvctxbtn');
    if (cb) rvToggleCtxImg(+cb.dataset.i);
  });
  $('#rv_send').onclick = rvSend;
  $('#rv_todo').onchange = () => { RV.snapshot = null; rvFilter(); };
  $('#rv_cards').addEventListener('click', ev => {
    // 点 OCR / 上下文给出的字 = 直接采信（省掉手抄；那些字本来就是对的居多）
    const take = ev.target.closest('.rvtake');
    if (take) {
      const i = +take.dataset.i;
      rvFocus(i);
      rvSet(i, take.dataset.ch);
      return;
    }
    const mark = ev.target.closest('.rvmark');
    if (mark) {
      const i = +mark.dataset.i;
      rvFocus(i);
      // 再点一次同一个标记 = 取消
      const cur = RV.verdicts[RV.cards[i]?.id];
      rvSet(i, '', '', cur && cur.done === mark.dataset.mark ? '' : mark.dataset.mark);
      return;
    }
    // 义定形未定：形取按钮、文意取整理本字（data-rd），两者不同就是一次转换
    const fp = ev.target.closest('.rvformpick');
    if (fp) {
      const i = +fp.dataset.i;
      rvFocus(i);
      rvSet(i, fp.dataset.ch, fp.dataset.rd || fp.dataset.ch);
      return;
    }
    const b = ev.target.closest('.rvpick');
    if (!b) return;
    const i = +b.dataset.i;
    rvFocus(i);
    rvSet(i, b.dataset.ch);
  });
  $('#rv_cards').addEventListener('change', ev => {
    const ck = ev.target.closest('.rvnolibck');
    if (!ck) return;
    const i = +ck.dataset.i, c = RV.cards[i];
    if (!c) return;
    const v = RV.verdicts[c.id] || (RV.verdicts[c.id] = { done: '' });
    v.noGlyphLib = ck.checked;
    const el = document.getElementById('rvc' + i);
    if (el) el.dataset.nolib = ck.checked ? '1' : '';
  });
  $('#rv_cards').addEventListener('input', ev => {
    const el = ev.target.closest('.rvin');
    if (!el) return;
    const i = +el.dataset.i, c = RV.cards[i];
    if (!c) return;
    const cur = RV.verdicts[c.id] || {};
    const shape = el.dataset.f === 'shape' ? el.value : (cur.shape || '');
    const reading = el.dataset.f === 'reading' ? el.value : (cur.reading || '');
    // **一律走 rvSet**——「己/已/巳 必须填文意」「非三字时文意跟随字形」这些
    // 规则只写在 rvSet 里。这里原先自己写状态、绕过了它，于是输入「巳」也被
    // 直接判成已裁（用户 2026-09-04 实锤：选了巳没让填文意）。
    // 传 undefined 让 rvSet 自己定 done（它会认出 need_reading）。
    rvSet(i, shape, reading, undefined, true);
  });
  // 键盘：1/2/3 采信第几个候选，N 非字，S 跳过，←/→ 翻卡
  document.addEventListener('keydown', ev => {
    if (!$('#view-review').classList.contains('active')) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    // 组合键放行（2026-09-07 用户：「没法 Ctrl+C 复制，会优先读取 C 标为有噪声」）
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const c = RV.cards[RV.cur];
    if (!c) return;
    if (ev.key === 'ArrowRight' || ev.key === 'j') { rvFocus(RV.cur + 1); ev.preventDefault(); }
    else if (ev.key === 'ArrowLeft' || ev.key === 'k') { rvFocus(RV.cur - 1); ev.preventDefault(); }
    else if (['1', '2', '3', '4', '5'].includes(ev.key)) {
      // 键号 = 候选按钮上的号：1 整理本 · 2 库最佳 · 3 生僻字算法 · 4/5 库次选（rvCandList）
      const pick = rvKeyList(c).find(e => e.keys.includes(+ev.key));
      if (pick && pick.ch) { rvSet(RV.cur, pick.ch); rvFocus(RV.cur + 1); ev.preventDefault(); }
    } else if (ev.key === 'n' || ev.key === 'N') {
      rvSet(RV.cur, '', '', 'non'); rvFocus(RV.cur + 1); ev.preventDefault();
    } else if (ev.key === 's' || ev.key === 'S') {
      rvSet(RV.cur, '', '', 'skip'); rvFocus(RV.cur + 1); ev.preventDefault();
    } else if (ev.key === 't' || ev.key === 'T') {
      // 切分问题：字形不完整（沿用 instances 金标的 truncated 口径）
      rvSet(RV.cur, '', '', 'truncated'); rvFocus(RV.cur + 1); ev.preventDefault();
    } else if (ev.key === 'c' || ev.key === 'C') {
      // 切分问题：有噪声（沿用 contaminated 口径：邻字残留/界行/版框混入）
      rvSet(RV.cur, '', '', 'contaminated'); rvFocus(RV.cur + 1); ev.preventDefault();
    }
  });
}

// 候选顺序（用户 2026-09-06「没看到整理本用的是什么，应该放第一位；然后字形库最佳匹配；
// 然后生僻字算法；paddle ocr 准确率不好」）：① 整理本用字 ② 库最佳 ③ 生僻字算法（字体模板+CNN）
// ④⑤ 库次选；OCR 只留在证据行末尾。位置固定、键 1–5 对应；同一个字从两路来就并成一个按钮
// （徽章并列，两个键都选它）。整理本印 即 而本书惯刻 卽 时，账本的 preferred 作无键按钮排在
// 整理本后面——忠于刻本字形，图上刻的是哪个就点哪个。
function rvCandList(c) {
  const db = (c.db && c.db.candidates || []).slice(0, 3);
  const rare = RV.rare[c.id];
  const list = [];
  if (c.ref && c.ref.char) {
    list.push({ ch: c.ref.char, src: '整理本',
                note: '整理本在这一位印的字' + (c.ref.op === 'replace' ? '（对齐段是 replace，位置可能错开一两格）' : '') });
    if (c.ref.form) list.push({ ch: c.ref.form, src: '刻本惯用', nokey: true,
                                note: `整理本印「${c.ref.char}」时本书惯刻这个形（用字账）` });
    // 维基文库版整理本与现有整理本不同时给第二意见（无键，点即选）。两本互不同的人裁位
    // 164 处里现有整理本对 75、维基对 8——整体信整理本，但 搏/摶、始/姑 这类整理本错字它能抓到。
    if (c.ref.wiki) list.push({ ch: c.ref.wiki, src: '维基', nokey: true,
                                note: `维基文库版整理本这一位印「${c.ref.wiki}」，与现有整理本「${c.ref.char}」不同` });
  }
  if (db[0]) list.push({ ch: db[0][0], src: '库', note: '字形库最佳匹配 cov ' + db[0][1] });
  if (rare && rare[0]) list.push({ ch: rare[0].char, src: '形', note: '生僻字算法（字体模板+CNN）相似度 ' + rare[0].score });
  else list.push({ ch: '', src: '形', note: rare ? '生僻字算法没给出候选' : '生僻字候选加载中…' });
  db.slice(1).forEach(([ch, cov]) => list.push({ ch, src: '库', note: '库次选 cov ' + cov }));
  return list;
}
// 键位表：去重后的 [{ch, keys, srcs, note}]，键号按出现顺序；重复的字把键并到先出现的那个按钮上
function rvKeyList(c) {
  const out = [], byCh = {};
  let key = 0;
  for (const x of rvCandList(c)) {
    if (x.ch && byCh[x.ch]) {
      byCh[x.ch].srcs.push(x.src);
      if (!x.nokey) byCh[x.ch].keys.push(++key);
      continue;
    }
    const e = { ch: x.ch, srcs: [x.src], keys: x.nokey ? [] : [++key], note: x.note, nokey: !!x.nokey };
    if (x.ch) byCh[x.ch] = e;
    out.push(e);
  }
  return out;
}
function rvBtnsHtml(c, i) {
  const v = RV.verdicts[c.id] || {};
  return rvKeyList(c).map(e => e.ch
    ? `<button data-i="${i}" data-ch="${e.ch}" class="rvpick${v.shape === e.ch ? ' pick' : ''}${e.nokey ? ' nokey' : ''}"
         title="${e.note}">${e.keys.length ? e.keys.join('/') + '·' : ''}${e.ch}<sub class="rvsrc">${e.srcs.join('·')}</sub></button>`
    : `<span class="rvwait" title="${e.note}">${e.keys.join('/')}·…<sub class="rvsrc">形</sub></span>`).join('');
}
// 生僻字 top1 只为当前卡和后两张拉（k=3，约 0.5s 一张，首次 5s 热索引）。
// 整批预取会让页面卡住（2026-09-05 教训），完整 10 个仍走「查候选」。
// 生僻字 top1 预取。一次请求约 0.35s（后端 HOG+CNN 检索，不可能更快），所以关键是
// **别让它挡住翻卡**：2026-09-07 用户报「页面经常卡，似乎在 load 候选字形」，实测翻卡本身
// 只要 17ms，但串行队列 5 秒才预取到 7 张——翻得比它快就一直看到「候选加载中…」，
// 按键 3 没反应，手感就是卡。三处改法：
//   1. **并发** PREFETCH_CONC 条（0.35s 是网络/计算等待，并发线性提速）；
//   2. 窗口放大到 PREFETCH_AHEAD 张，且以当前卡为中心**优先近的**，翻到哪儿都大概率已就绪；
//   3. 回填时**只改那一个按钮的 innerHTML**，不重建整行 DOM（原来重建会把正在按的按钮换掉）。
const PREFETCH_CHUNK = 24;

async function rvPrefetchRare(i) {
  RV.rareWant = i;
  if (RV.rareBusy) return;
  RV.rareBusy = true;
  const book = $('#rv_book').value || $('#book').value || 'vol01';
  try {
    for (;;) {
      // 以当前卡为中心、先后再前收一批还没拉过的
      const c0 = RV.rareWant ?? RV.cur; RV.rareWant = null;
      const batch = [];
      for (let d = 0; d < RV.cards.length && batch.length < PREFETCH_CHUNK; d++) {
        for (const j of (d ? [c0 + d, c0 - d] : [c0])) {
          const c = RV.cards[j];
          if (c && RV.rare[c.id] === undefined && !RV.rareFly.has(c.id)) {
            RV.rareFly.add(c.id); batch.push({ j, c });
          }
        }
      }
      if (!batch.length) return;
      try {
        const d = await api('/api/rare/batch', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book, k: 3,
            slots: batch.map(({ c }) => `${c.page}:${c.col}:${c.slot}${c.sub || ''}`) }),
        });
        for (const { j, c } of batch) {
          RV.rare[c.id] = d.rare[`${c.page}:${c.col}:${c.slot}${c.sub || ''}`] || [];
          RV.rareFly.delete(c.id);
          // 只换那个「形」占位按钮，别重建整行——重建会打断正在进行的点击/输入
          const el = document.getElementById('rvbtns' + j);
          if (el && RV.cards[j] === c) {
            const slot = el.querySelector('.rvwait');
            const one = slot ? rvOneBtnHtml(c, j) : null;
            if (slot && one) slot.outerHTML = one;      // 「形」是独立按钮：只换它
            else el.innerHTML = rvBtnsHtml(c, j);       // 合并了/没占位：整行重渲染
          }
        }
      } catch (e) {
        for (const { c } of batch) { RV.rare[c.id] = []; RV.rareFly.delete(c.id); }
      }
    }
  } finally { RV.rareBusy = false; }
}

/** 预取回填时用：只渲染「形」那一个按钮（替换占位的 .rvwait）。
 *
 * ⚠️ **只在「形」是独立按钮时能这么做**。生僻字 top1 常常与整理本字/库 top1 是同一个字
 * （vol02:128:8:4 整理本 語、rare top1 也是 語），rvKeyList 会把它们**合并成一个按钮**
 * （键 1/3/4）——这时再往占位处插一个，就成了两个「語」并排（2026-09-07 用户报的重复按钮）。
 * 合并了就返回 null，交给调用方整行重渲染。
 */
function rvOneBtnHtml(c, i) {
  const v = RV.verdicts[c.id] || {};
  const e = rvKeyList(c).find(x => x.srcs.includes('形'));
  if (!e) return null;
  if (!e.ch) return `<span class="rvwait" title="生僻字算法没给出候选">·</span>`;
  if (e.srcs.length > 1) return null;      // 与别的来源合并了，单独插会重复
  return `<button data-i="${i}" data-ch="${e.ch}" class="rvpick${v.shape === e.ch ? ' pick' : ''}"
     title="${e.note}">${e.keys.length ? e.keys.join('/') + '·' : ''}${e.ch}<sub class="rvsrc">${e.srcs.join('·')}</sub></button>`;
}

function rvCard(c, i) {
  const ocr = (c.ocr || []).slice(0, 2);
  const v = RV.verdicts[c.id] || {};
  const doubts =(c.doubts || []).map(d => `<div class="rvdoubt">⚠ ${d}</div>`).join('');
  // 「义定形未定」（variant_form）：文本两路已定语义，刻本刻的是哪个形没定。
  // 只列组内的形，点一个 = 字形取它、文意取整理本字（转换自动记上），账本下次就记住。
  const fm = c.form && c.form.state === 'open' ? c.form : null;
  const fbtns = fm ? `<div class="rvform"><span class="k" title="整理本对这一组只用一种形，它定得了义定不了形；库也没下断言。只在这几个形里选">义定形未定 · 整理本「${fm.semantic}」</span>`
      + (fm.forms || []).map(f => {
          const hn = (fm.human || {})[f] || 0;
          const lib = (fm.lib || []).find(x => x[0] === f);
          return `<button class="rvformpick${v.shape === f ? ' pick' : ''}" data-i="${i}" data-ch="${f}" data-rd="${fm.semantic}"
             title="${hn ? '本书人裁确认过 ' + hn + ' 次' : '本书还没人确认过这个形（首例）'}${lib ? ' · 库 cov ' + lib[1] : ''}">${f}<sub>${hn ? '人' + hn : '新'}</sub></button>`;
        }).join('') + `</div>` : '';
  return `<div class="rvcard" data-i="${i}" data-done="${v.done || ''}" data-nolib="${v.noGlyphLib ? '1' : ''}" id="rvc${i}">
    <div class="rvhead"><b class="rvsel">${c.id}</b><span class="muted">${c.channel || '待审'}</span>
      <label class="rvnolib" title="字形有无法修复的噪声（污墨/裂纹等），这次选字正常裁决，但这张图不进字形库，避免污染字形匹配索引">
        <input type="checkbox" data-i="${i}" class="rvnolibck"${v.noGlyphLib ? ' checked' : ''}> 字形不入库</label>
    </div>
    <div class="rvbody">
      <div class="rvimgcol">
        <img src="${c.patch}" alt="${c.id}" loading="lazy">
        <button class="rvctxbtn" data-i="${i}" title="切分/缩框前的列图原样，上下各带 2 格——排查是不是切分或缩框改坏了这一格">看原图</button>
      </div>
      <div class="rvev">
        <div><span class="k">整理本</span> ${c.ref && c.ref.char
          ? `<b>${c.ref.char}</b><span class="rvp">${c.ref.op}${c.ref.form ? ' · 惯刻 ' + c.ref.form : ''}${c.ref.wiki ? ' · <b style="color:var(--zhu)">维基 ' + c.ref.wiki + '</b>' : ''}</span>`
          : '<span class="muted" title="这页没锚到整理本，或这一格对齐时没有对应字">—</span>'}</div>
        <div><span class="k">库</span> ${c.db ? c.db.verdict + ' ' + c.db.cov : '—'}</div>
        <div><span class="k">上下文</span> ${c.ctx && c.ctx.char
          ? `<button class="rvtake" data-i="${i}" data-ch="${c.ctx.char}"
               title="采信上下文定的字（margin ${c.ctx.margin}）">${c.ctx.char}</button>`
            + `<span class="rvp">m=${c.ctx.margin}</span>`
          : '—'}</div>
        <div><span class="k" title="Paddle OCR，准确率一般，只作参考">OCR</span> ${ocr.length
          ? ocr.map(([ch, p]) =>
              `<button class="rvtake" data-i="${i}" data-ch="${ch}"
                 title="采信这个字（OCR 概率 ${Number(p).toFixed(3)}）">${ch}</button>`
              + `<span class="rvp">${Number(p).toFixed(2)}</span>`).join(' ')
          : '—'}</div>
        ${doubts}
      </div>
    </div>
    <div class="rvctximg" id="rvctximg${i}" style="display:none"></div>
    ${fbtns}
    <div class="rvcand"><span class="rvbtns" id="rvbtns${i}">${rvBtnsHtml(c, i)}</span>
      <input class="rvin" data-i="${i}" data-f="shape" placeholder="字" value="${v.shape || ''}">
      <span class="rvread" data-i="${i}" style="display:${(needsReading(v.shape) || (v.reading && v.reading !== v.shape)) ? '' : 'none'}">
        → <input class="rvin" data-i="${i}" data-f="reading" placeholder="文意"
                 value="${v.reading || ''}" title="己/已/巳 才需要：图上刻的是左边那个，这里填文意该读的">
      </span>
    </div>
    <div class="rvseg">
      <button data-i="${i}" data-mark="truncated" class="rvmark${v.done === 'truncated' ? ' on' : ''}"
        title="本字的笔画被切掉了一部分（T）">字形不完整</button>
      <button data-i="${i}" data-mark="contaminated" class="rvmark${v.done === 'contaminated' ? ' on' : ''}"
        title="混进了邻字残墨 / 界行 / 版框（C）">有噪声</button>
      <button data-i="${i}" data-mark="non" class="rvmark${v.done === 'non' ? ' on' : ''}"
        title="这一格根本不是字（N）">非字</button>
      <button data-i="${i}" data-mark="skip" class="rvmark${v.done === 'skip' ? ' on' : ''}"
        title="真拿不准，留给以后（S）">跳过</button>
    </div>
    <div class="rvctx" id="rvctx${i}"></div>
    <div class="rvrare"><button class="rvrarebtn" data-i="${i}">查候选</button>
      <span class="muted">字体模板 + CNN 融合，10 个；带释义与整理本对应字</span></div>
    <div class="rvrareout" id="rvrare${i}"></div>
  </div>`;
}

// 「看原图」：切分/缩框前的列图原样（用户 2026-09-09：「防止切分和缩框等等改变了图片」）。
// 图不会变，取一次就地缓存（data-src），再点只是显/隐——不重复打后端。
async function rvToggleCtxImg(i) {
  const c = RV.cards[i];
  const box = document.getElementById('rvctximg' + i);
  if (!c || !box) return;
  if (box.style.display !== 'none') { box.style.display = 'none'; return; }
  box.style.display = '';
  if (!box.dataset.done) {
    box.dataset.done = '1';
    box.textContent = '加载中…';
    const book = $('#rv_book').value || $('#book').value || 'vol01';
    const src = `/api/review/context-img/${book}/${c.page}/${c.col}/${c.slot}.png?around=2`;
    box.innerHTML = `<img src="${src}" alt="上下文原图">`;
  }
}

async function rvFetchRare(i, force) {
  const c = RV.cards[i];
  const out = document.getElementById('rvrare' + i);
  if (!c || !out) return;
  if (!force && out.dataset.done) return;
  out.dataset.done = '1';
  out.textContent = '候选加载中…';
  try {
    const sub = c.sub ? `?sub=${c.sub}&k=10` : '?k=10';
    const d = await api(`/api/rare/${$('#rv_book').value || 'vol01'}/${c.page}/${c.col}/${c.slot}${sub}`);
    // 一行一个候选：字 + 【整】/→ 同某字 + 释义。
    // 用户 2026-09-05：「异体字不用显示 unicode 和 ids，最好可以显示常见意思，以及对应哪个繁体整体字。」
    // 用户 2026-09-07：「注音不需要；整理本用字太占地方，加一个【整】即可；康熙字典也不需要说明，
    // 留空间给正式解释；→ 同某字很重要，要保留。」拼音/IDS/码点都进 title，悬停看。
    out.innerHTML = (d.candidates || []).map(x => {
      const std = x.std
        ? `<b class="rvstd" title="整理本里用的是这个字（${x.std_freq} 次）">→ ${x.std}</b>`
        : (x.freq ? `<span class="rvin" title="整理本里用过 ${x.freq} 次">【整】</span>` : '');
      return `<div class="rvrrow">`
        + `<button class="rvpick rvrarepick" data-i="${i}" data-ch="${x.char}"
             title="${x.py ? x.py + ' · ' : ''}相似度 ${x.score} · ${x.font} · ${x.ids || '—'} · ${x.cp}">${x.char}</button>`
        + std
        + `<span class="rvgloss" title="${(x.gloss || '').replace(/"/g, '&quot;')}">${x.gloss || ''}</span>`
        + `<a class="rvzi" href="${x.zi}" target="_blank" rel="noopener">字统网</a>`
        + `</div>`;
    }).join('') || '没有候选';
  } catch (e) { out.textContent = '失败：' + e.message; delete out.dataset.done; }
}

export async function rvLoad() {
  const book = $('#rv_book').value || $('#book').value;
  const pages = $('#rv_pages').value || 'dev_set';
  const only = $('#rv_only').value;
  const batch = rvBatch();
  $('#rv_msg').textContent = '载入中…';
  const d = await api(`/api/review/cards?book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}&only=${only}&limit=400`);
  // **把已裁过的读回来**——裁决早就落成事件了，前端此前只记在内存里，
  // 一刷新就要重审一遍（用户 2026-09-04 实锤）。同 id 后到覆盖。
  let done = {};
  try {
    const v = await api(`/api/review/verdicts?batch=${encodeURIComponent(batch)}`);
    done = v.verdicts || {};
  } catch (e) { /* 批次还不存在就是没裁过，正常 */ }
  RV = { cards: d.cards, cur: 0, verdicts: { ...done, ...(RV.verdicts || {}) },
       seen: RV.seen || {}, rare: RV.rare || {}, rareFly: new Set(), snapshot: null };
  // 卡片一进列表就算「看见」——dwell 从这里算到落裁那一刻
  const t0 = Date.now();
  d.cards.forEach(c => { if (!RV.seen[c.id]) RV.seen[c.id] = t0; });
  $('#rv_cards').innerHTML = d.cards.map(rvCard).join('');
  rvFilter();
  rvFocus(0);
  // 候选不再自动预取：一批 100 张卡就是 100 次 0.32s 的后端调用（并发 2 要 16 秒），
  // 载入时整页发卡。用户 2026-09-05 反馈「一打开裁决卡了好久」。改成点「查候选」按需拉。
  // 上下文批量拉：跨列/跨页凑够前后各 10 个字（用户 2026-09-09：「文字在
  // 第一个或最后一个字时看不到上下文，应该动态加载前十后十，不论是否在一
  // 行」）。**不能再按列分组只拉一次**——同一列的卡「本位」不同，拼接结果
  // 也不同；但一批 400 张卡逐个请求 = 逐个重读所在页产物，会重演「候选加载
  // 卡顿」那次教训，所以走批量接口，一页产物在后端只读一次。
  api('/api/review/around/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ book, before: 10, after: 10,
      items: d.cards.map(c => ({ page: c.page, col: c.col, slot: c.slot })) }),
  }).then(r => {
    const around = r.around || {};
    d.cards.forEach((c, i) => {
      const ctx = around[`${c.page}:${c.col}:${c.slot}`];
      const el = document.getElementById('rvctx' + i);
      if (!el || !ctx) return;
      const slots = ctx.slots || [];
      const at = ctx.at;
      // 读文定字：本位高亮，**其他待审位标虚线**（提醒这几个字还没定，
      // 别拿它们当可靠上下文），库/OCR 兜底来的字标灰（不是 Step6 定的）。
      el.innerHTML = slots.map((s, k) => {
        const ch = s.char || '□';
        if (k === at) return `<mark>${ch}</mark>`;
        const cls = s.review ? 'ctx-rev' : (s.source === 'db' || s.source === 'ocr' ? 'ctx-w' : '');
        return cls ? `<span class="${cls}">${ch}</span>` : ch;
      }).join('');
    });
  }).catch(() => {});
}

// 只看未裁决：纯前端过滤，不重新载入——裁完一张就让它消失，
// 剩下多少一眼可见。取消勾选即可回看已裁的（要改主意时用）。
function rvFilter() {
  // **快照式过滤**（用户 2026-09-04 定）：勾选的那一刻把「当时还没裁的」记下来，
  // 之后裁哪张都不再抽走卡片——边裁边消失会让页面一直跳，手上那张刚点完就
  // 位移了。要重新收拢，再点一次复选框即可。
  const todoOnly = $('#rv_todo') && $('#rv_todo').checked;
  if (todoOnly && !RV.snapshot) {
    RV.snapshot = new Set(RV.cards
      .filter(c => !(RV.verdicts[c.id] && RV.verdicts[c.id].done))
      .map(c => c.id));
  }
  if (!todoOnly) RV.snapshot = null;
  let shown = 0;
  RV.cards.forEach((c, i) => {
    const el = document.getElementById('rvc' + i);
    if (!el) return;
    const hide = todoOnly && RV.snapshot && !RV.snapshot.has(c.id);
    el.style.display = hide ? 'none' : '';
    if (!hide) shown++;
  });
  const n = RV.cards.length;
  const st = c => (RV.verdicts[c.id] || {}).done;
  // need_reading 是「选了 己/已/巳 但还没填文意」——**不算已裁**，单独报，
  // 否则人会以为裁完了，提交时才发现被拦下。
  const nDone = RV.cards.filter(c => st(c) && st(c) !== 'need_reading').length;
  const nNeed = RV.cards.filter(c => st(c) === 'need_reading').length;
  $('#rv_msg').textContent = `${n} 张 · 已裁 ${nDone}`
    + (nNeed ? ` · 待填文意 ${nNeed}` : '')
    + (todoOnly ? ` · 本轮待裁 ${shown}` : '');
}

function rvFocus(i) {
  if (!RV.cards.length) return;
  // 「只看未裁决」时，翻卡要跳过隐藏的那些，否则焦点会落到看不见的卡上
  const dir = i >= RV.cur ? 1 : -1;
  let j = Math.max(0, Math.min(i, RV.cards.length - 1));
  while (j >= 0 && j < RV.cards.length) {
    const el = document.getElementById('rvc' + j);
    if (!el || el.style.display !== 'none') break;
    j += dir;
  }
  if (j < 0 || j >= RV.cards.length) j = Math.max(0, Math.min(i, RV.cards.length - 1));
  RV.cur = j;
  document.querySelectorAll('.rvcard.cur').forEach(e => e.classList.remove('cur'));
  const el = document.getElementById('rvc' + RV.cur);
  if (el) { el.classList.add('cur'); el.scrollIntoView({ block: 'nearest' }); }
  rvPrefetchRare(RV.cur);
}

function rvSet(i, shape, reading, done, fromInput) {
  const c = RV.cards[i];
  if (!c) return;
  // `done` 显式传空串 = 撤销这张卡的裁决（再点一次同一个标记）；
  // 传 undefined 才走「有字就算已裁」的默认。用 `||` 会把空串兜成 '1'，
  // 撤销就失效了——实测点两次「字形不完整」会留下一个 done='1' 的假裁决。
  let mark = done === undefined ? (shape ? '1' : '') : done;
  // 己/已/巳 **必须**填文意才算裁完（用户 2026-09-04 定：「这 3 个形近字是
  // 一定要选文意的」）。只填字形就置成待填状态，卡片保持未完成、提交时不带上，
  // 免得默认把文意当成等于字形——那恰恰是这三个字最容易错的地方。
  const rd = reading || '';
  if (needsReading(shape) && !rd) mark = 'need_reading';
  // 记裁决时刻与停留时长。**事件里的 ts 是收割时间，不是裁决时间**
  // （324 条历史事件只有 4 个不同的 ts），所以「每条裁决多久」此前根本量不出来
  // ——而那正是 UI 改造唯一的验收指标。dwell 从卡片进列表算到落裁那一刻，
  // 改判时保留第一次的 dwell（第二次是复核，不是首次判断的耗时）。
  const _prev = RV.verdicts[c.id];
  const _now = Date.now();
  const _dwell = (_prev && _prev.dwell !== undefined) ? _prev.dwell
                 : (RV.seen && RV.seen[c.id] ? _now - RV.seen[c.id] : undefined);
  RV.verdicts[c.id] = { shape, reading: needsReading(shape) ? rd : (rd || shape),
                        done: mark, ts: _now, dwell: _dwell };
  const el = document.getElementById('rvc' + i);
  if (el) {
    el.dataset.done = mark;
    el.querySelectorAll('.rvpick').forEach(b =>
      b.classList.toggle('pick', !!shape && b.dataset.ch === shape));
    el.querySelectorAll('.rvmark').forEach(b =>
      b.classList.toggle('on', !!mark && b.dataset.mark === mark));
    // 从输入框来的不回写输入框——否则光标会跳、正在打的字被覆盖
    if (!fromInput) {
      const si = el.querySelector('[data-f="shape"]'), ri = el.querySelector('[data-f="reading"]');
      if (si) si.value = shape || '';
      if (ri) ri.value = needsReading(shape) ? (reading || '') : (reading || shape || '');
    }
    el.querySelectorAll('.rvformpick').forEach(b =>
      b.classList.toggle('pick', !!shape && b.dataset.ch === shape));
    const box = el.querySelector('.rvread');
    if (box) box.style.display = (needsReading(shape) || (reading && reading !== shape)) ? '' : 'none';
  }
}

// 载入与提交必须落在**同一个批次**上，否则读回的和写进去的对不上。
function rvBatch() {
  const book = $('#rv_book').value || $('#book').value;
  return $('#rv_batch').value.trim()
    || `${book}-${$('#rv_pages').value || 'dev_set'}-decide`;
}

async function rvSend() {
  const batch = rvBatch();
  const rows = [];
  let pending = 0;
  for (const [id, v] of Object.entries(RV.verdicts)) {
    if (v.done === 'need_reading') { pending++; continue; }
    if (!v.done) continue;
    if (v.done === 'skip') { rows.push({ id, v: 'skip' }); continue; }
    if (v.done === 'non') { rows.push({ id, v: 'not_a_char' }); continue; }
    // 切分问题：不是「这个字是什么」的裁决，而是「这块图不能用」。
    // quality 取值沿用 char-segmentation/instances 金标的四分类
    // （clean / truncated / contaminated / not_text），不另造词——
    // 那批 144 条 truncated + 128 条 contaminated 就是这两档的既有金标。
    if (v.done === 'truncated' || v.done === 'contaminated') {
      rows.push({ id, v: 'seg_defect', quality: v.done,
                  shape: v.shape || '', reading: readingOf(v),
                  client_ts: v.ts, dwell_ms: v.dwell });
      continue;
    }
    // 字形 / 文意分开带上；不同就是一次转换，下游按 shape/char 分岔存
    // no_glyph_lib（用户 2026-09-09）：字形本身有无法修复的噪声（污墨/裂纹等），
    // 字仍正常选，但这张图不该进 GlyphDB（会污染字形匹配索引）——
    // 只是不建库，不是不裁决，所以照常走 confirm，只多带一个标志给 glyphdb_admit 看。
    rows.push({ id, v: 'confirm', shape: v.shape, reading: readingOf(v),
                conversion: (readingOf(v) !== v.shape) ? 1 : 0,
                no_glyph_lib: !!v.noGlyphLib,
                client_ts: v.ts, dwell_ms: v.dwell });
  }
  if (pending) {
    $('#rv_msg').textContent = `有 ${pending} 张选了 己/已/巳 但没填文意（黄框那些），填完再提交`;
    const first = RV.cards.findIndex(c => (RV.verdicts[c.id] || {}).done === 'need_reading');
    if (first >= 0) rvFocus(first);
    return;
  }
  if (!rows.length) { $('#rv_msg').textContent = '还没有裁决'; return; }
  $('#rv_msg').textContent = '提交中…';
  const r = await api('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch, step: 'admit_decide', unit: 'cell', kind: 'confirm', events: rows }) });
  $('#rv_msg').textContent = `已写入 ${r.appended ?? r.n_appended ?? rows.length} 条事件 → 批次 ${batch}`
    + consumedMsg(r);
  _onSubmitted();
}

export const refresh = rvLoad;
