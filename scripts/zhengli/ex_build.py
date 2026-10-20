#!/usr/bin/env python3
"""同字例子雪碧图 `ex`（GUJI-557 / P1-4，字段表 ai-team team/CV/guji-proof-0.2-字段表-GUJI-557.md §三）。

来源：ai-team `team/整理/GUJI-557/ex_build.py`，2026-10-20 迁入 cv `scripts/zhengli/`（GUJI-652）。
迁入适配：只给 main() 加了可选 argv 参数（便于测试），不依赖 cv 包与 ai-team 路径；从同目录 sprite_build.py import TILE／COLS／tile_of。
用途：给每个待审格的每个候选字挑本册已放行的同字实例（≤5 个），从原图裁出拼成雪碧图，在 pending 每格标 ex。
注意：下面用法示例里 `--store <工作区>/output/glyph_store` 是中心库切换前的落点；现在字形库真源在中心库，
本机副本在 `$GUJI_DATA_HOME/<分支>/<工作区 id>/output/glyph_store/`（`guji db sync` 后），跑时 --store 指那里。脚本逻辑未改。

读：pending.json（0.2 版，可已带 img）＋NNN.cord.json（格框，canvas 坐标，同 sprite_build）＋字形库真源 glyph_store
（admissions／evictions／instances/*.jsonl）＋原图根目录（<raw-root>/<册>/<页>.png）。只读，不写 cv、不进 book-text git。
**框用 cord 里该格现行的 canvas 框，不用实例行里存的 bbox**（实例 bbox 是旧切分／旧坐标系，对不上现行原图，实测裁出来全是错位碎片）；
实例号 [v1:|v2:]<册>:<页>:<列>:<格> 的 <页>:<列>:<格> 即 cord 的格号 a。所以例子只来自**本册**（cord 只有本册的框）；
跨册例子要各册的 cord，待有了再放开。
**还要求实例标签＝现行文本（NNN.char.json）里该格的字**：字形库实例是旧切分时标的，重切后格位移动，
不核对会混进别的字（实测「曰」例子里混进「講」「人」）。cord 页图尺寸与原图不等的页跳过（同 sprite_build）。
候选字（每格）＝ lib_top 前 3 ∪ ocr ∪ ref ∪ ctx 的字（对应字表 cand{lib,ocr,rare,ref} 与 lib_top 前 3 的并集）；
每个候选字取本书已放行（admissions 有、evictions 没撤）的实例，一页最多一个，最多 5 个，
按 label_status（human>其余）、label_confidence 降序、实例号稳定排序（字形库实例上没有 cov，这是与字表「按 cov 降序」的差别）；
己／已／巳 不省例子。本格自己的实例不当例子。不足 5 就有几个给几个，不用字体字形凑数。
产出到 --out（与 sprite_build.py 的 --out 同一目录即可）：
  ex-<章号>.webp       96×96 网格、WebP q80、宽 ≤2048（每行 21 格），行数过多时拆 ex-<章号>-b.webp…
  assets.json          追加 ex 文件条目（rev 须与 pending.rev 一致，否则退出）
  pending.with-ex.json 每格加 ex={候选字:[{s,x,y,w,h}…]}（没例子的候选字不出；全空则不加 ex 键）
用法：
    python3 scripts/zhengli/ex_build.py --pending <pending.json> --cord <NNN.cord.json> --char <NNN.char.json> --store <工作区>/output/glyph_store \
        --raw-root <工作区>/data_full/zongmu --chapter 001 --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprite_build import COLS, TILE, tile_of  # noqa: E402

MAX_EX, MAX_ROWS = 5, 150          # 150×96=14400 < WebP 16383


def read_jsonl(p: Path):
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def cell_chars(c: dict) -> list[str]:
    seq = [x["c"] for x in c.get("lib_top", [])[:3]] + [x["c"] for x in c.get("ocr", [])]
    seq += [c["ref"]["c"]] if c.get("ref") else []
    seq += [c["ctx"]["c"]] if c.get("ctx") and c["ctx"].get("c") else []
    out = []
    for ch in seq:
        if ch and ch not in out:
            out.append(ch)
    return out


def load_instances(store: Path) -> dict[str, list[dict]]:
    """字 → 可用实例（已放行、没撤、本书原图可定位）。"""
    adm = {r["instance_id"]: r["char"] for r in read_jsonl(store / "admissions.jsonl")}
    evicted = {r["instance_id"] for r in read_jsonl(store / "evictions.jsonl")}
    by_char: dict[str, list[dict]] = {}
    for f in sorted((store / "instances").glob("*.jsonl")):
        for r in read_jsonl(f):
            iid = r["instance_id"]
            ch = adm.get(iid)
            if not ch or iid in evicted or r.get("label") != ch:
                continue
            by_char.setdefault(ch, []).append(r)
    return by_char


def rank(r: dict):
    return (r.get("label_status") != "human", -(r.get("label_confidence") or 0.0), r["instance_id"])


def cell_of(iid: str, book: str) -> str | None:
    """实例号 → 本册格号 <页>:<列>:<格>；不是本册的返回 None。"""
    m = re.fullmatch(rf"(?:v\d+:)?{re.escape(book)}:(\d+:\d+:\w+)", iid)
    return m.group(1) if m else None


def pick(rows: list[dict], own: str, usable: dict[str, tuple], book: str, text: dict[str, str]) -> list[dict]:
    """usable：本册格号 → (页, 框, 页图信息)，只含框存在且原图尺寸对得上的格。"""
    out, pages = [], set()
    for r in sorted(rows, key=rank):
        a = cell_of(r["instance_id"], book)
        if a is None or a == own or a not in usable or text.get(a) != r["label"]:
            continue
        pg = usable[a][0]
        if pg in pages:
            continue
        pages.add(pg)
        out.append(dict(r, _a=a))
        if len(out) == MAX_EX:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pending", required=True, type=Path)
    ap.add_argument("--cord", required=True, type=Path)
    ap.add_argument("--char", required=True, type=Path, help="NNN.char.json（格号 a → 现行字 c）")
    ap.add_argument("--store", required=True, type=Path)
    ap.add_argument("--raw-root", required=True, type=Path, help="<工作区>/data_full/zongmu（下面是 <册>/<页>.png）")
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--book", help="册号前缀，如 vol01，用来排除本格自己的实例", default="vol01")
    ap.add_argument("--pad", type=float, default=0.08)
    a = ap.parse_args(argv)

    pend = json.loads(a.pending.read_text(encoding="utf-8"))
    by_char = load_instances(a.store)
    cord = json.loads(a.cord.read_text(encoding="utf-8"))
    chardoc = json.loads(a.char.read_text(encoding="utf-8"))
    text = {c["a"]: c["c"] for pg in chardoc["pages"] for col in pg["columns"] for c in col["cells"]}
    usable: dict[str, tuple] = {}
    bad_pages: set[int] = set()
    for pg in cord["pages"]:
        src = a.raw_root / a.book / f"{pg['page']}.png"
        if not src.is_file():
            continue
        if Image.open(src).size != (pg["image"]["width"], pg["image"]["height"]):
            bad_pages.add(pg["page"])
            continue
        for c in pg.get("cells", []):
            if c.get("box"):
                usable[c["a"]] = (pg["page"], c["box"], pg["image"])
    # 每个 (字, 本格号) 要排除自己的实例：实例号以 "<册>:<格号>" 结尾
    tiles: list[tuple[str, dict]] = []          # 拼图顺序：(实例号, 行)
    where: dict[str, int] = {}
    chosen: dict[tuple[str, str], list[dict]] = {}
    for c in pend["cells"]:
        for ch in cell_chars(c):
            rows = pick(by_char.get(ch, []), c["cell"], usable, a.book, text)
            chosen[(c["cell"], ch)] = rows
            for r in rows:
                if r["instance_id"] not in where:
                    where[r["instance_id"]] = len(tiles)
                    tiles.append((r["instance_id"], r))
    pos: dict[str, dict] = {}
    files = []
    per_sheet = COLS * MAX_ROWS
    imcache: dict[Path, Image.Image] = {}
    for si in range(0, len(tiles), per_sheet):
        part = tiles[si:si + per_sheet]
        name = f"ex-{a.chapter}.webp" if si == 0 else f"ex-{a.chapter}-{chr(ord('a') + si // per_sheet)}.webp"
        n = len(part)
        cols = min(COLS, n)
        sheet = Image.new("L", (cols * TILE, -(-n // cols) * TILE), 255)
        for i, (iid, r) in enumerate(part):
            src = a.raw_root / a.book / f"{usable[r['_a']][0]}.png"
            im = imcache.get(src)
            if im is None:
                imcache.clear()                # 一次只留一页
                im = imcache[src] = Image.open(src)
                im.load()
            box = usable[r["_a"]][1]
            x, y = (i % cols) * TILE, (i // cols) * TILE
            sheet.paste(tile_of(im, box, a.pad), (x, y))
            pos[iid] = {"s": name, "x": x, "y": y, "w": TILE, "h": TILE}
        p = a.out / name
        a.out.mkdir(parents=True, exist_ok=True)
        sheet.save(p, "WEBP", quality=80)
        raw = p.read_bytes()
        files.append({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                      "w": sheet.width, "h": sheet.height})
    ap_path = a.out / "assets.json"
    if ap_path.is_file():
        man = json.loads(ap_path.read_text(encoding="utf-8"))
        if man["rev"] != pend["rev"]:
            sys.exit(f"assets.json rev={man['rev']} 与 pending.rev={pend['rev']} 不一致")
        keep = [f for f in man["files"] if not re.fullmatch(rf"ex-{re.escape(a.chapter)}(-[a-z])?\.webp", f["name"])]
        man["files"] = keep + files
        ap_path.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cells = []
    n_ex = n_cells = 0
    for c in pend["cells"]:
        ex = {ch: [dict(pos[r["instance_id"]]) for r in chosen[(c["cell"], ch)]] for ch in cell_chars(c) if chosen[(c["cell"], ch)]}
        if ex:
            n_cells += 1
            n_ex += sum(len(v) for v in ex.values())
            c = dict(c, ex=ex)
        cells.append(c)
    (a.out / "pending.with-ex.json").write_text(json.dumps(dict(pend, cells=cells), ensure_ascii=False, indent=1), encoding="utf-8")
    miss = sorted({ch for (_, ch), v in chosen.items() if not v})
    if bad_pages:
        print(f"跳过 {len(bad_pages)} 页（原图与 cord 页图尺寸不等）：{sorted(bad_pages)[:20]}", file=sys.stderr)
    print(f"候选字 {len({ch for _, ch in chosen})}，唯一例子图 {len(tiles)}，带 ex 的格 {n_cells}/{len(pend['cells'])}，例子引用 {n_ex}，"
          f"无例子的候选字 {len(miss)}：{''.join(miss[:40])}，字节 {sum(f['bytes'] for f in files)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
