"""把 structcmp 的错列归到用户说的四类问题上，基线 / 约束版并排。

用法：python analyze.py <base.json> <con.json> <wsBase> <wsCon> [--exclude-pages vol:p,...]
归因（只看与转写的差）：
  劈字（①）      多出的格落在本列字段内部（首字格与末字格之间）
  首末带框/渣（③）多出的格在首字之上或末字之下
  丢字           少了格（含列首/列尾「一」被当渣）
  夹注（④）      note_missed / note_false / note_count / note_shift
  格号平移       offset_only：字、类型、顺序都对，只是格号整体错位（抬头判错）
  整列失败 / 空列有字 另计
"""
import json, sys, collections

PROBLEM = ['劈字①', '首末渣③', '丢字', '夹注④', '格号平移', '空列有字', '整列失败', '混合']


def phys(s):
    return s - 1 if s > 0 else s


def locus(r):
    k = r['kind']
    if k == 'offset_only':
        return '格号平移'
    if k.startswith('note'):
        return '夹注④'
    if k == 'col_fail':
        return '整列失败'
    if r['ck'] == 'empty':
        return '空列有字'
    if k == 'under_lost':
        return '丢字'
    if k == 'over_split':
        E_slots = set()
        # 期望格 = (预测格 − 只在预测) ∪ 只在期望
        # 这里只有差集，用 only_P 相对「期望字段范围」判断：范围从 text 推不出，改用 nE 与 only_E/only_P
        return None
    return '混合'


_PC = {}


def _cells(ws, vol, page, col):
    key = (ws, vol, page)
    if key not in _PC:
        f = f'{ws}/products/{vol}/cell_shrink/p{page:04d}.json'
        _PC[key] = {c['col']: c for c in json.load(open(f))['char_index']['columns']}
    return [r for r in _PC[key][col]['chars'] if r['cell_type'] == 'char']


def split_like(ws, r, period=115.0):
    """多出的格与相邻字格合起来像不像一个字：间隙小、合高 ≤1.2 格、两者都矮。"""
    cs = sorted(_cells(ws, r['vol'], r['page'], r['col']), key=lambda c: (c['bbox_col'][1]))
    extra = {(s, u) for s, u in r['only_P']}
    for i, c in enumerate(cs):
        if (c['slot'], c.get('sub')) not in extra or c.get('sub'):
            continue
        y0, y1 = c['bbox_col'][1], c['bbox_col'][3]
        for j in (i - 1, i + 1):
            if 0 <= j < len(cs) and not cs[j].get('sub'):
                a0, a1 = cs[j]['bbox_col'][1], cs[j]['bbox_col'][3]
                gap = max(a0, y0) - min(a1, y1)
                span = max(a1, y1) - min(a0, y0)
                if gap < 0.2 * period and span <= 1.2 * period and (y1 - y0) < 0.75 * period:
                    return True
    return False


def classify_rows(rows, Eranges, ws):
    out = []
    for r in rows:
        l = locus(r)
        if l is None:
            if r['only_E']:
                l = '混合'
            else:
                l = '劈字①' if split_like(ws, r) else '首末渣③'
        out.append((r, l))
    return out


def eranges():
    sys.path.insert(0, '.')
    import structcmp as SC
    recs = SC.load_dzg(); R = {}
    for ln in open(SC.DZ / 'page_map.jsonl', encoding='utf-8'):
        m = json.loads(ln)
        if m['kind'] != 'text' or m.get('dzg_kind') != 'full':
            continue
        for c in recs[m['dzg_id']].get('cols', []):
            if (c['no'] >= 9) == bool(m['side']):
                E = SC.expected(c)
                if E:
                    ps = [phys(s) for s, _ in E]
                    R[(m['vol'], m['page'], c['no'] % 9 + 1)] = (min(ps), max(ps))
    return R


def main():
    b, c = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
    excl = set()
    if '--exclude-pages' in sys.argv:
        for x in sys.argv[sys.argv.index('--exclude-pages') + 1].split(','):
            v, p = x.split(':'); excl.add((v, int(p)))
    R = eranges()
    n = sum(b['total'].values())
    tabs = {}
    wss = {'基线': sys.argv[3], '约束': sys.argv[4]}
    for name, d in (('基线', b), ('约束', c)):
        rows = [r for r in d['rows'] if (r['vol'], r['page']) not in excl]
        cl = classify_rows(rows, R, wss[name])
        tabs[name] = collections.Counter(l for _, l in cl)
        tabs[name + '_rows'] = cl
    bad_b = sum(tabs['基线'].values()); bad_c = sum(tabs['约束'].values())
    print(f'列 {n}（排除页 {len(excl)}）：逐格全对 基线 {1 - bad_b / n:.4f} → 约束 {1 - bad_c / n:.4f}')
    print(f"{'类':8s} {'基线':>6s} {'约束':>6s}")
    for k in PROBLEM:
        print(f'{k:8s} {tabs["基线"][k]:6d} {tabs["约束"][k]:6d}')
    # 字数口径（与另一对话 eval_column_counts 同：只比字数）
    for name, d in (('基线', b), ('约束', c)):
        cnt_bad = sum(1 for r in d['rows'] if r['nE'] != r['nP'] and (r['vol'], r['page']) not in excl)
        print(f'字数口径 {name}：{1 - cnt_bad / n:.4f}')
    kb = {(r['vol'], r['page'], r['col']) for r in b['rows']}
    kc = {(r['vol'], r['page'], r['col']) for r in c['rows']}
    print('修好', len(kb - kc), '改坏', len(kc - kb), '两边都错', len(kb & kc))
    json.dump({k: [(r['vol'], r['page'], r['col'], l) for r, l in v] for k, v in tabs.items() if k.endswith('_rows')},
              open('analyze_out.json', 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()
