#!/usr/bin/env python3
"""S8 看图脚本化：联系页生成 → 人（或模型）看图 → 结论回填 → 停在 vision-gate 之前。

只做「生成」「校验」「回填」，不替人下结论，不写事件／裁决／字形库（落库由 `zl.py` 的
vision-gate 步调 `guji events import-vision` 完成）。不改 `zl.py`、Step 模块、yaml，
不在任何 Step 的 `code_deps` 里，改它不会让产物过期。

三个子命令（`--ws` 是书所在工作区，`--book` 如 vol03）：

  gen    联系页：给格清单（`--cells vol03:22:8:7,…` 或 `--cells-file`；不给则取
         `<册>.放行错穷举.json` 的「认字差异」档），出 `reports/<册>/s8/联系页/*.png`、索引 md，
         以及一份待填简表 `看图简表.tsv`（verdict 列留空）。
  overlay 整页叠图：每格出整页缩略图（红框＝目标格，浅蓝＝同列其它格）＋局部 1:1，看「框到底落在原图哪里」。
         **坑**：`char_index` 的 `bbox_page`／`quad_page` 的 x 是镜像坐标（W−x），叠原图前必须翻回来（`mirror_x`）。
  check  校验简表或 jsonl：格式错（含缺 judge/ts、未知键）报行号；简表里还有空 verdict 的格也报。
  fill   简表 → `reports/<册>/看图结论.jsonl`（只追加；`ts`、`judge` 在这里填），随后
         `zl.py run --book <册> --ws <ws> --only vision-gate` 即可导入并过闸。

边界（Mila 审阅 10-14）：
- 沙箱里只做到 `fill`，**不跑 vision-gate 的正式导入**——`import-vision` 的裁决表分片会写进工作区本体，
  不认 `GUJI_FEEDBACK_DIR`；导入由 CV 经理或 H 道做。
- 「文意定、字形分不出」的格（曰/日、曰/目…）不是看图结论：`--wenyi-list 文意定人裁清单.jsonl`
  给了就拒收清单里 `id` 的 ok/wrong（unsure 允许），这些格必须走人裁。
- `fill` 同一份简表可重跑：同 cell＋v＋char 已在 jsonl 里的行跳过。

简表 `看图简表.tsv`（UTF-8，TAB 分隔，首行表头）：

  cell    verdict    char    shown    group    note
  vol03:22:8:7    ok|wrong|unsure    wrong 时填看图认为该是的字    放行字(gen 已预填)    形近组(可空)    理由(可空)

`verdict` 就是 vision.py 的 `v`（ok/wrong/unsure）。以 `open_guji_cv/feedback/vision.py` 为准。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import zl  # noqa: E402  同目录的 zl.py：复用联系页生成器，不复制

COLS = ["cell", "verdict", "char", "shown", "group", "note"]
TSV = "看图简表.tsv"


def _ctx(book: str, ws: str, sub: str = "s8"):
    """Ctx 的 reports 改指到 `reports/<册>/<sub>`：联系页和简表不写进 `reports/<册>/` 本体，
    也就不会覆盖真的 `<册>.放行错穷举.json`。"""
    ctx = zl.Ctx(SimpleNamespace(book=book, ws=ws, jobs=1, snap=None))
    ctx.main_reports = ctx.reports
    ctx.reports = ctx.reports / sub
    ctx.reports.mkdir(parents=True, exist_ok=True)
    return ctx


def read_cells(book: str, cells: str | None, cells_file: str | None, main_reports: Path) -> list[dict]:
    """格清单 → [{id, char, witness, ctx}]。没给就取放行错穷举的认字差异档。"""
    ids: list[str] = []
    if cells:
        ids += [c.strip() for c in cells.split(",") if c.strip()]
    if cells_file:
        ids += [l.split("#")[0].strip() for l in Path(cells_file).read_text(encoding="utf-8").splitlines()
                if l.split("#")[0].strip()]
    audit = main_reports / f"{book}.放行错穷举.json"
    known: dict[str, dict] = {}
    if audit.exists():
        known = {r["id"]: r for r in json.loads(audit.read_text(encoding="utf-8")).get("rows", [])}
    if not ids:
        if not known:
            sys.exit(f"没给 --cells，也没有 {audit.name}：先跑 zl.py 的 audit 步，或用 --cells 点名")
        return zl.contact_rows({"rows": list(known.values())})
    out = []
    for cid in ids:
        r = known.get(cid, {})
        out.append({"id": cid, "tier": "real", "char": r.get("char"), "witness": r.get("witness"), "ctx": r.get("ctx")})
    return out


def mirror_x(bbox, width: int):
    """`bbox_page`（x0,y0,x1,y1）的 x 是镜像坐标（W−x）。翻回原图坐标；已用 `ink_ratio` 与记录值核对过（vol02 p113/130/165 等）。"""
    return [int(width - bbox[2]), int(bbox[1]), int(width - bbox[0]), int(bbox[3])]


def cmd_overlay(a) -> int:
    import cv2
    os.environ.setdefault("GUJI_WORKSPACE", str(Path(a.ws).resolve()))
    import open_guji_cv.steps  # noqa: F401  注册产物种类
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.store import ProductStore
    ctx = _ctx(a.book, a.ws)
    book, st = load_book(a.book), ProductStore()
    outd = ctx.reports / "叠图"
    outd.mkdir(parents=True, exist_ok=True)
    rows = read_cells(a.book, a.cells, a.cells_file, ctx.main_reports)
    bad = 0
    for r in rows:
        pid = zl.parse_cell_id(r["id"])
        if not pid:
            print(f"✗ {r['id']}：字位格式不识"); bad += 1; continue
        page, col, slot, sub = pid
        ci = st.read(a.book, "cell_shrink", page_key(page), "char_index")
        cc = ci.column(col) if ci else None
        tgt = next((c for c in (cc.chars if cc else []) if c.slot == slot and (c.sub or "") == sub), None)
        img = cv2.imread(str(book.raw_path(page)))
        if tgt is None or img is None:
            print(f"✗ {r['id']}：{'没有这一格' if tgt is None else '原图读不出来'}"); bad += 1; continue
        W = img.shape[1]
        for c in cc.chars:
            b = mirror_x(c.bbox_page, W)
            cv2.rectangle(img, (b[0], b[1]), (b[2], b[3]), (255, 160, 0), 2)
        b = mirror_x(tgt.bbox_page, W)
        cv2.rectangle(img, (b[0], b[1]), (b[2], b[3]), (0, 0, 255), 4)
        h, w = img.shape[:2]
        name = r["id"].replace(":", "_")
        cv2.imwrite(str(outd / f"{name}_整页.png"), cv2.resize(img, (int(w * 1100 / h), 1100), interpolation=cv2.INTER_AREA))
        pad = 140
        cv2.imwrite(str(outd / f"{name}_局部.png"),
                    img[max(0, b[1] - pad):min(h, b[3] + pad), max(0, b[0] - pad - 90):min(w, b[2] + pad + 90)])
    print(f"叠图 {len(rows) - bad}/{len(rows)} 格 → {outd}")
    return 1 if bad else 0


def cmd_gen(a) -> int:
    ctx = _ctx(a.book, a.ws)
    os.environ.setdefault("GUJI_WORKSPACE", str(ctx.ws))  # load_book/ProductStore 靠它找 books/ 与 products/
    rows = read_cells(a.book, a.cells, a.cells_file, ctx.main_reports)
    # 联系页生成器读 `<reports>/<册>.放行错穷举.json` 的 tier=="real" 行；这里写进 s8 子目录，不动真文件
    (ctx.reports / f"{a.book}.放行错穷举.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    try:
        md = zl.build_contact_sheets(ctx, per=a.per)
    except zl.Stop as e:
        print(f"✗ 联系页没出：{e}（见 {ctx.reports / 'NEXT.md'}）", file=sys.stderr)
        return 1
    tsv = ctx.reports / TSV
    if not tsv.exists():  # 已有的简表（可能已填了一半）不覆盖
        with tsv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(COLS)
            for r in rows:
                w.writerow([r["id"], "", "", r.get("char") or "", "", ""])
    print(f"联系页：{md}\n待填简表：{tsv}\n填完：python scripts/zhengli/s8_vision.py check --book {a.book} --ws {a.ws}")
    return 0


def load_tsv(path: Path) -> tuple[list[dict], list[str]]:
    errs: list[str] = []
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f, delimiter="\t")
        miss = [c for c in COLS if c not in (rd.fieldnames or [])]
        if miss:
            return [], [f"表头缺列 {miss}（要 {COLS}）"]
        for no, r in enumerate(rd, 2):
            if not any((v or "").strip() for v in r.values()):
                continue
            r = {k: (v or "").strip() for k, v in r.items() if k in COLS}
            r["_line"] = no
            rows.append(r)
    return rows, errs


def to_jsonl_rows(rows: list[dict], judge: str, ts: str) -> list[dict]:
    out = []
    for r in rows:
        d = {"cell": r["cell"], "v": r["verdict"], "judge": judge, "ts": ts}
        for src, dst in (("char", "char"), ("shown", "shown"), ("group", "group"), ("note", "note")):
            if r.get(src):
                d[dst] = r[src]
        out.append(d)
    return out


def load_wenyi(path: str | None) -> set[str]:
    if not path:
        return set()
    return {json.loads(l)["id"] for l in Path(path).read_text(encoding="utf-8-sig").splitlines() if l.strip()}


def validate(book: str, rows: list[dict], judge: str, ts: str, wenyi: set[str] | None = None) -> list[str]:
    """空 verdict 先报；其余交给 vision.parse_jsonl（同一套规则，不另立）。"""
    import tempfile
    errs = [f"简表第 {r['_line']} 行：{r['cell']} 在文意定清单里，ok/wrong 不是看图结论，走人裁（只许 unsure）"
            for r in rows if wenyi and re.sub(r"[ab]$", "", r["cell"]) in wenyi and r["verdict"] in ("ok", "wrong")]
    errs += [f"简表第 {r['_line']} 行：{r['cell']} 还没填 verdict" for r in rows if not r["verdict"]]
    todo = [r for r in rows if r["verdict"]]
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        p.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in to_jsonl_rows(todo, judge, ts)), encoding="utf-8")
        from open_guji_cv.feedback.vision import parse_jsonl
        res = parse_jsonl(p, "check", judge, book=book)
    for e in res.errors:  # parse_jsonl 报的是 todo 内的行号，换回简表行号
        m = re.match(r"第 (\d+) 行", e)
        if m:
            e = e.replace(m.group(0), f"简表第 {todo[int(m.group(1)) - 1]['_line']} 行", 1)
        errs.append(e)
    for r in todo:
        if r["verdict"] == "wrong" and not r["char"]:
            errs.append(f"简表第 {r['_line']} 行：{r['cell']} 判 wrong 但没填 char（可留空照样送审，这里只提醒）")
        if r["verdict"] == "wrong" and not r["shown"]:
            errs.append(f"简表第 {r['_line']} 行：{r['cell']} 判 wrong 但 shown 空（没有 audit 就手填放行字；照样送审，这里只提醒）")
    return errs


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_check(a) -> int:
    ctx = _ctx(a.book, a.ws)
    rows, errs = load_tsv(Path(a.tsv) if a.tsv else ctx.reports / TSV)
    errs += validate(a.book, rows, a.judge or "check", _now(), load_wenyi(a.wenyi_list))
    hard = [e for e in errs if "照样送审" not in e]
    for e in errs:
        print(("✗ " if e in hard else "· ") + e)
    print(f"共 {len(rows)} 格；{len(hard)} 处错，{len(errs) - len(hard)} 处提醒")
    return 1 if hard else 0


def cmd_fill(a) -> int:
    ctx = _ctx(a.book, a.ws)
    rows, errs = load_tsv(Path(a.tsv) if a.tsv else ctx.reports / TSV)
    ts = _now()
    errs += validate(a.book, rows, a.judge, ts, load_wenyi(a.wenyi_list))
    hard = [e for e in errs if "照样送审" not in e]
    if hard:
        for e in hard:
            print("✗ " + e, file=sys.stderr)
        print("没写。先改简表。", file=sys.stderr)
        return 1
    out = ctx.main_reports / "看图结论.jsonl"
    have = set()
    if out.exists():
        for l in out.read_text(encoding="utf-8-sig").splitlines():
            if l.strip():
                d = json.loads(l)
                have.add((d.get("cell"), d.get("v"), d.get("char", ""), d.get("judge", "")))
    new = [d for d in to_jsonl_rows(rows, a.judge, ts) if (d["cell"], d["v"], d.get("char", ""), d.get("judge", "")) not in have]
    skipped = len(rows) - len(new)
    print(f"跳过 {skipped} 行（同 cell＋verdict＋char＋judge 已在 {out.name}）")
    lines = [json.dumps(d, ensure_ascii=False) for d in new]
    with out.open("a", encoding="utf-8", newline="\n") as f:  # 只追加：改结论就再追加一行，旧行不动
        for l in lines:
            f.write(l + "\n")
    print(f"追加 {len(lines)} 行 → {out}\n下一步：python scripts/zhengli/zl.py run --book {a.book} --ws {a.ws} --only vision-gate")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("gen", cmd_gen), ("overlay", cmd_overlay), ("check", cmd_check), ("fill", cmd_fill)):
        p = sub.add_parser(name)
        p.add_argument("--book", required=True)
        p.add_argument("--ws", required=True)
        p.set_defaults(fn=fn)
        if name in ("gen", "overlay"):
            p.add_argument("--cells", help="逗号分隔的字位 id，如 vol03:22:8:7,vol03:90:5:16")
            p.add_argument("--cells-file", help="一行一个字位（# 后是注释）")
            if name == "gen":
                p.add_argument("--per", type=int, default=24, help="每张联系页放几格")
        else:
            p.add_argument("--wenyi-list", help="文意定人裁清单 jsonl；清单里的格 ok/wrong 拒收（unsure 允许）")
            p.add_argument("--tsv", help="简表路径（缺省 reports/<册>/s8/看图简表.tsv）")
            p.add_argument("--judge", required=(name == "fill"), help="谁看的图：模型名或人名（写进 judge）")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
