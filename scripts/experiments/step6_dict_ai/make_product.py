"""Step6-AI 产物（方案-词典加AI接入管线 §三）：把同一配置的 ≥1 次运行（harness runs/*.json）合成逐格证据 JSONL。
每格：img（图像共识/库首选/OCR首选）、groups（严格异体分组）、ai{runs, drop（各次都排除才记）, rank（按组，p 取各次均值）,
confidence（取最低档）, need_human, conflict_with_img（任一次首组不含图像共识）, disagree（各次首组不一致）, fingerprint}。
异步外包流程：harness --export → 常驻会话跑 muse（harness 缓存）→ 本脚本合产物 → 管线导回（接口另案）。
用法：python3 make_product.py --cells fullbook-hard --prompt v4n --out product_step6_ai_bxgb.jsonl runs/fb_a.json runs/fb_b.json"""
import json, os, sys, argparse, hashlib, unicodedata, collections
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import harness, dictlib
N = lambda x: unicodedata.normalize('NFC', x)
def fp(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()[:12] if os.path.exists(path) else None
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('runs', nargs='+'); ap.add_argument('--cells', default='human')
    ap.add_argument('--prompt', required=True); ap.add_argument('--model', default='muse'); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    harness.use_cells(a.cells)
    R = [{r['key']: r for r in json.load(open(p))['rows']} for p in a.runs]
    finger = {'model': a.model, 'prompt': a.prompt, 'runs': [os.path.basename(p) for p in a.runs],
              'dict': {'variants': fp(harness.CV_ROOT + '/config/variants/variants.json'), 'gloss': fp(harness.CV_ROOT + '/config/gloss/gloss.json')},
              'names': fp(H + '/data/names_auto.json') if a.prompt.startswith('v5') else None}
    CONF = {'高': 3, '中': 2, '低': 1}
    n = collections.Counter()
    with open(a.out, 'w') as f:
        for k, c in harness.CELLS.items():
            rows = [r[k] for r in R if k in r and r[k].get('ans')]
            cands = [N(x['c']) for x in c['cands']]
            lib = [N(x['c']) for x in c['cands'] if '库首选' in x['src']]; ocr = [N(x['c']) for x in c['cands'] if 'OCR第1' in x['src']]
            img = {'consensus': lib[0] if lib and ocr and lib[0] == ocr[0] else None, 'lib_top': lib[0] if lib else None, 'ocr_top': ocr[0] if ocr else None}
            groups = [{'id': chr(65 + i), 'members': m, 'why': w} for i, (m, w) in enumerate(dictlib.group_cands(cands, strict=True))]
            rec = {'key': k, 'img': img, 'groups': groups, 'ai': None}
            if rows:
                gid = {m: g['id'] for g in groups for m in g['members']}
                drops = [set(N(x) for x in (r['ans'].get('drop') or []) if isinstance(x, str)) for r in rows]
                P = collections.defaultdict(list); tops = []; whys = {}
                for r in rows:
                    G = [g for g in r['ans'].get('groups') or [] if isinstance(g, dict)]
                    for g in G:
                        ids = sorted({gid.get(N(m), '?') for m in g.get('members') or [] if isinstance(m, str)})
                        key = '+'.join(ids); P[key].append(float(g.get('p') or 0)); whys.setdefault(key, g.get('why', ''))
                    if G: tops.append(frozenset(N(m) for m in max(G, key=lambda g: float(g.get('p') or 0)).get('members') or []))
                rank = sorted(({'group': g, 'p': round(sum(v) / len(rows), 3), 'why': whys[g]} for g, v in P.items()), key=lambda x: -x['p'])
                conf = min((r['ans'].get('confidence') for r in rows), key=lambda x: CONF.get(x, 0))
                rec['ai'] = {'runs': len(rows), 'drop': sorted(set.intersection(*drops)) if drops else [],
                             'rank': rank, 'confidence': conf, 'need_human': '；'.join(sorted({r['ans'].get('need_human') or '' for r in rows} - {''})),
                             'conflict_with_img': bool(img['consensus']) and any(img['consensus'] not in t for t in tops),
                             'disagree': len(set(tops)) > 1, 'fingerprint': finger}
                n['问过'] += 1; n['首组不一致'] += rec['ai']['disagree']; n['与图像相左'] += rec['ai']['conflict_with_img']
            f.write(json.dumps(rec, ensure_ascii=False) + '\n'); n['格'] += 1
    print(a.out, dict(n))
if __name__ == '__main__':
    main()
