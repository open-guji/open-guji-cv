# -*- coding: utf-8 -*-
"""规范层（norm）方案演示：共享归一表 + 页上逐位例外 → 三档阅读文本（只读，不改输入）。

配合 `doc/formats/norm_layer_proposal.md`（F2，overview#381）。演示推荐方案 C：

1. **共享归一表**（无条件的纯字形异体 → 繁体通行字）按字套到原样层，物化成页上 `norm` 条目，
   `by` 指向表的版本（`producers.norm_table`）；
2. **页上逐位条目**（上下文才定的、人裁的）从 `--overrides` 读，盖在表的结果上；
3. 出三档：原样（`text`）、繁体通行（`layer="norm"`）、简体（繁体通行档再过 OpenCC t2s——
   网站用的是 opencc-js `t2cn`，本脚本用 Python 版 `t2s` 近似，个别字会不同）。

另报两个对照：`config/variants/variants.json` 的 `directed`（异体→正字）若直接拿来填 norm 会提多少条、
其中有几条是表里的；以及 OpenCC 单独转简体时漏掉（原样留下）的字。

    python scripts/demo_norm_layer.py --table doc/formats/samples/norm_demo/demo_norm_table.json \\
        --out doc/formats/samples/norm_demo doc/formats/samples/norm_demo/p0053.guji-page.json …
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.formats import guji_page as gp  # noqa: E402


def apply_table(page: dict, table: dict, overrides: list[dict] | None = None) -> dict:
    """返回填好 `norm` 的新页：表里的字逐位物化，`overrides` 逐位覆盖（`t` 与原字相同 = 此位不归一）。"""
    p = copy.deepcopy(page)
    lac = gp.lacuna_set(p)
    zi = {z["i"] for z in p.get("zi", [])}
    key = f"table:{table['version']}"
    by_i = {}
    for i, t in enumerate(p["text"]):
        if i in lac or i in zi:
            continue
        hit = table["map"].get(t)
        if hit:
            by_i[i] = {"i": i, "t": hit["t"], "by": key, "why": "异体"}
    for o in overrides or []:
        if o["t"] == p["text"][o["i"]]:
            by_i.pop(o["i"], None)          # 例外：表说要归一，这一位不归
        else:
            by_i[o["i"]] = {"i": o["i"], "t": o["t"], "by": o.get("by", "manual"), "why": "异体"}
    p["norm"] = [by_i[i] for i in sorted(by_i)]
    p.setdefault("producers", {})["norm_table"] = {"tool": "guji-variant-norm", "version": table["version"]}
    return p


def directed_noise(page: dict) -> tuple[int, list[str]]:
    """`variants.json` 的有向边（异体→正字）若直接拿来填 norm：会提几位、提成什么。"""
    from open_guji_cv import variants as V
    g = V._graph()
    lac = gp.lacuna_set(page)
    out = []
    for i, t in enumerate(page["text"]):
        if i in lac:
            continue
        regs = g.regulars_of(t)
        if regs:
            out.append(f"{t}→{'/'.join(r for r, _ in regs)}")
    return len(out), out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--table", required=True)
    ap.add_argument("--overrides", default=None, help="{页文件名: [{i, t, by}]}")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    table = json.loads(Path(a.table).read_text(encoding="utf-8"))
    ovr = json.loads(Path(a.overrides).read_text(encoding="utf-8")) if a.overrides else {}
    try:
        import opencc
        t2s = opencc.OpenCC("t2s").convert
    except ImportError:          # pragma: no cover
        t2s = None
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in a.pages:
        page = gp.read_page(f)
        name = Path(f).name
        p = apply_table(page, table, ovr.get(name))
        errs = gp.check(p)
        stem = name.replace(".guji-page.json", "")
        gp.dump(p, out / f"{stem}.norm.guji-page.json")
        orig = gp.to_guji_markdown(p)
        norm = gp.to_guji_markdown(p, layer="norm")
        layers = {"orig": orig, "norm": norm}
        if t2s:
            layers["simp"] = t2s(norm)
            layers["simp_without_norm"] = t2s(orig)
        for k, v in layers.items():
            (out / f"{stem}.{k}.md").write_text(v + "\n", encoding="utf-8")
        n_dir, ex = directed_noise(page)
        in_table = sum(1 for e in ex if e.split("→")[0] in table["map"])
        leak = sorted({ch for ch in orig if ch in table["map"] and t2s and t2s(ch) == ch})
        print(f"{stem}: 字元 {len(p['text'])}，norm {len(p['norm'])} 条"
              f"（表 {sum(1 for n in p['norm'] if n['by'].startswith('table:'))}、逐位 "
              f"{sum(1 for n in p['norm'] if not n['by'].startswith('table:'))}）"
              f"：{'、'.join(p['text'][n['i']] + '→' + n['t'] for n in p['norm'])}；检查 {'通过' if not errs else errs}")
        print(f"   variants.json 有向边直接填会提 {n_dir} 位，其中在表里的 {in_table} 位："
              f"{'、'.join(ex[:12])}{' …' if len(ex) > 12 else ''}")
        print(f"   不经 norm、直接 t2s 转简体后原样漏下的异体：{''.join(leak) or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
