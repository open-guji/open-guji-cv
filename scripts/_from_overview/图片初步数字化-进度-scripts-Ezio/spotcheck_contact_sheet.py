#!/usr/bin/env python3
"""放行格随机抽检联系页（GUJI-208lb；沿用 overlay_review.py / S8 看图的叠图口径）。

做什么：窗口甲前后各有一份产物根（A＝基线，B＝新）。找出「新放行格」＝B 里 admit=True 而 A 里 admit=False
（A 里没有这一格也算新放行，名单里标「基线无此格」）；按册分层随机抽 N 格，每格出一张叠图，拼成联系页，
并给一张回填表，由整理（Lucian）看图填 对／错／不定；填完用 summarize 汇总「错放几格」。

三个子命令（要 cv 仓 venv 里的 python：需要 cv2、numpy、PIL、fontTools；不需要 import open_guji_cv）：
  gen        出名单、抽样、叠图、联系页、回填表
  summarize  读填好的回填表，汇总错放
  selftest   造小产物根跑三种情形（无新放行／有新放行／某册 0 新放行），并核对没改任何输入文件

产物根布局（和 products/ 一致，只读）：
  <根>/<册>/seed_admit/pNNNN.json   columns[].chars[]：id、admit、char、channel、doubts、evidence{cov,verdict}
  <根>/<册>/cell_shrink/pNNNN.json  char_index.columns[].chars[]：id、bbox_page（x 是镜像 W−x）、ink_ratio
也可以把 --base／--new 指向 cell_table 的 jsonl(.gz)（Ethan 的 exports/cell_table/volNN_base.jsonl.gz，每行 id/admit/char/channel…）。
此时框要另给 --geom-root（含 <册>/cell_shrink/ 的产物根），缺省用 --new 本身。

用法：
  python spotcheck_contact_sheet.py gen --base <A根> --new <B根> --books vol01,vol02 --seed 20261015 --n 60 \\
      --raw-root <原图根，下面 <册>/<页>.png> --out <输出目录> [--geom-root <根>] [--cv-dir <open-guji-cv>]
  python spotcheck_contact_sheet.py summarize --sheet <输出目录>/回填表.tsv
  python spotcheck_contact_sheet.py selftest [--keep <目录>]

抽样规则：每册新放行数 k_b；总数 N 按 k_b 比例分配（四舍五入），每册至少 min(5,k_b)，至多 k_b（所以各册之和可能略多于 N，
gen 会打印）。册内先按 (页,列,格号,sub) 排序，再用 random.Random(f"{种子}:{册}").sample 抽，同一输入同一种子同一结果。

边界：只读——不改 --base／--new／--geom-root／--raw-root 下任何文件，只写 --out（--out 落在输入根里面直接拒绝）；
不写事件、不写 products、不碰字形库；看图结论不是人裁，也不导入 vision-gate。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import overlay_review as ov  # noqa: E402  复用叠图口径（build_tile／mirror_x／pick_font）

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ID_RE = ov.ID_RE
JUDGE = {"对": "对", "错": "错", "不定": "不定", "ok": "对", "wrong": "错", "unsure": "不定"}


def id_key(cid: str):
    m = ID_RE.match(cid)
    return (m["book"], int(m["page"]), int(m["col"]), int(m["slot"]), m["sub"] or "")


# ───────────── 读 admit 表 ─────────────
def _iter_seed_admit_dir(root: Path, book: str):
    d = root / book / "seed_admit"
    if not d.is_dir():
        return
    for f in sorted(d.glob("p*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 读不了 {f}：{e}", file=sys.stderr)
            continue
        for col in (data.get("seed_admit") or {}).get("columns", []):
            for c in col.get("chars", []):
                ev = c.get("evidence") or {}
                yield {"id": c["id"], "admit": bool(c.get("admit")), "char": c.get("char") or "",
                       "channel": c.get("channel") or "", "doubts": c.get("doubts") or [],
                       "verdict": ev.get("verdict") or "", "cov": ev.get("cov")}


def _iter_table(path: Path, book: str):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        for l in f:
            d = json.loads(l)
            if d.get("header") or "id" not in d:
                continue
            if not d["id"].startswith(book + ":"):
                continue
            yield {"id": d["id"], "admit": bool(d.get("admit")), "char": d.get("char") or "",
                   "channel": d.get("channel") or "", "doubts": d.get("doubts") or [],
                   "verdict": d.get("verdict") or "", "cov": d.get("cov")}


def load_admit(src: Path, book: str) -> dict[str, dict]:
    it = _iter_table(src, book) if src.is_file() else _iter_seed_admit_dir(src, book)
    return {r["id"]: r for r in it}


# ───────────── 新放行名单与抽样 ─────────────
def new_admits(base: dict[str, dict], new: dict[str, dict]) -> list[dict]:
    out = []
    for cid, r in new.items():
        if not r["admit"]:
            continue
        b = base.get(cid)
        if b is not None and b["admit"]:
            continue
        out.append({**r, "in_base": b is not None})
    out.sort(key=lambda r: id_key(r["id"]))
    return out


def allocate(counts: dict[str, int], n: int) -> dict[str, int]:
    total = sum(counts.values())
    alloc = {}
    for b, k in counts.items():
        if k == 0:
            alloc[b] = 0
            continue
        want = round(n * k / total) if total else 0
        alloc[b] = min(k, max(min(5, k), want))
    return alloc


def sample_cells(cells_by_book: dict[str, list[dict]], alloc: dict[str, int], seed) -> dict[str, list[dict]]:
    out = {}
    for b, cells in cells_by_book.items():
        k = alloc.get(b, 0)
        out[b] = sorted(random.Random(f"{seed}:{b}").sample(cells, k), key=lambda r: id_key(r["id"])) if k else []
    return out


# ───────────── 叠图 ─────────────
def load_geom(geom_root: Path, book: str, page: int):
    f = geom_root / book / "cell_shrink" / f"p{page:04d}.json"
    if not f.exists():
        return None
    ci = json.loads(f.read_text(encoding="utf-8")).get("char_index") or {}
    return {c["id"]: (c, col["chars"]) for col in ci.get("columns", []) for c in col.get("chars", [])}


def make_tiles(rows: list[dict], geom_root: Path, raw_root: Path | None, cv_dir: Path, font: str | None, out: Path):
    (out / "叠图").mkdir(parents=True, exist_ok=True)
    ov.CAPTION_FONT = font or str(cv_dir / "fonts" / "iming" / "I.Ming-8.10.ttf")
    geom_cache, img_cache, tiles, fails = {}, {}, [], []
    for r in rows:
        b, p = id_key(r["id"])[:2]
        if (b, p) not in geom_cache:
            geom_cache[(b, p)] = load_geom(geom_root, b, p)
        g = geom_cache[(b, p)]
        if g is None or r["id"] not in g:
            fails.append((r["id"], f"没有 {b} p{p:04d} 的 cell_shrink 框"))
            continue
        if (b, p) not in img_cache:
            cand = [raw_root / b / f"{p}.png"] if raw_root else []
            img_cache[(b, p)] = next((cv2.imread(str(c), cv2.IMREAD_GRAYSCALE) for c in cand if c.exists()), None)
        raw = img_cache[(b, p)]
        if raw is None:
            fails.append((r["id"], "原图读不出来"))
            continue
        cell, chars = g[r["id"]]
        W = raw.shape[1]
        box = ov.mirror_x(cell["bbox_page"], W)
        sib = [ov.mirror_x(c["bbox_page"], W) for c in chars if c["id"] != r["id"]]
        fp = ov.pick_font(r["char"], cv_dir, font) if r["char"] else None
        tile = ov.build_tile(raw, box, sib, r, r["id"], fp)
        cv2.imwrite(str(out / "叠图" / (r["id"].replace(":", "_") + ".png")), tile)
        tiles.append((r, tile))
    return tiles, fails


def write_sheets(tiles, out: Path, per: int = 24):
    names = []
    for si in range(0, len(tiles), per):
        chunk = [t for _, t in tiles[si:si + per]]
        w = max(t.shape[1] for t in chunk)
        pad = lambda im: np.hstack([im, np.full((im.shape[0], w - im.shape[1], 3), 255, np.uint8)]) if im.shape[1] < w else im
        lines = []
        for r in range(0, len(chunk), 2):
            seg = [pad(t) for t in chunk[r:r + 2]]
            while len(seg) < 2:
                seg.append(np.full_like(seg[0], 255))
            lines.append(np.hstack(seg))
        nm = f"联系页{si // per + 1:02d}.png"
        cv2.imwrite(str(out / nm), np.vstack(lines))
        names.append(nm)
    return names


def write_tsv(path: Path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ───────────── gen ─────────────
def cmd_gen(a) -> int:
    base, new = Path(a.base), Path(a.new)
    geom = Path(a.geom_root) if a.geom_root else new
    out = Path(a.out)
    for inp in (base, new, geom, Path(a.raw_root) if a.raw_root else None):
        if inp is not None and (inside(out, inp) or inside(inp, out)):
            sys.exit(f"--out 不能和输入根互相包含：{out} ／ {inp}")
    cv_dir = Path(a.cv_dir)
    books = [b for b in a.books.split(",") if b]
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    cells_by_book = {}
    for b in books:
        cells_by_book[b] = new_admits(load_admit(base, b), load_admit(new, b))
    counts = {b: len(v) for b, v in cells_by_book.items()}
    all_new = [r for b in books for r in cells_by_book[b]]
    write_tsv(out / "新放行格名单.tsv", ["id", "册", "字", "通道", "基线有此格", "verdict", "cov", "doubts"],
              [[r["id"], id_key(r["id"])[0], r["char"], r["channel"], "是" if r["in_base"] else "基线无此格",
                r["verdict"], "" if r["cov"] is None else r["cov"], ",".join(r["doubts"])] for r in all_new])

    alloc = allocate(counts, a.n)
    picked = sample_cells(cells_by_book, alloc, a.seed)
    rows = [r for b in books for r in picked[b]]
    write_tsv(out / "抽样名单.tsv", ["id", "册", "字", "通道"], [[r["id"], id_key(r["id"])[0], r["char"], r["channel"]] for r in rows])

    t1 = time.perf_counter()
    tiles, fails = make_tiles(rows, geom, Path(a.raw_root) if a.raw_root else None, cv_dir, a.font, out)
    t2 = time.perf_counter()
    sheets = write_sheets(tiles, out, a.per) if tiles else []
    t3 = time.perf_counter()
    done = {r["id"] for r, _ in tiles}
    write_tsv(out / "回填表.tsv", ["id", "放行字", "看图判读", "备注"],
              [[r["id"], r["char"], "", ""] for r in rows if r["id"] in done])

    md = [f"# 放行格随机抽检联系页（种子 {a.seed}，N={a.n}）", "",
          f"- 基线 A：`{base}`；新 B：`{new}`", "- 每册：新放行数／抽样数："]
    for b in books:
        md.append(f"  - {b}：{counts[b]}／{alloc[b]}" + ("（0 新放行，不抽）" if counts[b] == 0 else ""))
    md += [f"- 新放行总数 {len(all_new)}，抽样 {len(rows)}，成图 {len(tiles)}，联系页 {len(sheets)} 张",
           "- 每格四联图：原字块局部（红框＝目标格，浅蓝＝同列其它格）｜原字块放大｜放行字字形｜字形半透明叠在原字块上",
           "- 判读写进 `回填表.tsv` 的「看图判读」列：对＝放行字对；错＝放行字错；不定＝看不清。没把握写不定。",
           "", "| 序号 | 格 | 放行字 | 通道 | 联系页 |", "|---|---|---|---|---|"]
    for k, (r, _) in enumerate(tiles):
        md.append(f"| {k + 1} | `{r['id']}` | {r['char']} | {r['channel']} | {sheets[k // a.per]} |")
    for cid, why in fails:
        md.append(f"| — | `{cid}` | | | ⚠ {why} |")
    (out / "联系页.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"新放行 {len(all_new)} 格（各册 {counts}）；抽样 {len(rows)} 格（各册 {alloc}）；成图 {len(tiles)}；联系页 {len(sheets)} 张 → {out}")
    print(f"耗时：出名单＋抽样 {t1 - t0:.1f}s；出叠图 {t2 - t1:.1f}s；出联系页 {t3 - t2:.1f}s")
    for cid, why in fails:
        print(f"⚠ {cid}：{why}", file=sys.stderr)
    miss = sorted({id_key(c)[:2] for c, why in fails if "cell_shrink" in why})
    if miss:
        pg = defaultdict(list)
        for b, p in miss:
            pg[b].append(p)
        print("⚠ 这些页没有 cell_shrink 框（先在沙箱补，GUJI_PRODUCTS_DIR 设沙箱，不要写正式 products）：", file=sys.stderr)
        for b, ps in pg.items():
            print(f"   guji-cv pipeline keben_body_v2 {b} --to cell_shrink --pages {','.join(map(str, ps))} -w <工作区>", file=sys.stderr)
    return 1 if fails else 0


# ───────────── summarize ─────────────
def cmd_summarize(a) -> int:
    rows = list(csv.DictReader(Path(a.sheet).open(encoding="utf-8", newline=""), delimiter="\t"))
    per = defaultdict(lambda: {"对": 0, "错": 0, "不定": 0, "未填": 0})
    bad, errors = [], []
    for r in rows:
        raw = (r.get("看图判读") or "").strip()
        b = id_key(r["id"])[0]
        if not raw:
            per[b]["未填"] += 1
            continue
        j = JUDGE.get(raw)
        if j is None:
            errors.append(f"{r['id']}：看不懂的判读「{raw}」（只认 对／错／不定）")
            continue
        per[b][j] += 1
        if j == "错":
            bad.append(r)
    if errors:
        print("回填表有问题，先改：\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2
    tot = {k: sum(v[k] for v in per.values()) for k in ("对", "错", "不定", "未填")}
    print("册\t对\t错\t不定\t未填")
    for b in sorted(per):
        v = per[b]
        print(f"{b}\t{v['对']}\t{v['错']}\t{v['不定']}\t{v['未填']}")
    print(f"合计\t{tot['对']}\t{tot['错']}\t{tot['不定']}\t{tot['未填']}")
    judged = tot["对"] + tot["错"]
    print(f"\n错放 {tot['错']} 格（已判 对／错 共 {judged} 格，不定 {tot['不定']}，未填 {tot['未填']}）")
    if tot["错"]:
        print("错放格：")
        for r in bad:
            print(f"  {r['id']}  放行字={r.get('放行字', '')}  {r.get('备注', '')}")
        print("⚠ 有错放，红线触发：按队列「放行格随机抽检」记入 #473。")
    elif judged:
        print(f"抽检内 0 错放（rule of three：这一批的错放率 95% 上界约 {3 / judged:.1%}；不定与未填不算对）。")
    if tot["未填"]:
        print(f"⚠ 还有 {tot['未填']} 格没填，结论不完整。")
    return 1 if tot["错"] else 0


# ───────────── selftest ─────────────
def _mk_page(root: Path, raw_root: Path, book: str, page: int, ids_admit: list[tuple[int, int, str, bool]], W=600, H=800):
    """造一页：原图（白底，每格画一个黑块）＋ cell_shrink ＋ seed_admit。ids_admit=[(col,slot,char,admit)]"""
    img = np.full((H, W), 255, np.uint8)
    chars_geom, chars_adm = [], []
    for col, slot, ch, adm in ids_admit:
        x0, y0 = 60 + (col - 1) * 120, 60 + (slot - 1) * 100
        box = [x0, y0, x0 + 90, y0 + 90]
        img[box[1] + 20:box[3] - 20, box[0] + 20:box[2] - 20] = 0
        cid = f"{book}:{page}:{col}:{slot}"
        chars_geom.append({"id": cid, "bbox_page": [W - box[2], box[1], W - box[0], box[3]], "ink_ratio": 0.3, "slot": slot})
        chars_adm.append({"id": cid, "admit": adm, "char": ch, "channel": "match_ref" if adm else None, "doubts": [],
                          "evidence": {"cov": 0.9, "verdict": "unsure"}, "slot": slot})
    (raw_root / book).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(raw_root / book / f"{page}.png"), img)
    for step, key, payload in (("cell_shrink", "char_index", chars_geom), ("seed_admit", "seed_admit", chars_adm)):
        d = root / book / step
        d.mkdir(parents=True, exist_ok=True)
        (d / f"p{page:04d}.json").write_text(json.dumps({key: {"columns": [{"col": 1, "chars": payload}], "page": page}}, ensure_ascii=False), encoding="utf-8")


def _tree_hash(*roots: Path) -> str:
    h = hashlib.sha256()
    for r in roots:
        for f in sorted(p for p in r.rglob("*") if p.is_file()):
            h.update(str(f.relative_to(r)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def cmd_selftest(a) -> int:
    tmp = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="spotcheck_selftest_"))
    tmp.mkdir(parents=True, exist_ok=True)
    cv_dir = Path(a.cv_dir)
    chars = "天地玄黃宇宙洪荒日月盈昃辰宿列張"
    fails = 0

    def build(case):
        base, new, raw = tmp / case / "A", tmp / case / "B", tmp / case / "raw"
        for b in ("vol01", "vol02"):
            for p in (1, 2):
                cells = [(c, s, chars[(c * 3 + s + p) % len(chars)]) for c in (1, 2, 3) for s in (1, 2, 3, 4)]
                _mk_page(base, raw, b, p, [(c, s, ch, False) for c, s, ch in cells])
                if case == "1_无新放行":
                    admit = lambda c, s: False
                elif case == "2_有新放行":
                    admit = lambda c, s, b=b: (c + s) % 2 == 0 if b == "vol01" else (c == 1 and s == 1)
                else:  # 3_某册0新放行：vol02 一个也不放
                    admit = lambda c, s, b=b: (c + s) % 2 == 0 if b == "vol01" else False
                _mk_page(new, raw, b, p, [(c, s, ch, admit(c, s)) for c, s, ch in cells])
        return base, new, raw

    def run_gen(case, seed, n):
        base, new, raw = build(case) if not (tmp / case / "A").exists() else (tmp / case / "A", tmp / case / "B", tmp / case / "raw")
        out = tmp / case / f"out_s{seed}"
        before = _tree_hash(base, new, raw)
        ns = argparse.Namespace(base=str(base), new=str(new), geom_root=None, raw_root=str(raw), out=str(out), books="vol01,vol02",
                                seed=seed, n=n, cv_dir=str(cv_dir), font=None, per=24)
        rc = cmd_gen(ns)
        after = _tree_hash(base, new, raw)
        return out, rc, before == after

    def check(cond, msg):
        nonlocal fails
        print(("  ✓ " if cond else "  ✗ ") + msg)
        fails += 0 if cond else 1

    def ids_of(out, f="抽样名单.tsv"):
        return [r["id"] for r in csv.DictReader((out / f).open(encoding="utf-8"), delimiter="\t")]

    for case in ("1_无新放行", "2_有新放行", "3_某册0新放行"):
        print(f"\n=== 情形 {case} ===")
        out, rc, same = run_gen(case, 7, 10)
        newl, samp = ids_of(out, "新放行格名单.tsv"), ids_of(out)
        check(same, "输入文件（A／B／原图）运行前后哈希一致，没被改")
        if case == "1_无新放行":
            check(len(newl) == 0 and len(samp) == 0, f"新放行 {len(newl)}、抽样 {len(samp)}（应为 0／0），脚本正常结束 rc={rc}")
        elif case == "2_有新放行":
            check(len(newl) > 0 and 0 < len(samp) <= len(newl), f"新放行 {len(newl)}、抽样 {len(samp)}")
            out2, _, _ = run_gen(case, 7, 10)
            check(ids_of(out2) == samp, "同种子再抽，名单完全一致（可复现）")
            out3, _, _ = run_gen(case, 8, 10)
            check(ids_of(out3) != samp or len(samp) == len(newl), "换种子，名单变化")
            png = len(list((out / "叠图").glob("*.png")))
            check(png == len(samp) and (out / "联系页01.png").exists(), f"叠图 {png} 张、联系页01.png 已出")
            # 回填：把前一半写 对、一格写 错、一格不填 → summarize
            tsv = out / "回填表.tsv"
            rows = list(csv.DictReader(tsv.open(encoding="utf-8"), delimiter="\t"))
            for i, r in enumerate(rows):
                r["看图判读"] = "对" if i < len(rows) - 2 else ("错" if i == len(rows) - 2 else "")
            write_tsv(tsv, ["id", "放行字", "看图判读", "备注"], [[r["id"], r["放行字"], r["看图判读"], r["备注"]] for r in rows])
            print("--- summarize（造了 1 格错、1 格未填） ---")
            rc2 = cmd_summarize(argparse.Namespace(sheet=str(tsv)))
            check(rc2 == 1, "summarize 返回 1（有错放）")
        else:
            by = defaultdict(int)
            for i in newl:
                by[id_key(i)[0]] += 1
            sb = defaultdict(int)
            for i in samp:
                sb[id_key(i)[0]] += 1
            check(by.get("vol02", 0) == 0 and sb.get("vol02", 0) == 0 and sb.get("vol01", 0) > 0,
                  f"vol02 0 新放行 0 抽样；vol01 新放行 {by['vol01']} 抽 {sb['vol01']}")
    # 小册：每册至少 min(5,k)
    print("\n=== 分层名额：vol01 新放行 32、vol02 新放行 2 时，N=10 ===")
    al = allocate({"vol01": 32, "vol02": 2, "vol03": 0}, 10)
    check(al == {"vol01": 9, "vol02": 2, "vol03": 0} or (al["vol02"] == 2 and al["vol03"] == 0 and al["vol01"] >= 8), f"分配 {al}")
    print(f"\n自测目录：{tmp}")
    print("自测通过" if not fails else f"自测有 {fails} 项失败")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--base", required=True)
    g.add_argument("--new", required=True)
    g.add_argument("--geom-root")
    g.add_argument("--books", required=True, help="逗号分隔，如 vol01,vol02")
    g.add_argument("--seed", required=True)
    g.add_argument("--n", type=int, required=True)
    g.add_argument("--raw-root")
    g.add_argument("--out", required=True)
    g.add_argument("--cv-dir", default=str(Path.home() / "open-guji-cv") if (Path.home() / "open-guji-cv").exists() else "/home/user/open-guji-cv")
    g.add_argument("--font")
    g.add_argument("--per", type=int, default=24)
    s = sub.add_parser("summarize")
    s.add_argument("--sheet", required=True)
    t = sub.add_parser("selftest")
    t.add_argument("--keep")
    t.add_argument("--cv-dir", default="/home/user/open-guji-cv")
    a = ap.parse_args(argv)
    if a.cmd == "gen":
        if a.per > 24:
            sys.exit("--per 最大 24")
        return cmd_gen(a)
    return {"summarize": cmd_summarize, "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
