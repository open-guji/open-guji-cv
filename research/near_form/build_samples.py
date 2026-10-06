"""形近字组样本集（overview#428，N1，2026-10-06）。

只读：guji-workspace 快照（先 `git archive <snap> products | tar -x` 解到沙箱）、工作区原图、
人裁事件（feedback/events）、overview 里各册看图判过的清单。不碰正式 products。

三组：jys = 己/已/巳；ry = 日/曰；rr = 入/人/八（入↔人、人↔八 两对）。
一格进某组：放行字 / 整理本字 / 坐标证人字 / 库前二候选 / 上下文首选 / 真值 任一属于该组。

真值来源（gold_src，先命中先用）：
  look_v04_jys  overview 书/四庫vol04/己已巳-v1.md「文意判」（会话逐格看列图）
  look_v04_s8 / look_v03_s8  放行错穷举-v1.md「看图结论」（对 / 错→X）
  card426       overview#426 点名的 3 格（看图）
  human         人裁事件（`feedback.lookup.human_chars`，后到覆盖）
  muse_truth    vol03 己已巳 muse 试点 truth.jsonl（human + claude_z39 看图）
  witness_agree 弱真值：已放行、非人裁、放行字＝整理本字＝坐标证人字（己已巳族不用这一档，证人在这族上常讹）
用法：python build_samples.py <snap_root> <out_dir>
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import Counter

import cv2
import numpy as np

from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.feedback.lookup import human_chars
from open_guji_cv.utils.jiazhu_order import order_keys

SNAP, OUT = sys.argv[1], sys.argv[2]
WS = glob.glob("/home/user/guji-workspace/96mid1ogzk-*")[0]
OV = "/home/user/overview/项目进展/新书整理/书"
GROUPS = {"jys": set("己已巳"), "ry": set("日曰"), "rr": set("入人八")}
ALL = set().union(*GROUPS.values())
# 册 → (seed_admit 快照, 上游全量快照, 原图/切分快照)
BOOKS = {
    "vol02": ("vol02_20260930T0339", "vol02_20260929T1024", "vol02_20260929T1023"),
    "vol03": ("vol03_20260930T0457", "vol03_20260928T1708-full", "vol03_20260928T1708-full"),
    "vol04": ("vol04_20261006T0716", "vol04_20261006T0716", "vol04_20261006T0716"),
}
CTX = 5


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def parse_look(path, tag, col_char, col_verdict):
    """markdown 表 → {id: (gold, note)}。只收「对…」「X 对」「错→X」。"""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        if not line.startswith("| `vol"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cid = cells[0].strip("`")
        if col_verdict is None:   # vol03 v1：「图上是」一栏直接写字（可带括注）
            if len(cells) > 6 and cells[5] and cells[5][0] not in "?？—-" and cells[5] != "看不清":
                out[cid] = (cells[5][0], tag, f"{cells[5]} / {cells[6]}")
            continue
        v, cur = cells[-1], cells[col_char]
        m = re.match(r"错→(.)", v)
        if m:
            out[cid] = (m.group(1), tag, v)
        elif v.startswith("对") or re.match(r"^. 对", v):
            g = v[0] if re.match(r"^. 对", v) else cur
            if g:
                out[cid] = (g, tag, v)
    return out


def gold_tables():
    g = {}
    g.update(parse_look(f"{OV}/四庫vol03/放行错穷举-v1.md", "look_v03_s8", 1, None))
    g.update(parse_look(f"{OV}/四庫vol04/放行错穷举-v1.md", "look_v04_s8", 1, -1))
    g.update(parse_look(f"{OV}/四庫vol04/己已巳-v1.md", "look_v04_jys", 1, 5))
    for cid, ch in (("vol04:40:2:2", "日"), ("vol04:60:9:6", "日"), ("vol04:188:2:20", "八")):
        g[cid] = (ch, "card426", "overview#426 看图")
    for line in open(f"{OV}/四庫vol03/muse-己已巳试点/truth.jsonl", encoding="utf-8"):
        r = json.loads(line)
        g.setdefault(r["id"], (r["truth"], "muse_truth", r["truth_src"]))
    return g


def cols_of(d, key):
    return {c["col"]: c for c in d[key]["columns"]} if d else {}


def main():
    os.makedirs(f"{OUT}/crops", exist_ok=True)
    look = gold_tables()
    rows = []
    for book, (s_seed, s_up, s_cut) in BOOKS.items():
        os.environ["GUJI_WORKSPACE"] = WS
        hum = human_chars(book)
        base = lambda s, st: f"{SNAP}/{s}/products/{book}/{st}"
        pages = sorted(os.path.basename(p)[:-5] for p in glob.glob(base(s_seed, "seed_admit") + "/p*.json"))
        for key in pages:
            page = int(key[1:])
            sa = load(f"{base(s_seed, 'seed_admit')}/{key}.json")["seed_admit"]
            def opt(s, st, k):
                p = f"{base(s, st)}/{key}.json"
                return load(p)[k] if os.path.exists(p) else None
            ar = opt(s_up, "align_ref", "align_ref") or {}
            gm = opt(s_up, "glyph_match", "glyph_match")
            cd = opt(s_up, "context_decide", "context_decision")
            ci = opt(s_cut, "cell_shrink", "char_index")
            amap = {c["id"]: c.get("align_char") for c in ar.get("chars", [])}
            aop = {c["id"]: c.get("align_op") for c in ar.get("chars", [])}
            coord = {c["id"]: c.get("ref_char") for c in ar.get("coord", [])}
            gmap = {ch["id"]: ch for c in (gm or {}).get("columns", []) for ch in c["chars"]}
            cmap = {ch["id"]: ch for c in (cd or {}).get("columns", []) for ch in c["chars"]}
            bmap = {ch["id"]: ch for c in (ci or {}).get("columns", []) for ch in c["chars"]}
            # 读序：列号升序（右→左），列内正文/夹注读序
            seq = []
            for c in sorted(sa["columns"], key=lambda c: c["col"]):
                chs = c["chars"]
                ok = order_keys((r["slot"], r.get("sub")) for r in chs)
                for r in sorted(chs, key=lambda r: ok[(r["slot"], r.get("sub") or "")]):
                    if "excluded" in (r.get("doubts") or []):
                        continue
                    seq.append((c["col"], r))
            img = None
            def show(r):
                return r.get("char") or amap.get(r["id"]) or coord.get(r["id"]) or "□"
            def ref_show(r):
                return amap.get(r["id"]) or coord.get(r["id"]) or "□"
            for i, (col, r) in enumerate(seq):
                cid = r["id"]
                g = gmap.get(cid, {})
                cands = [x[0] for x in (g.get("candidates") or [])[:2]]
                cx = cmap.get(cid, {})
                ctx_top = cx.get("char")
                gold, gsrc, gnote = None, None, None
                if cid in look:
                    gold, gsrc, gnote = look[cid]
                elif cid in hum:
                    gold, gsrc = hum[cid], "human"
                cand_set = {r.get("char"), amap.get(cid), coord.get(cid), ctx_top, gold, *cands} - {None}
                grp = [k for k, s in GROUPS.items() if cand_set & s]
                if not grp:
                    continue
                if (gold is None and r.get("admit") and r.get("channel") != "human"
                        and r.get("char") and r["char"] == amap.get(cid) == coord.get(cid)
                        and r["char"] not in GROUPS["jys"]):
                    gold, gsrc = r["char"], "witness_agree"
                left = "".join(show(x[1]) for x in seq[max(0, i - CTX):i])
                right = "".join(show(x[1]) for x in seq[i + 1:i + 1 + CTX])
                rleft = "".join(ref_show(x[1]) for x in seq[max(0, i - CTX):i])
                rright = "".join(ref_show(x[1]) for x in seq[i + 1:i + 1 + CTX])
                ev = r.get("evidence") or {}
                bx = bmap.get(cid)
                crop = None
                if bx and bx.get("bbox_page"):
                    if img is None:
                        img = cv2.imdecode(np.fromfile(f"{WS}/data_full/zongmu/{book}/{page}.png", np.uint8), 0)
                    p = crop_patch(img, tuple(bx["bbox_page"])) if img is not None else None
                    if p is not None and p.size:
                        crop = f"crops/{cid.replace(':', '_')}.png"
                        cv2.imwrite(f"{OUT}/{crop}", p)
                for grp_k in grp:
                    rows.append(dict(
                        id=cid, book=book, page=page, col=col, slot=r["slot"], sub=r.get("sub"),
                        group=grp_k, gold=gold, gold_src=gsrc, gold_note=gnote,
                        admit=bool(r.get("admit")), channel=r.get("channel"), char=r.get("char"),
                        doubts=r.get("doubts") or [],
                        ref=amap.get(cid), ref_op=aop.get(cid), coord_ref=coord.get(cid),
                        lib=(g.get("candidates") or [])[:3], lib_verdict=g.get("verdict"),
                        ctx=ctx_top, ctx_ranked=(cx.get("ranked") or [])[:3], ctx_source=cx.get("source"),
                        ocr=(ev.get("ocr") or [])[:3], ji_yi_si=ev.get("ji_yi_si"),
                        left=left, right=right, ref_left=rleft, ref_right=rright,
                        word=f"{left[-2:]}【{show(r)}】{right[:2]}",
                        kind=(bx or {}).get("step3_kind"), ink=(bx or {}).get("ink_ratio"),
                        wh=[(bx or {}).get("width"), (bx or {}).get("height")], crop=crop,
                    ))
        print(book, sum(1 for x in rows if x["book"] == book), file=sys.stderr)
    with open(f"{OUT}/items.jsonl", "w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    c = Counter((x["book"], x["group"], x["gold_src"]) for x in rows)
    for k in sorted(c, key=str):
        print(k, c[k])


if __name__ == "__main__":
    main()
