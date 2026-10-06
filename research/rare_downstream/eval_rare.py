"""D 道 #126：5-b 接下游 开/关 对照。

  python eval_rare.py <book> <products_dir_A> <products_dir_B> [--truth qtw] [--collate A.json B.json]

每个产物目录读 align_ref / seed_admit，报：锚定页数、待审率、放出格数、
放错率（有真值的格里放出去且字不对的比例，严格 / 含异体两种口径），
以及两边逐格差异（放行状态或字变了的格）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_v = json.loads((REPO / "config/variants/variants.json").read_text(encoding="utf-8"))
TRUTH_DIR = Path(os.environ.get("QTW_TRUTH_DIR", "../overview/项目进展/新书整理/书/全唐文/人裁待导入"))


def rel(a, b):
    """同 R 道 a1 / C 道 evaluate 的口径：字同或 variants.json 登记的异体对。"""
    if a is None or b is None:
        return False
    if a == b:
        return True
    P, D = _v.get("pairs", {}), _v.get("directed", {})
    return (b in (P.get(a) or {})) or (a in (P.get(b) or {})) or (b in (D.get(a) or {})) or (a in (D.get(b) or {}))


def load(pd: Path, book: str, step: str, kind: str) -> dict[int, dict]:
    out = {}
    for f in sorted((pd / book / step).glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if kind in d:
            out[int(f.stem[1:])] = d[kind]
    return out


def qtw_truth(book: str) -> dict[str, str]:
    """人裁真值：batch2/3（按簇确认，accepted_char）+ batch5（source=human，char 非空）。
    batch1 只标了「AI 首选错」（bad）没给真字，不用；ai-vision 不是真值，不用。"""
    t: dict[str, str] = {}
    for f in ("batch2-v2-partial.jsonl", "batch3-v3-partial.jsonl"):
        for line in open(TRUTH_DIR / f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("accepted_char") and d["id"].startswith(book + ":"):
                t[d["id"]] = d["accepted_char"]
    for line in open(TRUTH_DIR / "batch5-v5.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if d.get("source") == "human" and d.get("char") and d["key"].startswith(book + ":"):
            t[d["key"]] = d["char"]
    return t


def summarize(pd: Path, book: str, truth: dict[str, str] | None):
    al = load(pd, book, "align_ref", "align_ref")
    sa = load(pd, book, "seed_admit", "seed_admit")
    cells = {}
    n_auto = n_rev = n_ex = 0
    for pg, d in sa.items():
        n_auto += d["n_auto"]; n_rev += d["n_review"]; n_ex += d.get("n_excluded", 0)
        for cc in d["columns"]:
            for r in cc["chars"]:
                cells[r["id"]] = r
    anchored = sorted(pg for pg, d in al.items() if d.get("anchored"))
    s = {"pages": len(sa), "anchored": len(anchored), "n_auto": n_auto, "n_review": n_rev,
         "n_excluded": n_ex, "review_rate": n_rev / max(1, n_auto + n_rev),
         "anchored_pages": anchored}
    if truth is not None:
        rel_ids = [i for i in truth if i in cells]
        adm = [i for i in rel_ids if cells[i]["admit"]]
        wrong_s = [i for i in adm if cells[i]["char"] != truth[i]]
        wrong_r = [i for i in adm if not rel(cells[i]["char"], truth[i])]
        s.update({"truth_n": len(rel_ids), "truth_admitted": len(adm),
                  "truth_review": len(rel_ids) - len(adm),
                  "wrong_strict": len(wrong_s), "wrong_rel": len(wrong_r),
                  "wrong_rel_ids": [(i, cells[i]["char"], truth[i], cells[i]["channel"]) for i in wrong_r]})
    return s, cells


def collate_stats(path: str, released: dict[str, dict]):
    """collate JSON（光盘版那家）→ 放出格里与光盘版字不同的格（sub.* / variant.*）。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    w = next(x["label"] for x in d["witnesses"] if x.get("quality") == "best")
    unanch = set(d["unanchored"].get(w, []))
    sub = [x for x in d["diffs"] if x["witness"] == w and x.get("admit") and x["kind"].startswith("sub")]
    var = [x for x in d["diffs"] if x["witness"] == w and x.get("admit") and x["kind"].startswith("variant")]
    n_rel = sum(1 for i, r in released.items() if r["admit"] and int(i.split(":")[1]) not in unanch)
    eq = d["summary"]["by_witness"][w]["n_equal"]
    return {"witness": w, "released_on_anchored": n_rel, "admit_sub": len(sub), "admit_variant": len(var),
            "n_equal": eq, "sub_ids": {x["id"]: (x["char"], x["ref"], x["channel"]) for x in sub}}


def main():
    book, A, B = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    truth = qtw_truth(book) if "--truth" in sys.argv else None
    sA, cA = summarize(A, book, truth)
    sB, cB = summarize(B, book, truth)
    rep = {"A": str(A), "B": str(B)}
    for k in ("pages", "anchored", "n_auto", "n_review", "n_excluded", "review_rate",
              "truth_n", "truth_admitted", "truth_review", "wrong_strict", "wrong_rel"):
        if k in sA:
            rep[k] = (sA[k], sB[k])
    rep["anchored_diff"] = {"only_A": sorted(set(sA["anchored_pages"]) - set(sB["anchored_pages"])),
                            "only_B": sorted(set(sB["anchored_pages"]) - set(sA["anchored_pages"]))}
    ch = []
    for i in sorted(set(cA) | set(cB)):
        a, b = cA.get(i), cB.get(i)
        if not a or not b or (a["admit"], a["char"], a["channel"]) != (b["admit"], b["char"], b["channel"]):
            ch.append((i, a and (a["admit"], a["char"], a["channel"]), b and (b["admit"], b["char"], b["channel"]),
                       (truth or {}).get(i)))
    rep["n_changed"] = len(ch)
    rep["changed_admit_A_to_B"] = {
        "review→auto": sum(1 for _i, a, b, _t in ch if a and b and not a[0] and b[0]),
        "auto→review": sum(1 for _i, a, b, _t in ch if a and b and a[0] and not b[0]),
        "auto→auto(char/channel changed)": sum(1 for _i, a, b, _t in ch if a and b and a[0] and b[0]),
    }
    rep["changed_sample"] = ch[:60]
    if truth is not None:
        rep["wrong_rel_ids"] = (sA["wrong_rel_ids"], sB["wrong_rel_ids"])
    if "--collate" in sys.argv:
        k = sys.argv.index("--collate")
        ca, cb = collate_stats(sys.argv[k + 1], cA), collate_stats(sys.argv[k + 2], cB)
        rep["collate"] = {x: (ca[x], cb[x]) for x in ("witness", "released_on_anchored", "admit_sub",
                                                      "admit_variant", "n_equal")}
        rep["collate_sub_only_A"] = {i: v for i, v in ca["sub_ids"].items() if i not in cb["sub_ids"]}
        rep["collate_sub_only_B"] = {i: v for i, v in cb["sub_ids"].items() if i not in ca["sub_ids"]}
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
