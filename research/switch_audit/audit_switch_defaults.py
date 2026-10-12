#!/usr/bin/env python3
"""开关登记表「默认」列 vs 代码缺省值：只列不一致的行，不改任何文件。

用法（仓根）：python research/switch_audit/audit_switch_defaults.py

- 读 doc/开关登记表.md 的「参数 | 默认」两列；
- 读 open_guji_cv/ 下三个 Params 类的字段缺省值（ast 解析字面量，不 import，不需要 torch）；
- 范围：seed_admit.*、glyph_match.*、column_gate.*；
- 不一致两类：开／关 与代码缺省的 bool 相反；登记表里的数字与代码对应数值字段不等；
- 另列：登记表写了键、代码类里找不到同名字段（需人看是改名还是已删）。

只读，退出码恒为 0。非字面量缺省（如引用别的模块常量）、嵌套键（如 near_shape.allow_guarded）
无法静态核对，只计数不列出。
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "doc" / "开关登记表.md"
SOURCES = {
    "seed_admit": ("open_guji_cv/steps/seed_admit.py", "SeedAdmitParams"),
    "glyph_match": ("open_guji_cv/steps/glyph_match.py", "GlyphMatchParams"),
    "column_gate": ("open_guji_cv/gates/column_gate.py", "ColumnGateParams"),
}
MISSING = object()


def code_defaults(prefix):
    """返回 {字段名: (缺省值或 MISSING, 'file:line')}。"""
    rel, cls = SOURCES[prefix]
    path = ROOT / rel
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out = {}
            for stmt in node.body:
                if (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                        and stmt.value is not None):
                    try:
                        val = ast.literal_eval(stmt.value)
                    except (ValueError, TypeError):
                        val = MISSING
                    out[stmt.target.id] = (val, f"{rel}:{stmt.lineno}")
            return out
    raise SystemExit(f"找不到类 {cls}（{rel}）")


def registry_rows():
    """返回 [(行号, [参数里的反引号键], 默认列原文)]。"""
    rows = []
    for lineno, line in enumerate(REGISTRY.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("| `"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) != 7:
            continue
        keys = re.findall(r"`([^`]+)`", parts[0])
        if keys:
            rows.append((lineno, keys, parts[1]))
    return rows


def claim_of(default):
    """登记表「默认」声称的开关态：True／False／None（不是开关，如「空列表」「—」）。"""
    if default[:1] == "开":
        return True
    if default[:1] == "关":
        return False
    tok = re.search(r"\b(True|False)\b", default)
    return (tok.group(1) == "True") if tok else None


def numbers_of(default):
    return re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", default)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def main():
    cache = {p: code_defaults(p) for p in SOURCES}
    mismatches, missing = [], []
    checked = skipped = 0

    for lineno, keys, default in registry_rows():
        primary = keys[0]
        prefix, _, field = primary.partition(".")
        if prefix not in SOURCES or not field:
            continue  # 不在本次范围
        if "." in field:
            skipped += 1  # 嵌套键（如 near_shape.allow_guarded），静态核不了
            continue
        defs = cache[prefix]
        if field not in defs:
            missing.append(f"L{lineno}  {primary}  （代码类里没有字段 `{field}`）")
            continue
        pval, ploc = defs[field]
        if pval is MISSING:
            skipped += 1  # 非字面量缺省
            continue
        checked += 1

        claim = claim_of(default)
        if isinstance(pval, bool) and claim is not None and claim != pval:
            mismatches.append(
                f"L{lineno}  {primary}  登记表默认={default!r}  "
                f"代码缺省={pval}（{ploc}）  →  开／关不符"
            )

        nums = numbers_of(default)
        if nums:
            target = None
            for k in [field] + [k.split(".", 1)[-1] for k in keys[1:] if k.startswith(prefix + ".")] \
                    + [k for k in keys[1:] if "." not in k]:
                if k in defs and is_number(defs[k][0]):
                    target = (k, defs[k])
                    break
            if target is None:
                skipped += 1
            else:
                tk, (tval, tloc) = target
                if float(nums[0]) != float(tval):
                    mismatches.append(
                        f"L{lineno}  {primary}  登记表默认={default!r}  "
                        f"代码缺省 {tk}={tval}（{tloc}）  →  数值不符"
                    )

    print("# 开关登记表「默认」列 vs 代码缺省值（只列不一致）")
    print(f"仓库：{ROOT}")
    print()
    print(f"## 不一致（{len(mismatches)}）")
    for line in mismatches:
        print(line)
    print()
    print(f"## 登记表有键、代码类里没有同名字段（{len(missing)}）")
    for line in missing:
        print(line)
    print()
    print(f"核对 {checked} 行；嵌套键／非字面量缺省／无数值对应，未核 {skipped} 行。")


if __name__ == "__main__":
    main()
