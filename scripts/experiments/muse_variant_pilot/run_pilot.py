"""muse 试点驱动：每对一次 muse exec（--output-schema schema.json，--max-model-steps 2），缓存复用 step6 harness 的 muse 调用层。
用法：python3 run_pilot.py pairs.jsonl 200 [--workers 6]   → variant_relation_muse.jsonl（追加/覆盖同对）
      python3 run_pilot.py calib.jsonl all                 → calib_muse.jsonl（自动真值校准集）"""
import json, os, sys, argparse, concurrent.futures as cf
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(H, '..', 'step6_dict_ai'))
import harness
SYS = """你是文字學與古籍校勘專家。判斷兩個漢字之間的關係，只憑字書常識（《說文》《玉篇》《廣韻》《集韻》《康熙字典》《漢語大字典》、教育部《異體字字典》等）。
關係只能選一種：
- 异体：同一個字的不同寫法，音義全同，可互換（如 爲/為、旣/既）；
- 通假：本字與借字，讀音相同或相近而義不同（如 早/蚤）；
- 形近易混：字形相近但音義不同的兩個字（如 己/已、日/曰）；
- 简繁：現行簡化字與傳統字（如 为/為）；
- 古今字：古字與後起分化字（如 莫/暮、然/燃）；
- 无关：以上都不是；
- 拿不准：看不準就選這個，**不許猜**。
canonical：若一方是正字（通行規範字）填 a 或 b，否則填 null。basis：40 字以內的依據。
所附「詞典來源標籤」只是參考，不是答案（例如教育部異體字字典也收古文 上~二，那不等於它們是一般異體）。所附上下文來自刻本機器識別，【?】處是兩字之一。"""
def one(r):
    u = f"a：{r['a']}\nb：{r['b']}\n詞典來源標籤：{'、'.join(r.get('tags') or []) or '（無）'}\n本書出現上下文：{'；'.join(r.get('ctx') or []) or '（無）'}"
    out = harness.call_muse('muse', [{'role': 'system', 'content': SYS}, {'role': 'user', 'content': u}], None, H + '/schema.json')
    js = harness.parse(out.get('text', '')) if out.get('text') else None
    return dict(r, muse=js, error=out.get('error'), cached=bool(out.get('cached')))
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('n'); ap.add_argument('--workers', type=int, default=6); ap.add_argument('--out')
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(os.path.join(H, a.inp))]
    if a.n != 'all': rows = rows[:int(a.n)]
    outp = a.out or ('calib_muse.jsonl' if a.inp.startswith('calib') else 'variant_relation_muse.jsonl')
    with cf.ThreadPoolExecutor(a.workers) as ex: res = list(ex.map(one, rows))
    with open(os.path.join(H, outp), 'w') as f:
        for r in res: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    ok = [r for r in res if r['muse']]
    import collections
    print(outp, '条数', len(res), '成功', len(ok), '新调用', sum(1 for r in res if r['muse'] and not r['cached']), '失败', len(res) - len(ok),
          collections.Counter(r['muse']['relation'] for r in ok).most_common())
