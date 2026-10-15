# -*- coding: utf-8 -*-
"""w5_demoted_diff.py 的修正版 v2.1（GUJI-208kl，Evan；原脚本在候选终头树 scripts/ 里，不动它）。
v2 → v2.1（Elena 208kn 复验后的小修）：①`demoted_from` 只认**字块格**（含 id 与 admit 的 dict）的 evidence 下，`by` 在 `--strict-by` 下须在 9 遍白名单内、
`channel` 须 str 或 None；列／页级 evidence 里的 demoted_from 算 stray。②JSON 读入遇重复键即报读失败；带键页另做一次保序比较。
③某册读文件失败不中断，打印「册 X 读失败：<path>」、rc=1、继续下一册。④页文件名改 `p[0-9]*.json`，其余 .json 计入 odd_json、rc=1。

用法（与原脚本同序，只多开关）：
  python w5_demoted_diff_v2.py <基线产物根> <W5 产物根> <册> [<册>…] [--sha256] [--strict-by]
  产物路径 <根>/<册>/seed_admit/pNNNN.json。只读。

判据（任一不过 rc=1）：
  ① 把 W5 产物里每个字块格的 `evidence.demoted_from` 去掉后，与基线逐页（JSON 语义）相等；带键的页另须**保序**相同（不 sort_keys）。
  ② 每个 `demoted_from` 都落在 admit=False、channel=None 的格上，形如 {"channel": str|None, "by": str（--strict-by：白名单内的遍名）}。
  ③ `demoted_from` 只许出现在字块格的 evidence 下；格顶层、列／页级、嵌套处出现＝stray。
  ④ 页集合对称（missing／extra），任一边页数为 0（empty）、有不合 `p[0-9]*.json` 命名的 .json（odd_json）都 rc=1。
  --strict-by：`by` 必须在 9 遍白名单内（缺省只验 str，保持与 v2／Elena 14 情形的自造数据 by="x" 兼容；**真书产物请加此开关**）。
  --sha256：没有 demoted_from 的页必须与基线**原始字节**相同（sha256）；带 demoted_from 的页不比原始字节。
输出：每册一行 JSON（原字段不变；v2 增 extra/stray/empty[/sha_diff_pages]；v2.1 增 odd_json／order_diff_pages；读失败只打一行文字）。
退出码：0 全过；1 有不过；2 用法错。"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

# 终头 seed_admit.py 写 demoted_from 的 9 遍（Elena 208kn §二④）
BY_WHITELIST = {"rare_cp_ctx_review", "shadow_veto", "runt_cell_review", "rr_clf", "seal_blank_flip",
                "ji_yi_si_ctx_review", "ji_yi_si_review", "ji_yi_si_clf_conflict", "ji_yi_si_clf_review"}


class ReadFail(Exception):
    pass


def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"重复键 {k!r}")
        d[k] = v
    return d


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=_no_dup)
    except (OSError, ValueError) as e:      # JSONDecodeError／UnicodeDecodeError 都是 ValueError
        raise ReadFail(f"{p}（{type(e).__name__}: {str(e)[:60]}）") from e


def _is_cell(o: dict) -> bool:
    return "id" in o and "admit" in o


def _strip(o, found: list, stray: list, in_evidence=False):
    """去掉字块格 evidence 下的 demoted_from；found＝带键的字块格，stray＝出现在其他位置的 demoted_from（记 id 或 '?'）。"""
    if isinstance(o, dict):
        if in_evidence:
            return {k: _strip(v, found, stray) for k, v in o.items() if k != "demoted_from"}
        if "demoted_from" in o:
            stray.append(o.get("id", "?"))
        out = {}
        for k, v in o.items():
            if k == "evidence" and isinstance(v, dict):
                if "demoted_from" in v:
                    if _is_cell(o):
                        found.append(o)
                        out[k] = _strip(v, found, stray, in_evidence=True)
                    else:                       # 列／页级 evidence：不剥，算 stray
                        stray.append(f"非字块格:{o.get('col', o.get('page', '?'))}")
                        out[k] = _strip(v, found, stray)
                else:
                    out[k] = _strip(v, found, stray)
            else:
                out[k] = _strip(v, found, stray)
        return out
    if isinstance(o, list):
        return [_strip(x, found, stray) for x in o]
    return o


def _dump(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _dump_ordered(o) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _scan(d: Path):
    if not d.is_dir():
        return [], []
    pages = sorted(p.name for p in d.glob("p[0-9]*.json"))
    odd = sorted(p.name for p in d.glob("*.json") if p.name not in set(pages))
    return pages, odd


def compare(a_root: Path, b_root: Path, book: str, sha: bool = False, strict_by: bool = False) -> dict:
    a_dir, b_dir = Path(a_root) / book / "seed_admit", Path(b_root) / book / "seed_admit"
    a_pages, a_odd = _scan(a_dir)
    b_pages, b_odd = _scan(b_dir)
    missing = sorted(set(a_pages) - set(b_pages))
    extra = sorted(set(b_pages) - set(a_pages))
    diff_pages, order_diff, sha_diff, by, bad, stray = [], [], [], Counter(), [], []
    for n in sorted(set(a_pages) & set(b_pages)):
        a = _load(a_dir / n)
        b = _load(b_dir / n)
        found: list = []
        pg_stray: list = []
        b2 = _strip(b, found, pg_stray)
        if _dump(a) != _dump(b2):
            diff_pages.append(n)
        elif found and _dump_ordered(a) != _dump_ordered(b2):
            order_diff.append(n)
        stray += [(n, i) for i in pg_stray]
        if sha and not found and not pg_stray and _sha(a_dir / n) != _sha(b_dir / n):
            sha_diff.append(n)
        for rec in found:
            d = rec["evidence"]["demoted_from"]
            ok = (not rec.get("admit") and rec.get("channel") is None and isinstance(d, dict)
                  and set(d) == {"channel", "by"} and isinstance(d["by"], str) and (not strict_by or d["by"] in BY_WHITELIST)
                  and (d["channel"] is None or isinstance(d["channel"], str)))
            by[d.get("by") if isinstance(d, dict) else "?"] += 1
            if not ok:
                bad.append((n, rec.get("id")))
    r = {"book": book, "pages": len(a_pages), "missing": missing, "extra": extra, "diff_pages": diff_pages,
         "order_diff_pages": order_diff, "demoted_from": dict(by), "bad": bad, "stray": stray,
         "odd_json": {"基线": a_odd, "新根": b_odd} if (a_odd or b_odd) else {},
         "empty": [s for s, n in (("基线", len(a_pages)), ("新根", len(b_pages))) if n == 0]}
    if sha:
        r["sha_diff_pages"] = sha_diff
    return r


def _fails(r: dict) -> bool:
    return bool(r["diff_pages"] or r["order_diff_pages"] or r["bad"] or r["missing"] or r["extra"] or r["stray"]
                or r["empty"] or r["odd_json"] or r.get("sha_diff_pages"))


def main(argv: list[str]) -> int:
    pos = [a for a in argv[1:] if not a.startswith("--")]
    sha = "--sha256" in argv
    if len(pos) < 3:
        print(__doc__)
        return 2
    rc = 0
    for book in pos[2:]:
        try:
            r = compare(Path(pos[0]), Path(pos[1]), book, sha, "--strict-by" in argv)
        except ReadFail as e:
            print(f"册 {book} 读失败：{e}")
            rc = 1
            continue
        print(json.dumps(r, ensure_ascii=False))
        if r["empty"]:
            print(f"册 {book} 页数 0（{'、'.join(r['empty'])}）")
        if _fails(r):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
