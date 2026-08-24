"""审查页三层持久化核心（整页 publish + localStorage + 复制兜底）。

种子审查页与对勘复审页共用同一份——这段重试/超时/冲突处理是实测踩
出来的（单文件 artifact 对 files 形式发布拒 capability_disabled；
publish 成功后 shell 会重载视图，故滚动位置要先存 sessionStorage），
复制两份必然长歪。

**宿主契约**：把本串拼进宿主自己的 IIFE 里（函数声明提升，先后无所谓），
宿主须提供：

- 常量 ``BATCH``（批次 id）；
- ``list``：卡片容器元素；
- ``progress()``：每次发事件后刷新进度显示；
- ``cardOf(iid)`` / ``setActive(card)``：恢复视图时定位到上次那张卡；
- 手输框类名 ``.other-in``（正在输入时推迟发布，别把半截字存进去）。

事件格式与 ``seed_queue.SEED_EVENT_PREFIX`` 同源，故两个页面产出的
记录都能被 ``guji-cv seed-ingest`` 直接回收。

**改这里要跑 tests/clustering/test_persist_js.py**：它比对两个页面产出
的 HTML 里这段是否逐字节一致，防止有人只改一处。
"""

PERSIST_JS = """  var log = document.getElementById('guji-log');
  var list = document.getElementById('list');
  var PREFIX = 'GUJI-SEED-EVENT';
  var LSKEY = 'guji-seed:' + BATCH;
  var undoStack = [];

  function lines(){
    return log.textContent.match(/GUJI-SEED-EVENT .*/g) || []; }
  function events(){
    return lines().map(function(l){
      try { return JSON.parse(l.slice(PREFIX.length + 1)); }
      catch(e){ return null; }
    }).filter(Boolean); }
  function status(msg, bad){
    var el = document.getElementById('save-status');
    if(!el) return;
    el.textContent = msg;
    el.setAttribute('data-bad', bad ? '1' : '0'); }
  function fail(why){
    disabled = true;
    status(why + ' — 記錄仍在本機，請點上方「複製記錄」貼回對話', true); }

  // ── 持久化：整頁 publish(html)。單文件經典 artifact 只有這條自動路徑
  // ——files 形式對它拒 capability_disabled（vol01 第 4 頁首輪實測）。
  // 日誌內嵌在 #guji-log 裡隨頁面一起發布：發布成功後 shell 會重載本視
  // 圖到新版本，重載前把滾動位置存 sessionStorage，重載後日誌已在頁裡、
  // 狀態由 restore() 重放。複製/下載兜底照舊，永遠可用。
  var pubTimer = 0, disabled = false, publishing = false;
  function withTimeout(pr, ms, tag){
    return new Promise(function(res, rej){
      var done = false;
      var t = setTimeout(function(){
        if(!done){ done = true; rej({code: tag + '_timeout'}); } }, ms);
      pr.then(function(v){ if(!done){ done=true; clearTimeout(t); res(v); } },
              function(e){ if(!done){ done=true; clearTimeout(t); rej(e); } });
    }); }
  var nsPromise = (window.claude && window.claude.use)
    ? withTimeout(window.claude.use('artifact'), 15000, 'use')
        .catch(function(){ return null; })
    : Promise.resolve(null);

  function saveLocal(){
    try { localStorage.setItem(LSKEY, log.textContent); } catch(e){} }
  function exportedCount(){
    try { return parseInt(localStorage.getItem(LSKEY + ':exported') || '0', 10); }
    catch(e){ return 0; } }
  function markExported(n){
    try { localStorage.setItem(LSKEY + ':exported', String(n)); } catch(e){}
    refreshBar(); }
  function refreshBar(){
    var n = lines().length, pending = n - exportedCount();
    var bar = document.getElementById('copybar');
    if(!bar) return;
    bar.textContent = pending > 0
      ? '複製 ' + n + ' 條記錄（' + pending + ' 條未匯出）'
      : (n ? '複製 ' + n + ' 條記錄' : '尚無記錄');
    bar.setAttribute('data-pending', pending > 0 ? '1' : '0'); }

  function snapshotHtml(){
    // 當前 DOM 就是要發布的頁面：日誌/卡片狀態已寫在屬性與文本裡，
    // 重開時 restore() 按日誌重放即可。active 高亮不入快照。
    var a = list.querySelector('.card.active');
    if(a) a.classList.remove('active');
    var html = '<!doctype html>\\n' + document.documentElement.outerHTML;
    if(a) a.classList.add('active');
    return html; }
  function stashView(){
    try {
      var a = list.querySelector('.card.active');
      sessionStorage.setItem(LSKEY + ':view', JSON.stringify({
        iid: a ? a.getAttribute('data-iid') : null,
        y: window.scrollY || 0 }));
    } catch(e){} }
  function restoreView(){
    try {
      var raw = sessionStorage.getItem(LSKEY + ':view');
      if(!raw) return;
      sessionStorage.removeItem(LSKEY + ':view');
      var v = JSON.parse(raw);
      if(v.iid){ var c = cardOf(v.iid); if(c){ setActive(c); return; } }
      if(v.y) window.scrollTo(0, v.y);
    } catch(e){} }

  function publishNow(){
    if(disabled || publishing) return;
    var t = document.querySelector('.other-in:focus');
    if(t && t.value){ schedulePublish(); return; }   // 正在手輸，等一等
    nsPromise.then(function(ns){
      if(!ns){ fail('此視圖無自動儲存'); return; }
      publishing = true;
      status('儲存中…');
      saveLocal(); stashView();
      withTimeout(ns.publish(snapshotHtml()), 30000, 'publish')
        .then(function(){
          // 成功後 shell 會把本視圖重載到新版本；此行多半來不及顯示
          publishing = false; disabled = false;
          status('已儲存 ' + lines().length + ' 條');
        }).catch(function(e){
          publishing = false;
          var c = (e && e.code) || 'unknown';
          if(c === 'rate_limited'){
            status('儲存排隊中…'); pubTimer = setTimeout(publishNow, 30000); }
          else if(c === 'upstream_error' || c === 'publish_timeout'){
            pubTimer = setTimeout(publishNow, 5000 + Math.random() * 4000); }
          else if(c === 'conflict'){ saveLocal(); /* shell 正在重載到新版 */ }
          else { fail('自動儲存失效（' + c + '）'); }
        });
    }); }
  function schedulePublish(){
    status('未儲存…');
    clearTimeout(pubTimer); pubTimer = setTimeout(publishNow, 6000); }
  window.addEventListener('beforeunload', function(){ saveLocal(); });
  document.addEventListener('visibilitychange', function(){
    if(document.visibilityState === 'hidden'){ saveLocal(); } });

  // ── 事件發射 ──
  function seqNext(){
    var n = parseInt(log.getAttribute('data-seq') || '0', 10) + 1;
    log.setAttribute('data-seq', String(n)); return n; }
  function emit(ev){
    ev.batch = BATCH; ev.seq = seqNext();
    ev.ts = new Date().toISOString().slice(0, 19) + '+00:00';
    log.textContent += PREFIX + ' ' + JSON.stringify(ev) + '\\n';
    saveLocal(); schedulePublish(); progress(); refreshBar(); }"""
