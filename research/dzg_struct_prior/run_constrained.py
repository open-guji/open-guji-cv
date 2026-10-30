"""在真管线里跑「daizhige 格位约束」的 Step3→Step4（只在本进程 monkeypatch，不改仓里代码）。

用法：python run_constrained.py --pen 0.5 -- <guji pipeline 的参数…>
做三件事：
  1. feedback.lookup 的 resolved_forced_jiazhu / resolved_forced_main 换成 daizhige 给的夹注格 / 正文格；
  2. column_gate 产物读出来时把 n_raised_hint 改成 daizhige 的出格级数（抬头列 top_slack 开到顶）；
  3. row_segment.segment_column 包一层：按 forced 集合算「第 k 格该空/该有字」掩码，换上带罚分的 DP。
"""
import json, os, sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE))
args = sys.argv[1:]
PEN = 0.5
if args and args[0] == '--pen':
    PEN = float(args[1]); args = args[2:]
if args and args[0] == '--':
    args = args[1:]
os.environ['CONSTRAINED_PEN'] = str(PEN)

import structcmp as SC
from open_guji_cv.feedback import lookup as LK
from open_guji_cv.steps import row_segment as RS
from open_guji_cv.core import step as CS
from open_guji_cv.books.siku_zongmu import row_boundaries as RB

# ── daizhige 期望表：(book, page, col) → E ──
_recs = SC.load_dzg()
EXP = {}
for ln in open(SC.DZ / 'page_map.jsonl', encoding='utf-8'):
    m = json.loads(ln)
    if m['kind'] != 'text' or m.get('dzg_kind') != 'full':
        continue
    rec = _recs[m['dzg_id']]
    for c in rec.get('cols', []):
        if (c['no'] >= 9) == bool(m['side']):
            E = SC.expected(c)
            if E:
                EXP[(m['vol'], m['page'], c['no'] % 9 + 1)] = E


def _by(book, want_note):
    out = {}
    for (b, pg, col), E in EXP.items():
        if b != book:
            continue
        if want_note:
            s = {sl for sl, u in E if u == 'a' and (sl, 'b') in E}
        else:
            s = {sl for sl, u in E if u is None}
        if s:
            out[(pg, col)] = s
    return out


def _occupied(book, pg, col):
    E = EXP.get((book, pg, col))
    return None if E is None else {sl for sl, _ in E}


if os.environ.get('CONSTRAINED_NOFORCE') != '1':
    LK.resolved_forced_jiazhu = lambda book_id, *a, **k: _by(book_id, True)
    LK.resolved_forced_main = lambda book_id, *a, **k: _by(book_id, False)

# ── 抬头级数：改 gate 产物 ──
_orig_product = CS.RunContext.product


def _product(self, kind_id, page):
    obj = _orig_product(self, kind_id, page)
    if kind_id == 'gate_manifest' and obj is not None:
        for gc in obj.columns:
            E = EXP.get((self.book.id, page, gc.col))
            if E is None:
                continue
            neg = [s for s, _ in E if s < 0]
            nr = -min(neg) if neg else 0
            if os.environ.get('CONSTRAINED_RAISE_EXACT') == '1':
                gc.n_raised_hint = nr
                if nr:
                    gc.top_slack = gc.border_top
            elif nr > (gc.n_raised_hint or 0):
                gc.n_raised_hint = nr
                gc.top_slack = gc.border_top
    return obj


if os.environ.get('CONSTRAINED_NORAISE') != '1':
    CS.RunContext.product = _product
CUR = {}
_orig_rs_run = RS.RowSegmentStep.run_page


def _rs_run(self, ctx, page):
    CUR['book'] = ctx.book.id; CUR['page'] = page; CUR['col'] = None
    orig_image = ctx.image

    def image(kind_id, key, *a, **k):
        if kind_id == 'column_image':
            CUR['col'] = int(str(key).split('c')[-1])
        return orig_image(kind_id, key, *a, **k)

    ctx.image = image
    try:
        return _orig_rs_run(self, ctx, page)
    finally:
        ctx.image = orig_image


RS.RowSegmentStep.run_page = _rs_run

# ── 带掩码的 DP ──
import constrained_dp as CD   # noqa: E402  （与 constrained.py 同一份源码替换）
_orig_seg = RS.segment_column


def _seg(img, *a, **kw):
    col = CUR.get('col')
    CUR['occ'] = _occupied(CUR.get('book'), CUR.get('page'), col) if col else None
    occ = CUR.get('occ')
    if not occ or os.environ.get('CONSTRAINED_NOMASK') == '1':
        return _orig_seg(img, *a, **kw)
    n_body, n_raised = kw['n_body_slots'], kw['n_raised']
    mask = []
    for pos in range(1, n_body + n_raised + 1):
        slot = pos - n_raised - 1 if pos <= n_raised else pos - n_raised
        mask.append(slot not in occ)
    CD.MASK['m'] = mask
    RB._bounded_elastic_dp = CD.masked
    try:
        return _orig_seg(img, *a, **kw)
    finally:
        CD.MASK['m'] = None
        RB._bounded_elastic_dp = CD.ORIG


RS.segment_column = _seg

if os.environ.get('CONSTRAINED_KIND') == 'narrow':
    # 窄规则：只管「列端、扁而宽、像一道横线」的格——一与框线二选一，交给转写
    from open_guji_cv.steps import cell_shrink as CSH
    _orig_cs = CSH.CellShrinkStep.run_page

    def _phys(s):
        return s - 1 if s > 0 else s

    def _cs_run(self, ctx, page):
        out = _orig_cs(self, ctx, page)
        cells = ctx.product('cells', page)
        P = cells.period or 115.0
        for c in out['char_index'].columns:
            E = EXP.get((ctx.book.id, page, c.col))
            if not E:
                continue
            ps = [_phys(s) for s, _ in E]; lo, hi = min(ps), max(ps)
            colw = max((r.bbox_col[2] for r in c.chars), default=0) - min((r.bbox_col[0] for r in c.chars), default=0)
            for r in c.chars:
                if r.sub:
                    continue
                x0, y0, x1, y1 = r.bbox_col
                flat = (y1 - y0) < 0.35 * P and (x1 - x0) > 1.5 * (y1 - y0)
                if not flat:
                    continue
                key = (r.slot, None); ph = _phys(r.slot)
                at_end = ph <= lo or ph >= hi
                if r.cell_type == 'char' and key not in E and (ph < lo or ph > hi):
                    r.cell_type = 'empty'; r.flags.append('ref_blank')
                elif r.cell_type == 'empty' and key in E and at_end and any(f in r.flags for f in ('tail_junk', 'sliver')):
                    r.cell_type = 'char'; r.flags.append('ref_char')
        return out

    CSH.CellShrinkStep.run_page = _cs_run

if os.environ.get('CONSTRAINED_KIND') == '1':
    from open_guji_cv.steps import cell_shrink as CSH
    _orig_cs = CSH.CellShrinkStep.run_page

    def _cs_run(self, ctx, page):
        out = _orig_cs(self, ctx, page)
        for c in out['char_index'].columns:
            E = EXP.get((ctx.book.id, page, c.col))
            if E is None:
                continue
            for r in c.chars:
                key = (r.slot, r.sub)
                if r.cell_type == 'char' and key not in E:
                    r.cell_type = 'empty'; r.flags.append('ref_blank')
                elif r.cell_type == 'empty' and key in E and any(f in r.flags for f in ('tail_junk', 'sliver')):
                    r.cell_type = 'char'; r.flags.append('ref_char')
        return out

    CSH.CellShrinkStep.run_page = _cs_run

from open_guji_cv.cli_v2 import main  # noqa: E402
main(args)
