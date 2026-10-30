"""把 B 批列端(L3-batch 231 端)冻结成回归 fixture:tests/fixtures/colend/。

存什么:每个涉及的**整列** column_raw(1-bit PNG,朝向不变;224 个唯一列)+ manifest.json(每端:人判、冻结时的
规则档位/削行数)。为什么存整列不存端部 crop:clean_column 里的 strip_column_rules 等依赖整列统计,
实测端部 300 行 crop 重算只有 216/231 与产物一致,整列 1-bit 重算 231/231 一致(见 README)。

用法(需 GUJI_WORKSPACE/GUJI_PRODUCTS_DIR 指向含 vol02 原图+snap 产物的工作区):
  python3 -I build_fixture.py <items.jsonl> <out_dir> [--check-only]
  items.jsonl = dataset char-segmentation/column-end-class/items.jsonl(取 source=L3-batch)"""
import sys, json, pathlib, collections, numpy as np, cv2
from PIL import Image
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import column_key, page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.books.siku_zongmu.column import clean_column

def save_1bit(a: np.ndarray, fn) -> None:
    Image.fromarray(a >= 128).convert("1").save(fn, optimize=True)

def main(items, out, check_only=False):
    out = pathlib.Path(out); (out / "cols").mkdir(parents=True, exist_ok=True)
    book = load_book("vol02"); ctx = RunContext(book, ProductStore(), ImageCache(), log=lambda s: None)
    fl, og = book.frame_layers or {}, book.outer_gap or {}
    layers = [int(fl.get("top", 1)), int(fl.get("bottom", 1))]; gap = [og.get("top"), og.get("bottom")]
    cols, ends, bad = {}, [], 0
    for l in open(items, encoding="utf-8"):
        d = json.loads(l)
        if d["input"]["source"] != "L3-batch": continue
        _, pg, col, end = d["id"].split(":"); pg, col = int(pg), int(col); e = d["expected"]
        key = f"p{pg}_c{col}"
        if key not in cols:
            w = next(x for x in ctx.store.read("vol02", "column_warp", page_key(pg), "column_windows").columns if x.col == col)
            raw = cv2.imdecode(np.fromfile(str(ctx.materialize("column_raw", column_key(pg, col))), np.uint8), cv2.IMREAD_GRAYSCALE)
            b = np.where(raw < 128, 0, 255).astype(np.uint8)
            if not check_only: save_1bit(b, out / "cols" / f"{key}.png")
            cols[key] = dict(file=f"cols/{key}.png", page=pg, col=col, inner_bottom=round(float(w.border_bottom_in_column), 2), bin=b)
        c = cols[key]
        _, diag = clean_column(c["bin"], layers=tuple(layers), layer_gap=tuple(gap), inner_bottom=c["inner_bottom"])
        dd = diag["top" if end == "top" else "bottom"]
        if (dd["case"], int(dd["px"])) != (e["engine_trim_case"], int(e["engine_trim_px"])): bad += 1; print("不一致", d["id"], (e["engine_trim_case"], e["engine_trim_px"]), "->", (dd["case"], dd["px"]))
        ends.append(dict(id=d["id"], col_key=key, end=end, label=e["class"], frozen_case=e["engine_trim_case"], frozen_px=int(e["engine_trim_px"])))
    print(f"端 {len(ends)},唯一列 {len(cols)},1-bit 整列重算与冻结档位不一致 {bad}")
    print("人判分布", dict(collections.Counter(x["label"] for x in ends)))
    if not check_only:
        man = dict(book="vol02", layers=layers, layer_gap=gap,
                   source="dataset char-segmentation/column-end-class items.jsonl, L3-batch 231 端",
                   columns={k: {kk: vv for kk, vv in v.items() if kk != "bin"} for k, v in cols.items()}, ends=ends)
        json.dump(man, open(out / "manifest.json", "w"), ensure_ascii=False, indent=0)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--check-only" in sys.argv)
