"""切分体检：一册（或几册）产物上算一组全自动的切分指标，新跑一批后和上一批比，看有没有成规模回退。

两级口径（2026-10-25，殿本 vol06–20 v0.5.12 基准：一级 99.82%、几何标出 0.48%，见 m12/seg-accuracy 报告）：

一级「每列格位切对没有」
  - colnet_pages   列宽异常页：某列宽 < 页中位 0.7（列网把一列劈成两窄列，常伴整列丢字）
  - layout_miss    对格位表：一列切出的字格号集合 ≠ 表（表是 Step3 的约束，只能证明两边一致）
  - text_shift     对整理本逐列文字：放行字在邻列或差一两格处对得更好（不依赖格位表；抬头列格号差一也落这里）
  - merged_cols    一格挤两个字的列：字框高 > 本列中位 1.6 倍
二级「字和字分开没有」
  - geo_flag       字墨截断或邻字侵入超过框面积 4% 的格（几何上限，含框线擦边、粘连细颈）
  - geo_hit        geo_flag 里送审、或放行字与整理本不一致的格（要看图的那一小撮）

用法：
  python scripts/eval_seg_health.py --root <产物根> --books vol06 vol07 … [--raw <原图目录模板>] [--json out.json]
原图目录模板缺省 `<工作区>/data_full/zongmu/{vol}/{page}.png`；没有原图时跳过二级。
整理本与格位表从中心库数据目录读（`corpus_path("daizhige/…")`，要先 `guji db pull`）。

推到后台数据控制台（网站后台「文本整理 › 切分」，表 progress.metric、section seg，见 kaiyuanguji-web docs/text-progress.md）：
  python scripts/eval_seg_health.py --root <产物根> --books vol06 … vol20 --push
  每册写一行（册号按 progress.volume 的 ws＋cv_book 对到 book-text 章号），再按库里各册的数重算整套合计；
  只跑了几册也不会冲掉别册。「看图核」的两级准确率（l1_acc、l2_acc）是人看图定的，本脚本不碰。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import statistics
from pathlib import Path


def _pages(root: Path, book: str, step: str) -> dict[int, dict]:
    out = {}
    for f in sorted(glob.glob(str(root / book / step / "p*.json"))):
        out[int(f[-9:-5])] = next(iter(json.load(open(f, encoding="utf-8")).values()))
    return out


def _cid(ch: dict) -> tuple[int, int]:
    _, p, c = ch["id"].split(":")[:3]
    return int(p), int(c)


class Ref:
    """格位表 + daizhige 逐列文字（我们一页＝一个半叶，列一一对应）。"""

    def __init__(self, corpus: Path):
        self.slots = {}
        for line in open(corpus / "layout_slots.jsonl", encoding="utf-8"):
            d = json.loads(line)
            self.slots[(d["vol"], d["page"], d["col"])] = set(d["slots"])
        self.pm = {}
        for line in open(corpus / "page_map.jsonl", encoding="utf-8"):
            d = json.loads(line)
            if d.get("dzg_id"):
                self.pm[(d["vol"], d["page"])] = (d["dzg_id"], d["side"])
        self.rec = {}
        for f in sorted(corpus.glob("000*.jsonl")):
            for line in open(f, encoding="utf-8"):
                d = json.loads(line)
                self.rec[d["id"]] = d

    def text(self, book: str, page: int) -> dict[int, dict[int, str]]:
        m = self.pm.get((book, page))
        if not m:
            return {}
        out = {}
        for c in self.rec[m[0]]["cols"]:
            if c["no"] // 9 != m[1]:
                continue
            s = {}
            for run in c["runs"]:
                if run["t"] == "text":
                    for i, ch in enumerate(run["s"]):
                        s[run["start"] + 1 + i] = ch
            out[c["no"] % 9 + 1] = s
        return out


def _seg_rev(root: Path, book: str) -> str:
    """这批切分产物（Step4 cell_shrink）是哪版代码出的：各页最后一次写的 code_rev 取多数，能对上 tag 就报版本号。"""
    import subprocess
    last = {}
    for line in open(root / book / "cell_shrink" / "_manifest.jsonl", encoding="utf-8"):
        d = json.loads(line)
        last[d["key"]] = d.get("code_rev")
    rev = collections.Counter(last.values()).most_common(1)[0][0] if last else None
    if not rev:
        return "?"
    r = subprocess.run(["git", "-C", str(Path(__file__).parent), "describe", "--tags", "--abbrev=0", rev],
                       capture_output=True, text=True)
    return f"{r.stdout.strip()}（{rev}）" if r.returncode == 0 else rev


def level1(root: Path, book: str, ref: Ref) -> dict:
    gate = _pages(root, book, "column_gate")
    cs = _pages(root, book, "cell_shrink")
    sa = _pages(root, book, "seed_admit")
    colnet = []
    for p, d in gate.items():
        w = d.get("column_widths") or []
        if len(w) >= 3 and any(x < 0.7 * statistics.median(w) for x in w):
            colnet.append(p)
    got: dict[tuple[int, int], set] = collections.defaultdict(set)
    merged = []
    n_cols = 0
    for p, d in cs.items():
        for c in d["columns"]:
            chs = [ch for ch in c["chars"] if ch.get("cell_type") != "blank"]
            if not chs:
                continue
            n_cols += 1
            for ch in chs:
                got[_cid(ch)].add(ch["slot"])
            body = [ch for ch in chs if ch.get("cell_type") == "char" and not ch.get("sub")]
            if len(body) >= 6:
                hs = [ch["bbox_page"][3] - ch["bbox_page"][1] for ch in body]
                m = statistics.median(hs)
                if any(h > 1.6 * m for h in hs):
                    merged.append(_cid(body[0]))
    miss = [(p, c) for (b, p, c), want in ref.slots.items()
            if b == book and p in cs and (want or got.get((p, c))) and got.get((p, c), set()) != want]
    shift = []
    for p, d in sa.items():
        dz = ref.text(book, p)
        if not dz:
            continue
        for col in d["columns"]:
            a = {ch["slot"]: ch["char"] for ch in col["chars"]
                 if ch["admit"] and ch["char"] and not ch.get("sub")}
            if len(a) < 4:
                continue
            k = col["col"]

            def sc(kk, off):
                t = dz.get(kk, {})
                return sum(1 for s, ch in a.items() if t.get(s + off) == ch)
            m0 = sc(k, 0)
            best = max(sc(kk, off) for kk in (k - 1, k, k + 1) for off in (-2, -1, 0, 1, 2))
            if best > m0 and m0 < 0.5 * len(a) and best >= 0.4 * len(a):
                shift.append((p, k))
    return dict(seg_rev=_seg_rev(root, book), cols=n_cols, colnet_pages=sorted(colnet), layout_miss=sorted(miss),
                text_shift=sorted(shift), merged_cols=sorted(merged))


def level2(root: Path, book: str, ref: Ref, raw_tpl: str, thr: float = 0.04) -> dict:
    import cv2
    import numpy as np
    cs = _pages(root, book, "cell_shrink")
    sa = _pages(root, book, "seed_admit")
    adm = {ch["id"]: ch for d in sa.values() for c in d["columns"] for ch in c["chars"]}
    flags, hits, n = [], [], 0
    for p, d in cs.items():
        path = raw_tpl.format(vol=book, page=p)
        if not Path(path).exists():
            continue
        g = cv2.imread(path, 0)
        H, W = g.shape
        bw = (g < 128).astype(np.uint8)
        B = []
        for c in d["columns"]:
            for ch in c["chars"]:
                if ch.get("cell_type") == "blank":
                    continue
                x0, y0, x1, y1 = ch["bbox_page"]        # x 从右边量
                B.append((int(W - x1), int(y0), int(np.ceil(W - x0)), int(np.ceil(y1)), ch["id"]))
        n += len(B)
        if not B:
            continue
        lab = np.full((H, W), -1, np.int32)
        cnt = np.zeros((H, W), np.uint8)
        for i, (x0, y0, x1, y1, _) in enumerate(B):
            lab[y0:y1, x0:x1] = i
            cnt[y0:y1, x0:x1] += 1
        medh = np.median([b[3] - b[1] for b in B])
        medw = np.median([b[2] - b[0] for b in B])
        k_, cc, st, _ = cv2.connectedComponentsWithStats(bw, 8)
        acc = collections.defaultdict(lambda: [0, 0])
        for k in range(1, k_):
            x, y, w, h, a = st[k]
            if a < 15 or h > 1.6 * medh or w > 1.5 * medw:
                continue                                  # 碎点、框线界行
            m = cc[y:y + h, x:x + w] == k
            L, C = lab[y:y + h, x:x + w][m], cnt[y:y + h, x:x + w][m]
            if (L < 0).all():
                continue
            vals, counts = np.unique(L[L >= 0], return_counts=True)
            if counts.max() < 0.5 * a:
                continue
            own = vals[np.argmax(counts)]
            acc[own][0] += int((L < 0).sum())             # 本字伸出所有字框
            for v, _c in zip(vals, counts):
                if v != own:
                    acc[v][1] += int(((L == v) & (C == 1)).sum())   # 邻字落进本框独占区
        for i, (lost, intr) in acc.items():
            x0, y0, x1, y1, id_ = B[i]
            area = max(1, (x1 - x0) * (y1 - y0))
            if lost / area > thr or intr / area > thr:
                flags.append(id_)
                ch = adm.get(id_)
                if ch is None:
                    continue
                pg, col = _cid(ch)
                refc = ref.text(book, pg).get(col, {}).get(ch["slot"])
                if not ch["admit"] or (refc and not ch.get("sub") and refc != ch["char"]):
                    hits.append(id_)
    return dict(cells=n, geo_flag=len(flags), geo_hit=sorted(hits))


PUSH_KEYS = [  # key, 显示名, 单位, 排序；整套合计按各册相加
    ("suspect_cols", "自动可疑列", "列", 20), ("cols", "列数", "列", 40), ("cells", "格数", "格", 50),
    ("colnet_pages", "列网异常页（自动）", "页", 60), ("layout_miss", "对格位表错列（自动）", "列", 70),
    ("text_shift", "对整理本整列错位（自动）", "列", 80), ("merged_cols", "一格挤两字列（自动）", "列", 90),
    ("geo_flag", "几何标出格（自动）", "格", 100), ("geo_hit", "几何标出且要看图（自动）", "格", 110),
]


def _counts(r: dict) -> dict:
    return {"cols": r["cols"], "suspect_cols": _suspect_cols(r), "colnet_pages": len(r["colnet_pages"]), "layout_miss": len(r["layout_miss"]),
            "text_shift": len(r["text_shift"]), "merged_cols": len(r["merged_cols"]),
            **({"cells": r["cells"], "geo_flag": r["geo_flag"], "geo_hit": len(r["geo_hit"])} if "cells" in r else {})}


def _suspect_cols(r: dict) -> int:
    """自动可疑列：对表错、整列错位、挤格三类的并集（含抬头格号差一，所以是下限估）。"""
    return len({tuple(x) for k in ("layout_miss", "text_shift", "merged_cols") for x in r[k]})


def push(out: dict, ws: str, by: str = "A22") -> None:
    """把各册体检数写进 progress.metric（section seg），再按库里各册重算整套合计。"""
    from datetime import date
    from open_guji_cv.datastore.connect import connect
    put = "SELECT progress.put_metric(%s, %s, 'seg', %s, %s, %s, %s, %s, %s, %s::jsonb, %s)"
    with connect() as conn:
        vmap = {cvb: (b, v) for b, v, cvb in conn.execute(
            "SELECT book_id, vol, cv_book FROM progress.volume WHERE ws = %s", (ws,)).fetchall()}
        books = set()
        for cvb, r in out.items():
            if cvb not in vmap:
                print(f"跳过 {cvb}：progress.volume 里没有 ws={ws} 的这一册")
                continue
            b, v = vmap[cvb]
            books.add(b)
            c = _counts(r)
            meta = json.dumps({"seg_rev": r["seg_rev"], "at": date.today().isoformat()})
            for k, label, unit, sort in PUSH_KEYS:
                if k in c:
                    conn.execute(put, (b, v, k, label, c[k], unit, by, None, meta, sort))
            conn.execute(put, (b, v, "l1_auto", "一级自动估（下限）", 1 - c["suspect_cols"] / max(1, c["cols"]), "%",
                               by, None, meta, 15))
            if "cells" in r:
                conn.execute(put, (b, v, "geo_flag_rate", "几何标出率（自动，最严上限）", r["geo_flag"] / max(1, r["cells"]),
                                   "%", by, None, meta, 105))
            conn.execute(put, (b, v, "seg_cv", "切分代码版本", None, None, by, r["seg_rev"], meta, 5))
        for b in books:     # 整套合计：按库里该书已有的各册行相加（只跑几册也不冲掉别册）
            rows = conn.execute("SELECT vol, key, value FROM progress.metric WHERE section = 'seg' AND book_id = %s "
                                "AND vol <> '' AND value IS NOT NULL", (b,)).fetchall()
            tot, vols = collections.Counter(), set()
            for v, k, val in rows:
                tot[k] += val
                vols.add(v)
            revs = sorted({r["seg_rev"] for r in out.values()})
            meta = json.dumps({"vols": sorted(vols), "seg_rev": revs, "at": date.today().isoformat()}, ensure_ascii=False)
            for k, label, unit, sort in PUSH_KEYS:
                if k in tot:
                    conn.execute(put, (b, "", k, label, tot[k], unit, by, None, meta, sort))
            if tot["cols"]:
                conn.execute(put, (b, "", "l1_auto", "一级自动估（下限）", 1 - tot["suspect_cols"] / tot["cols"], "%", by, None, meta, 25))
            if tot["cells"]:
                conn.execute(put, (b, "", "geo_flag_rate", "几何标出率（自动，最严上限）", tot["geo_flag"] / tot["cells"], "%",
                                   by, None, meta, 105))
            conn.execute(put, (b, "", "auto_basis", "自动数依据", None, None, by,
                               f"{len(vols)} 册 · 本次算的切分代码 {'、'.join(revs)} · {date.today().isoformat()}", meta, 35))
        conn.commit()
    print(f"已推 {len(out)} 册到 progress.metric（section seg）")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="产物根（下有 <册>/<step>/p*.json）")
    ap.add_argument("--books", nargs="+", required=True)
    ap.add_argument("--corpus", help="daizhige 目录；缺省 corpus_path('daizhige')")
    ap.add_argument("--raw", help="原图路径模板，{vol}、{page}；缺省 <工作区>/data_full/zongmu/{vol}/{page}.png")
    ap.add_argument("--no-l2", action="store_true", help="不算二级（不读原图，快）")
    ap.add_argument("--json", help="明细写到这个文件")
    ap.add_argument("--push", action="store_true", help="算完推到后台数据控制台（progress.metric，section seg）")
    ap.add_argument("--ws", default="siku-zongmu", help="--push 用：工作区 id，按它把册对到 book-text 章号")
    a = ap.parse_args(argv)
    if a.corpus:
        corpus = Path(a.corpus)
    else:
        from open_guji_cv.core.workspace import corpus_path
        corpus = corpus_path("daizhige")
    raw = a.raw
    if raw is None and not a.no_l2:
        from open_guji_cv.core.workspace import workspace_root
        ws = workspace_root()
        raw = str(ws / "data_full" / "zongmu" / "{vol}" / "{page}.png") if ws else None
    ref = Ref(corpus)
    out, tot = {}, collections.Counter()
    print("册     列数   列网页 对表错列 文字错位 挤格列 |   格数  几何标出  要看图")
    for b in a.books:
        r = level1(Path(a.root), b, ref)
        if raw and not a.no_l2:
            r.update(level2(Path(a.root), b, ref, raw))
        out[b] = r
        row = [r["cols"], len(r["colnet_pages"]), len(r["layout_miss"]), len(r["text_shift"]), len(r["merged_cols"]),
               r.get("cells", 0), r.get("geo_flag", 0), len(r.get("geo_hit", []))]
        for k, v in zip(("cols", "colnet", "miss", "shift", "merged", "cells", "geo", "hit"), row):
            tot[k] += v
        print(f"{b:6s} {row[0]:5d} {row[1]:6d} {row[2]:7d} {row[3]:7d} {row[4]:6d} | {row[5]:7d} {row[6]:7d} {row[7]:6d}",
              flush=True)
    print(f"{'合计':5s} {tot['cols']:5d} {tot['colnet']:6d} {tot['miss']:7d} {tot['shift']:7d} {tot['merged']:6d} | "
          f"{tot['cells']:7d} {tot['geo']:7d} {tot['hit']:6d}")
    if tot["cells"]:
        print(f"几何标出率 {tot['geo'] / tot['cells']:.2%}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    if a.push:
        push(out, a.ws)


if __name__ == "__main__":
    main()
