"""线上取框／整字判法（`ids_online.SPECS` 里 whole=hog|pix 的组）的诚实复核：配置固定为线上的（特征、尺寸、区域、λ），
只看门槛。①线上门槛下按册留一的错数；②嵌套门槛：外层留一册，门槛取其余册按册留一的 0 错门槛，再判外层册。
用法：python check_prod.py <dataset char-groups 根> <字块图目录> <组,组…>
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench import load  # noqa: E402

from open_guji_cv.groups import ids_online as O, ids_whole  # noqa: E402
from open_guji_cv.groups.registry import FLOW_GROUPS  # noqa: E402


def lobo(cells, sp, books_subset):
    """books_subset 里的格按册留一 → [(真, 判, margin, 格 id, 册)]。"""
    xs = [(f, ids_whole.norm(np.asarray(g), sp.size), b, i) for f, g, b, i in cells if b in books_subset]
    xs = [t for t in xs if t[1] is not None]
    res = []
    for bk in sorted({b for _f, _x, b, _i in xs}):
        bank = {}
        for f, x, b, _i in xs:
            if b != bk:
                bank.setdefault(f, []).append(x)
        if len(bank) < 2:
            continue
        ids_whole._CACHE.clear()
        for f, x, b, i in xs:
            if b == bk:
                ch, m, _ = ids_whole.score_norm(x, bank, sp.whole, tuple(sp.region), sp.lam)
                res.append((f, ch, m, i, b))
    return res


def main():
    root, crops, gids = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split(",")
    for g in gids:
        sp = O.SPECS[g]
        cells = load(root, crops, set(FLOW_GROUPS[g].members))
        books = sorted({c[2] for c in cells})
        r = lobo(cells, sp, set(books))
        at = [t for t in r if t[2] >= sp.min_margin]
        w1 = [(i, f, ch, round(m, 3)) for f, ch, m, i, _b in at if ch != f]
        ok1 = sum(1 for f, ch, m, _i, _b in at if ch == f)
        # 嵌套门槛
        ok2, w2, n = 0, [], 0
        for bk in books:
            inner = lobo(cells, sp, set(books) - {bk})
            wr = [m for f, ch, m, _i, _b in inner if ch != f]
            thr = max(wr) + 1e-6 if wr else 0.0
            for f, ch, m, i, b in r:
                if b != bk:
                    continue
                n += 1
                if m >= thr:
                    if ch == f:
                        ok2 += 1
                    else:
                        w2.append((i, f, ch, round(m, 3), round(thr, 3)))
        print(g, "".join(sorted(FLOW_GROUPS[g].members)), "格", len(r), dict(Counter(t[0] for t in r)),
              f"| 线上门槛 {sp.min_margin}: 对 {ok1} 错 {len(w1)} {w1}",
              f"| 嵌套门槛: 对 {ok2} 错 {len(w2)} {w2}", flush=True)


if __name__ == "__main__":
    main()
