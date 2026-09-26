"""提示词 v2（相对 v1 三处改动）：
1. 候选先按词典确定性分「關聯組」（直接異體或經同一第三字兩跳相連），以組為單位呈現；
2. 排除規則收緊：與「此處讀得通的詞」同一關聯組的候選，不得以「文意不通」排除（只能拆組並給出非文意理由）；
3. 整理本放最後並加一條硬規則：整理本與刻本候選不同時，不得僅據整理本排除刻本候選。"""
from . import v1
VERSION = 'v2-2026-09-26'
SYSTEM = v1.SYSTEM.replace('判斷要求：', '''候選已按詞典預先分成「關聯組」：同組的字在詞典裡互為異體、古今字、簡繁或俗正（含經同一個字間接相連）。詞典關聯有噪聲（例如「义」既是「義」的簡體又是「叉」的古寫，會把兩個詞連到一組），所以你可以拆組，但須說明理由。

判斷要求：''').replace('1. 排除（drop）：', '''0. 硬規則：若某關聯組裡有一個字在此處讀得通，則同組其他字**不得以「文意不通」為由排除**——刻本可能就刻作它的異體。整理本與刻本候選不同時，**不得僅據整理本排除刻本候選**；整理本改字是常態。
1. 排除（drop）：''')
def build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=True, min_ctx=300):
    msgs, marks = v1.build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=with_ref, min_ctx=min_ctx)
    u = msgs[1]['content']
    head, rest = u.split('【待判字位與候選】', 1)
    cand_part, tail = rest.split('【詞典', 1)
    lines = []
    for m, c in marks.items():
        src = {x['c']: x['src'] for x in c['cands']}
        gs = dictlib.group_cands([x['c'] for x in c['cands']])
        lines.append(f'{m}：')
        for gi, (mem, why) in enumerate(gs):
            s = '，'.join(f"{ch}（{'、'.join(src[ch]) or '其他'}）" for ch in mem)
            lines.append(f"　{chr(65+gi)}組：{s}" + (f'　〔{why}〕' if why else ''))
    SYSTEM2 = SYSTEM
    return [{'role': 'system', 'content': SYSTEM2}, {'role': 'user', 'content': head + '【待判字位與候選（按詞典關聯分組）】\n' + '\n'.join(lines) + '\n\n【詞典' + tail}], marks
