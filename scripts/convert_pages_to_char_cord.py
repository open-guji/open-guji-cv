# -*- coding: utf-8 -*-
"""旧 `NNN.pages.json`（guji-pages/0.1，格里带字）→ book-text 新形态 `NNN.char.json` ＋ `NNN.cord.json` ＋ `NNN.norm.json`。
纯转换，不读产物。F4，overview#419。格式与字段对应见 `open_guji_cv/formats/guji_char_cord.py` 模块头。

    python scripts/convert_pages_to_char_cord.py --pages-json 002.pages.json --out out/ \\
        [--zi 002.zi.json] [--norm 002.norm.json] [--lines-md 002.lines.md] [--keys cv|lines] [--text-version 0.1.0]

给了 `--lines-md` 就核往返：char 生成的分行稿必须与它逐字节相同。另外总要过 schema、过 `check`（cord 的格位
都在 char 里，页号、列号两边一致）。任何一项不过返回 1，文件照写，方便对照。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.formats import guji_char_cord as cc  # noqa: E402


def report(files: dict, lines_md: str | None = None) -> int:
    """过 schema、两边一致、（给了旧 lines.md 时）往返逐字节相同；打印并返回不过的项数。"""
    char = next(v for k, v in files.items() if k.endswith(".char.json"))
    cord = next(v for k, v in files.items() if k.endswith(".cord.json"))
    norm = next((v for k, v in files.items() if k.endswith(".norm.json")), None)
    bad = 0
    for kind, obj in (("char", char), ("cord", cord)):
        errs = cc.validate(obj, kind)
        print(f"   {kind} schema：{'过' if not errs else f'不过 {len(errs)} 处，如 {errs[:3]}'}")
        bad += bool(errs)
    errs = cc.check(char, cord, norm)
    print(f"   格位/页号/列号一致：{'过' if not errs else f'不过 {len(errs)} 处，如 {errs[:3]}'}")
    bad += bool(errs)
    if lines_md is not None:
        gen = cc.char_to_lines_md(char)
        if gen == lines_md:
            print(f"   往返：char 生成的分行稿与 lines.md 逐字节相同（{len(gen.splitlines())} 行）")
        else:
            a, b = gen.splitlines(), lines_md.splitlines()
            diff = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            print(f"   ✗ 往返不同：首处第 {diff + 1} 行\n     生成：{a[diff] if diff < len(a) else '（无）'}"
                  f"\n     原稿：{b[diff] if diff < len(b) else '（无）'}")
            bad += 1
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--zi", default=None, help="同章 zi.json（guji-zi/0.1）；有未收字时要给")
    ap.add_argument("--norm", default=None, help="同章 norm.json（guji-norm/0.1，带 a）")
    ap.add_argument("--lines-md", default=None, help="同一份产物导出的旧 lines.md，给了就核往返")
    ap.add_argument("--keys", choices=cc.KEYS, default="cv", help="格位口径，见模块头；缺省 cv（照 spec 02）")
    ap.add_argument("--text-version", default="0.1.0", help="char 的 version（文本线版本）")
    a = ap.parse_args(argv)

    load = (lambda x: json.loads(Path(x).read_text(encoding="utf-8")) if x else None)
    pj = load(a.pages_json)
    files, rep = cc.from_pages_json(pj, zi=load(a.zi), norm=load(a.norm), version=a.text_version, keys=a.keys)
    cc.write_files(files, a.out)
    char = next(v for k, v in files.items() if k.endswith(".char.json"))
    cord = next(v for k, v in files.items() if k.endswith(".cord.json"))
    st = cc.stats(char, cord)
    print(f"{pj.get('chapter')}（keys={a.keys}）：{st['pages']} 页、{st['columns']} 列、{st['cells']} 格（有框 {st['boxed']}），"
          f"阙文 {st['lacuna']}、残字 {st['guess']}、组字 {st['zi']}；与 CV 锚点不同的 key {rep['rekeyed']}；"
          f"没写进 cord 的（框为空/类别不认）{rep['dropped']} → {a.out}")
    lines_md = Path(a.lines_md).read_text(encoding="utf-8") if a.lines_md else None
    return 1 if report(files, lines_md) else 0


if __name__ == "__main__":
    raise SystemExit(main())
