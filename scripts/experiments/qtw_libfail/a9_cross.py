"""a9：像素比对（a4 base）× CNN 原型（a5 base）交叉：两路一致时的精确率、各自对错的交叉表。"""
import json, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from a1_score_dist import rel
for rm, cn in zip(sys.argv[1::2], sys.argv[2::2]):
    A = {json.loads(l)["id"]: json.loads(l) for l in open(rm, encoding="utf-8")}
    B = {json.loads(l)["id"]: json.loads(l) for l in open(cn, encoding="utf-8")}
    ks = [k for k in A if k in B]
    n = len(ks); t = {}
    agree = agree_ok = 0
    for k in ks:
        a, b = A[k]["base"], B[k]["base"]; tr = A[k]["truth"]
        pa, pb = a["rank"] == 1, b["rank"] == 1
        t[(pa, pb)] = t.get((pa, pb), 0) + 1
        if a["top"] and rel(a["top"], b["top"]):
            agree += 1; agree_ok += pa
    print(rm.split("/")[-1], f"n={n}",
          f"像素对&CNN对 {t.get((True,True),0)} 像素错&CNN对 {t.get((False,True),0)} 像素对&CNN错 {t.get((True,False),0)} 都错 {t.get((False,False),0)}",
          f"| 两路首选一致 {agree}/{n}={agree/n:.1%}，一致时精确率 {agree_ok}/{agree}={agree_ok/max(1,agree):.1%}")
