"""提示词 v1：按天批量；候选+来源+词典（释义、候选间异体关系、主要异体）；整理本单列并警示。"""
import json, os
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENDING = set(json.load(open(H + '/data/cells_human1135.json')))
VERSION = 'v1-2026-09-26'
SYSTEM = """你是宋代文献与古籍版本的校勘专家。任务：为清乾隆知不足齋叢書本、樓鑰《北行日錄》（乾道五年至六年，隨汪大猷使金賀正旦的日記）的刻本逐字識別結果做「上下文裁決」。

背景：
- 刻本圖像已經過字形匹配與 OCR，每個待判字位給出若干候選字；正確答案幾乎總在候選之中。你**看不到圖像**，只能依據上下文、詞典與你的學識判斷。
- 我們要的是**刻本在這一格實際刻的字形**，不是它的現代通行寫法。清代刻本常用異體字、俗字、古字、通假字，甚至形近訛字；現代整理本則常把它們改成通行字、或改字。
- 因此「文意上讀不通」不足以排除一個候選：若它是某個讀得通的字的異體／俗寫／古字／通假，刻本完全可能就刻作它。
- 候選之間若表示同一個詞（互為異體、簡繁、俗正），你無法也不需要在其中挑選——字形交給圖像證據，你只需把它們歸為一組。

判斷要求：
1. 排除（drop）：只有當某候選在此處**既不能直接講通、也不是任何講得通之字的異體／俗寫／古字／通假**時才排除。拿不準一律保留。把正確答案排除是最嚴重的錯誤。
2. 分組（groups）：把保留的候選按「在此處表示的是同一個詞」分組；每組給出此處是該詞的概率 p（各組 p 之和為 1），並說明理由。
3. 理由要具體：引用上下文、詞典條目（注明來源），或明確說「據本人學識」。人名、地名、官名、干支、日期、數字尤其要依據上下文前後呼應。
4. confidence：高／中／低。高＝你確信首組正確、不需要人看；否則說明 need_human 的原因。
5. 只能在候選中選，不得新增候選外的字。

輸出 JSON（不要多餘文字）：
{"items":[{"pos":"①","drop":["字",...],"drop_why":{"字":"理由"},"groups":[{"members":["字",...],"word":"此處的詞義","p":0.97,"why":"理由"}],"confidence":"高","need_human":""}]}"""

def ctx_text(keys, txt, i0, i1, marks_at):
    out = []
    for i in range(i0, i1):
        k = keys[i]
        if k in marks_at: out.append(marks_at[k])
        elif k in PENDING: out.append('▢')
        else: out.append(txt[i])
    return ''.join(out)

def build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=True, min_ctx=300):
    day = DAYS[d]
    marks = {MARK[i]: c for i, c in enumerate(ask)}
    marks_at = {c['key']: m for m, c in marks.items()}
    i0, i1 = day['i0'], day['i1']
    # 太短就向前后各补整天，直到够 min_ctx 字
    a, b = d, d
    while DAYS[b]['i1'] - DAYS[a]['i0'] < min_ctx and (a > 0 or b < len(DAYS) - 1):
        if a > 0: a -= 1
        if DAYS[b]['i1'] - DAYS[a]['i0'] < min_ctx and b < len(DAYS) - 1: b += 1
    parts = []
    if a < d: parts.append('【前文】' + ctx_text(keys, txt, DAYS[a]['i0'], i0, {}))
    parts.append('【本日（待判字位以圈號標出，▢ 為其他未定字）】' + ctx_text(keys, txt, i0, i1, marks_at))
    if b > d: parts.append('【後文】' + ctx_text(keys, txt, i1, DAYS[b]['i1'], {}))
    lines = ['\n'.join(parts), '', '【待判字位與候選】']
    allchars = []
    for m, c in marks.items():
        cs = '；'.join(f"{x['c']}（{'、'.join(x['src']) or '其他'}）" for x in c['cands'])
        lines.append(f'{m}：{cs}')
        allchars += [x['c'] for x in c['cands']]
        rel = dictlib.pair_relations([x['c'] for x in c['cands']])
        if rel: lines.append('　候選間詞典關係：' + '；'.join(rel))
    lines += ['', '【詞典（各候選字的首義項與主要異體；釋義只收首義項，多義字請結合你的學識）】']
    for ch in dict.fromkeys(allchars):
        g = dictlib.gloss(ch) or f'{ch}：詞典未收'
        mv = dictlib.main_variants(ch, 4)
        if mv: g += '　主要異體：' + '、'.join(f"{x}〔{'/'.join(s[:2])}〕" for x, s in mv)
        lines.append('- ' + g)
    if with_ref:
        lines += ['', '【現代整理本對應段落（僅供參考）】', '注意：這是現代排印整理本（《攻媿集》點校本），**常把刻本的異體改成通行字，也有改字、刪字、錄錯**；清刻本又系統改動了「虜、夷」等字眼。它只能證明文意，不能證明刻本字形。', day['ref']]
    lines += ['', f'請對 {"、".join(marks)} 共 {len(marks)} 個字位作答。']
    return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': '\n'.join(lines)}], marks
