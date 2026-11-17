# -*- coding: utf-8 -*-
"""整理本占位符区分（A23 2026-11-16，Sheldon 审定）：现网 `siku_daizhige.txt` 里的 〓 就地改写，并出侧表。

  python scripts/dzg_placeholders.py --ws <工作区数据目录（含 corpus/）> --out DIR [--table pua_table.jsonl] [--picks cell_picks_mapped.json]

做什么（只读：不改工作区，结果写 --out）：
 1. 用 `dzg_import.build_halves` 从源 jsonl 重生成「保留原码位」的变体（私用码、缅甸缺字图占位码原样留着）；
 2. 现网整理本与变体逐半叶逐列对。源文件之后改过（蘊/蕴、黃/黄 这类字面改动、约 90 行列首缩进），不能整份重生成，
    只能就地换：两边列长相同、〓 位置一致就按位取码（其余字面保持现网，记 `源文改字但〓位一致`）；
 3. 私用码：码表 verdict=char → 换成码表字；multi／待收／无码表行／「古文作」后 → 仍 `〓`；
    缅甸缺字图占位码（以图代字）→ `▣`；
 4. 侧表 `slots.jsonl` 一处一行，含原码位、前后文、码表依据、字图（见设计文档第 3.2 节）。
输出：`siku_daizhige.new.txt`、`slots.jsonl`、`summary.json`。行数、逐行字数与现网相同，只有 〓 位置的字变。
设计与迁移步骤：/mnt/project-files/A23/整理本占位符区分设计-2026-11-16.md（ai-team 里同名备份）。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dzg_import as Z  # noqa: E402
import open_guji_cv.utils.daizhige as D  # noqa: E402
from open_guji_cv.utils.gap import GAP_IMAGE, GAP_PUA  # noqa: E402

U, IMG = GAP_PUA, GAP_IMAGE
BUR = re.compile(r"[က-႟]")
NO_CHAR_CTX = re.compile(r"(古文|篆文|篆|古)作$|古文作.?$|篆作.?$")
QUOTE_CTX = re.compile(r"作.{0,1}$")


def load_table(path: Path) -> dict[str, dict]:
    tab = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r["code"].startswith("daizhige:"):
            tab[r["code"].split("U+")[1].upper()] = r
    return tab


def keep_codes(s, pua_map, glyphs=None):
    """`fix_pua` 的变体：映不上的私用码、缺字图占位码（缅甸字母）原样留着，个数照记。"""
    if not s:
        return s, 0
    out, miss = [], 0
    for ch in s:
        k = f"U+{ord(ch):04X}"
        if D._is_pua(ch):
            real = (pua_map or {}).get(k)
            if real:
                out.append(real)
            else:
                out.append(ch)
                miss += 1
        else:
            out.append(ch)
            miss += bool(BUR.match(ch))
    return "".join(out), miss


def _groups(lines):
    g, k = {}, None
    for x in lines:
        if x.startswith("#@ "):
            k = x
            g[k] = []
        elif k:
            g[k].append(x)
    return g


def load_picks(path: Path | None) -> dict[str, list[dict]]:
    """逐格人裁（A24 11-06 审核页，`cell_picks_mapped_*.json`）：按码分组，用 `text_ctx`（前后各几字）对位。"""
    by: dict[str, list[dict]] = collections.defaultdict(list)
    if path:
        for p in json.loads(path.read_text(encoding="utf-8")):
            by[p["code"]].append(p)
    return by


def _pick_for(picks, raw: str, left: str, right: str):
    hit = []
    for p in picks.get("daizhige:" + raw, []):
        t = p.get("text_ctx") or ""
        i = t.find("〓")
        if i >= 0 and left.endswith(t[:i]) and right.startswith(t[i + 1:]):
            hit.append(p)
    return hit[0] if len(hit) == 1 else None


GLYPH_BASE = "https://sikuquanshu.daizhige.net/"


def fetch_glyph_strips(slots: list[dict], glyph_dir: Path) -> dict[str, dict]:
    """把以图代字的字图条（源 `glyphs` 里的 `img/glyphs/NNNN-k.png`，一条图多处裁）下到 glyph_dir，返回 {src: {file,sha256,bytes}}。
    侧表 `img` 里再补 sha256，之后不必依赖殆知阁站点（图条进语料目录 `corpus/daizhige/glyphs/`）。"""
    import hashlib
    import urllib.request
    glyph_dir.mkdir(parents=True, exist_ok=True)
    man = {}
    for src in sorted({s["img"]["src"] for s in slots if s.get("img")}):
        f = glyph_dir / Path(src).name
        if not f.exists():
            req = urllib.request.Request(GLYPH_BASE + src, headers={"User-Agent": "open-guji-cv/dzg_placeholders"})
            f.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        b = f.read_bytes()
        man[src] = {"file": f.name, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
    return man


def run(ws: Path, table: Path, out: Path, picks_path: Path | None = None, glyph_dir: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tab = load_table(table)
    picks = load_picks(picks_path)
    glyphs = {}
    for f in Z.source_files(ws):
        for r in D.load_records(f):
            if isinstance(r.get("glyphs"), dict):
                glyphs[r["id"]] = r["glyphs"]
    pm = {}
    pmf = ws / "corpus" / "daizhige" / "page_map.jsonl"
    if pmf.exists():
        for ln in pmf.read_text(encoding="utf-8").splitlines():
            d = json.loads(ln)
            pm[(d["dzg_id"], d["dzg_page"], d["side"])] = (d["vol"], d["page"])

    saved = D.fix_pua
    D.fix_pua = keep_codes
    try:
        halves = D.build_halves(Z.source_files(ws))
        var, _, _ = Z.convert(halves)
    finally:
        D.fix_pua = saved
    cur = (ws / "corpus" / Z.TXT_NAME).read_text(encoding="utf-8").split("\n")
    if cur and cur[-1] == "":
        cur.pop()
    gv = _groups(var)

    def norm(s):
        return "".join(U if (D._is_pua(c) or BUR.match(c)) else c for c in s)

    new, slots, st, idx, k = [], [], collections.Counter(), {}, None
    for x in cur:
        if x.startswith("#@ "):
            k = x
            idx[k] = 0
            new.append(x)
            continue
        if k is None:
            new.append(x)
            continue
        if k not in gv:
            new.append(x)
            st["半叶对不上列数"] += 1
            st["半叶对不上〓"] += x.count(U)
            continue
        i = idx[k]
        idx[k] += 1
        v = gv[k][i] if i < len(gv[k]) else None
        if U not in x:
            new.append(x)
            continue
        xs = x.lstrip("　")
        vn = norm(v).lstrip("　") if v else None
        if vn is not None and xs != vn and len(xs) == len(vn) and \
                [j for j, c in enumerate(xs) if c == U] == [j for j, c in enumerate(vn) if c == U]:
            st["源文改字但〓位一致"] += 1
            vs0 = v.lstrip("　")
            v = "　" * (len(v) - len(vs0)) + "".join(
                vs0[j] if (D._is_pua(vs0[j]) or BUR.match(vs0[j])) else xs[j] for j in range(len(vs0)))
            vn = norm(v).lstrip("　")
        if v is None or xs != vn:
            new.append(x)
            st["列对不上列数"] += 1
            st["列对不上〓"] += x.count(U)
            slots.append(dict(half=k, col=i, kind="unmatched", n=x.count(U)))
            continue
        p = k.split()
        rid, page, side = p[1], p[2], int(p[3][1:])
        vs = v.lstrip("　")
        lead = x[:len(x) - len(xs)]
        o = []
        for ci, ch in enumerate(vs):
            left = "".join(o)[-6:]
            volp = pm.get((rid, page, side))
            base = dict(dzg=rid, page=page, side=side, col=i, pos=ci + len(lead),
                        vol=volp[0] if volp else None, pg=volp[1] if volp else None,
                        left=left, right=vs[ci + 1:ci + 7])
            if BUR.match(ch):
                g = glyphs.get(rid, {}).get(f"U+{ord(ch):04X}")
                q = bool(QUOTE_CTX.search(left))
                slots.append(dict(base, kind="image", raw=f"U+{ord(ch):04X}", text=IMG, quote=q,
                                  img=dict(src=g[0], x=g[1], y=g[2], w=g[3], h=g[4]) if g else None))
                st["image"] += 1
                st["image_quote"] += q
                o.append(IMG)
            elif D._is_pua(ch):
                code = "%04X" % ord(ch)
                r = tab.get(code)
                if r is None:
                    act, to = "无码表行", U
                elif NO_CHAR_CTX.search(left):
                    act, to = "古文作留〓", U
                elif r["verdict"] == "char" and r.get("char"):
                    act, to = "换字", r["char"]
                elif r["verdict"] == "multi":
                    pk = _pick_for(picks, f"U+{code}", left, vs[ci + 1:ci + 7])
                    act, to = ("多字码按逐格人裁", pk["char"]) if pk else ("多字码留〓", U)
                else:
                    act, to = "码表未定留〓", U
                st["pua:" + act] += 1
                slots.append(dict(base, kind="pua", raw=f"U+{code}", text=to, replaced=to != U, action=act,
                                  table=dict(verdict=r["verdict"], char=r.get("char"), chars=r.get("chars"),
                                             nearest=r.get("nearest")) if r else None,
                                  wiki=dict(sk_no=int(code, 16) - 0xE000 + 1)))
                o.append(to)
            else:
                o.append(ch)
        new.append(lead + "".join(o))
    if new and new[0].startswith("# daizhige"):
        new[0] = Z.TXT_HEADER                 # 抬头里「〓／▣」两种占位的说明同步更新（只此一行字数会变）
    (out / "siku_daizhige.new.txt").write_text("\n".join(new) + "\n", encoding="utf-8")
    if glyph_dir is not None:
        man = fetch_glyph_strips(slots, glyph_dir)
        for sl in slots:
            if sl.get("img") and sl["img"]["src"] in man:
                sl["img"]["sha256"] = man[sl["img"]["src"]]["sha256"]
        (out / "glyph_strips.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "slots.jsonl", "w", encoding="utf-8") as f:
        for s in slots:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    st = dict(st)
    st.update({"现网〓": sum(ln.count(U) for ln in cur), "新〓": sum(ln.count(U) for ln in new[1:]),
               "新▣": sum(ln.count(IMG) for ln in new[1:]), "行数相同": len(cur) == len(new),
               "逐行字数相同": all(len(a) == len(b) for a, b in zip(cur[1:], new[1:]))})
    (out / "summary.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ws", required=True, help="含 corpus/ 的数据目录")
    ap.add_argument("--table", help="pua_table.jsonl（缺省 <ws>/config/pua/pua_table.jsonl）")
    ap.add_argument("--picks", help="逐格人裁 cell_picks_mapped_*.json（给一码多字按 text_ctx 对位取字）")
    ap.add_argument("--glyph-dir", help="把以图代字的字图条下到这里并在侧表记 sha256")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ws = Path(a.ws)
    st = run(ws, Path(a.table) if a.table else ws / "config" / "pua" / "pua_table.jsonl", Path(a.out),
             Path(a.picks) if a.picks else None, Path(a.glyph_dir) if a.glyph_dir else None)
    print(json.dumps(st, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
