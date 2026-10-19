"""逐列结构比对：cell_shrink 产物的字格 (slot, sub) 集合 vs daizhige 逐列本给出的格位。

用法：python structcmp.py <products_dir> <vol,...> [--out out.json]
口径：daizhige 格位 pos（start 起算，-1/-2 是出格抬头）→ 我们的 slot：pos>=0 → pos+1，pos<0 → pos。
夹注 r（右行）→ sub a，l（左行）→ sub b，与 Step3 的 a=右子列 一致。
只比 page_map 里 kind=text、dzg_kind=full 的页。
"""
import json, os, sys, collections
from pathlib import Path

# 四庫總目工作区（guji-workspace 里那本书的目录）。daizhige 目录：GUJI_DZG 直接指定；否则按 corpus_dir 找
# （迁过中心库的工作区，corpus/ 在数据目录里）；都不行就退回工作区根下的 corpus/daizhige。
WS = Path(os.environ.get('GUJI_WS96', '../guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本'))


def _dz_dir() -> Path:
    if os.environ.get('GUJI_DZG'):
        return Path(os.environ['GUJI_DZG'])
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from open_guji_cv.core.workspace import corpus_dir
        d = corpus_dir(WS)
        if d is not None and (d / 'daizhige').is_dir():
            return d / 'daizhige'
    except Exception:
        pass
    return WS / 'corpus/daizhige'


DZ = _dz_dir()


def load_dzg():
    recs = {}
    for f in sorted(DZ.glob('000*.jsonl')):
        for ln in open(f, encoding='utf-8'):
            d = json.loads(ln)
            recs[d['id']] = d
    return recs


def slot_of(pos):
    return pos + 1 if pos >= 0 else pos


def expected(col):
    """一列 daizhige → {(slot, sub): 字}"""
    E = {}
    for r in col.get('runs', []):
        if r['t'] == 'text':
            for i, ch in enumerate(r['s']):
                E[(slot_of(r['start'] + i), None)] = ch
        elif r['t'] == 'note':
            for side, sub in (('r', 'a'), ('l', 'b')):
                for off, s in r.get(side, []):
                    for i, ch in enumerate(s):
                        E[(slot_of(r['start'] + off + i), sub)] = ch
    return E


def predicted(c):
    return {(r['slot'], r.get('sub')) for r in c['chars'] if r['cell_type'] == 'char'}


def phys(sl):
    return sl - 1 if sl > 0 else sl


def offset_only(Es, P):
    if not Es or len(Es) != len(P):
        return False
    a = sorted((phys(s), u or '') for s, u in Es); b = sorted((phys(s), u or '') for s, u in P)
    k = b[0][0] - a[0][0]
    return k != 0 and all(x[0] + k == y[0] and x[1] == y[1] for x, y in zip(a, b))


def classify(E, P, ok):
    Es = set(E)
    if Es == P:
        return 'exact'
    if offset_only(Es, P):
        return 'offset_only'            # 格位整体平移（抬头/起始格判错），字、类型、顺序都对
    if not ok:
        return 'col_fail'
    eb = {k for k in Es if k[1] is None}; en = Es - eb
    pb = {k for k in P if k[1] is None}; pn = P - pb
    if en and not pn:
        return 'note_missed'            # 夹注当正文 / 没拆
    if pn and not en:
        return 'note_false'             # 正文当夹注
    if en and pn and en != pn:
        if len(Es) == len(P):
            return 'note_shift'
        return 'note_count'
    # 夹注一致，只有正文差
    d = len(pb) - len(eb)
    if d > 0:
        return 'over_split'
    if d < 0:
        return 'under_lost'
    return 'shift'                      # 字数对、格位错（相位/起始格）


def main():
    prod = Path(sys.argv[1]); vols = sys.argv[2].split(',')
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None
    recs = load_dzg()
    pm = [json.loads(l) for l in open(DZ / 'page_map.jsonl', encoding='utf-8')]
    T = collections.Counter(); byvol = collections.defaultdict(collections.Counter)
    bykind = collections.defaultdict(collections.Counter)
    rows = []; pages_bad = collections.Counter(); missing = []; ncols = collections.Counter()
    for m in pm:
        if m['vol'] not in vols or m['kind'] != 'text' or m.get('dzg_kind') != 'full':
            continue
        f = prod / m['vol'] / 'cell_shrink' / f"p{m['page']:04d}.json"
        if not f.exists():
            missing.append((m['vol'], m['page'])); continue
        ci = json.loads(f.read_text())['char_index']
        rec = recs[m['dzg_id']]
        dcols = {c['no'] % 9 + 1: c for c in rec.get('cols', []) if (c['no'] >= 9) == bool(m['side'])}
        ours = {c['col']: c for c in ci['columns']}
        nbad = 0
        for col in range(1, 10):
            E = expected(dcols.get(col, {'runs': []}))
            c = ours.get(col)
            P = predicted(c) if c else set()
            k = classify(E, P, bool(c and c.get('ok')))
            ck = 'note' if any(s for _, s in E) else ('raised' if any(sl < 0 for sl, _ in E) else 'body')
            if not E:
                ck = 'empty'
            T[k] += 1; byvol[m['vol']][k] += 1; bykind[ck][k] += 1; ncols[f"{m['vol']}:{m['page']}"] += 1
            if k != 'exact':
                nbad += 1
                eb = sorted(E);
                rows.append(dict(vol=m['vol'], page=m['page'], col=col, kind=k, ck=ck,
                                 nE=len(E), nP=len(P),
                                 only_E=sorted([list(x) for x in set(E) - P], key=str),
                                 only_P=sorted([list(x) for x in P - set(E)], key=str),
                                 text=''.join(E[x] for x in sorted(E, key=lambda x: (x[0], x[1] or '')))))
        pages_bad[nbad] += 1
    n = sum(T.values())
    print(f'列 {n}，逐格全对 {T["exact"]} = {T["exact"]/max(n,1):.4f}')
    for k, v in T.most_common():
        print(f'  {k:12s} {v:6d} {v/n:.4%}')
    print('按册：')
    for v in vols:
        c = byvol[v]; nn = sum(c.values())
        if nn:
            print(f'  {v} {c["exact"]}/{nn} = {c["exact"]/nn:.4f}  ', dict(c.most_common()))
    print('按列型：')
    for k, c in bykind.items():
        nn = sum(c.values()); print(f'  {k} {c["exact"]}/{nn} = {c["exact"]/nn:.4f}  ', dict(c.most_common()))
    print('每页错列数分布：', sorted(pages_bad.items()))
    if missing:
        print('缺产物页：', len(missing), missing[:10])
    if out:
        json.dump(dict(total=dict(T), byvol={k: dict(v) for k, v in byvol.items()},
                       bykind={k: dict(v) for k, v in bykind.items()}, rows=rows,
                       pages_bad=dict(pages_bad), ncols=dict(ncols)), open(out, 'w'), ensure_ascii=False, indent=0)


if __name__ == '__main__':
    main()
