"""row_boundaries._bounded_elastic_dp 的替身：源码替换，加「第 k 格该空 / 该有字」软罚分。"""
import inspect, os, textwrap
import numpy as np
from open_guji_cv.books.siku_zongmu import row_boundaries as RB

MASK = {'m': None}
PEN = float(os.environ.get('CONSTRAINED_PEN', '0.5'))
ORIG = RB._bounded_elastic_dp

_src = textwrap.dedent(inspect.getsource(ORIG))
_src = _src.replace('def _bounded_elastic_dp(', 'def masked(', 1)
reps = [
    ("                dp_cost[0, m] = c + ink_lam * ink + eps + drop_cost_0",
     "                dp_cost[0, m] = c + ink_lam * ink + eps + drop_cost_0 + _pen(0, v0, y)"),
    ("            tot = dp_cost[k - 1][:, None] + C\n",
     "            tot = dp_cost[k - 1][:, None] + C + (PK[k] if PK is not None else 0.0)\n"),
    ("    col_idx = np.arange(m_count)\n",
     "    col_idx = np.arange(m_count)\n"
     "    _mk = _MASK['m']\n"
     "    def _charrows(ya, yb):\n"
     "        return _dropped_rows(ya, yb) / period if drop_lam > 0 else 0.0\n"
     "    PK = None\n"
     "    if _mk is not None and len(_mk) == n_slots:\n"
     "        Bm = np.zeros((m_count, m_count), dtype=bool)\n"
     "        Mm = np.zeros((m_count, m_count))\n"
     "        for m in range(m_count):\n"
     "            for mp in range(m):\n"
     "                if np.isfinite(C[mp, m]):\n"
     "                    Bm[mp, m] = _is_blank(mid_y[mp], mid_y[m])\n"
     "                    Mm[mp, m] = _charrows(mid_y[mp], mid_y[m])\n"
     "        PB = _PEN * np.minimum(1.0, Mm / _MASS_FULL)\n"
     "        PC = _PEN * Bm\n"
     "        PK = [None] * n_interior\n"
     "        for k in range(1, n_interior):\n"
     "            PK[k] = PB if _mk[k] else PC\n"
     "    def _pen(k, ya, yb):\n"
     "        if _mk is None or len(_mk) != n_slots:\n"
     "            return 0.0\n"
     "        if _mk[k]:\n"
     "            return _PEN * min(1.0, _charrows(ya, yb) / _MASS_FULL)\n"
     "        return _PEN * _is_blank(ya, yb)\n"),
    ("                total = dp_cost[k_last, m] + c + drop_cost_N[vN]",
     "                total = dp_cost[k_last, m] + c + drop_cost_N[vN] + _pen(n_slots - 1, y, vN)"),
]
for a, b in reps:
    assert _src.count(a) == 1, ('源码替换没命中', a[:60])
    _src = _src.replace(a, b)
_ns = dict(RB.__dict__); _ns.update(_MASK=MASK, _PEN=PEN, _MASS_FULL=float(os.environ.get('CONSTRAINED_MASS', '0.05')))
exec(compile(_src, '<masked_dp>', 'exec'), _ns)
masked = _ns['masked']
