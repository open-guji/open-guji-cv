"""入人八 17 格审查页（Z-rr，overview#442）：分类器与放行字分歧 11 格 + 整理本=分类器且 p≥0.8 的待审 6 格。
复用 G1 的 review_pages（壳、卡面）；没有快照/工作区，不出整列小图；卡面不印分类器结论。
用法：python rr/review_rr17.py <dataset>/char-groups -o page.html [--seed-verdicts v.jsonl]"""
import argparse, json, sys, os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import review_pages as rp
from common import GROUPS


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--seed-verdicts"); a = ap.parse_args()
    root = a.root
    items = {json.loads(l)["id"]: json.loads(l) for l in open(f"{root}/rr/items.jsonl", encoding="utf-8")}
    cpath = Path(root) / "review" / "rr17_cards.jsonl"
    if not cpath.exists():
        cand = json.load(open(f"{root}/rr/clf_candidates.json", encoding="utf-8"))
        sel = [d for d in cand if d["类"].startswith("分歧")] + [d for d in cand if d["类"] == "待审:整理本=分类器" and d["p"] >= 0.8]
        with open(cpath, "w", encoding="utf-8") as f:
            for d in sel:  # 顺序按 id 打散（固定）
                f.write(json.dumps({"id": d["id"], "stratum": "rr17:" + ("分歧" if d["类"].startswith("分歧") else "待审"),
                                    "stratum_weight": 1.0, "group": "rr"}, ensure_ascii=False) + "\n")
        lines = sorted(open(cpath, encoding="utf-8"), key=lambda s: __import__("hashlib").md5(s.encode()).hexdigest())
        open(cpath, "w", encoding="utf-8").writelines(lines)
    cards = [json.loads(l) for l in open(cpath, encoding="utf-8")]
    members = list(GROUPS["rr"]["members"])
    rows, imgs = [], {}
    for i, c in enumerate(cards, 1):
        r = items[c["id"]]
        crop = rp.crop_img(root, "rr", r)
        if crop: imgs[f"c:{r['id']}"] = crop
        rows.append(dict(id=r["id"], no=f"#{i:02d}", book=r["book"], page=r["page"], col=r["col"], slot=r["slot"], sub=r["sub"],
            left=r["left"], right=r["right"], ref_left=r["ref_left"], ref_right=r["ref_right"],
            m_char=r["char"] if r["admit"] else None, m_ref=r["ref"] or r["coord_ref"], m_channel=r["channel"] or "待审",
            img=bool(crop), colimg=False, col_top=None, col_h=None, stratum=c["stratum"], stratum_weight=1.0))
    verdicts = {}
    if a.seed_verdicts:
        for l in open(a.seed_verdicts, encoding="utf-8"):
            x = json.loads(l); verdicts[x["id"]] = {"v": x["verdict"], "t": x.get("t") or 0}
    intro = f"入人八人裁（第二轮，只 {len(rows)} 格）：看字块和上下文，点这一格实际是人、入、八哪个字。上头有横且与撇相连是「入」；有横但不与撇相连是「八」；没有横是「人」。"
    title = "入人八十七格"
    js = (rp.PAGE_JS.replace("__MEMBERS__", json.dumps(members, ensure_ascii=False)).replace("__TITLE__", title).replace("__INTRO__", intro))
    css = rp.VERDICT_CSS.replace("NMEM", str(len(members)))
    html = rp.render(title, "char-groups-rr17-review-z", verdicts=verdicts, css=css, page_js=js,
                     payload={"rows": rows, "imgs": imgs, "group": "rr17"})
    Path(a.out).write_text(html, encoding="utf-8")
    print(a.out, f"{len(html)/1024/1024:.2f} MB", len(rows), file=sys.stderr)
main()
