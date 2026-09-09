// ── 体检 / 质量 / 四把尺子 / 人审率台账 ──────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分，方案 §8.1 里跟「定字裁决」
// 挤在同一个 727 行大段的第二块）。「跑这批」（runBatch）跑完要回填「定字裁决」
// 面板的卡片——那是另一个面板，按约定不直接 import，由 mount() 的 deps 转接。
import { $, api } from '../api.js';

export const id = 'review';

let _rvLoad = () => {};

export function mount(root, deps = {}) {
  if (deps.rvLoad) _rvLoad = deps.rvLoad;
  $('#rl_go').onclick = loadRulers;
  $('#rv_run').onclick = runBatch;
  $('#rd_go').onclick = loadRound;
  $('#q_go').onclick = loadQuality;
}

async function loadRulers() {
  const book = $('#book') ? $('#book').value : 'vol01';
  $('#rl_out').textContent = '测量中…（要读列图，十几秒）';
  let d;
  try { d = await api('/api/rulers?book=' + encodeURIComponent(book) + '&pages=dev_set'); }
  catch (e) { $('#rl_out').textContent = '测量失败：' + e.message; return; }
  const rows = d.rulers.map(r => {
    const v = r.value == null ? '—' : r.value.toFixed(2) + r.unit;
    // 达标判定：目标写 0 的就要求为 0，写 100% 的就要求满分；'—' 是只报不判
    const good = r.goal === '0' ? r.num === 0
               : (r.goal === '100%' ? r.num === r.den : null);
    const cls = good === null ? '' : (good ? 'qok' : 'qbad');
    const det = (r.detail || []).slice(0, 6).map(x =>
      'p' + x.page + (x.col != null ? ' c' + x.col : '')
      + (x.slot != null ? ' s' + x.slot : '')
      + (x.px != null ? ' ' + x.px + 'px' : '')).join(' · ');
    return '<tr><td class="mono">' + r.key + '</td><td>' + r.title
      + '<div class="qs">' + r.note + '</div></td>'
      + '<td class="mono ' + cls + '">' + v + '</td>'
      + '<td class="mono qs">' + r.num + '/' + r.den + '</td>'
      + '<td class="qs">' + r.goal + '</td>'
      + '<td class="qs">' + det + '</td></tr>';
  }).join('');
  $('#rl_out').innerHTML =
    '<table class="jobs"><thead><tr><th>#</th><th>尺子</th><th>现值</th>'
    + '<th>分子/分母</th><th>目标</th><th>头几条（可点页去看）</th></tr></thead>'
    + '<tbody>' + rows + '</tbody></table>'
    + '<div class="qs" style="margin-top:.5rem;line-height:1.7">'
    + '<b>怎么读</b>：R2「真粘连」是图像极限（笔画物理相连），'
    + '标 flag 交人审即可，<b>不算错</b>；要盯的是「可改善」。'
    + 'R4 只认紧贴紧框的笔画级墨段——窗口若开到版框会扫进邻字，'
    + '把整字高度（~110px）误报成被切。</div>';
}

const RD_MARK = { green: '✓ 绿', yellow: '~ 黄', red: '✗ 红', none: '—' };
const RD_CLS = { green: 'qok', yellow: '', red: 'qbad', none: 'muted' };

async function runBatch() {
  const book = $('#rv_book').value || 'vol01';
  const pages = ($('#rv_pages').value || '').trim();
  if (!pages) { $('#rv_msg').textContent = '先填页码（或点体检里的「填入页框」）'; return; }
  const btn = $('#rv_run');
  btn.disabled = true;
  $('#rv_msg').textContent = '入队中…';
  let job;
  try {
    job = await api('/api/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book, pipeline: 'keben_body_v2', from_step: '', to_step: '',
                             pages, force: false, params: {} })
    });
  } catch (e) { $('#rv_msg').textContent = '入队失败：' + e.message; btn.disabled = false; return; }
  // 轮询到结束。跑完**自动载入卡片**——省掉「跑完了吗→再点载入」这一步。
  const t0 = Date.now();
  while (Date.now() - t0 < 30 * 60 * 1000) {
    await new Promise(r => setTimeout(r, 2000));
    let j;
    try { j = await api('/api/runs/' + job.id); } catch (e) { continue; }
    const secs = ((Date.now() - t0) / 1000).toFixed(0);
    if (j.status === 'running' || j.status === 'queued') {
      $('#rv_msg').textContent = `跑管线中… ${j.status} ${secs}s（九步 × ${pages.split(',').length} 页，约 3 分钟）`;
      continue;
    }
    btn.disabled = false;
    if (j.status === 'completed') {
      $('#rv_msg').textContent = `跑完了（${secs}s），正在载入待审卡片…`;
      await _rvLoad();
      return;
    }
    $('#rv_msg').textContent = `作业 ${j.status}：去「运行」页看日志（${job.id}）`;
    return;
  }
  btn.disabled = false;
  $('#rv_msg').textContent = '等超时了，去「运行」页看 ' + job.id;
}

async function loadRound() {
  const book = $('#rv_book').value || 'vol01';
  const pages = $('#rv_pages').value || 'dev_set';
  $('#rd_out').textContent = '体检中…（要读产物与金标，十几秒）';
  let d;
  try {
    d = await api('/api/round?book=' + encodeURIComponent(book)
                  + '&pages=' + encodeURIComponent(pages));
  } catch (e) { $('#rd_out').textContent = '体检失败：' + e.message; return; }
  const row = (k, title, light, body, hint) =>
    '<tr><td class="mono">' + k + '</td><td>' + title
    + (hint ? '<div class="qs">' + hint + '</div>' : '') + '</td>'
    + '<td class="mono ' + (RD_CLS[light] || '') + '">' + (RD_MARK[light] || '—') + '</td>'
    + '<td class="qs">' + body + '</td></tr>';
  let rows = '';
  if (d.A) {
    const a = d.A, pct = ([o, n]) => n ? (o / n * 100).toFixed(2) + '%' : '—';
    let body = '整理本 ' + a.gold[0] + '/' + a.gold[1] + ' = ' + pct(a.gold);
    if (a.human[1]) body += ' · 你的裁决 ' + a.human[0] + '/' + a.human[1] + ' = ' + pct(a.human);
    if ((a.errors || []).length)
      body += '<div class="qerr">' + a.errors.slice(0, 4).map(e =>
        e.id + ' 判「' + e.pred + '」金标「' + e.gold + '」').join(' · ') + '</div>';
    rows += row('A', '自动放行错误率', a.light, body,
                a.light === 'green' ? '' : '先看图：管线错？金标错？还是你被坏图块误导？');
  }
  if (d.B) {
    const b = d.B;
    rows += row('B', '人审率', b.light,
      b.review + '/' + b.total + ' = ' + (b.rate * 100).toFixed(2) + '%'
      + (b.excluded ? '<span class="qs">（另有 ' + b.excluded + ' 格在排除名单里，不进分母）</span>' : '')
      + '<div id="rate_hist" class="qs">台账载入中…</div>'
      + (b.by_page.length ? '<div class="qs">' + b.by_page.map(r => 'p' + r.page + ':' + r.n).join(' ') + '</div>' : ''),
      '');
  }
  if (d.C) {
    const c = d.C;
    rows += row('C', '缺陷聚集（累计 ' + c.total + ' 条）', c.light,
      c.rows.slice(0, 5).map(r => '格位 ' + r.slot + ': ' + r.n + ' 条/' + r.pages + ' 页'
        + (c.worst && r.slot === c.worst.slot ? ' ← 扎堆' : '')).join('<br>'),
      c.worst ? '<b>停下修算法</b>：孤例是个案，扎堆才是系统性问题'
              : '孤例是个案，扎堆才是系统性问题；黄灯先记着别动算法');
  }
  if (d.C2) {
    const t = d.C2;
    rows += row('C2', '字距（挤排页）', t.light,
      t.rows.length ? t.rows.map(r => 'p' + r.page + ' 间隙中位 ' + r.median_gap
        + 'px，' + (r.near_ratio * 100).toFixed(0) + '% 不足 5px').join('<br>') : '字距正常',
      t.rows.length ? '这几页字<b>物理相连</b>，切分做不到完美；人审会偏多，标缺陷即可，<b>不算算法退步</b>' : '');
  }
  if (d.D && d.D.rate != null) {
    const x = d.D;
    rows += row('D', '生僻字 top-10（字体模板+CNN 融合）', x.light,
      x.hit + '/' + x.n + ' = ' + (x.rate * 100).toFixed(1) + '%' + (x.note ? ' · ' + x.note : ''),
      x.cnn ? '' : '没有 CNN checkpoint，退回纯 HOG——数字会明显低');
  }
  if (d.E) {
    const e = d.E, fa = e.form_auto || [0, 0];
    const body = (e.audited
        ? '人裁核过 ' + e.hit + '/' + e.audited + ' = ' + (e.rate * 100).toFixed(1) + '%（Wilson 下界 ' + e.wilson_low + '；variant_form 定形 ' + fa[0] + '/' + fa[1] + '）'
        : '还没有人裁核过的异体位')
      + '<div class="qs">异体位自动放行 ' + e.variant_admits + ' 条 · 义定形未定待审 ' + e.form_open + ' 条' + (e.note ? ' · ' + e.note : '') + '</div>'
      + ((e.errors || []).length ? '<div class="qerr">' + e.errors.slice(0, 4).map(x => x.id + ' 存「' + x.pred + '」人裁「' + x.human + '」').join(' · ') + '</div>' : '');
    rows += row('E', '字形保真率（自动放行的异体位，字形须与人裁完全一致）', e.light, body,
                e.light === 'none' ? '去「异体 → 组视图」照准一批，攒够 50 条才亮灯' : '');
  }
  // F 夹注：只有本册这批页里有夹注格才亮灯（vol01 卷首一一处没有）
  if (d.F && d.F.n_cells) {
    const f = d.F;
    const bt = f.by_type || {};
    const tstr = ['T1', 'T2'].filter(k => bt[k]).map(k =>
      k + (k === 'T1' ? '版本注' : '案語') + ' ' + bt[k].n_review + '/' + bt[k].n_cells
        + ' = ' + (bt[k].rate * 100).toFixed(2) + '%').join(' · ');
    const body = '人审 ' + f.n_review + '/' + f.n_cells + ' = ' + (f.rate * 100).toFixed(2) + '%'
      + ' · 段 ' + f.n_segments + '（有整理本参照 ' + f.n_segments_with_ref + '）'
      + (tstr ? '<div class="qs">' + tstr + '</div>' : '')
      + '<div class="qs">丢字 ' + f.n_lost + ' 段'
      + (f.lost_rate != null ? '（' + (f.lost_rate * 100).toFixed(1) + '%）' : '')
      + (f.n_no_ref ? ' · 锚不上整理本 ' + f.n_no_ref + ' 段（多为 T2 案語）' : '') + '</div>'
      + ((f.lost || []).length
          ? '<div class="qerr">' + f.lost.slice(0, 4).map(x => 'p' + x.page + ' c' + x.col + ' a' + x.a + '/b' + x.b).join(' · ') + '</div>'
          : '');
    rows += row('F', '夹注（雙行小注）人审率与丢字率', f.light, body,
                f.n_lost ? '段格数与 a/b 不匹配 = 丢数据，比认错字严重，先修切分' : '');
  }
  const nx = d.next || {};
  const nxt = (nx.batch || []).length
    ? '<div class="qs" style="margin-top:.6rem">下一批（正文页，已跳过职名/目录页）：'
      + '<span class="mono">' + nx.batch.join(',') + '</span>'
      + ' <button id="rd_use">填入页框</button>'
      + '<div class="qs">正文页 ' + nx.body_total + '，已处理 ' + nx.done + '，剩 ' + nx.todo + '</div></div>'
    : '<div class="qs" style="margin-top:.6rem">正文页跑完了。</div>';
  $('#rd_out').innerHTML =
    (rows ? '<table class="jobs"><thead><tr><th>#</th><th>判据</th><th>灯</th><th>数</th></tr></thead>'
            + '<tbody>' + rows + '</tbody></table>'
          : '<div class="qs">没填页码，只给下一批建议。</div>') + nxt;
  const use = document.getElementById('rd_use');
  if (use) use.onclick = () => { $('#rv_pages').value = (nx.batch || []).join(','); };
  loadRateHistory(book);
}

/** 人审率台账：B 行下面的趋势条。判据只报当下这一跑，趋势要看纵向。 */
async function loadRateHistory(book) {
  const box = document.getElementById('rate_hist');
  if (!box) return;
  let rows;
  try { rows = (await api('/api/review/rate-history?book=' + encodeURIComponent(book))).rows || []; }
  catch (e) { box.textContent = '台账读不出来：' + e.message; return; }
  if (!rows.length) { box.innerHTML = '台账还没有 ' + book + ' 的记录 ' + snapBtn(); return; }
  const first = rows[0], last = rows[rows.length - 1];
  const max = Math.max(...rows.map(r => r.rate));
  const bars = rows.map(r => {
    const h = Math.max(2, Math.round(r.rate / max * 22));
    const un = r.unseen_rate != null ? `　未审段 ${(r.unseen_rate * 100).toFixed(2)}%` : '';
    return `<span class="rbar" style="height:${h}px" title="${r.date} ${(r.rate * 100).toFixed(2)}%${un}\n${(r.note || '').replace(/"/g, '')}"></span>`;
  }).join('');
  box.innerHTML = `<b>台账</b> ${first.date} <b>${(first.rate * 100).toFixed(2)}%</b>`
    + ` → 今 <b>${(last.rate * 100).toFixed(2)}%</b>`
    + `（降 ${((1 - last.rate / Math.max(first.rate, 1e-9)) * 100).toFixed(0)}%，${rows.length} 次记录）`
    + (last.unseen_rate != null ? `　未审段 <b>${(last.unseen_rate * 100).toFixed(2)}%</b>` : '')
    + `<span class="rbars">${bars}</span> ` + snapBtn();
  const btn = document.getElementById('rate_snap');
  if (btn) btn.onclick = async () => {
    btn.disabled = true; btn.textContent = '记录中…';
    try {
      await api('/api/review/rate-history', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ books: book, note: prompt('这次的说明（可留空）') || '' }) });
      loadRateHistory(book);
    } catch (e) { btn.disabled = false; btn.textContent = '记一笔失败'; }
  };
}
const snapBtn = () => '<button id="rate_snap" class="mini">记一笔</button>';

async function loadQuality() {
  const book = $('#rv_book').value || $('#book').value;
  const pages = $('#rv_pages').value || 'dev_set';
  $('#q_out').textContent = '统计中…';
  const d = await api('/api/quality?book=' + encodeURIComponent(book)
                      + '&pages=' + encodeURIComponent(pages));
  const a = d.accuracy, g = d.defects;
  const pct = x => x == null ? '—' : (x * 100).toFixed(2) + '%';
  const chips = rows => rows.map(r =>
    '<span class="qchip">' + r.key + '<b>' + r.n + '</b></span>').join('');
  const chan = a.by_channel.map(c =>
    '<tr><td>' + c.channel + '</td><td class="mono">' + c.ok + '/' + c.n + '</td>'
    + '<td class="mono ' + (c.acc < 1 ? 'qbad' : 'qok') + '">' + pct(c.acc)
    + '</td></tr>').join('');
  const errs = a.errors.length
    ? '<div class="qerr">错例：' + a.errors.slice(0, 8).map(e =>
        '<span class="mono">' + e.id + ' 判「' + e.pred + '」金标「' + e.gold
        + '」(' + e.channel + ')</span>').join(' · ') + '</div>'
    : '<div class="qok" style="font-size:.78rem;margin-top:.4rem">金标覆盖范围内零错例</div>';
  $('#q_out').innerHTML =
    '<div class="qgrid">'
    + '<div>'
    +   '<div class="qk">定字准确率</div>'
    +   '<div class="qv ' + (a.overall === 1 ? 'qok' : 'qbad') + '">' + pct(a.overall) + '</div>'
    +   '<div class="qs">对整理本自动金标 ' + a.n_gold + ' 条（覆盖 '
    +      pct(a.gold_coverage) + ' 的字位）</div>'
    +   '<table class="jobs" style="margin-top:.4rem">' + chan + '</table>'
    +   errs
    + '</div>'
    + '<div>'
    +   '<div class="qk">人裁标出的切分缺陷 <b>' + g.n + '</b> 条</div>'
    +   '<div class="qs" style="margin:.3rem 0">类型 ' + chips(g.by_quality) + '</div>'
    +   '<div class="qs">按页 ' + chips(g.by_page) + '</div>'
    +   '<div class="qs">按列 ' + chips(g.by_col) + '</div>'
    +   '<div class="qs">按格位 ' + chips(g.by_slot) + '</div>'
    +   '<div class="qs" style="margin-top:.5rem;line-height:1.7">'
    +     '<b>怎么读</b>：孤例是个案，<b>扎堆才是系统性问题</b>。某个格位反复出问题'
    +     ' → 那一格的先验或边界有系统偏差；某一页占了大半 → 先查那页的上游几何。'
    +   '</div>'
    + '</div>'
    + '</div>';
}

export const refresh = loadQuality;
