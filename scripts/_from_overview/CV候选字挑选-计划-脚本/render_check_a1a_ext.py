"""A1a 渲染抽样复现（扩区段版，GUJI-208eg 件三，Emi，2026-10-15）。

与 `render_check_a1a.py` 的差别只有一处：CJK 区段扩到 Unicode 全部统一表意文字扩展区
（Ext A–I，含 U+30000 起的 Ext G/H/I），旧脚本的区段不含 U+30000 起，漏掉 Jigmo3 的大部分独家字。
抽样种子、每字体抽 200 格、`render_char` 调用都与旧脚本相同，只改区段。

另加：列出渲染为空或抛异常的码位（旧脚本只计数），便于逐个核。

用法（cv 仓 venv，cv 仓根目录作为 --cv-root）：
  python render_check_a1a_ext.py --cv-root /home/user/open-guji-cv [--ranges old|ext] [--font-filter Jigmo3]
--ranges old 复跑旧区段，用来和旧结果对照。
输出的临时目录不保留图（同旧脚本）。
"""
import argparse
import json
import random
import sys
import tempfile

SEED = 20261013
N = 200

RANGES_OLD = [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2A6DF)]
# Ext A–I 与 CJK 兼容表意文字补充（U+2F800–U+2FA1F）；Ext G/H/I 为 U+30000 起
RANGES_EXT = RANGES_OLD + [
    (0x2A700, 0x2B73F),  # Ext C
    (0x2B740, 0x2B81F),  # Ext D
    (0x2B820, 0x2CEAF),  # Ext E
    (0x2CEB0, 0x2EBEF),  # Ext F
    (0x2EBF0, 0x2EE5F),  # Ext I
    (0x2F800, 0x2FA1F),  # 兼容表意文字补充
    (0x30000, 0x3134F),  # Ext G
    (0x31350, 0x323AF),  # Ext H
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv-root", default="/home/user/open-guji-cv")
    ap.add_argument("--ranges", choices=["old", "ext"], default="ext")
    ap.add_argument("--font-filter", default="", help="只跑文件名含此串的字体")
    args = ap.parse_args(argv)

    sys.path.insert(0, args.cv_root)
    from fontTools.ttLib import TTFont
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.synth import render_char

    ranges = RANGES_OLD if args.ranges == "old" else RANGES_EXT
    tmp = tempfile.mkdtemp(prefix="a1a_render_ext_")  # 临时目录，不留图
    for fp in _font_files():
        if args.font_filter and args.font_filter not in str(fp):
            continue
        f = TTFont(fp, lazy=True, fontNumber=0)
        cmap = f.getBestCmap() or {}
        f.close()
        cov = {cp for cp in cmap if any(lo <= cp <= hi for lo, hi in ranges)}
        pop = sorted(cov)
        rng = random.Random(SEED)
        pick = rng.sample(pop, min(N, len(pop)))
        ok, empty, exc = 0, [], []
        for cp in pick:
            try:
                im = render_char(chr(cp), fp, size=64)
                if im is not None and im.any():
                    ok += 1
                else:
                    empty.append(f"U+{cp:04X}")
            except Exception as e:  # 记录异常类型，不吞
                exc.append(f"U+{cp:04X}:{type(e).__name__}")
        row = {
            "font": str(fp),
            "ranges": args.ranges,
            "cmap_cover": len(cov),
            "sampled": len(pick),
            "sampled_ge_U30000": sum(1 for cp in pick if cp >= 0x30000),
            "render_ok": ok,
            "render_empty": len(empty),
            "render_exc": len(exc),
            "empty_cps": empty,
            "exc_cps": exc,
        }
        print(json.dumps(row, ensure_ascii=False))
    print("tmp dir (not kept):", tmp)


if __name__ == "__main__":
    main()
