"""文意 L2 表的强模型复核批（`groups.l2_panel`，2026-10-24 A24「优化己已巳判别」）。
  make   <产物根> <册,册…> <现表 json> <输出目录> [--group jys] [--size 40]
  ingest <输出目录> <现表 json> <新表 json> [--group jys] [--main haiku --strong opus --second sonnet]

make：从产物（`<册>/seed_admit`、`<册>/align_ref`，`guji products pack fetch` 的布局）取进组格，窗口与管线同一取法
（同 `l2_make_book.py`）。出批的格＝表里全部格（已给字的拿去否决、弃权的拿去补字）＋本组 L1 现在弃权、表里又没有的格
（规则收窄后从 L1 挪到表的格）。写 `<组>p_NN.txt`（整条消息）、`manifest.json`（批 → 格）、`cells.json`（格 → [left, right]）。
模型不是本脚本调用的：每个模型各跑一遍全部批，输出放 `<输出目录>/runs/<模型>/<批名>.json`（JSON 数组，同 L2 批）。
ingest：合进现表（规则见 `groups.l2_panel` 模块头），打印各结局格数。
"""
import argparse, glob, json, random
from pathlib import Path
from types import SimpleNamespace

from open_guji_cv.groups.context import WIDTH, ctx_key
from open_guji_cv.groups.ctx_l3 import parse_output
from open_guji_cv.groups.flow import ctx_judge as judge
from open_guji_cv.groups.l2_panel import panel_merge
from open_guji_cv.groups.prompt_template import book_prompt_vars, build_batch_rendered as build_batch
from open_guji_cv.groups.registry import GROUPS
from open_guji_cv.steps.seed_admit import _clf_ctx
from open_guji_cv.utils.jiazhu_order import sort_by_reading

REPO = Path(__file__).resolve().parents[3]


def cells_of(root: Path, vols: list[str], g: str) -> dict:
    """→ {格: (left, right, 进没进组流程)}，窗口宽 WIDTH，读序与 seed_admit._group_flow_pass 一致。"""
    mem = GROUPS[g].members
    out = {}
    for v in vols:
        for f in sorted(glob.glob(str(root / v / "seed_admit" / "p*.json"))):
            d = json.load(open(f, encoding="utf-8"))["seed_admit"]
            af = root / v / "align_ref" / Path(f).name
            amap = {c["id"]: (c["align_char"], c.get("align_op")) for c in json.load(open(af, encoding="utf-8"))["align_ref"]["chars"]}
            raw = {c["id"]: c for col in d["columns"] for c in col["chars"]}
            seq = [SimpleNamespace(**{k: getattr(c, k, None) for k in ("id", "char", "admit", "doubts")})
                   for col in sorted(d["columns"], key=lambda c: c["col"])
                   for c in sort_by_reading([SimpleNamespace(**c) for c in col["chars"]])
                   if not (c.doubts and "excluded" in c.doubts)]
            for i, r in enumerate(seq):
                ref = (amap.get(r.id) or (None, None))[0]
                grp = ((raw[r.id].get("evidence") or {}).get("group") or {})
                if grp.get("id") != g and ref not in mem and r.char not in mem:
                    continue
                out[r.id] = (_clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH), grp.get("id") == g, ref,
                             (grp.get("solvers") or [{}])[0].get("via"))
    return out


def split_key(k: str) -> tuple[str, str]:
    body = k.split(":", 1)[1]
    left, _, right = body.partition("|")
    return left, right


ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["make", "ingest"]); ap.add_argument("pos", nargs="+")
ap.add_argument("--group", default="jys"); ap.add_argument("--size", type=int, default=40)
ap.add_argument("--main", default="haiku"); ap.add_argument("--strong", default="opus"); ap.add_argument("--second", default="sonnet")
a = ap.parse_args(); g = a.group; spec = GROUPS[g]; members = "".join(sorted(spec.members))

if a.cmd == "make":
    root, vols, table, out = Path(a.pos[0]), a.pos[1].split(","), Path(a.pos[2]), Path(a.pos[3])
    out.mkdir(parents=True, exist_ok=True)
    T = json.loads(table.read_text(encoding="utf-8"))["cells"]
    C = cells_of(root, vols, g)
    rows = [dict(id=k, left=split_key(e["ctx"])[0], right=split_key(e["ctx"])[1]) for k, e in sorted(T.items())
            if k.split(":")[0] in vols]
    moved = []
    for k, (left, right, in_flow, ref, via) in sorted(C.items()):
        if not in_flow or k in T or via == "ctx:pair":
            continue
        if judge(g, k, ref, left, right, None).char is None:
            moved.append(dict(id=k, left=left[-WIDTH:], right=right[:WIDTH]))
    rows += moved
    random.Random(7).shuffle(rows)
    man, cells = {}, {}
    prompt = REPO / spec.config_dir / "prompt.md"
    for i in range(0, len(rows), a.size):
        name = f"{g}p_{i // a.size:02d}"; chunk = rows[i:i + a.size]
        (out / f"{name}.txt").write_text(build_batch(prompt, chunk, book_prompt_vars()), encoding="utf-8")
        man[name] = [c["id"] for c in chunk]
        cells.update({c["id"]: [c["left"], c["right"]] for c in chunk})
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    (out / "cells.json").write_text(json.dumps(cells, ensure_ascii=False), encoding="utf-8")
    print(g, "表里", len(rows) - len(moved), "格，L1 挪出", len(moved), "格，共", len(man), "批")
else:
    d, table, new = Path(a.pos[0]), Path(a.pos[1]), Path(a.pos[2])
    t = json.loads(table.read_text(encoding="utf-8"))
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    cells = json.loads((d / "cells.json").read_text(encoding="utf-8"))
    runs = {}
    for m in (a.main, a.strong, a.second):
        r = {}
        for name in man:
            f = d / "runs" / m / f"{name}.json"
            if f.exists():
                r.update(parse_output(f.read_text(encoding="utf-8")))
        runs[m] = r
    want = {i for ids in man.values() for i in ids}
    ctxs = {i: tuple(cells[i]) for i in want if i not in t["cells"]}
    for i, (left, right) in ctxs.items():
        assert ctx_key(left[-WIDTH:], right[:WIDTH]).startswith("v"), i
    n = panel_merge(t, {m: {k: v for k, v in r.items() if k in want} for m, r in runs.items() if r}, members, ctxs,
                    main=a.main, strong=a.strong, second=a.second)
    t["panel"] = {"strong": a.strong, "second": a.second, "by": "A24 优化己已巳判别 2026-10-24"}
    new.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    print({m: len(r) for m, r in runs.items()}, "/", len(want), dict(n))
