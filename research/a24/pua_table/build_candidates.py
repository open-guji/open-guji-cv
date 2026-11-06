# -*- coding: utf-8 -*-
"""私用码全套映射·第一步：殆知阁總目 142 个码的候选表（A24 2026-11-06）。

输入：殆知阁总目源 0001–0005.jsonl、维基文库 Module:SKchar / SKchar2（Lua 源）、siku-qiefen-v2 发布包（zip，文本层）、
      F→E 对照（pua_src/F2E.json）、待收字登记（glyph_pending_codes.json）、码表（code_table.json）。
输出：pua_table_candidates.jsonl（一码一行；格式见方案「码表长什么样」）＋ summary.json。
候选只是起点，不自动算「已定」；已在待收字登记／码表里的，verdict 沿用，写 note 说明来源。
用法：python3 build_candidates.py --dzg DIR --wiki DIR --v2zip q.zip --out DIR
"""
from __future__ import annotations
import argparse, collections, glob, gzip, io, json, re, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f\U000323b0-\U0003347f]")


def parse_lua(path: Path) -> dict[int, tuple[str | None, str | None]]:
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*\['(\d+)'\]=\{(.*)\},?\s*$", line)
        if not m:
            continue
        parts = re.findall(r'nil|"((?:[^"\\]|\\.)*)"', m.group(2))
        toks = re.findall(r'nil|"(?:[^"\\]|\\.)*"', m.group(2))
        vals = [None if t == "nil" else t[1:-1] for t in toks]
        out[int(m.group(1))] = (vals[0] if vals else None, vals[1] if len(vals) > 1 else None)
    return out


def sk_number(cp: int) -> int:
    return cp - 0xE000 + 1


def v2_stream(zpath: Path):
    Z = zipfile.ZipFile(zpath)
    names = [n for n in Z.namelist() if n.startswith("96mid1ogzk/") and n.endswith("/text.jsonl.gz")]
    names.sort(key=lambda n: int(n.split("/")[1]) if n.split("/")[1].isdigit() else 0)
    parts, meta = [], []
    for n in names:
        rows = [json.loads(l) for l in gzip.open(io.BytesIO(Z.read(n)), "rt", encoding="utf-8")]
        rows.sort(key=lambda r: int(r["p"]) if str(r["p"]).isdigit() else 0)
        ch = n.split("/")[1]
        for r in rows:
            parts.append(r["c"] + "\n")  # 页间换行隔开，窗口不跨页
            meta.extend((ch, r["p"], k) for k in range(len(r["c"]) + 1))
    return "".join(parts), meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dzg", required=True)
    ap.add_argument("--wiki", required=True)
    ap.add_argument("--v2zip", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    from open_guji_cv.utils.pua_lookup import PuaIndex
    files = sorted(glob.glob(f"{a.dzg}/[0-9][0-9][0-9][0-9].jsonl"))
    idx = PuaIndex.from_source([Path(f) for f in files])
    D, codes = idx.stream, idx.codes
    cnt = collections.Counter(codes.values())
    # 殆知阁窗口：左右各取到 〓/非汉字 为止、至多 8 字
    def side(i, step):
        s, k = [], i + step
        while 0 <= k < len(D) and len(s) < 8:
            ch = D[k]
            if not HAN.match(ch):
                break
            s.append(ch); k += step
        return "".join(s if step > 0 else reversed(s))

    # v2 文本层窗口
    S, META = v2_stream(Path(a.v2zip))
    key = collections.defaultdict(list)
    for j in range(3, len(S) - 3):
        if S[j] == "\n":
            continue
        L, R = S[j - 3:j], S[j + 1:j + 4]
        if "\n" in L or "\n" in R:
            continue
        key[L + "|" + R].append(j)
    v2vote = collections.defaultdict(collections.Counter)
    v2hit = collections.Counter()
    locs = collections.defaultdict(list)
    samples = collections.defaultdict(list)
    for i, code in codes.items():
        L, R = side(i, -1), side(i, 1)
        if len(L) < 3 or len(R) < 3:
            continue
        cand = key.get(L[-3:] + "|" + R[:3], [])
        best, bj = -1, []
        for j in cand:
            sc = sum(1 for x, y in zip(reversed(L), reversed(S[max(0, j - len(L)):j])) if x == y)
            sc += sum(1 for x, y in zip(R, S[j + 1:j + 1 + len(R)]) if x == y)
            if sc > best:
                best, bj = sc, [j]
            elif sc == best:
                bj.append(j)
        if best < 8 or len({S[j] for j in bj}) != 1:
            continue
        v2vote[code][S[bj[0]]] += 1
        if len(locs[code]) < 8:
            locs[code].append(list(META[bj[0]]))
        v2hit[code] += 1
        if len(samples[code]) < 3:
            samples[code].append(L[-5:] + "〓" + R[:5])
    for i, code in codes.items():
        if len(samples[code]) < 3 and code not in samples:
            samples[code].append(side(i, -1)[-5:] + "〓" + side(i, 1)[:5])
    # 没有 v2 命中的码补取样
    for i, code in codes.items():
        if not samples[code]:
            samples[code].append(side(i, -1)[-5:] + "〓" + side(i, 1)[:5])

    sk1 = parse_lua(Path(a.wiki) / "SKchar.lua")
    sk2 = parse_lua(Path(a.wiki) / "SKchar2.lua")
    pua = ROOT / "research/a24/pua_src"
    f2e = json.load(open(pua / "F2E.json"))["F2E"]
    e2f = collections.defaultdict(list)
    for f, e in f2e.items():
        e2f[e].append(f)
    pend = json.load(open(pua / "glyph_pending_codes.json"))
    pend_items = set(pend.get("codes", []))
    ctable = json.load(open(pua / "code_table.json"))

    from open_guji_cv.clustering import ids_lookup

    rows = []
    for code in sorted(cnt, key=lambda c: -cnt[c]):
        cp = int(code.split("U+")[1], 16)
        n = sk_number(cp)
        bz, desc = sk1.get(n, (None, None))
        cands = []
        def add(ch, src, note=""):
            if ch and all(c["char"] != ch or c["src"] != src for c in cands):
                cands.append({"char": ch, "src": src, **({"note": note} if note else {})})
        # v2
        v2_chars = v2vote.get(code, collections.Counter())
        v2_han = [(c, k) for c, k in v2_chars.most_common() if HAN.match(c)]
        v2_pua = [(c, k) for c, k in v2_chars.most_common() if not HAN.match(c) and 0xE000 <= ord(c) <= 0x10FFFD]
        for c, k in v2_han:
            add(c, "v2", f"{k}/{v2hit[code]}处")
        # 维基 本字 / 描述字
        wiki_desc_chars, wiki_ids = [], []
        if bz:
            add(bz, "wiki_bz")
        if desc:
            d = desc.strip("（）() ")
            # 写法：「X」单字／「⿰氵閠」拆字／「拆字 -- 对应字」／「X -- A or B ?」／「「絃」字少最後一點」文字说明
            left, _, right = d.partition("--")
            left, right = left.strip(), right.strip()
            uncertain = "?" in right or "？" in right
            def one_char(t):
                return len(t) == 1 or (len(t) == 2 and ord(t[0]) > 0xFFFF and 0xFE00 <= ord(t[1]) <= 0xFE0F)
            if left and one_char(left) and HAN.match(left[0]):
                add(left, "wiki_desc")
            elif re.search(r"[⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻]", left):
                wiki_ids.append(left)
                for q in re.findall(r"[⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻][^\s，、]+", left)[:1]:
                    try:
                        r = ids_lookup.lookup(q, near=0)
                        for h in (r.get("exact") or []) + (r.get("expanded") or []):
                            ch = h["char"] if isinstance(h, dict) else h
                            add(ch, "ids", q)
                    except Exception:
                        pass
            else:
                for q in re.findall(r"[「『]([^」』]+)[」』]", left):
                    if len(q) == 1 and HAN.match(q):
                        add(q, "wiki_note", left)
            for ch in re.findall(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f\U000323b0-\U0003347f]", right):
                add(ch, "wiki_note", "拆字注对应字" + ("（维基带问号）" if uncertain else ""))
        # 殆知阁原已映（不会出现在剩余码里）：略
        c_v2 = {c["char"] for c in cands if c["src"] == "v2"}
        c_wk = {c["char"] for c in cands if c["src"] in ("wiki_desc", "wiki_bz", "wiki_note", "ids")}
        conflict = bool(c_v2 and c_wk and not (c_v2 & c_wk))
        # 同义码：F→E 对照、v2 对应的私用码
        same_as = [f"siku-qiefen-v2:U+{f}" for f in e2f.get(code, [])]
        for c, k in v2_pua:
            s = f"siku-qiefen-v2:U+{ord(c):X}"
            if s not in same_as:
                same_as.append(s)
        # 已有登记：待收字／码表
        verdict, char, note, by = "open", None, "", None
        fs = list(dict.fromkeys(e2f.get(code, []) + [x.split("U+")[1] for x in same_as if x.startswith("siku-qiefen-v2:")]))
        pend_hit = [f for f in fs if f"siku-qiefen-v2:U+{f}" in pend_items] + ([code] if code in pend_items else [])
        tab_hit = [(f, ctable[f]) for f in fs if f in ctable]
        if pend_hit:
            verdict, by, note = "pending", "sheldon", "11-05 点选页已判定待收（glyph_pending_codes.json）"
        elif tab_hit:
            verdict, char, by = "char", tab_hit[0][1], "a24-code_table"
            note = f"沿用 code_table.json（{tab_hit[0][0]}→{tab_hit[0][1]}，11-05 前人裁一致或 sheldon 点选）"
            if len({c for _, c in tab_hit}) > 1:
                note += "；多个 F 码对应此码且字不同，待核"
        if verdict == "char" and cands and char not in [c["char"] for c in cands]:
            note += "；已定字不在候选里，复核"
        row = {
            "code": code, "verdict": verdict, "char": char, "orig": None, "variant": None,
            "cands": cands, "same_as": same_as, "by": by, "at": None, "note": note,
            "count": cnt[code], "sk_no": n, "wiki_img": f"SKQS_{n:04d}.svg",
            "wiki_bz": bz, "wiki_desc": desc, "v2": {c: k for c, k in v2_chars.most_common()},
            "v2_hit": v2hit[code], "v2_locs": locs[code], "conflict": conflict, "samples": samples[code],
        }
        rows.append(row)
    with open(out / "pua_table_candidates.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    def bucket(r):
        srcs = {c["src"] for c in r["cands"]}
        if "v2" in srcs: return "v2"
        if srcs & {"wiki_desc", "wiki_bz"}: return "wiki_desc"
        if srcs & {"wiki_note", "ids"}: return "ids_or_note"
        return "none"
    summ = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        b = bucket(r); summ[b][0] += 1; summ[b][1] += r["count"]
    stat = {"codes": len(rows), "total": sum(r["count"] for r in rows),
            "by_best_source": {k: {"codes": v[0], "count": v[1]} for k, v in summ.items()},
            "conflict": [r["code"] for r in rows if r["conflict"]],
            "verdict": dict(collections.Counter(r["verdict"] for r in rows)),
            "v2_pua_only": [r["code"] for r in rows if r["v2"] and not any(HAN.match(c) for c in r["v2"])]}
    json.dump(stat, open(out / "summary.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(stat, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
