"""逐页比两个沙箱根下某册的 seed_admit 产物（GUJI-208jb 补，窗口手册 §〇点六 ②）。

用法：python compare_seed_admit_products.py <基线根> <新根> <册> [--strip-demoted-from]
  根＝GUJI_PRODUCTS_DIR（其下 <册>/seed_admit/p*.json）。只读，不写任何东西。
  --strip-demoted-from：比之前把所有层级的 `demoted_from` 键去掉（W5 在被降级格多记的键，Elena 208if）。
退出码：0＝逐页相同；1＝有页不同或页集合不同。输出不同页号和第一处不同的路径。
"""
import json
import sys
from pathlib import Path


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k != "demoted_from"}
    if isinstance(o, list):
        return [strip(v) for v in o]
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


def main(argv):
    pos = [a for a in argv if not a.startswith("--")]
    do_strip = "--strip-demoted-from" in argv
    base, new, book = Path(pos[0]), Path(pos[1]), pos[2]
    fa = {p.name: p for p in (base / book / "seed_admit").glob("p*.json")}
    fb = {p.name: p for p in (new / book / "seed_admit").glob("p*.json")}
    bad = []
    if set(fa) != set(fb):
        print("页集合不同：只在基线", sorted(set(fa) - set(fb))[:10], "只在新", sorted(set(fb) - set(fa))[:10])
        bad.append("pageset")
    n_dm = 0
    for name in sorted(set(fa) & set(fb)):
        ja, jb = json.loads(fa[name].read_text("utf-8")), json.loads(fb[name].read_text("utf-8"))
        if do_strip:
            n_dm += json.dumps(jb, ensure_ascii=False).count('"demoted_from"')
            ja, jb = strip(ja), strip(jb)
        d = first_diff(ja, jb)
        if d:
            bad.append(name)
            print(f"不同 {name}: {d}")
    print(f"{book}: 比 {len(set(fa) & set(fb))} 页，不同 {len(bad)} 页"
          + (f"；新根里 demoted_from 出现 {n_dm} 处（已剥）" if do_strip else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
