"""muse 试点驱动：每对一次 muse exec（--output-schema schema.json，--max-model-steps 2），缓存复用 step6 harness 的 muse 调用层。
二分口径（CV 总管 09-27 定，七分类作废）：加 --binary → schema_bin.json，输出 variant_same_muse.jsonl / calib_bin_muse.jsonl。
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
SYS_BIN = """你是文字學與古籍校勘專家。只回答一個問題：這兩個字是不是**同一個字**（音義全同、只是寫法不同，可互換）。
- 異體字、簡繁字都算「是」（如 爲/為、旣/既、為/为、㠶/帆）；
- 音義不同的兩個字一律「否」，不管字形多像（如 己/已、日/曰、橋/櫃），也不管是否古今分化（如 莫/暮 算「否」）；
- 看不準就答「拿不准」，**不許猜**。
另外單獨標一個 tongjia：兩字在古書中有公認的通假關係（本字與借字，如 早/蚤）就填 true，否則 false；它與「是不是同一個字」無關（通假字是兩個不同的字）。
canonical：若是同一個字，填正字（通行規範字）是 a 還是 b，否則 null。basis：40 字以內的依據，說明出自哪部字書或你的學識。
所附「詞典來源標籤」只是參考，不是答案；上下文來自刻本機器識別，【?】處是兩字之一。"""
MODE = {'sys': None, 'schema': 'schema.json'}

def one(r):
    u = f"a：{r['a']}\nb：{r['b']}\n詞典來源標籤：{'、'.join(r.get('tags') or []) or '（無）'}\n本書出現上下文：{'；'.join(r.get('ctx') or []) or '（無）'}"
    out = harness.call_muse('muse', [{'role': 'system', 'content': MODE['sys'] or SYS}, {'role': 'user', 'content': u}], None, H + '/' + MODE['schema'])
    js = harness.parse(out.get('text', '')) if out.get('text') else None
    return dict(r, muse=js, error=out.get('error'), cached=bool(out.get('cached')))
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('n'); ap.add_argument('--workers', type=int, default=6); ap.add_argument('--out')
    ap.add_argument('--binary', action='store_true', help='二分口径（CV 总管 09-27 定）：是否同一个字 + 可选通假标记')
    a = ap.parse_args()
    if a.binary: MODE.update(sys=SYS_BIN, schema='schema_bin.json')
    rows = [json.loads(l) for l in open(os.path.join(H, a.inp))]
    if a.n != 'all': rows = rows[:int(a.n)]
    outp = a.out or (('calib' if a.inp.startswith('calib') else 'variant_same') + ('_bin' if a.binary else '') + '_muse.jsonl') if a.binary else \
        (a.out or ('calib_muse.jsonl' if a.inp.startswith('calib') else 'variant_relation_muse.jsonl'))
    with cf.ThreadPoolExecutor(a.workers) as ex: res = list(ex.map(one, rows))
    with open(os.path.join(H, outp), 'w') as f:
        for r in res: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    ok = [r for r in res if r['muse']]
    import collections
    print(outp, '条数', len(res), '成功', len(ok), '新调用', sum(1 for r in res if r['muse'] and not r['cached']), '失败', len(res) - len(ok),
          collections.Counter(r['muse'].get('same_char') or r['muse'].get('relation') for r in ok).most_common(),
          '通假标记', sum(1 for r in ok if r['muse'].get('tongjia')))
