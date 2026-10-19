"""§四-4 实验：原生 YOLO 字框当「横画字被切开」的第二意见。

闸：同列相邻两个正文格（slot 相邻、非夹注）的紧框，各有 ≥cover 的面积落在同一个 YOLO 字框（conf≥conf）里 → 该列标「疑似多切」。
真值：该列 CV 字数 > release 字数。YOLO 用原生输出（不做任何清理）——用户 10-19：今后只有原生 yolo-tool 输出。
用法：python gate_merge.py a <wsA> <yA.jsonl> | b <wsB> <yB.jsonl>
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from their import load_ch, boxes  # noqa: E402
from colcount import their_colcounts, ours_colcounts  # noqa: E402
from ours_prod import load_chars  # noqa: E402
from evaluate import _img_w, WS96  # noqa: E402


def covered(cell, y):
    iw = min(cell[2], y[2]) - max(cell[0], y[0])
    ih = min(cell[3], y[3]) - max(cell[1], y[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    return iw * ih / max(1e-6, (cell[2] - cell[0]) * (cell[3] - cell[1]))


def fired_cols(chars, ybs, cover, conf, max_h=None):
    """max_h：YOLO 框高上限（× 本页 YOLO 字框中位高）。YOLO 偶尔把两字并成一框，那种框约两倍高；
    「三」被我们切开时 YOLO 给的是一个正常高的字框。"""
    ys = [b for b, c in ybs if c >= conf]
    if max_h and ys:
        hs = sorted(b[3] - b[1] for b in ys)
        mh = hs[len(hs) // 2]
        ys = [b for b in ys if b[3] - b[1] <= max_h * mh]
    out = set()
    bycol = collections.defaultdict(list)
    for c in chars:
        if c["sub"] is None and c["slot"] is not None:
            bycol[c["col"]].append(c)
    for col, cs in bycol.items():
        cs.sort(key=lambda c: c["slot"])
        for a, b in zip(cs, cs[1:]):
            if b["slot"] - a["slot"] != 1 and not (a["slot"] == -1 and b["slot"] == 1):
                continue
            if any(covered(a["box"], y) >= cover and covered(b["box"], y) >= cover for y in ys):
                out.add(col)
                break
    return out


def pages(mode, ws, yl):
    Y = {json.loads(ln)["key"]: json.loads(ln) for ln in open(yl)}
    if mode == "a":
        mp = json.load(open(f"{ws}/map.json"))
        for n, ch, p in mp["map"]:
            _, P = load_ch(ch)
            sc = mp["scale"]
            chars = load_chars(ws, "A", n, _img_w(f"{ws}/data_full/A/{n}.png"))
            for c in chars:
                c["box"] = [v / sc for v in c["box"]]
            yield f"A:{ch}:{p}", chars, Y[f"{ch}:{p}"], their_colcounts(P[p], boxes)
    else:
        sel = json.load(open(f"{ws}/testB_pages.json"))
        for v in sel:
            for o, ch, p in sel[v]:
                _, P = load_ch(ch)
                chars = load_chars(ws, v, o, _img_w(f"{WS96}/data_full/zongmu/{v}/{o}.png"))
                yield f"{v}:{o}", chars, Y[f"{v}:{o}"], their_colcounts(P[p], boxes)


if __name__ == "__main__":
    mode, ws, yl = sys.argv[1:4]
    data = list(pages(mode, ws, yl))
    for cover, conf, max_h in ((0.6, 0.5, None), (0.6, 0.5, 1.3), (0.6, 0.25, 1.3), (0.5, 0.25, 1.3)):
        if True:
            tp = fp = n_over = 0
            for key, chars, y, truth in data:
                pred = ours_colcounts(chars)
                over = {i + 1 for i, t in enumerate(truth) if i < len(pred) and pred[i] > t}
                ybs = [([c["xywh"][0], c["xywh"][1], c["xywh"][0] + c["xywh"][2], c["xywh"][1] + c["xywh"][3]], c["conf"])
                       for c in y["chars"]]
                f = fired_cols(chars, ybs, cover, conf, max_h)
                tp += len(f & over); fp += len(f - over); n_over += len(over)
            print(f"cover≥{cover} conf≥{conf} 框高≤{max_h}×中位: 抓到多切列 {tp}/{n_over}，误报 {fp} 列（{len(data)} 页）")
