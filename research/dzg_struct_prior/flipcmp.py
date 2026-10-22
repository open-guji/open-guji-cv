"""两份 structcmp 结果并排比：两种口径各报准确率、修好几列、改坏几列，并列出改坏的列。

    python flipcmp.py <基线.json> <对照.json> [--min-page 4]

总列数取基线 json 里的 `ncols`（structcmp 逐页记的列数）；老结果没有这一项时用 `--cols` 手给。
口径：**逐格**＝列里每个 (slot, sub) 与 daizhige 一致；**字数**＝列里非空格数与 daizhige 一致（不管落在哪格）。
**对位**＝列里没有字格偏离本页同格号的高度（structcmp 的 `misplaced`，两份结果都有这一项时才报）：格号集合对上、
字却整列错一格的列（卷端页大印下）只有这个口径看得见。
默认从第 1 页起比，卷端页（p2/p3）在内（用户 10-22：卷端页纳入切分评测）；`--min-page 4` 去掉它们，只为和老结果对数。
前两个口径都要报：只看字数会高估逐列字数先验、低估逐列格位约束（研究文档 §八）。
"""
import argparse
import json


def errs(path, min_page, count):
    rows = json.load(open(path, encoding='utf-8'))['rows']
    return {(r['page'], r['col']): r for r in rows
            if r['page'] >= min_page and (not count or r['nE'] != r['nP'])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base'); ap.add_argument('other')
    ap.add_argument('--cols', type=int, default=0)
    ap.add_argument('--min-page', type=int, default=1)
    a = ap.parse_args()
    if not a.cols:
        nc = json.load(open(a.base, encoding='utf-8')).get('ncols')
        if not nc:
            ap.error('基线 json 里没有 ncols（老版 structcmp 出的），用 --cols 给总列数')
        a.cols = sum(n for k, n in nc.items() if int(k.split(':')[1]) >= a.min_page)
    print(f'列 {a.cols}（第 {a.min_page} 页起）')
    for count, name in ((False, '逐格'), (True, '字数')):
        b, o = errs(a.base, a.min_page, count), errs(a.other, a.min_page, count)
        fixed, broke = sorted(set(b) - set(o)), sorted(set(o) - set(b))
        print(f"{name}：{1 - len(b) / a.cols:.2%} → {1 - len(o) / a.cols:.2%}  修好 {len(fixed)}  改坏 {len(broke)}")
        for k in broke:
            r = o[k]
            print(f"   改坏 p{k[0]} c{k[1]}  {r['kind']}  多 {r['only_P']}  少 {r['only_E']}  {r['text'][:24]}")
    mb, mo = (json.load(open(p, encoding='utf-8')).get('misplaced') for p in (a.base, a.other))
    if mb is not None and mo is not None:
        b, o = ({k: v for k, v in m.items() if int(k.split(':')[1]) >= a.min_page} for m in (mb, mo))
        print(f"对位：{1 - len(b) / a.cols:.2%} → {1 - len(o) / a.cols:.2%}  修好 {len(set(b) - set(o))}  改坏 {len(set(o) - set(b))}")
        for k in sorted(set(o) - set(b)):
            print(f"   改坏 {k}  错位格 {o[k]}")


if __name__ == '__main__':
    main()
