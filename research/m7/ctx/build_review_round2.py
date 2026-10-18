# -*- coding: utf-8 -*-
"""第二轮复审页（2026-10-17，sheldon 看完第一轮后）：规则／过滤修完之后仍待人裁的格，字块图放大。
入选：修后管线（L1→haiku 高置信）仍弃权／与金标不符／模型分歧，且 有图、前后文各≥8 字、金标在组内、第一轮没给出组内字裁决；
另加两格「文意与刻字可能不一致」（日曰），请 sheldon 按图上刻的字选。
用法：python build_review_round2.py <out.html>"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import build_review_page as b
from common import *
from review_shell import render

IDS = {"vol02:119:6:6": "", "vol02:10:5:14": "", "vol02:176:7:17": "", "vol04:62:2:9": "", "vol03:3:9:9": "",
       "vol02:183:8:7": "文意像「曰」，请按图上刻的是日还是曰来选。", "vol03:9:6:12": "文意像「曰」，请按图上刻的是日还是曰来选。"}
FROZEN = Path(__file__).parent / "l2_results" / "review_cards_r2.jsonl"
NOTE_ALL = "按图上刻的字选；图糊到看不清、文意也定不了再点拿不准。"

def main():
    if FROZEN.exists(): cards = [json.loads(l) for l in FROZEN.open(encoding="utf-8")]
    else:
        cards = []
        for g in ("jys", "ry", "rr"):
            for r in load(g):
                if r["id"] in IDS:
                    l, rt = window(r)
                    cards.append(dict(id=r["id"], group=g, left=l, right=rt, gold=r["gold"], note=IDS[r["id"]] or NOTE_ALL))
        FROZEN.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    rows, imgs = [], {}
    for c in cards:
        u = b.crop_uri(c["group"], c["id"], h=120, q=80)
        if u: imgs[c["id"]] = u
        rows.append(dict(id=c["id"], group=c["group"], left=c["left"], right=c["right"], chars=FAMILY[c["group"]], img=bool(u), note=c["note"]))
    js = b.PAGE_JS.replace("按前后文（和字块图）选它**应当是哪个字**", "按字块图上刻的字选（文意只作参考）")
    html = render("形近字复审二", "m7-ctx-review-v2", verdicts={}, css=b.CSS + ".card img{height:120px}", page_js=js, payload={"rows": rows, "imgs": imgs})
    Path(sys.argv[1]).write_text(html, encoding="utf-8"); print(sys.argv[1], f"{len(html)/1024:.0f} KB", len(rows))
if __name__ == "__main__": main()
