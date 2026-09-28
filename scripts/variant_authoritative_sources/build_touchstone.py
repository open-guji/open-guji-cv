#!/usr/bin/env python3
"""合并 muse 87 对 + Unihan 命中 + zdic 字头页证据，出试金石 TSV。
只汇总证据，不下判定——判定留给人（或下一轮）。
"""
import json, csv, sys

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def cp_of(ch):
    return f"U+{ord(ch):04X}"

def mentions(text, ch):
    return bool(text) and ch in text

def main():
    pairs = load("muse_87pairs.json")
    rows = {r["id"]: r for r in pairs["rows"]}
    verdicts = pairs.get("verdicts", {})
    unihan = {o["id"]: o for o in load("unihan_results.json")}
    zdic = load("zdic_results.json")

    out_rows = []
    for pid, r in rows.items():
        a, b = r["a"], r["b"]
        za = zdic.get(cp_of(a), {})
        zb = zdic.get(cp_of(b), {})
        uh = unihan.get(pid, {}).get("unihan_hits", [])
        uh_str = "; ".join(f"{h[0]}({h[1]}{h[2]})" for h in uh) if uh else ""
        a_kangxi = (za.get("kangxi") or "").replace("\n", " ")[:200]
        b_kangxi = (zb.get("kangxi") or "").replace("\n", " ")[:200]
        a_basic = (za.get("basic") or "").replace("\n", " ")[:150]
        b_basic = (zb.get("basic") or "").replace("\n", " ")[:150]
        a_pinyin = za.get("pinyin") or ""
        b_pinyin = zb.get("pinyin") or ""
        b_in_a_kangxi = mentions(a_kangxi, b) or mentions(a_basic, b)
        a_in_b_kangxi = mentions(b_kangxi, a) or mentions(b_basic, a)
        user_verdict = verdicts.get(pid, {}).get("v", "")
        out_rows.append({
            "id": pid, "sec": r["sec"], "cells": r["cells"],
            "a": a, "b": b,
            "muse_canonical": r.get("canonical"),
            "muse_basis": r.get("basis"),
            "existing_table_srcs": ",".join(r.get("existing_srcs") or []),
            "user_verdict_已裁": user_verdict,
            "unihan_hit": uh_str,
            "a_pinyin_zdic": a_pinyin, "b_pinyin_zdic": b_pinyin,
            "a_zdic_basic": a_basic, "a_zdic_kangxi": a_kangxi,
            "b_zdic_basic": b_basic, "b_zdic_kangxi": b_kangxi,
            "b字出现在a的zdic正文里": "Y" if b_in_a_kangxi else "",
            "a字出现在b的zdic正文里": "Y" if a_in_b_kangxi else "",
            "zdic_fetch_error_a": za.get("error", ""),
            "zdic_fetch_error_b": zb.get("error", ""),
        })

    fields = list(out_rows[0].keys())
    with open("touchstone_87pairs.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for row in out_rows:
            w.writerow(row)
    print(f"wrote touchstone_87pairs.tsv: {len(out_rows)} rows")

    # 摘要统计
    n_unihan = sum(1 for r in out_rows if r["unihan_hit"])
    n_mention_either = sum(1 for r in out_rows if r["b字出现在a的zdic正文里"] or r["a字出现在b的zdic正文里"])
    n_err = sum(1 for r in out_rows if r["zdic_fetch_error_a"] or r["zdic_fetch_error_b"])
    print(f"Unihan 命中: {n_unihan}/{len(out_rows)}")
    print(f"zdic 正文互相提及: {n_mention_either}/{len(out_rows)}")
    print(f"zdic 抓取失败（需重试）: {n_err}/{len(out_rows)}")

if __name__ == "__main__":
    main()
