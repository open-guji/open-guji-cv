# -*- coding: utf-8 -*-
"""候选表 → 码表 config/pua/pua_table.jsonl（一码一行），并核对与待收字登记 glyph_pending_codes.json 一致。

字段：code（带来源前缀，如 daizhige:U+EA96）、verdict（char|not_char|pending|open）、char（归一后的字）、orig（变体归一前的原形，没归一为空）、
variant（true=char 是变体的归一字；null=未标）、nearest（true=char 是最相近的异体字、不保证与原字形同字；verdict=char 的行一律 true，入字形库时必须带这个标注，sheldon 11-06）、cands[{char,src[,note]}]、same_as[…]、by、at、note；另带 count、sk_no（维基 SKchar 号）。
用法：python3 export_table.py CAND.jsonl OUT.jsonl
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KEEP = ["code", "verdict", "char", "chars", "orig", "variant", "nearest", "cands", "same_as", "by", "at", "note", "count", "sk_no"]


def main(cand, out):
    rows = [json.loads(l) for l in open(cand, encoding="utf-8")]
    reg = set(json.load(open(ROOT / "research/a24/pua_src/glyph_pending_codes.json"))["codes"])
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            r = dict(r)
            if r["verdict"] in ("char", "pending") and not r.get("by"):
                r["by"] = "sheldon"
            if r["verdict"] == "char":
                r["nearest"] = True        # sheldon 11-06：码表字是「最相近的异体字」（不一定与原字形同字），入字形库必须注明
            if r["verdict"] in ("char", "pending") and not r.get("at"):
                r["at"] = "2026-11-05"
            f.write(json.dumps({k: r.get(k) for k in KEEP}, ensure_ascii=False) + "\n")
    pend = {r["code"] for r in rows if r["verdict"] == "pending"}
    reg_dz = {c for c in reg if c.startswith("daizhige:")}
    reg_v2 = {c for c in reg if c.startswith("siku-qiefen-v2:")}
    v2_in_table = {s for r in rows if r["verdict"] == "pending" for s in r["same_as"] if s in reg_v2}
    print("表内待收", len(pend), "；登记表 daizhige 码", len(reg_dz), "；登记表 v2 码", len(reg_v2))
    print("登记表 daizhige 码不在表内待收：", sorted(reg_dz - pend))
    print("表内待收不在登记表（码本身或 v2 同义码都不在）：", sorted(c for c in pend if c not in reg_dz and not any(s in reg_v2 for r in rows if r["code"] == c for s in r["same_as"])))
    print("登记表 v2 码在表里有对应的", len(v2_in_table), "/", len(reg_v2), "（其余是总目以外或还没有 E 码的）")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
