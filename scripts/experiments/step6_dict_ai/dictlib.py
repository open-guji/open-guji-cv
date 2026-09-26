"""词典层：直接加载 cv 仓 variants.py（绕开包 __init__ 的 cv2 依赖）+ gloss.json。"""
import importlib.util, json, itertools, os
CV = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../..'))
spec = importlib.util.spec_from_file_location('gv', CV + '/open_guji_cv/variants.py')
V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
G = json.load(open(CV + '/config/gloss/gloss.json', encoding='utf-8'))
SRC = {'moe': '教育部重編國語辭典', 'kangxi': '康熙字典', 'wikt': '维基词典', 'unihan': 'Unihan(英文)'}
TAG = {'twedu': '教育部異體字字典', 'hydzd': '漢語大字典', 'yitizi': 'yitizi', 'dypytz': '第一批异体字整理表',
       'cjkvi-simplified': '简繁对照', 'hydzd-borrowed': '漢語大字典·通假', 'local:keben': '本项目刻本实证',
       'unihan:kSemanticVariant': 'Unihan语义异体', 'unihan:kZVariant': 'Unihan字形异体',
       'unihan:kSpecializedSemanticVariant': 'Unihan部分义项异体', 'unihan:kSpoofingVariant': 'Unihan形近(非异体)',
       'unihan:kSimplifiedVariant': 'Unihan简体', 'unihan:kTraditionalVariant': 'Unihan繁体'}
def gloss(c):
    g = G.get(c)
    if not g: return None
    s = g.get('d', '')
    return f"{c}（{g.get('p','')}{'，'+g['fq'] if g.get('fq') else ''}）{s}　〔{SRC.get(g.get('s'), g.get('s'))}〕"
def relation(a, b):
    """a,b 之间词典关系：返回 [(关系, 来源...)]"""
    out = []
    for x, tags in V.variants_of(a):
        if x == b:
            names = [TAG.get(t, t) for t in tags]
            kind = '通假' if all(t == 'hydzd-borrowed' for t in tags) else ('形近(非异体)' if all(t == 'unihan:kSpoofingVariant' for t in tags) else '异体/简繁')
            out.append((kind, names))
    return out
def main_variants(c, n=6):
    """c 的主要异体（桥接来源），给模型补全异体扩展用"""
    r = []
    for x, tags in V.variants_of(c):
        good = [t for t in tags if t in V.BRIDGE_SOURCES or t == 'hydzd-borrowed']
        if good: r.append((x, [TAG.get(t, t) for t in good]))
    r.sort(key=lambda t: -len(t[1]))
    return r[:n]
def pair_relations(chars):
    res = []
    for a, b in itertools.combinations(chars, 2):
        for kind, names in relation(a, b):
            res.append(f"{a}—{b}：{kind}（{'、'.join(names)}）")
    return res
if __name__ == '__main__':
    for c in '䣛厀旦且': print(gloss(c))
    print(pair_relations(['䣛', '厀', '膝', '邲']), pair_relations(['擔', '檐', '簷']))
    print(main_variants('檐'))

def _bridge_nb(c):
    return {x for x, tags in V.variants_of(c) if any(t in V.BRIDGE_SOURCES or t in ('cjkvi-simplified', 'unihan:kSimplifiedVariant', 'unihan:kTraditionalVariant', 'dypytz') for t in tags)}

WEAK = {'hydzd-borrowed', 'unihan:kSpoofingVariant', 'yitizi', 'unihan:kSpecializedSemanticVariant'}
def strict_variant(a, b):
    """严格异体：≥2 个独立来源（不含通假/形近/yitizi/部分义项），或本项目刻本实证。且—旦（仅 twedu）不算。"""
    if a == b: return True
    for x, tags in V.variants_of(a):
        if x == b:
            good = set(tags) - WEAK
            return 'local:keben' in good or len(good) >= 2
    return False

def _strict_nb(c):
    return {x for x, tags in V.variants_of(c) if 'local:keben' in tags or len(set(tags) - WEAK) >= 2}

def group_cands(chars, strict=False):
    """确定性分组：直接异体边，或经同一第三字（两跳）相连 → 同组。返回 [(members, 说明)]"""
    chars = list(dict.fromkeys(chars)); nb = {c: (_strict_nb(c) if strict else _bridge_nb(c)) for c in chars}
    par = {c: c for c in chars}; why = {}
    def f(x):
        while par[x] != x: x = par[x]
        return x
    for i, a in enumerate(chars):
        for b in chars[i + 1:]:
            if b in nb[a] or a in nb[b]:
                par[f(b)] = f(a); why.setdefault(f(a), []).append(f'{a}—{b}直接異體')
            else:
                via = (nb[a] & nb[b]) - {a, b}
                if via:
                    v = sorted(via)[0]; par[f(b)] = f(a); why.setdefault(f(a), []).append(f'{a}、{b}同為「{v}」的異體')
    G = {}
    for c in chars: G.setdefault(f(c), []).append(c)
    return [(m, '；'.join(why.get(r, []))) for r, m in G.items()]
