"""`guji pagekinds <册>`：页型对账表（只读；页型表第 2 步，2026-11-04）。

三样东西摆在一起，人一眼看出哪里对不上：

1. **册配置点名的**（`page_kinds:` 或老写法的 `body_pages／table_pages／roster_pages`，读进来是同一张表）；
2. **页型规则自己判的**（`border_detect_gate` 产物里 `page_type`；被配置或完整栏格改过的页，原判读 flag 里的「…」）；
3. **最后怎么处理的**（正文／点名正文／点名表格／栏格救回正文／自动跳过／其他页型）。

只读产物，不跑 Step。对账项：
- 点名了、产物却没反映（没跑过或没重跑）；
- 点名正文但页型规则本来就判正文（多余，可删）；
- 没点名却被自动跳过（页型 skip）：列出来让人确认是封面／题签／牌记，**探出完整栏格的特别标「疑似误判」**；
- 点名了页号不在本册页范围里。
职名页（roster）是 Step3 里的分支，看不到判定，只核页号在不在册内。

本模块在 ops，只读 `products.store` 的 JSON，不 import steps。不在任何 Step 的 `code_deps` 里。
"""
from __future__ import annotations

import re
from collections import Counter

_FROM = re.compile(r"页型规则判「([^」]+)」")

#: 最后处理方式的显示顺序
HANDLING = ("正文", "点名正文", "点名表格", "栏格救回正文", "自动跳过", "其他页型", "无产物")


def fmt_pages(pages) -> str:
    """页号列表 → `3-5,9,12-15`（排序去重压区间）。"""
    ps = sorted(set(int(p) for p in pages))
    out: list[str] = []
    i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[j] + 1:
            j += 1
        out.append(str(ps[i]) if i == j else f"{ps[i]}-{ps[j]}")
        i = j + 1
    return ",".join(out)


def _flag(flags: list[str], name: str) -> str | None:
    return next((f for f in flags if f.startswith(name + "：") or f.startswith(name + ":")), None)


def judge(m: dict | None) -> dict:
    """一页闸产物 → {auto, handling, n_cols, expected_cols}。`auto` 是页型规则自己判的「类/策略」。"""
    if not m:
        return {"auto": None, "handling": "无产物", "n_cols": None, "expected_cols": None}
    flags = [str(f) for f in (m.get("flags") or [])]
    reject = [str(r) for r in (m.get("reject") or [])]
    here = f"{m.get('page_type')}/{m.get('page_type_policy') or 'standard'}"
    auto, handling = here, None
    for name, h in (("page_type_forced", "点名正文"), ("page_type_table", "点名表格"), ("page_type_grid", "栏格救回正文")):
        f = _flag(flags, name)
        if f:
            mm = _FROM.search(f)
            auto, handling = (mm.group(1) if mm else here), h
            break
    if handling is None:
        if any(r.startswith("page_type_skip") for r in reject):
            handling = "自动跳过"
        elif here == "body/standard":
            handling = "正文"
        else:
            handling = "其他页型"
    return {"auto": auto, "handling": handling,
            "n_cols": m.get("n_cols"), "expected_cols": m.get("expected_cols")}


def build(book, store, pages: list[int]) -> dict:
    """对账。`book` 是 `BookSpec`，`pages` 是要看的页号（缺省整册）。返回可直接 JSON 化的字典。"""
    from ..core.book import _expand_pages
    from ..core.step import page_key
    cfg = {k: sorted(set(_expand_pages(v))) for k, v in (book.page_kinds or {}).items()}
    rows: dict[int, dict] = {}
    for p in pages:
        raw = store.read_raw(book.id, "border_detect_gate", page_key(p))
        rows[p] = judge((raw or {}).get("border_detect_gate_manifest"))
    in_scope = set(pages)
    out_of_scope = {k: [p for p in v if p not in in_scope] for k, v in cfg.items()}
    out_of_scope = {k: v for k, v in out_of_scope.items() if v}
    kind_pages = {k: set(v) for k, v in cfg.items()}
    issues: dict[str, list] = {"not_reflected": [], "redundant_body": [], "auto_skip": [], "auto_skip_suspect": []}
    want = {"body": "点名正文", "table": "点名表格"}
    for kind, ps in kind_pages.items():
        for p in sorted(ps & in_scope):
            r = rows[p]
            if kind in want and r["handling"] != want[kind]:
                if kind == "body" and r["handling"] == "正文" and r["auto"] == "body/standard":
                    issues["redundant_body"].append(p)
                else:
                    issues["not_reflected"].append({"page": p, "kind": kind, "handling": r["handling"]})
    named = kind_pages.get("body", set()) | kind_pages.get("table", set())
    for p in pages:
        r = rows[p]
        if r["handling"] == "自动跳过" and p not in named:
            full = bool(r["n_cols"] and r["expected_cols"] and r["n_cols"] >= r["expected_cols"])
            (issues["auto_skip_suspect"] if full else issues["auto_skip"]).append(
                {"page": p, "auto": r["auto"], "n_cols": r["n_cols"], "expected_cols": r["expected_cols"]})
    counts = Counter(r["handling"] for r in rows.values())
    return {"book": book.id, "n_pages": len(pages), "configured": cfg, "configured_out_of_scope": out_of_scope,
            "handling": {h: counts[h] for h in HANDLING if counts.get(h)},
            "issues": issues,
            "rows": {str(p): rows[p] for p in pages}}


def print_report(res: dict, *, show: int = 30) -> None:
    print(f"{res['book']} · 页型对账 · {res['n_pages']} 页")
    cfg = res["configured"]
    print("  册配置点名：" + ("；".join(f"{k} {fmt_pages(v)}" for k, v in cfg.items()) if cfg else "无（全部交页型规则判）"))
    print("  最后处理：" + "，".join(f"{h} {n}" for h, n in res["handling"].items()))
    iss = res["issues"]
    bad = False
    for k, v in res["configured_out_of_scope"].items():
        bad = True
        print(f"  ✗ {k} 点名的页不在本次范围内：{fmt_pages(v)}（页号写错，或这次没选到）")
    if iss["not_reflected"]:
        bad = True
        c = Counter((x["kind"], x["handling"]) for x in iss["not_reflected"])
        for (kind, h), n in c.items():
            ps = fmt_pages(x["page"] for x in iss["not_reflected"] if (x["kind"], x["handling"]) == (kind, h))
            print(f"  ✗ {kind} 点名了但产物里是「{h}」{n} 页：{ps}（还没重跑 Step1 闸，或页范围不含）")
    if iss["redundant_body"]:
        bad = True
        print(f"  ⚠ body 点名但页型规则本来就判正文，可删 {len(iss['redundant_body'])} 页：{fmt_pages(iss['redundant_body'])}")
    if iss["auto_skip_suspect"]:
        bad = True
        print(f"  ⚠ 没点名、被自动跳过、却探出完整栏格（疑似误判，真是正文的话加进 page_kinds.body）"
              f"{len(iss['auto_skip_suspect'])} 页：")
        for x in iss["auto_skip_suspect"][:show]:
            print(f"      p{x['page']}  页型判「{x['auto']}」  栏 {x['n_cols']}/{x['expected_cols']}")
    if iss["auto_skip"]:
        print(f"  · 没点名、被自动跳过（封面／题签／牌记一类，扫一眼确认）{len(iss['auto_skip'])} 页：{fmt_pages(x['page'] for x in iss['auto_skip'])}")
    if not bad:
        print("  ✓ 点名与产物对得上，没有疑似误判的跳过页")
