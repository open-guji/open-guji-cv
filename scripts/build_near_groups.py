# -*- coding: utf-8 -*-
"""形近字组表 `config/near_groups.json` 的生成（表怎么用见 `open_guji_cv/clustering/near_route.py`）。

    # 一本书：从它的字形库自身挖极近字对（约 1～3 分钟，要这本书的 5a 相似度 CNN 权重与校准表）
    python scripts/build_near_groups.py mine --book qtw --db <glyph.db> --model models/glyph_sim_qtw/model.pt \\
        [--exclude <评测分片>/expected.json ...] --out /tmp/near_qtw.json

    # 合表：各书挖的＋手工表＋人裁表＋字体表＋同形异码
    python scripts/build_near_groups.py merge /tmp/near_qtw.json /tmp/near_sj.json /tmp/near_sk.json \\
        [--variants <同形异码对.tsv>] --out config/near_groups.json

`mine` 的做法（不看任何评测查询，`--exclude` 给的评测格不用）：
- 同一物理格挂在别的字下的行不当对家；`--trusted` 时只用**可信刻例**（人裁的，加上 CNN 最像的人裁刻例与它同字的机器进库刻例）——
  机器进库标签不干净的书要开（殿本、史記开了；全唐文开了会丢掉没有人裁刻例的字，表从 220 对缩到 40 对，没开）；
- 库里每个刻例 x（字 a），取 CNN 最像的 `TOPC` 个**别的字**各一例，算校准后 CNN 分与覆盖分（`verify_pair_elastic`）的平均 m；
- 一对字 (a, b) 的「近度」取各刻例 m 的**第二高**（要两个刻例都这么像才算，防单个错标刻例把常用字拖进表；
  只出现过一次就用那一次），a→b、b→a 取大；
- 近度 ≥ `near_route.WIDE_NEAR` 的进表，≥ `CORE_NEAR` 的在合表时算核心对。

没有按书训过 CNN 的书别拿别的书的权重来挖：全唐文权重在史記、殿本上闸下同字放行率只有 2～3%（对抗评测集实测），
挖出来的近度不可信。库小的书拿全唐文权重起步按本书刻例微调（`train_glyph_sim_cnn.py --init`）再挖。

`merge` 的 `--drop`（缺省 `config/near_groups_drop.tsv`）：库里挖出来、但其实是错标刻例造成的假字对（事/日、功/臣 这类两个字毫不相干的），
每行 `两个字<TAB>原因`。现有名单是按「字体渲染下两个字的 CNN 余弦 < 0.2」自动筛的，待人核；人核过的手工表、人裁表里的对不受它管。

`merge` 的 `--variants`：每行 `字甲<TAB>字乙[<TAB>…]` 的同形异码／异体对（侯/𠋫、歳/歲 这类，Sheldon 11-15 定不算同一个字）。
"""

from __future__ import annotations

import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOPC = 3
_P: list = []


def _cell(iid: str) -> str:
    return iid.split(":", 1)[1] if iid.startswith(("v2:", "v1:")) else iid


def _cov(pairs):
    from open_guji_cv.clustering.verify import verify_pair_elastic
    return [float(verify_pair_elastic(_P[i], _P[j]).f1) for i, j in pairs]


def near_from_scores(rows: list[tuple[str, str, float]]) -> dict[tuple[str, str], tuple[float, int]]:
    """[(字 a, 对家字 b, 这一例的 m)] → {(小码位字, 大码位字): (近度, 出现次数)}。近度＝每个方向第二高的 m，两个方向取大。"""
    acc: dict[tuple[str, str], list[float]] = {}
    for a, b, m in rows:
        acc.setdefault((a, b), []).append(m)
    out: dict[tuple[str, str], tuple[float, int]] = {}
    for (a, b), ms in acc.items():
        ms.sort(reverse=True)
        m2 = ms[1] if len(ms) > 1 else ms[0]
        key = (a, b) if a < b else (b, a)
        o = out.get(key, (0.0, 0))
        out[key] = (max(o[0], m2), o[1] + len(ms))
    return out


def variant_pairs(lib_chars) -> set[tuple[str, str]]:
    """库里两个字都有、且算「同一个字的不同写法」的对：语义表归到同一个字，或关系层有高置信来源的边。"""
    from open_guji_cv import variants as VG
    from open_guji_cv.clustering.variants import VariantMap
    vm, cs, out = VariantMap.load(), set(lib_chars), set()
    by_sem: dict[str, list[str]] = {}
    for c in cs:
        by_sem.setdefault(vm.semantic(c), []).append(c)
    for g in by_sem.values():
        out |= {(x, y) for x in g for y in g if x < y}
    for x in cs:
        for y, src in VG.variants_of(x):
            if y in cs and x < y and set(src) & VG.HIGH_CONFIDENCE_SOURCES:
                out.add((x, y))
    return out


def variant_rows(E, chars, use) -> list[tuple[int, int, float]]:
    """每个库内异体对，两个方向各取每个刻例在对家字里 CNN 最像的一例（每个方向至多 40 个刻例）。"""
    rows: dict[str, list[int]] = {}
    for i in np.nonzero(use)[0]:
        rows.setdefault(str(chars[i]), []).append(int(i))
    out = []
    for x, y in sorted(variant_pairs(rows)):
        for a, b in ((x, y), (y, x)):
            ia, ib = np.array(rows[a][:40]), np.array(rows[b])
            sim = E[ia] @ E[ib].T
            out += [(int(i), int(ib[k]), float(sim[n, k])) for n, (i, k) in enumerate(zip(ia, sim.argmax(1)))]
    return out


def trusted_rows(E, chars, cells, human, use) -> np.ndarray:
    """可信刻例＝人裁的，加上「CNN 最像的那张人裁刻例（不同格）和它同字」的机器进库刻例。

    机器进库的标签有错位（殿本对齐进库的「祖」图上是「太」；同一张图挂在两个字下）。不筛的话这些错标刻例
    两三张就能把一对毫不相干的常用字顶到近度 1.0（殿本实测：我/錄、聖/謨、一/二）。"""
    hi = np.flatnonzero(human & use)
    out = human.copy()
    if not len(hi):
        return out
    for s in range(0, len(E), 2000):
        sim = E[s:s + 2000] @ E[hi].T
        sim[cells[s:s + 2000, None] == cells[hi][None, :]] = -2
        out[s:s + 2000] |= chars[hi[sim.argmax(1)]] == chars[s:s + 2000]
    return out


def mine(a) -> int:
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.near_route import WIDE_NEAR
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    from open_guji_cv.clustering.sim_cnn import embed, load_calib, load_net
    db = GlyphDB(a.db)
    m, _ = load_matcher_from_db(db)
    human = {str(r[0]) for r in db.conn.execute("SELECT DISTINCT instance_id FROM admissions WHERE provenance = 'human'")}
    held: set[str] = set()
    for f in a.exclude:
        held |= {_cell(x["instance_id"]) for x in json.loads(Path(f).read_text(encoding="utf-8"))["instances"]}
    use = np.array([_cell(str(i)) not in held and not str(i).startswith("font:") for i in m._ids])
    chars = np.array(m._chars)
    for f in a.exclude_chars:          # 整字类不用（对抗评测集留出当「库外字」的那些字）
        use &= ~np.isin(chars, Path(f).read_text(encoding="utf-8").split())
    cal = load_calib(a.model)
    if cal is None:
        raise SystemExit(f"{a.model} 旁没有 calib.json：近度要两路分在同一尺度上，先跑 scripts/fit_glyph_sim_calib.py")
    E = embed(load_net(a.model), m._patches)
    cells = np.array([_cell(str(i)) for i in m._ids])
    if a.trusted:
        use &= trusted_rows(E, chars, cells, np.array([str(i) in human for i in m._ids]), use)
    by_cell: dict[str, list[int]] = {}
    for j, c in enumerate(cells):
        by_cell.setdefault(c, []).append(j)
    idx = np.nonzero(use)[0]
    pairs: list[tuple[int, int, float]] = []
    for s in range(0, len(idx), 1000):
        ii = idx[s:s + 1000]
        sim = E[ii] @ E.T
        sim[:, ~use] = -2
        for k, i in enumerate(ii):
            r = sim[k]
            r[chars == chars[i]] = -2
            r[by_cell[cells[i]]] = -2          # 同一物理格挂在别的字下的行：同一张图，不是形近
            cand = np.argpartition(-r, 40)[:40]
            got: dict[str, tuple[int, float]] = {}
            for j in cand[np.argsort(-r[cand])]:
                if r[j] <= -2:
                    break
                c = chars[j]
                if c not in got:
                    got[c] = (int(j), float(r[j]))
                    if len(got) >= TOPC:
                        break
            pairs += [(int(i), j, v) for j, v in got.values()]
    _P[:] = m._patches
    ij = [(i, j) for i, j, _ in pairs]
    with Pool(a.procs) as p:          # fork：子进程带着 _P
        cov = [v for ch in p.map(_cov, [ij[k:k + 500] for k in range(0, len(ij), 500)]) for v in ch]
        vij = variant_rows(E, chars, use)
        vcov = [v for ch in p.map(_cov, [[(i, j) for i, j, _ in vij[k:k + 500]] for k in range(0, len(vij), 500)]) for v in ch]
    cn = np.interp([v for _, _, v in pairs], *cal)
    near = near_from_scores([(str(chars[i]), str(chars[j]), float((c + v) / 2)) for (i, j, _), c, v in zip(pairs, cn, cov)])
    vcn = np.interp([v for _, _, v in vij], *cal) if vij else []
    vnear = near_from_scores([(str(chars[i]), str(chars[j]), float((c + v) / 2)) for (i, j, _), c, v in zip(vij, vcn, vcov)])
    keep = {x + y: [round(n, 4), cnt] for (x, y), (n, cnt) in sorted(near.items(), key=lambda t: -t[1][0]) if n >= WIDE_NEAR}
    Path(a.out).write_text(json.dumps({"book": a.book, "db": Path(a.db).name, "model": str(a.model), "lib_rows": int(use.sum()), "trusted_only": bool(a.trusted),
                                       "pairs": keep,
                                       "variants": {x + y: [round(n, 4), cnt] for (x, y), (n, cnt) in sorted(vnear.items(), key=lambda t: -t[1][0])}},
                                      ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{a.book}：刻例 {int(use.sum())}、候选对 {len(pairs)} → 近度 ≥{WIDE_NEAR} 的 {len(keep)} 对；库内异体对 {len(vnear)} → {a.out}")
    return 0


def merge(a) -> int:
    from open_guji_cv.clustering import confusable as C
    from open_guji_cv.clustering.near_route import CORE_NEAR, VAR_NEAR, WIDE_NEAR
    tab: dict[str, dict] = {}

    def add(x: str, y: str, src: str, book: str | None = None, near: float | None = None):
        if x == y:
            return
        k = x + y if x < y else y + x
        e = tab.setdefault(k, {"src": [], "near": {}})
        if src not in e["src"]:
            e["src"].append(src)
        if book is not None:
            e["near"][book] = max(near, e["near"].get(book, 0.0))

    drop = {}
    if a.drop and Path(a.drop).exists():
        for line in Path(a.drop).read_text(encoding="utf-8").splitlines():
            p = line.split("\t")
            if not line.startswith("#") and len(p[0]) == 2:
                drop["".join(sorted(p[0]))] = p[1] if len(p) > 1 else ""
    books = {}
    for f in a.mined:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        books[d["book"]] = {"lib_rows": d["lib_rows"], "trusted_only": d.get("trusted_only", False), "model": Path(d["model"]).parent.name,
                            "pairs": len(d["pairs"])}
        for k, (n, _) in d["pairs"].items():
            x, y = list(k)
            add(x, y, f"lib:{d['book']}", d["book"], n)
        for k, (n, _) in d.get("variants", {}).items():
            if n >= VAR_NEAR:
                x, y = list(k)
                add(x, y, "variant", d["book"], n)
    for x, y in C.NEVER_MATCH_FAMILIES:
        add(x, y, "hand")
    for x, y in C._flat(C.HUMAN_TABLE):
        add(x, y, "human")
    for x, y in C.font_pairs():
        add(x, y, "font")
    for f in a.variants or ():
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            p = line.split("\t")
            if len(p) >= 2 and len(p[0]) == 1 and len(p[1]) == 1:
                add(p[0], p[1], "variant")
    dropped = sorted(k for k in tab if k in drop and not {"hand", "human"} & set(tab[k]["src"]))   # 人核过的对不受剔除名单管
    for k in dropped:
        del tab[k]
    for e in tab.values():
        e["src"].sort()
        e["core"] = bool({"hand", "human", "variant"} & set(e["src"])) or any(n >= CORE_NEAR for n in e["near"].values())
        if not e["near"]:
            del e["near"]
    from open_guji_cv.groups.registry import FLOW_GROUPS     # 第 7 步字组注册表：哪个字已经有组、哪一对已经在同一组里（有判法）
    char_groups: dict[str, list[str]] = {}
    for g in FLOW_GROUPS.values():
        for c in g.members:
            char_groups.setdefault(c, []).append(g.id)
    for k, e in tab.items():
        shared = sorted(set(char_groups.get(k[0], ())) & set(char_groups.get(k[1], ())))
        if shared:
            e["group"] = shared
    pairs = dict(sorted(tab.items(), key=lambda t: (not t[1]["core"], -max(t[1].get("near", {}).values(), default=0), t[0])))
    core = [k for k, e in pairs.items() if e["core"]]
    doc = ("形近字组表（scripts/build_near_groups.py 生成，读法见 open_guji_cv/clustering/near_route.py）。pairs 的键是两个字，"
           "src：lib:<书>＝从该书字形库挖的（near 是近度）、hand／human／font＝confusable.py 的三张表、variant＝同形异码；"
           f"core＝核心对（手工、人裁、同形异码，或某本书近度 ≥{CORE_NEAR}）；全表另含近度 ≥{WIDE_NEAR} 的库内对与字体表。"
           "group＝这一对两个字同在第 7 步字组注册表（groups/registry.py）的哪个组里，有它就是已经有判法；char_groups＝注册表里每个字属哪些组"
           "（注册表是字组的单一真源，这里只是生成时抄的一份，供第 5 步不 import groups 包就能查）。"
           "名单用前要人看一遍：库里挖的对有少量是切图丢偏旁造成的假形近。")
    Path(a.out).write_text(json.dumps({"_doc": doc, "books": books, "n_dropped": len(dropped), "n_pairs": len(pairs), "n_core": len(core),
                                       "n_chars": len({c for k in pairs for c in k}),
                                       "n_core_chars": len({c for k in core for c in k}),
                                       "n_core_in_group": sum(1 for k in core if "group" in pairs[k]),
                                       "char_groups": dict(sorted(char_groups.items())), "pairs": pairs},
                                      ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"核心对里两个字已在同一个字组（第 7 步有判法）的 {sum(1 for k in core if 'group' in pairs[k])} 对")
    print(f"合表：剔除名单去掉 {len(dropped)} 对；{len(pairs)} 对／{len({c for k in pairs for c in k})} 字，其中核心 {len(core)} 对／{len({c for k in core for c in k})} 字 → {a.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mine")
    m.add_argument("--book", required=True)
    m.add_argument("--db", required=True)
    m.add_argument("--model", required=True)
    m.add_argument("--exclude", action="append", default=[])
    m.add_argument("--exclude-chars", action="append", default=[], help="每行一个字的文件：这些字的刻例整类不用")
    m.add_argument("--trusted", action="store_true", help="只用可信刻例（人裁的＋CNN 最像的人裁刻例与它同字的）；机器进库标签不干净的书用")
    m.add_argument("--procs", type=int, default=4)
    m.add_argument("--out", required=True)
    g = sub.add_parser("merge")
    g.add_argument("mined", nargs="*")
    g.add_argument("--variants", action="append")
    g.add_argument("--drop", default=str(ROOT / "config" / "near_groups_drop.tsv"), help="剔除名单：每行 `两个字<TAB>原因`")
    g.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return mine(a) if a.cmd == "mine" else merge(a)


if __name__ == "__main__":
    raise SystemExit(main())
