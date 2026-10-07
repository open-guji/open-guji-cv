from lib import *
import collections,re
def cls_of(r):
    d=r['doubts']; s=' '.join(d)
    if 'occluded' in d: return '印章遮挡'
    if 'ji_yi_si_ctx_review' in d or any(x in d for x in('ji_yi_si_review',)): return '己已巳'
    if '库里没有这个字' in d or 'ctx_garble_shape' in d or 'ctx_garble_rare' in d: return '库里没有/乱码形'
    if 'context_vs_ref' in d or 'iron_vs_ref' in d: return '与整理本冲突'
    if 'replace_align' in d: return '对齐改字'
    if 'near_form' in d or any('护栏' in x for x in d): return '形近/护栏'
    if 'shadow_veto' in d: return 'shadow_veto'
    if any('margin 不足' in x for x in d): return 'margin不足'
    if any(x.startswith('库 unsure') for x in d): return '仅库unsure'
    return '其它:'+s[:30]
