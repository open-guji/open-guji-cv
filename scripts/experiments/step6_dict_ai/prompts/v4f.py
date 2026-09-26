"""v4f = v4 + 全义项释义（E2）。只换【詞典】一节：data/gloss_full.json（萌典全部读音义项，萌典无则康熙整条）。
动机：旧 gloss.json 只收首义项（羹→「不羹：地名」、且→「農曆六月」），v1 冒烟里模型据此排除了「肚羹」的羹。"""
import json, os, re, unicodedata
from . import v4
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 'v4f-2026-09-26'
_G = None
def gfull(c):
    global _G
    if _G is None: _G = json.load(open(H + '/data/gloss_full.json'))
    return _G.get(unicodedata.normalize('NFC', c))
SYSTEM = v4.SYSTEM
def build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, **kw):
    msgs, marks = v4.build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, **kw)
    u = msgs[1]['content']
    i = u.find('【詞典'); j = u.find('\n\n【', i + 1)
    if j < 0: j = u.find('\n\n請對', i + 1)
    chars = list(dict.fromkeys(x['c'] for c in marks.values() for x in c['cands']))
    lines = ['【詞典（各候選字的全部讀音與義項；生僻字取康熙字典原文）】']
    for ch in chars:
        g = gfull(ch)
        s = f"{ch}：{g['d']}〔{g['s']}〕" if g else f"{ch}：詞典未收"
        mv = dictlib.main_variants(ch, 4)
        if mv: s += '　主要異體：' + '、'.join(f"{x}〔{'/'.join(t[:2])}〕" for x, t in mv)
        lines.append('- ' + s)
    msgs[1] = {'role': 'user', 'content': u[:i] + '\n'.join(lines) + u[j:]}
    return msgs, marks
