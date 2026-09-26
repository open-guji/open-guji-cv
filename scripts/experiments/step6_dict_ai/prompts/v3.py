"""提示词 v3 = v2 + 专名线索（2026-09-26）。
动机：冒烟第二轮三个模型都把人名「石旦」判成「且」。专名表来自整理本（data/names.json，muse 抽取、按原文计数）。
做法是**确定性匹配**，不让模型自己去翻表：把候选字放进待判位后，前后文若能拼成表里某条专名（其他字位允许
异体写法；别的待判位 ▢ 只在它的候选里有所需字时才算匹配），就写一条「候选 X → 可构成本书某类专名 N（整理本出现 k 次）」。
另附本日整理本片段里出现过的专名（最多 30 条），给模型看上下文里是谁。"""
import json, os, unicodedata
from . import v1, v2
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 'v3-2026-09-26'
_NAMES = None
def names():
    global _NAMES
    if _NAMES is None:
        p = H + '/data/names.json'
        _NAMES = json.load(open(p))['names'] if os.path.exists(p) else []
    return _NAMES
NFC = lambda x: unicodedata.normalize('NFC', x)
SYSTEM = v2.SYSTEM.replace('3. 理由要具體：', '''3. 【專名線索】是程序按本書專名表（從整理本抽出）機械匹配的結果：某候選放進此位後能與前後文拼成本書出現過的人名、地名、官名。它是很強的證據，但整理本的專名寫法可能是通行字，刻本可能刻異體；線索只證明「是哪個詞」，不證明刻的是哪個字形。
4. 理由要具體：''').replace('4. confidence：', '5. confidence：').replace('5. 只能在候選中選', '6. 只能在候選中選')

def _eq(a, b, dictlib):
    a, b = NFC(a), NFC(b)
    return a == b or dictlib.V.are_variants(a, b)

def name_hits(pos, cand, keys, txt, cellmap, dictlib, max_len=8):
    """候选 cand 放在全书位置 pos，能拼出的专名列表"""
    hits = []
    for e in names():
        n = e['n']; L = len(n)
        if L > max_len or not any(_eq(ch, cand, dictlib) for ch in n): continue
        for off in range(L):
            if not _eq(n[off], cand, dictlib): continue
            s = pos - off
            if s < 0 or s + L > len(txt): continue
            ok = True
            for i in range(L):
                p = s + i
                if p == pos: continue
                k = keys[p]
                if k in cellmap:        # 另一个待判位：它的候选里得有所需字
                    if not any(_eq(x['c'], n[i], dictlib) for x in cellmap[k]['cands']): ok = False; break
                elif not _eq(txt[p], n[i], dictlib): ok = False; break
            if ok: hits.append(e); break
    return hits

def build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=True, min_ctx=300):
    msgs, marks = v2.build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=with_ref, min_ctx=min_ctx)
    cellmap = {c['key']: c for c in _allcells()}
    lines = []
    for m, c in marks.items():
        for x in c['cands']:
            hs = name_hits(c['pos'], x['c'], keys, txt, cellmap, dictlib)
            for e in hs[:3]:
                lines.append(f"{m} 候選「{x['c']}」→ 可構成本書{e['t']}「{e['n']}」（整理本出現 {e['count']} 次{'；' + e['note'] if e.get('note') else ''}）")
    ref = DAYS[d].get('ref', '')
    today = [e for e in names() if e['n'] in ref][:30]
    block = '\n\n【專名線索（程序匹配）】\n' + ('\n'.join(lines) if lines else '（無候選能拼成本書專名）')
    if today:
        block += '\n\n【本日整理本中出現的專名】' + '；'.join(f"{e['n']}（{e['t']}）" for e in today)
    u = msgs[1]['content']
    u = u.replace('\n\n【詞典', block + '\n\n【詞典', 1)
    return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': u}], marks

_CELLS = None
def _allcells():
    global _CELLS
    if _CELLS is None:
        _CELLS = list(json.load(open(H + '/data/cells_human1135.json')).values())
    return _CELLS
