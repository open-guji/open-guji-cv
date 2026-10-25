"""送审格分类（2026-10-25，sheldon「以后用一个脚本很快统计出这个表」）：一轮产物里的送审格，有多少是异体字／形近字造成的。

由 ai-team `domain/CV/质检/异体形近送审统计/scripts/`（1_dump＋2_classify）并进来，`guji groups status` 一条命令同时出字组状态与本表。
产物根下要有 `<册>/seed_admit/`；`glyph_match/`（库候选）、`align_ref/`（整理本对位字）缺了也能跑，只是 V／N 分得粗。

四类（一格只进一类，按下面的顺序判）：
- **G 字组**：证据里有 `group`（字组流程判过但没定），键＝组 id。
- **O 与异体形近无关**：印章遮挡、库里没有这个字、整理本缺字（〓／缅甸字母占位）或无整理本对位。
- **V 组外异体对**：整理本字与库首位（或库前五里某个候选）在异体边表 `config/hanzi/core/edges.tsv` 里相连，键＝字对。
- **N 形近护栏**：conflict／never_match／near_form 拦下的，键＝整理本字＋库里紧咬的几个字。
- 其余归 **O**（乱码闸、影子闸、对位替换、库没把握＋上下文不足）。
"""
from __future__ import annotations

import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

CATS = {"G": "字组", "V": "组外异体对", "N": "形近护栏", "O": "与异体形近无关"}
_EDGE_KINDS = ("variant", "simp", "variant_partial")


def load_edges(path: Path | None = None) -> dict[str, set]:
    path = path or Path(__file__).resolve().parents[2] / "config" / "hanzi" / "core" / "edges.tsv"
    e: dict[str, set] = defaultdict(set)
    if not Path(path).exists():
        return e
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[2] in _EDGE_KINDS:
            e[p[0]].add(p[1])
            e[p[1]].add(p[0])
    return e


def _missing(ch) -> bool:
    return ch is None or ch == "〓" or any(0x1000 <= ord(c) <= 0x109F for c in ch)


def classify(r: dict, ref: str | None, cands: list, cand_variants, edges: dict) -> tuple[str, str]:
    """一格送审格 → (类, 键)。`cands` 是 glyph_match 的 [[字, 分], …]。"""
    ds = [x.split("(")[0] for x in (r.get("doubts") or []) if isinstance(x, str)]
    ev = r.get("evidence") or {}
    g = ev.get("group")
    if g:
        return "G", g.get("id") or "?"
    if "occluded" in ds:
        return "O", "印章遮挡"
    if "库里没有这个字" in ds:
        return "O", "库里没有这个字"
    if _missing(ref):
        return "O", "整理本缺字(〓/缅甸)" if ref else "无整理本对位"
    top = cands[0][0] if cands else None
    var = lambda x, y: bool(x and y and x != y and y in edges.get(x, ()))  # noqa: E731
    if var(ref, top):
        return "V", "/".join(sorted({ref, top}))
    vc = [c for c, _ in cands[:5] if var(ref, c)]
    if vc:
        return "V", "/".join(sorted({ref, vc[0]}))
    if any(x in ds for x in ("context_variant_form", "ref_lib_variant")) or cand_variants:
        return "V", "/".join(sorted({x for x in (ref, top) if x}))
    guard = ev.get("guard")
    if guard in ("conflict", "never_match") or any(x in ds for x in ("near_form", "iron_confusable_ref", "护栏:conflict", "护栏:never_match")):
        near = [c for c, s in cands if s >= cands[0][1] - 0.03] if cands else []
        return "N", "/".join(sorted({x for x in [ref] + near[:3] if x}))
    return "O", ("乱码闸" if "ctx_garble_shape" in ds else "影子闸" if "shadow_veto" in ds
                 else "对位替换" if "replace_align" in ds else "库没把握+上下文不足")


def _side(root: Path, book: str, step: str, page: str):
    p = root / book / step / f"{page}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))[step]
    except (ValueError, KeyError):
        return None


def collect(prods: list[Path], edges: dict | None = None) -> dict:
    """→ {"books": {册: {cells, admit, review, G, V, N, O}}, "keys": {类: Counter(键)}, "keys_by_book": {类: {键: {册: n}}}}。"""
    edges = load_edges() if edges is None else edges
    books: dict = defaultdict(Counter)
    keys: dict = {c: Counter() for c in CATS}
    kb: dict = {c: defaultdict(Counter) for c in CATS}
    for root in prods:
        root = Path(root)
        for f in sorted(glob.glob(str(root / "*" / "seed_admit" / "p*.json"))):
            book, page = Path(f).parts[-3], Path(f).stem
            cols = json.loads(Path(f).read_text(encoding="utf-8"))["seed_admit"]["columns"]
            gm, ar = {}, {}
            if (g := _side(root, book, "glyph_match", page)):
                gm = {c["id"]: c for col in g.get("columns", []) for c in col.get("chars", [])}
            if (a := _side(root, book, "align_ref", page)):
                ar = {c["id"]: c.get("align_char") for c in a.get("chars", [])}
                for c in a.get("coord") or []:           # 只有坐标对位的格，整理本字在 coord
                    if c.get("ref_char") and not ar.get(c["id"]):
                        ar[c["id"]] = c["ref_char"]
            for col in cols:
                for r in col["chars"]:
                    b = books[book]
                    b["cells"] += 1
                    if r.get("admit"):
                        b["admit"] += 1
                        continue
                    b["review"] += 1
                    m = gm.get(r["id"], {})
                    cat, key = classify(r, ar.get(r["id"]), m.get("candidates") or [], m.get("cand_variants"), edges)
                    b[cat] += 1
                    keys[cat][key] += 1
                    kb[cat][key][book] += 1
    return {"books": {b: dict(c) for b, c in sorted(books.items())}, "keys": {c: dict(k) for c, k in keys.items()},
            "keys_by_book": {c: {k: dict(v) for k, v in d.items()} for c, d in kb.items()}}


def _delta(now: int, prev: int | None) -> str:
    if prev is None:
        return ""
    d = now - prev
    return f"（{'+' if d > 0 else ''}{d}）" if d else "（0）"


def render_md(d: dict, prev: dict | None = None, top: int = 40) -> list[str]:
    """送审分类的几张表（拼在字组状态报告后面）。`prev` 是上一份报告 json 的 `review` 段，给了就在括号里写增减。"""
    pb = (prev or {}).get("books", {})
    pk = (prev or {}).get("keys", {})
    tot = Counter()
    for c in d["books"].values():
        tot.update(c)
    ptot = Counter()
    for c in pb.values():
        ptot.update(c)
    out = ["## 送审格分类", "",
           "口径见 cv 仓 `open_guji_cv/eval/review_breakdown.py` 模块头。括号里是比上一份的增减" + ("。" if prev else "（这一份没给上一份）。"), "",
           "| 册 | 格 | 放行率 | 送审 | G 字组 | V 组外异体对 | N 形近护栏 | O 无关 |", "|---|---|---|---|---|---|---|---|"]
    for b, c in list(d["books"].items()) + [("合计", tot)]:
        p = pb.get(b) if b != "合计" else (ptot if prev else None)
        g = (lambda k: (p or {}).get(k, 0)) if p is not None else (lambda k: None)
        rate = f"{c.get('admit', 0) / c['cells']:.1%}" if c.get("cells") else "—"
        out.append(f"| {b} | {c.get('cells', 0)} | {rate} | {c.get('review', 0)}{_delta(c.get('review', 0), g('review'))} | "
                   + " | ".join(f"{c.get(k, 0)}{_delta(c.get(k, 0), g(k))}" for k in "GVNO") + " |")
    for cat in "GVN":
        ks = sorted(d["keys"][cat].items(), key=lambda kv: -kv[1])
        if not ks:
            continue
        out += ["", f"### {cat} {CATS[cat]}（{sum(v for _, v in ks)} 格，{len(ks)} 个键；前 {min(top, len(ks))} 个）", "",
                "| 键 | 送审 | 各册 |", "|---|---|---|"]
        for k, v in ks[:top]:
            per = d["keys_by_book"][cat].get(k, {})
            out.append(f"| {k} | {v}{_delta(v, pk.get(cat, {}).get(k, 0) if prev else None)} | "
                       + " ".join(f"{b.replace('vol', '')}:{n}" for b, n in sorted(per.items())) + " |")
    o = sorted(d["keys"]["O"].items(), key=lambda kv: -kv[1])
    if o:
        out += ["", f"### O 无关（{sum(v for _, v in o)} 格）", "", "| 原因 | 送审 |", "|---|---|"]
        out += [f"| {k} | {v}{_delta(v, pk.get('O', {}).get(k, 0) if prev else None)} |" for k, v in o]
    return out
