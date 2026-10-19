# -*- coding: utf-8 -*-
"""整理本**不分行**时，用逐格识别把全文对到列上，得逐列字数表（colgold 同格式，喂 `row_segment.colgold_prior`）。

    <装了 opencc 的 python> unsplit_colcount.py --ws <沙箱工作区> --vol vol04 --ocr ocr_vol04.jsonl \
        --text <光盘版 txt> --out gp_vol04.jsonl [--start-from-image]

做法（研究文档 §十一）：
1. 整理本去掉换行，小注 `<…>` 只留「这几个字是小注」的标记。两边都转成简体再比（OCR 繁简混淆多）。
2. 载体串：一页非空格的识别 top1，按列、按格拼起来。夹注段先右半、后左半，同光盘版 `<右左>` 的读序。
3. 每页用 6-gram 投票定窗，再用 difflib 对齐。equal 段全收；等长 replace 段（≤3 字、一侧夹着 ≥2 字的 equal）一一对应。
4. 列里有「载体多一格、整理本没字、两侧都对上」的，疑是整理本缺字，这一列不给数（`--keep-holes` 关掉这条）。
5. 列边界：本列首格（或末格）对上了，就以它定界；没对上，看相邻列的末格（或首格）对上没有，对上了就借它。
   两侧都没对上时，若列端是孤格（与相邻格隔着空格，多是框线残渣），跳过它再看；还不行就不给数。相邻两列的界中间夹着没分配的字时，两列都不给数。
6. 字数 = 这一列在全文里占的字数；跨到小注的列记 note（`colgold_prior` 本来就不碰夹注列）。
   start 不分行时不知道，缺省写 null（C 按 0 算）；`--start-from-image` 取纯算法第一个非空格的格号推。
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
from pathlib import Path

from opencc import OpenCC

_CC = OpenCC("t2s")
_NORM: dict[str, str] = {}


def norm(ch: str) -> str:
    if ch not in _NORM:
        s = _CC.convert(ch)
        _NORM[ch] = s if len(s) == 1 else ch
    return _NORM[ch]


def load_text(path: Path) -> tuple[str, list[bool], str]:
    """→ (原字串, 是否小注, 简体串)，换行、尖括号都去掉。"""
    raw, note = [], []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#"):
            continue
        inn = False
        for ch in ln:
            if ch == "<":
                inn = True
            elif ch == ">":
                inn = False
            elif ch.strip():
                raw.append(ch)
                note.append(inn)
    s = "".join(raw)
    return s, note, "".join(norm(c) for c in s)


def carrier(ws: Path, vol: str, ocr: dict[str, str]):
    """→ {页: [(列, [(格 id, slot, 字), …]), …]}，列按列号，格按读序（夹注段先 a 后 b）。"""
    out = {}
    for f in sorted((ws / "products" / vol / "cell_shrink").glob("p*.json")):
        page = int(f.stem[1:])
        cols = []
        for col in json.loads(f.read_text(encoding="utf-8"))["char_index"]["columns"]:
            cells = [c for c in col["chars"] if c.get("cell_type") != "empty" and c["id"] in ocr]
            cells.sort(key=lambda c: (c["slot"] if c["slot"] < 0 else c["slot"] + 0.5, c.get("sub") or ""))
            seq, run = [], []
            for c in cells + [None]:
                if c is not None and c.get("sub"):
                    run.append(c)
                    continue
                if run:
                    seq += [x for x in run if x["sub"] == "a"] + [x for x in run if x["sub"] != "a"]
                    run = []
                if c is not None:
                    seq.append(c)
            cols.append((col["col"], [(c["id"], c["slot"], norm(ocr[c["id"]]) or "□") for c in seq]))
        out[page] = sorted(cols)
    return out


def ngram_index(s: str, lo: int, hi: int, n: int):
    idx = collections.defaultdict(list)
    for i in range(lo, hi - n + 1):
        idx[s[i:i + n]].append(i)
    return idx


def align_page(q: str, T: str, idx, n: int, lo: int, hi: int) -> tuple[dict[int, int], set[int]]:
    """载体串 q → ({q 下标: T 位置}, 疑似整理本缺字的 q 下标)。

    缺字：载体多一格、整理本这里没字（difflib 的 delete 段，长 1），两侧各夹着 ≥2 字的 equal 段。
    整理本丢了生僻字（光盘版的查表模板整条丢弃）就是这个形状；劈字是两格对一字的 replace，不像它。"""
    votes = collections.Counter()
    for i in range(len(q) - n + 1):
        ps = idx.get(q[i:i + n], ())
        if 0 < len(ps) <= 3:
            for p in ps:
                votes[(p - i) // 16] += 1
    if not votes:
        return {}, set()
    b, v = votes.most_common(1)[0]
    if v < 2:
        return {}, set()
    w0 = max(lo, b * 16 - 64)
    w1 = min(hi, b * 16 + int(len(q) * 1.3) + 96)
    ops = difflib.SequenceMatcher(None, q, T[w0:w1], autojunk=False).get_opcodes()
    m, gap = {}, set()
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            m.update({i1 + d: w0 + j1 + d for d in range(i2 - i1)})
        elif tag == "replace" and i2 - i1 == j2 - j1 <= 3:
            left = ops[k - 1] if k else None
            right = ops[k + 1] if k + 1 < len(ops) else None
            ln = (left[2] - left[1]) if left and left[0] == "equal" else 0
            rn = (right[2] - right[1]) if right and right[0] == "equal" else 0
            if max(ln, rn) >= 2:          # 只要位置，不要字认对：一侧夹着 ≥2 字的 equal 段就够
                m.update({i1 + d: w0 + j1 + d for d in range(i2 - i1)})
        elif tag == "delete" and i2 - i1 == 1 and 0 < k < len(ops) - 1:
            (lt, li1, li2, _, _), (rt, ri1, ri2, _, _) = ops[k - 1], ops[k + 1]
            if lt == rt == "equal" and li2 - li1 >= 2 and ri2 - ri1 >= 2:
                gap.add(i1)
    return m, gap


def _phys(slot: int) -> int:
    """对外 slot（抬头 -1，正文从 1 起、没有 0）→ 连续的物理格号。"""
    return slot if slot < 0 else slot - 1


def colcounts(car, T, idx, n, lo, hi):
    """→ [(页, 列, 格列表, S, E)]，S/E 是全文位置（含），不确定为 None。"""
    seq = []   # 全册非空列，按读序
    for page in sorted(car):
        cols = car[page]
        q = "".join(ch for _, cells in cols for _, _, ch in cells)
        m, gap = align_page(q, T, idx, n, lo, hi)
        k = 0
        for col, cells in cols:
            if not cells:
                continue
            pos = [m.get(k + i) for i in range(len(cells))]
            holes = sum(1 for i in range(len(cells)) if k + i in gap)
            # 列端孤格（与相邻格之间隔着空格，多是框线残渣）：两侧都锚不住时退一步，跳过它定界
            sl = [_phys(c[1]) for c in cells]
            i0, i1 = 0, len(pos) - 1
            while i0 < i1 and pos[i0] is None and sl[i0 + 1] - sl[i0] > 1:
                i0 += 1
            while i1 > i0 and pos[i1] is None and sl[i1] - sl[i1 - 1] > 1:
                i1 -= 1
            pos.append((pos[i0], pos[i1]))     # 末位放「跳过孤格后的首、末」，下面 colcounts 取用
            k += len(cells)
            seq.append([page, col, cells, pos, holes])
    res = []
    for i, (page, col, cells, pos, holes) in enumerate(seq):
        (first, last), alt = (pos[0], pos[-2]), pos[-1]
        prev = seq[i - 1][3][:-1] if i else None
        nxt = seq[i + 1][3][:-1] if i + 1 < len(seq) else None
        S = first if first is not None else (prev[-1] + 1 if prev and prev[-1] is not None else alt[0])
        E = last if last is not None else (nxt[0] - 1 if nxt and nxt[0] is not None else alt[1])
        # 界上不能夹着没人要的字：前一列的末格与本列首格都对上时，二者须相邻
        if first is not None and prev and prev[-1] is not None and first != prev[-1] + 1:
            S = None
        if last is not None and nxt and nxt[0] is not None and last != nxt[0] - 1:
            E = None
        if S is not None and E is not None and not (0 < E - S + 1 <= 40):
            S = E = None
        res.append((page, col, cells, S, E, holes))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", required=True)
    ap.add_argument("--vol", required=True)
    ap.add_argument("--ocr", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--region", default="", help="全文里本册的大致起止字位置 lo,hi（相当于知道本册是哪几卷）")
    ap.add_argument("--start-from-image", action="store_true")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--keep-holes", action="store_true", help="疑似整理本缺字的列也给数（对照用）")
    a = ap.parse_args()
    raw, note, T = load_text(Path(a.text))
    lo, hi = (map(int, a.region.split(","))) if a.region else (0, len(T))
    idx = ngram_index(T, lo, hi, a.n)
    ocr = {}
    for ln in open(a.ocr, encoding="utf-8"):
        r = json.loads(ln)
        ocr[r["id"]] = r["ch"]
    car = carrier(Path(a.ws), a.vol, ocr)
    rows, stat = [], collections.Counter()
    for page, col, cells, S, E, holes in colcounts(car, T, idx, a.n, lo, hi):
        stat["列"] += 1
        if S is None or E is None:
            stat["不给数"] += 1
            continue
        if holes and not a.keep_holes:
            stat["疑缺字不给数"] += 1
            continue
        has_note = any(note[S:E + 1])
        stat["小注列" if has_note else "给数"] += 1
        start = None
        if a.start_from_image:
            s0 = min(sl for _, sl, _ in cells)
            start = s0 - 1 if s0 > 0 else s0
        n = E - S + 1
        g = {"start": start, "n_main": sum(1 for x in note[S:E + 1] if not x), "n": n,
             "note": {"start": None, "r": None, "l": None} if has_note else None, "text": raw[S:E + 1]}
        rows.append({"vol": a.vol, "page": page, "col": col, "dzg": g, "agree": True,
                     "label_origin": "unsplit_align"})
    Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(a.vol, dict(stat), "→", a.out)


if __name__ == "__main__":
    main()
