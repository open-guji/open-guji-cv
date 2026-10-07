"""导出「待标」样本：基线重放里仍待审、且属于 margin 不足／仅库 unsure／对齐改字 三类的格，附证据特征。
用法：python pending_samples.py <重放 seed_admit 产物根> <快照 products 根> <book> <输出.jsonl>
这三类在现有看图结论里没有任何样本（看图结论只覆盖已放行格），阈值无法标定；
拿这份清单去看图（整理侧 sheet16 / 对照图），回填 ok／wrong 后即可标定。"""
import json, sys
from lib import load_step
from cls import cls_of
prod, src, book, out = sys.argv[1:5]
sa = load_step(prod, book, 'seed_admit'); gm = load_step(src, book, 'glyph_match')
cd = load_step(src, book, 'context_decide'); al = load_step(src, book, 'align_ref')
ci = load_step(src, book, 'cell_shrink')
n = 0
with open(out, 'w', encoding='utf-8') as f:
    for k, r in sa.items():
        if r['admit']:
            continue
        c = cls_of(r)
        if c not in ('margin不足', '仅库unsure', '对齐改字'):
            continue
        g = gm[k]; d = cd[k]; a = al.get(k, {}); cand = g['candidates']
        f.write(json.dumps(dict(
            id=k, cls=c, doubts=r['doubts'], lib_top=[(x, y) for x, y in cand[:4]], cov=g['cov'],
            verdict=g['verdict'], ref=a.get('align_char'), ref_op=a.get('align_op'),
            ctx_margin=d['margin'], ctx_top=[x for x, _ in d['ranked'][:3]],
            ink=ci.get(k, {}).get('ink_ratio'), flags=ci.get(k, {}).get('flags'),
            label=None), ensure_ascii=False) + '\n')
        n += 1
print(n)
