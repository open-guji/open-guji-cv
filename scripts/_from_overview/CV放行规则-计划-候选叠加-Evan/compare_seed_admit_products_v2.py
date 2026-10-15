"""compare_seed_admit_products.py 的修正版 v2.1（GUJI-208kl，Evan）。原文件不动。
v2 → v2.1（Elena 208kn 复验后的小修）：①`--strip-demoted-from` 只剥**字块格**（含 id 与 admit）evidence 下的键，列／页级出现算 stray；
②JSON 读入遇重复键即读失败；带键页另做一次保序比较；③单册读文件失败不中断：打印「册 X 读失败：<path>」、rc=1、继续下一册；
④页文件名改 `p[0-9]*.json`，其余 .json 计数，非零 rc=1。（`demoted_from` 的格式／白名单仍归 w5_demoted_diff_v2 查，这里不查。）

用法（与原脚本同序，只多开关与多册）：
  python compare_seed_admit_products_v2.py <基线根> <新根> <册> [<册>…] [--strip-demoted-from] [--sha256]
  根＝GUJI_PRODUCTS_DIR（其下 <册>/seed_admit/p*.json）。只读。
  --sha256：对每页**原始字节**做 sha256 逐页比对（默认只比 JSON 语义，键序／缩进不同判相同）。
       与 --strip-demoted-from 同用时，带 demoted_from 的页不比原始字节。
多册：逐册各报一行并汇总，任一册不过 rc=1。
退出码：0＝全过；1＝有页不同、页集合不同、某册任一边页数为 0、stray、读失败、odd 命名；2＝用法错。
输出行格式沿用原脚本：「不同 pNNNN.json: <路径>」「<册>: 比 N 页，不同 M 页[；新根里 demoted_from 出现 K 处（已剥）]」。"""
import hashlib
import json
import sys
from pathlib import Path


class ReadFail(Exception):
    pass


def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"重复键 {k!r}")
        d[k] = v
    return d


def load(p: Path):
    try:
        return json.loads(p.read_text("utf-8"), object_pairs_hook=_no_dup)
    except (OSError, ValueError) as e:
        raise ReadFail(f"{p}（{type(e).__name__}: {str(e)[:60]}）") from e


def strip_evidence(o, stray: list, found: list, in_evidence=False):
    if isinstance(o, dict):
        if in_evidence:
            return {k: strip_evidence(v, stray, found) for k, v in o.items() if k != "demoted_from"}
        if "demoted_from" in o:
            stray.append(o.get("id", "?"))
        out = {}
        for k, v in o.items():
            if k == "evidence" and isinstance(v, dict) and "demoted_from" in v:
                if "id" in o and "admit" in o:
                    found.append(o.get("id"))
                    out[k] = strip_evidence(v, stray, found, True)
                else:
                    stray.append(f"非字块格:{o.get('col', o.get('page', '?'))}")
                    out[k] = strip_evidence(v, stray, found)
            else:
                out[k] = strip_evidence(v, stray, found)
        return out
    if isinstance(o, list):
        return [strip_evidence(v, stray, found) for v in o]
    return o


def first_diff(a, b, path=""):
    if type(a) is not type(b):
        return path or "/"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}/{k}"
            d = first_diff(a[k], b[k], f"{path}/{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}[len {len(a)}→{len(b)}]"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else path or "/"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _scan(d: Path):
    if not d.is_dir():
        return {}, []
    pages = {p.name: p for p in d.glob("p[0-9]*.json")}
    odd = sorted(p.name for p in d.glob("*.json") if p.name not in pages)
    return pages, odd


def compare_book(base: Path, new: Path, book: str, do_strip: bool, do_sha: bool) -> int:
    fa, odd_a = _scan(base / book / "seed_admit")
    fb, odd_b = _scan(new / book / "seed_admit")
    bad = []
    if not fa or not fb:
        print(f"册 {book} 页数 0（基线 {len(fa)} 页，新根 {len(fb)} 页）")
        bad.append("empty")
    if odd_a or odd_b:
        print(f"册 {book} 有不合 p[0-9]*.json 命名的 .json：基线 {odd_a[:10]}，新根 {odd_b[:10]}")
        bad.append("odd")
    if set(fa) != set(fb):
        print("页集合不同：只在基线", sorted(set(fa) - set(fb))[:10], "只在新", sorted(set(fb) - set(fa))[:10])
        bad.append("pageset")
    n_dm, stray_all, sha_bad = 0, [], []
    n_diff = 0
    for name in sorted(set(fa) & set(fb)):
        ja, jb = load(fa[name]), load(fb[name])
        has_dm = False
        if do_strip:
            stray, found = [], []
            jb = strip_evidence(jb, stray, found)
            n_dm += len(found)
            has_dm = bool(found or stray)
            if stray:
                stray_all += [(name, i) for i in stray]
                print(f"stray {name}: demoted_from 不在字块格 evidence 下（{stray}）")
        d = first_diff(ja, jb)
        if d:
            n_diff += 1
            bad.append(name)
            print(f"不同 {name}: {d}")
        elif do_strip and found and json.dumps(ja, ensure_ascii=False) != json.dumps(jb, ensure_ascii=False):
            n_diff += 1
            bad.append(name)
            print(f"不同 {name}: 剥键后语义同，但键序不同（保序比较）")
        if do_sha and not has_dm and _sha(fa[name]) != _sha(fb[name]):
            sha_bad.append(name)
    if stray_all:
        bad.append("stray")
    if sha_bad:
        print(f"sha256 不同页（{len(sha_bad)}）：{sha_bad[:20]}")
        bad.append("sha256")
    print(f"{book}: 比 {len(set(fa) & set(fb))} 页，不同 {n_diff} 页"
          + (f"；新根里 demoted_from 出现 {n_dm} 处（已剥）" if do_strip else "")
          + (f"；sha256 不同 {len(sha_bad)} 页" if do_sha else ""))
    return 1 if bad else 0


def main(argv):
    pos = [a for a in argv if not a.startswith("--")]
    if len(pos) < 3:
        print(__doc__)
        return 2
    do_strip, do_sha = "--strip-demoted-from" in argv, "--sha256" in argv
    rc = 0
    for book in pos[2:]:
        try:
            rc |= compare_book(Path(pos[0]), Path(pos[1]), book, do_strip, do_sha)
        except ReadFail as e:
            print(f"册 {book} 读失败：{e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
