"""M7 上下文路（GUJI-563 块 D/E）共用：读 char-groups、窗口、Wilson 下界、按层评测。
数据根：环境变量 CHAR_GROUPS（缺省 /home/user/open-guji/open-guji-dataset/char-groups）。
"""
import json, math, os
from pathlib import Path

CG = Path(os.environ.get("CHAR_GROUPS", "/home/user/open-guji/open-guji-dataset/char-groups"))
FAMILY = {"jys": "己已巳", "ry": "日曰", "rr": "入人八"}
STRONG = ("A_human", "B_vision")
W = 20


def load(group):
    return [json.loads(l) for l in (CG / group / "items.jsonl").open(encoding="utf-8")]


def window(r, w=W):
    """前后各 w 字。items 的 left/right 是 30 字、跨列连读、到页首页尾止；本数据集没有段界信息，所以这里
    只做定宽截取（段界停止由管线侧 groups.context 负责，评测里标为已知差异）。"""
    return (r.get("left") or "")[-w:], (r.get("right") or "")[:w]


def wilson_lo(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - a) / d


def score(rows, pick, group, tiers=STRONG):
    """pick(row)->(char|None, why)。口径同 eval/groups.py（S1）：只在 gold_tier∈tiers 的格上数；
    gold 不在本组成员内的格（路由问题，不是本组分类器的事）不进准确率分母，单独记 leak（pick 给了字）/out（总数）。"""
    fam = set(FAMILY[group])
    n = give = ok = out = leak = 0
    errs, leaks = [], []
    for r in rows:
        if r.get("gold_tier") not in tiers:
            continue
        ch, why = pick(r)
        if r["gold"] not in fam:
            out += 1
            if ch is not None:
                leak += 1; leaks.append((r["id"], r["gold"], ch, why))
            continue
        n += 1
        if ch is None:
            continue
        give += 1
        if ch == r["gold"]:
            ok += 1
        else:
            errs.append((r["id"], r["gold"], ch, why))
    return dict(n=n, give=give, ok=ok, err=give - ok, cover=round(give / n, 3) if n else 0,
                acc=round(ok / give, 4) if give else None, wilson_lo=round(wilson_lo(ok, give), 3),
                out_of_family=out, leak=leak), errs
