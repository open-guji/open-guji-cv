#!/usr/bin/env python3
"""对 87 对 muse 异体，查 Unihan_Variants.txt 里的
kSemanticVariant / kZVariant / kSpecializedSemanticVariant /
kTraditionalVariant / kSimplifiedVariant 字段，看两字是否互相收录为异体。
Unihan 数据许可见 unicode.org/license.txt（UNICODE LICENSE V3，
允许自由使用/复制/修改/分发，须保留版权声明）。
"""
import json, re, sys

UNIHAN_DIR = "unihan"
FIELDS = ["kSemanticVariant", "kZVariant", "kSpecializedSemanticVariant",
          "kTraditionalVariant", "kSimplifiedVariant", "kJapaneseNewVariant", "kJapaneseOldVariant"]

def load_variants():
    table = {}  # cp -> {field: [(target_cp, tags)]}
    with open(f"{UNIHAN_DIR}/Unihan_Variants.txt", encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            cp, field, rest = line.rstrip("\n").split("\t", 2)
            if field not in FIELDS:
                continue
            entries = []
            for tok in rest.split():
                m = re.match(r"(U\+[0-9A-F]+)(<.*)?", tok)
                if m:
                    entries.append((m.group(1), m.group(2) or ""))
            table.setdefault(cp, {}).setdefault(field, []).extend(entries)
    return table

def cp_of(ch):
    return f"U+{ord(ch):04X}"

def check_pair(table, a, b):
    cpa, cpb = cp_of(a), cp_of(b)
    hits = []  # (direction, field, tag)
    for field, entries in table.get(cpa, {}).items():
        for tgt, tag in entries:
            if tgt == cpb:
                hits.append((f"{a}->{b}", field, tag))
    for field, entries in table.get(cpb, {}).items():
        for tgt, tag in entries:
            if tgt == cpa:
                hits.append((f"{b}->{a}", field, tag))
    return hits

def main():
    table = load_variants()
    with open("muse_87pairs.json", encoding="utf-8") as f:
        d = json.load(f)
    out = []
    for r in d["rows"]:
        hits = check_pair(table, r["a"], r["b"])
        out.append({"id": r["id"], "a": r["a"], "b": r["b"], "unihan_hits": hits})
    with open("unihan_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    n_hit = sum(1 for o in out if o["unihan_hits"])
    print(f"{n_hit}/{len(out)} 对在 Unihan 变体字段里有直接或反向命中")

if __name__ == "__main__":
    main()
