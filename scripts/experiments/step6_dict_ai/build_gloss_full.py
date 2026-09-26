"""E2：全义项释义表 data/gloss_full.json（只收本书候选里出现过的字）。
cv 仓 config/gloss/gloss.json 是给审阅界面「扫一眼」的，每字只收首义项且截到 64 字——对 AI 有害：
羹 首义项是「不羹：地名」，且 首义项是「農曆六月」。这里：
  萌典（教育部重編國語辭典修訂本，CC BY-ND 3.0 TW）列全部读音与义项（去书证）；
  萌典没有的字用《康熙字典》点校文本（CC BY-SA 3.0）整条，截到 240 字。
数据源：cache_src/moe/dict-revised.json（g0v/moedict-data main 分支 .xz）、cache_src/kangxi.txt。"""
import json, gzip, os, re, unicodedata
H = os.path.dirname(os.path.abspath(__file__))
N = lambda x: unicodedata.normalize('NFC', x)
chars = set()
for c in json.load(open(H + '/data/cells_human1135.json')).values():
    chars |= {N(x['c']) for x in c['cands']}
CJK = re.compile(r'"([\u3400-\u9fff\uf900-\ufaff\U00020000-\U0003134f])"')
with gzip.open(H + '/data/cells_bxgb_fullbook.jsonl.gz', 'rt') as f:   # 全书候选：各路候选里的单字
    for line in f:
        chars |= {N(ch) for ch in CJK.findall(json.dumps(json.loads(line), ensure_ascii=False))}
moe = {}
for e in json.load(open(H + '/cache_src/moe/dict-revised.json')):
    t = e.get('title', '')
    if len(t) == 1 and N(t) in chars:
        segs = []
        for h in e.get('heteronyms', []):
            ds = [f"{i + 1}.{('〔' + d['type'] + '〕') if d.get('type') else ''}{d['def']}" for i, d in enumerate(h.get('definitions', [])) if d.get('def')]
            if ds: segs.append(f"[{h.get('pinyin', '')}] " + ' '.join(ds))
        if segs: moe[N(t)] = '；'.join(segs)[:600]
kx = {}
for line in open(H + '/cache_src/kangxi.txt', encoding='utf-8'):
    p = line.rstrip('\n').split('\t')
    if len(p) < 3 or len(p[0]) != 1 or N(p[0]) not in chars or N(p[0]) in moe: continue
    body = re.sub(r'^《康熙字典》〈[^〉]*〉【[^】]*】頁\d+第\d+\s*', '', p[-1])
    kx[N(p[0])] = body[:240]
out = {c: {'d': moe[c], 's': '教育部重編國語辭典（全義項）'} for c in moe}
out.update({c: {'d': kx[c], 's': '康熙字典'} for c in kx})
json.dump(out, open(H + '/data/gloss_full.json', 'w'), ensure_ascii=False)
print('候选字', len(chars), '萌典', len(moe), '康熙', len(kx), '未收', len(chars - set(out)))
for c in '且羹糜倫': print(c, out.get(c, {}).get('d', '')[:160])
