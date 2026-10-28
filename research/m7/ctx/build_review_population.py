# -*- coding: utf-8 -*-
"""全书随机抽样复审页（日曰、入人八；2026-10-20，第 2 道）。
总体＝殿本 vol02–10 整理本里的日曰／入人八候选格（整理本字当弱真值）。系统＝L1 先，弃权的随机抽样送 haiku（只收 conf=high）。
入页：系统与整理本字不一致的格（全部）＋系统与整理本一致的格随机各 20（盲审，估整理本与系统「同错」的比例）。
卡上不显示整理本字、不显示机器答案，顺序打散。冻结在 l2_results/pop1/cards.jsonl，重建页时照旧读。
用法：python build_review_population.py <out.html> [--build <scratch>]"""
import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, "/home/user/open-guji-cv/.claude/skills/review-artifact/scripts"); sys.path.insert(0, "/home/user/open-guji-cv")
import build_review_page as b
from review_shell import render
FAM = {"ry": "日曰", "rr": "入人八"}
FROZEN = Path(__file__).parent / "l2_results" / "pop1" / "cards.jsonl"

def build(S):
    from open_guji_cv.groups.ctx_l3 import parse_output
    random.seed(1020)
    cards = []
    for g in FAM:
        smp = json.load(open(f"{S}/{g}_sample.json")); l1 = json.load(open(f"{S}/{g}_l1.json")); man = json.load(open(f"{S}/{g}_manifest.json")); out = {}
        for n in man: out.update(parse_output(open(f"{S}/out/{n}.json").read()))
        cells = [json.loads(l) for l in open(f"{S}/cells.jsonl")]
        dis, agree = [], []
        for c in cells:
            if c["group"] != g: continue
            sysch, via = l1.get(c["id"]), "L1"
            if sysch is None:
                o = out.get(c["id"])
                if not o: continue
                sysch, via = (o["char"] if o["conf"] == "high" and o["char"] in FAM[g] else None), "haiku"
            if sysch is None: continue
            row = dict(id=c["id"], group=g, left=c["left"][-20:], right=c["right"][:20], corpus=c["ref"], system=sysch, via=via)
            (agree if sysch == c["ref"] else dis).append(row)
        cards += [dict(r, why="disagree") for r in dis] + [dict(r, why="agree_audit") for r in random.sample(agree, 20)]
    random.shuffle(cards)
    FROZEN.parent.mkdir(exist_ok=True); FROZEN.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")

def main():
    if "--build" in sys.argv: build(sys.argv[sys.argv.index("--build") + 1])
    cards = [json.loads(l) for l in FROZEN.open(encoding="utf-8")]
    rows = [dict(id=c["id"], group=c["group"], left=c["left"], right=c["right"], chars=FAM[c["group"]], img=False, note="") for c in cards]
    js = b.PAGE_JS.replace("（和字块图）", "").replace("形近字复审", "形近字抽样复审").replace('<button data-g="" aria-pressed="true">全组</button><button data-g="jys" aria-pressed="false">己已巳</button>', '<button data-g="" aria-pressed="true">全组</button>')
    html = render("形近字抽样复审", "m7-pop1-review-v1", verdicts={}, css=b.CSS, page_js=js, payload={"rows": rows, "imgs": {}})
    Path(sys.argv[1]).write_text(html, encoding="utf-8"); print(sys.argv[1], f"{len(html)/1024:.0f} KB", len(rows))
main()
