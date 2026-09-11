# -*- coding: utf-8 -*-
"""字形库自洽审计：放行错了，库自己把它揪出来。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/audit_glyph_consistency.py
    … --books vol02 --out output/audit_glyph_ids.txt
    然后：scripts/build_char_review.py --ids output/audit_glyph_ids.txt --title 库自洽审计

## 思路

只拿**人裁过的刻例**建一个子库（零机器污染），把每个机器放行的刻例拿去跟子库比：
子库 top1 与放行字**不同字**（语义归一后），且子库里**有**放行字的刻例——这才有比较
的意义，子库里根本没这个字时 top1 必然是别的字——就是可疑。

## 为什么是这个口径（2026-09-06 原型实测，audit_proto）

953 个有人裁真值的机器放行位，真错 3 条（0.3%）。
- 只看「子库 top1 ≠ 放行字」：标 420，真错 3 全抓，误报 417——子库缺字的全报了；
- 加「子库里有放行字的刻例」：标 **42**，真错 **3 全抓**，误报 39。

误报清一色是形近对（人/入、日/曰、末/未、間/聞、與/興），本来就值得人瞄一眼。
这是**定期审计**不是准入闸：42 条一页看完，换来 100% 的召回。
差距门槛（top1 cov − 放行字 cov）会丢真错（≥0.02 就只剩 1/3），所以不设。

跑一遍全库约 15k 例 × 10 次 verify ≈ 十来分钟。产物是一个 id 清单，
按字复核页（build_char_review --ids）直接出可改判的页面。
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.glyph_db import GlyphDB, _unpng  # noqa: E402
from open_guji_cv.clustering.match import GlyphMatcher  # noqa: E402
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="字形库自洽审计")
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--books", default="", help="只查这些书的刻例（逗号分隔；空 = 全库 v2 实例）")
    ap.add_argument("--out", default="output/audit_glyph_ids.txt")
    ap.add_argument("--knn", type=int, default=10)
    a = ap.parse_args()
    t0 = time.time()

    vm = VariantMap.load()
    db = GlyphDB(a.db)
    cur = db.conn.cursor()
    human = cur.execute("""
        SELECT g.char, e.instance_id, d.data FROM exemplars e
        JOIN glyphs g ON g.glyph_id = e.glyph_id
        JOIN admissions a ON a.instance_id = e.instance_id
        JOIN derived d ON d.instance_id = e.instance_id AND d.kind='norm'
        WHERE a.provenance = 'human'""").fetchall()
    matcher = GlyphMatcher(k=a.knn)
    human_chars: set[str] = set()
    for ch, iid, data in human:
        matcher.add(iid, ch, _unpng(data))
        human_chars.add(vm.semantic(ch))
    print(f"人裁子库 {len(matcher)} 例，{len(human_chars)} 字种（按语义）")

    books = {b.strip() for b in a.books.split(",") if b.strip()}
    # ⚠️ 机器刻例全是 v1 时代的（provenance align/context/match，id 无 v2: 前缀）：
    # v2 管线的自动放行**不进库**（admit_decide 模块头「进库不在这一步做」，走
    # 事件→消费者的只有人裁）。所以 glyph_match 用的库 = v1 机器刻例 + v2 人裁刻例，
    # 要审的正是前者。v1 id 对不上 v2 字位，页面直接用库里的图块，改判走撤库。
    rows = cur.execute("""
        SELECT g.char, e.instance_id, a.provenance, a.char, d.data, i.patch_png FROM exemplars e
        JOIN glyphs g ON g.glyph_id = e.glyph_id
        JOIN admissions a ON a.instance_id = e.instance_id
        JOIN derived d ON d.instance_id = e.instance_id AND d.kind='norm'
        JOIN instances i ON i.instance_id = e.instance_id
        WHERE a.provenance != 'human'""").fetchall()
    if books:
        rows = [r for r in rows if r[1].removeprefix("v2:").split(":")[0] in books]
    print(f"待查机器刻例 {len(rows)}（provenance: "
          + ", ".join(f"{k}×{v}" for k, v in Counter(r[2] for r in rows).most_common()) + "）")

    flagged = []
    skipped_nochar = 0
    by_pair: Counter = Counter()
    for n, (shape, iid, prov, reading, data, png) in enumerate(rows, 1):
        if vm.semantic(shape) not in human_chars:
            skipped_nochar += 1
            continue
        m = matcher.match(_unpng(data))
        top = m.char or (m.candidates[0][0] if m.candidates else None)
        if not top or vm.semantic(top) == vm.semantic(shape):
            continue
        topcov = m.cov if m.char else m.candidates[0][1]
        mine = max([v for c, v in m.candidates if vm.semantic(c) == vm.semantic(shape)] or [0.0])
        flagged.append({"id": iid, "shape": shape, "top": top, "topcov": round(float(topcov), 4),
                        "mine": round(float(mine), 4), "prov": prov, "png": png,
                        "top_id": m.matched_id or ""})
        by_pair[(shape, top)] += 1
        if n % 2000 == 0:
            print(f"  {n}/{len(rows)}  已标 {len(flagged)}  {time.time() - t0:.0f}s", flush=True)
    # 排序：**放行字在子库里有命中（mine>0）的排前面**，再按差距。原型里精准的正是这一档
    # （42 标 / 3 真错全抓）；mine=0 的一档在 v1 刻例上被「v1 图块细、v2 人裁图块粗」的
    # 归一化漂移淹了——自/目、固/因、雨/兩、四/曰 这些框形字整片误报，真错只有 已→巳 那一类。
    flagged.sort(key=lambda r: (r["mine"] <= 0, -(r["topcov"] - r["mine"])))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# 字形库自洽审计 {time.strftime('%Y-%m-%d %H:%M')}：机器刻例 {len(rows)}，"
                f"子库无该字跳过 {skipped_nochar}，标出 {len(flagged)}\n")
        f.write("# id\t放行字\t子库top1\ttop1cov\t放行字cov\tprovenance\n")
        for r in flagged:
            f.write("\t".join(str(r[k]) for k in ("id", "shape", "top", "topcov", "mine", "prov")) + "\n")
    html_out = out.with_suffix(".html")
    html_out.write_text(_render(flagged, len(rows), skipped_nochar, matcher), encoding="utf-8")
    print(f"标出 {len(flagged)} 条（{len(flagged) / max(len(rows), 1):.1%}），"
          f"子库无该字跳过 {skipped_nochar}；{time.time() - t0:.0f}s → {out} / {html_out}")
    print("  形近对 top：", "  ".join(f"{s}→{t}×{n}" for (s, t), n in by_pair.most_common(12)))
    return 0


def _render(flagged: list[dict], n_rows: int, n_skip: int, matcher: GlyphMatcher) -> str:
    """一页看完：库里的图块 + 放行字 + 子库最像的那个人裁刻例（并排，看是不是真错）。"""
    import base64
    import html as _h

    import cv2
    import numpy as np

    def b64(png: bytes | None) -> str:
        if not png:
            return ""
        arr = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        if arr is None:
            return ""
        arr = cv2.resize(arr, (96, 96), interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".webp", arr, [cv2.IMWRITE_WEBP_QUALITY, 80])
        return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""

    # 子库刻例的图：matcher 里存的是归一图（norm，64×64 的 0/1 二值，1 = 墨），够看。
    # MatchResult 只在 same 档给 matched_id，unsure 档没有——那就拿子库里该字随便一个
    # 人裁刻例当对照（看的是「这个字长什么样」，不必是最像的那一个）。
    norm_of = {iid: p for iid, p in zip(matcher._ids, matcher._patches)}
    any_of: dict[str, str] = {}
    for iid, ch in zip(matcher._ids, matcher._chars):
        any_of.setdefault(ch, iid)

    def b64norm(iid: str, ch: str) -> str:
        p = norm_of.get(iid) if iid else None
        if p is None:
            p = norm_of.get(any_of.get(ch, ""))
        if p is None:
            return ""
        arr = p.astype(np.float32)
        if arr.max() <= 1.0:
            arr = arr * 255.0
        arr = (255 - arr).astype(np.uint8)          # 墨黑纸白，与左边的原图块一致
        arr = cv2.resize(arr, (96, 96), interpolation=cv2.INTER_NEAREST)
        ok, buf = cv2.imencode(".webp", arr, [cv2.IMWRITE_WEBP_QUALITY, 80])
        return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""

    cards = []
    for r in flagged:
        cards.append(f"""<div class="c">
  <div class="imgs">
    <figure><img src="data:image/webp;base64,{b64(r['png'])}"><figcaption>库存为「{_h.escape(r['shape'])}」</figcaption></figure>
    <figure><img src="data:image/webp;base64,{b64norm(r['top_id'], r['top'])}"><figcaption>人裁「{_h.escape(r['top'])}」{_h.escape(r['top_id'] or any_of.get(r['top'], ''))}</figcaption></figure>
  </div>
  <div class="t"><b class="ch">{_h.escape(r['shape'])}</b> → 子库更像 <b class="ch alt">{_h.escape(r['top'])}</b>
    <span class="m">top1 {r['topcov']} · 自己 {r['mine']} · 差 {round(r['topcov'] - r['mine'], 4)}</span><br>
    <span class="m">{_h.escape(r['id'])} · {_h.escape(r['prov'])}</span></div>
</div>""")
    return f"""<title>字形库自洽审计</title>
<style>
 :root {{ --paper:#F5F4F0; --panel:#fff; --ink:#1B1F24; --mute:#6A7383; --rule:#DAD9D3; --zhu:#B3261E; color-scheme:light; }}
 @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --paper:#16191E; --panel:#1E2228; --ink:#E4E3DD; --mute:#9AA3B2; --rule:#2E343D; --zhu:#E57368; color-scheme:dark; }} }}
 :root[data-theme="dark"] {{ --paper:#16191E; --panel:#1E2228; --ink:#E4E3DD; --mute:#9AA3B2; --rule:#2E343D; --zhu:#E57368; color-scheme:dark; }}
 body {{ margin:0; padding:1.2rem 1.4rem 3rem; background:var(--paper); color:var(--ink); font-family:"Noto Sans TC",sans-serif; }}
 h1 {{ font-family:"Noto Serif TC",serif; font-size:1.6rem; margin:.2rem 0 .3rem; }}
 .note {{ color:var(--mute); font-size:.85rem; max-width:70ch; margin-bottom:1rem; }}
 .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(19rem,1fr)); gap:.6rem; }}
 .c {{ background:var(--panel); border:1px solid var(--rule); border-left:3px solid var(--zhu); border-radius:4px; padding:.5rem; }}
 .imgs {{ display:flex; gap:.5rem; }}
 figure {{ margin:0; text-align:center; font-size:.7rem; color:var(--mute); }}
 figure img {{ width:96px; height:96px; background:#fff; border:1px solid var(--rule); }}
 .t {{ margin-top:.3rem; font-size:.85rem; }}
 .ch {{ font-family:"Noto Serif TC",serif; font-size:1.3rem; }} .alt {{ color:var(--zhu); }}
 .m {{ font-family:Consolas,monospace; font-size:.7rem; color:var(--mute); }}
</style>
<h1>字形库自洽审计</h1>
<p class="note">机器刻例 {n_rows} 例，子库无该字跳过 {n_skip}，标出 <b>{len(flagged)}</b>。每张卡左边是库里的图块及它被存成的字，
右边是人裁子库里最像它的那个刻例。左右两个字一样就是误报（形近对，正常）；不一样、且右边更像——左边多半存错了，
用 <code>evict_instance</code> 撤库。按「差距」降序，越靠前越可疑。</p>
<div class="grid">{"".join(cards)}</div>"""


if __name__ == "__main__":
    raise SystemExit(main())
