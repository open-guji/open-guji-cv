#!/usr/bin/env python3
"""把 reports/bxgb/wikisource/p003..p056.wiki 解析成 {key: 字}。
key = bxgb:页:列:格[a|b]
规则：<poem> 内第 i 行 = 第 i 列（第 10 行=版心，空）；行内每个字符占一格，
全角空格　= 空格（跳过但占格）；{{small|XY}} 單行小注每字一格（sub 无）；
{{*|...}} 雙行夹注：n 字按 ceil(n/2)|floor 拆为 a(右)/b(左)，每格 a、b 各一字。
（与 bxgb.md 的 <a|b> 对照：本书 5 处全部符合 ceil 拆法。）
dict 的插入顺序即全书读序（页→列→格，双行夹注先 a 后 b）。
用法: python3 parse_bxgb_wiki.py [WS] [--json out.json]
"""
import json, re, sys, glob, os

WS = os.environ.get("GUJI_WORKSPACE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../guji-workspace/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一"))
TOK = re.compile(r"\{\{(small|\*)\|([^}]*)\}\}|(.)", re.S)


def parse_line(line):
    """-> list of (slot, sub, ch, kind)"""
    out, slot = [], 0
    for m in TOK.finditer(line):
        tpl, body, ch = m.groups()
        if tpl == "small":
            for c in body:
                slot += 1
                out.append((slot, "", c, "jiazhu_solo"))
        elif tpl == "*":
            n = len(body); na = (n + 1) // 2
            a, b = body[:na], body[na:]
            # 输出按读序：先右半 a 全部，再左半 b（dict 插入序 = 读序）
            for i in range(na):
                out.append((slot + 1 + i, "a", a[i], "jiazhu_a"))
            for i in range(len(b)):
                out.append((slot + 1 + i, "b", b[i], "jiazhu_b"))
            slot += na
        else:
            if ch in " \t":
                continue
            slot += 1
            if ch != "　":
                out.append((slot, "", ch, "char"))
    return out, slot


def parse_book(ws=WS):
    res, meta, warn = {}, {}, []
    for f in sorted(glob.glob(os.path.join(ws, "reports/bxgb/wikisource/p0*.wiki"))):
        page = int(re.search(r"p(\d+)\.wiki", f).group(1))
        txt = open(f, encoding="utf-8").read()
        body = txt.split("<poem>", 1)[1].split("</poem>", 1)[0]
        lines = body.split("\n")[1:]          # <poem> 后第一个换行
        if lines and lines[-1] == "":
            lines = lines[:-1]
        if len(lines) > 19:
            warn.append(f"p{page}: {len(lines)} 行 > 19")
        for col, line in enumerate(lines, 1):
            cells, n = parse_line(line)
            if n > 21:
                warn.append(f"p{page} col{col}: {n} 格 > 21")
            if col == 10 and cells:
                warn.append(f"p{page} col10(版心) 有字: {line}")
            for slot, sub, ch, kind in cells:
                k = f"bxgb:{page}:{col}:{slot}{sub}"
                res[k] = ch
                meta[k] = kind
    return res, meta, warn


if __name__ == "__main__":
    res, meta, warn = parse_book()
    from collections import Counter
    print("字位数", len(res), Counter(meta.values()))
    print("\n".join(warn[:30]))
    print("p020 col1 slot16 =", res.get("bxgb:20:1:16"))
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump({"chars": res, "kind": meta}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
