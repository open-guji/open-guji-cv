"""把 a8 的 JSON 与汇总表填进 review_page.tmpl.html，产出可发布的单文件页。"""
import json, sys
from pathlib import Path
here = Path(__file__).parent
data, out = sys.argv[1], sys.argv[2]
rows = [
    ("四庫 vol03 · 光盘版锚定", "3000", "97.5%", "98.5%", "0.990", "8.1", "0.195", "98.8%"),
    ("全唐文 · 维基锚定", "3000", "79.9%", "85.3%", "0.939", "22.7", "0.127", "92.2%"),
    ("全唐文 · 用户人裁（待审难例）", "2851", "52.4%", "71.7%", "0.942", "21.1", "0.111", "94.2%"),
]
exp = [
    ("vol03 → 只放大到全唐文尺寸", "97.3%", "0.990", "分辨率不是原因"),
    ("vol03 → 只加针孔毛刺", "97.1%", "0.975", "影响小"),
    ("vol03 → 只削细到全唐文相对笔粗", "86.8%", "0.935", "复现全唐文分数刻度"),
    ("vol03 → 削细 + 针孔", "84.5%", "0.886", ""),
    ("全唐文人裁 → 中值去针孔 + 64² 膨胀 1px（最好）", "60.4%", "0.956", "+8.0pp"),
    ("全唐文人裁 → 去针孔 + 原分辨率加粗 3px", "59.2%", "0.959", "+6.8pp"),
    ("全唐文维基 → 去针孔 + 原分辨率加粗 1px（最好）", "80.5%", "0.948", "+0.6pp"),
    ("全唐文维基 → 中值去针孔 + 64² 膨胀 1px", "76.3%", "0.959", "−3.6pp"),
    ("全唐文人裁 · 自举每字 1 例（按页留出）", "96.6%", "", "+42.5pp（同源偏高）"),
    ("全唐文维基 · 自举每字 1 例（异源测试 464 格）", "95.7%", "", "基线 91.4%"),
]
t1 = "<div class=\"table-wrap\"><table><thead><tr><th>测试集</th><th>n</th><th>像素比对 top-1</th><th>top-5</th><th>cov 中位</th><th>wmax 中位</th><th>64² 墨占比</th><th>CNN 原型 top-1</th></tr></thead><tbody>" + \
    "".join(f"<tr{' class=hl' if i==2 else ''}>" + "".join(f"<td class=mono>{c}</td>" if j else f"<td>{c}</td>" for j, c in enumerate(r)) + "</tr>" for i, r in enumerate(rows)) + "</tbody></table></div>"
t2 = "<div class=\"table-wrap\"><table><thead><tr><th>实验（四庫库不动）</th><th>top-1</th><th>cov 中位</th><th>说明</th></tr></thead><tbody>" + \
    "".join("<tr>" + f"<td>{a}</td><td class=mono>{b}</td><td class=mono>{c}</td><td>{d}</td></tr>" for a, b, c, d in exp) + "</tbody></table></div>"
note = ("<p class=\"note\">结论：我们的预处理没有出错，两书原图都是 1-bit 双值，分辨率也不影响结果。"
        "全唐文的笔画相对字身只有四庫的六成粗，这把分数刻度整体压低（cov 0.99→0.94）；但排名错主要来自刻工字样，"
        "查询侧怎么加粗都救不回来。补救有两条：像素比对这一层，自举每字进一个刻例就够；"
        "另外，同一个借来的库换成 CNN 原型检索，本来就有 92–94%。</p>")
s = (here / "review_page.tmpl.html").read_text(encoding="utf-8")
s = s.replace("__SUMMARY__", t1 + t2 + note).replace("__DATA__", Path(data).read_text(encoding="utf-8"))
Path(out).write_text(s, encoding="utf-8")
print(len(s))
