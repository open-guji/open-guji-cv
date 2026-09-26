"""从整理本抽本书专名表（人名／地名／官名机构／书名／其他）→ data/names.json。
整理本是证人不是人审结果，拿来当 Step6 的输入不违反「不看人审」。抽取用 muse（harness.call）。
每条专名按整理本原文精确计数；只出现在模型输出、原文里找不到的丢掉（防编造）。"""
import json, os, re, sys, collections, concurrent.futures as cf
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import harness
from parse_bxgb_wiki import WS
raw = open(WS + '/corpus/beixingrilu_jiaoduiben.txt', encoding='utf-8').read()
lines = [l for l in raw.split('\n') if not re.fullmatch(r'\s*\d+\s*', l)]
ref = ''.join(lines)
SYS = """你是宋史與宋金關係史專家。下面是樓鑰《北行日錄》（乾道五年隨汪大猷使金賀正旦）現代點校本的一段。
請窮盡列出其中出現的全部專名：人名（含字號、官稱連姓的稱呼如「汪尚書」也列）、地名（州縣、驛館、山川、寺觀、橋、門、殿閣）、官名與機構名、書名篇名、年號與其他專名。
要求：每條必須是原文中逐字出現的字串；不要改字、不要補字；同一專名的不同稱呼分列。
只輸出 JSON：{"names":[{"n":"專名","t":"人名|地名|官名機構|書名|其他","note":"簡注，如某人字某、屬何國"}]}"""
MODEL = sys.argv[1] if len(sys.argv) > 1 else 'muse'
CH = 1500
chunks = [ref[i:i + CH + 20] for i in range(0, len(ref), CH)]   # 20 字重叠，防专名被切断
def one(ch):
    out = harness.call(MODEL, [{'role': 'system', 'content': SYS}, {'role': 'user', 'content': ch}])
    js = harness.parse(out.get('text', '')) if out.get('text') else None
    if js is None and out.get('text'):
        try:
            import json_repair; js = json_repair.loads(out['text'])
        except Exception: js = None
    return (js or {}).get('names', []) if isinstance(js, dict) else []
with cf.ThreadPoolExecutor(3) as ex:
    res = list(ex.map(one, chunks))
agg = {}
for L in res:
    for e in L:
        n = re.sub(r'[\s，。、；：「」『』《》〈〉？！（）·【】]', '', str(e.get('n', '')))
        if len(n) < 2 or n not in ref: continue
        a = agg.setdefault(n, {'n': n, 't': e.get('t', '其他'), 'note': e.get('note', ''), 'count': ref.count(n)})
        if not a['note'] and e.get('note'): a['note'] = e['note']
names = sorted(agg.values(), key=lambda x: (-x['count'], x['n']))
json.dump({'source': '整理本（攻媿集点校本）', 'model': MODEL, 'names': names}, open(H + '/data/names.json', 'w'), ensure_ascii=False, indent=0)
print('chunks', len(chunks), '专名', len(names), collections.Counter(x['t'] for x in names).most_common())
print([f"{x['n']}{x['count']}" for x in names[:40]])
for q in ['石旦', '烏古倫', '汪大猷', '耶律成']: print(q, [x for x in names if q in x['n']][:3])
