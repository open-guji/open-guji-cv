"""形近对消歧：各臂对答案 + 逐题对照表。

答案文件在评分这一刻才读——盲测的意义全在这个先后顺序上。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

TIER_CN = {"hard_ref_silent": "真难档", "easy_ref_gives_answer": "送分档"}


def load_answers(path: Path) -> dict[int, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        n, ch = line.split()
        out[int(n)] = ch
    return out


def tally(key: list[dict], pick_of, label: str) -> dict:
    rows = []
    for k in key:
        p = pick_of(k)
        rows.append({**k, "pick": p, "correct": p == k["gold"]})
    out = {"arm": label, "rows": rows}
    for tier in ("hard_ref_silent", "easy_ref_gives_answer", None):
        sub = [r for r in rows if tier is None or r["tier"] == tier]
        if not sub:
            continue
        n_ok = sum(r["correct"] for r in sub)
        out[TIER_CN.get(tier, "合计")] = (n_ok, len(sub))
    return out


def majority_baseline(key: list[dict]) -> dict:
    """每个形近对内部按金标众数猜——先验极不平衡时的真实对照线。"""
    major = {}
    for pk in {k["pair"] for k in key}:
        g = Counter(k["gold"] for k in key if k["pair"] == pk)
        major[pk] = g.most_common(1)[0][0]
    return tally(key, lambda k: major[k["pair"]], "多数类基线")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("key", help="blind.key.json")
    ap.add_argument("--cases", required=True, help="confusable.json（取形状/OCR 臂）")
    ap.add_argument("--llm", help="大模型答案 txt：每行「题号 字」")
    ap.add_argument("--lm", action="append", default=[],
                    help="n-gram 臂逐题 json（可给多次）")
    ap.add_argument("--out", help="逐题对照写出 json")
    args = ap.parse_args()

    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in json.loads(
        Path(args.cases).read_text(encoding="utf-8"))["cases"]}

    arms = [majority_baseline(key)]

    # 形状臂：库 top-1 落在选项里就用它，否则算弃权（记为错）
    def shape(k):
        c = cases[k["id"]]
        t = c.get("shape_top")
        return t if t in k["options"] else "—"
    arms.append(tally(key, shape, "字形层 top-1"))

    def ocr(k):
        c = cases[k["id"]]
        t = c.get("ocr_char")
        return t if t in k["options"] else "—"
    arms.append(tally(key, ocr, "OCR"))

    for p in args.lm:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        by = {r["id"]: r["pick"] for r in d["results"]}
        arms.append(tally(key, lambda k, by=by: by.get(k["id"], "—"),
                          d.get("arm", Path(p).stem)))

    if args.llm:
        ans = load_answers(Path(args.llm))
        arms.append(tally(key, lambda k: ans.get(k["n"], "—"), "大模型（盲测）"))

    print(f"{'臂':<22}{'真难档':>12}{'送分档':>12}{'合计':>12}")
    print("-" * 58)
    for a in arms:
        cells = []
        for t in ("真难档", "送分档", "合计"):
            ok, n = a.get(t, (0, 0))
            cells.append(f"{ok}/{n} {ok / n:5.1%}" if n else "—")
        print(f"{a['arm']:<22}" + "".join(f"{c:>16}" for c in cells))

    # 逐题：谁错了
    print("\n各臂错题（题号·金标·各臂所选）：")
    picks = {a["arm"]: {r["n"]: r["pick"] for r in a["rows"]} for a in arms}
    names = [a["arm"] for a in arms if a["arm"] != "多数类基线"]
    for k in key:
        wrong = [nm for nm in names if picks[nm][k["n"]] != k["gold"]]
        if not wrong:
            continue
        who = "、".join(f"{nm}={picks[nm][k['n']]}" for nm in wrong)
        print(f"  [{k['n']:03d}] {k['id']:<16} {k['pair']:<8} "
              f"金标 {k['gold']}  {TIER_CN[k['tier']]}   {who}")

    # 逐形近对：哪几对上下文治得了、哪几对治不了——这张表才是能拿去改
    # 管线的东西。语义层归并过的异体对（已/巳）注定治不了，见文档。
    print("\n逐形近对准确率：")
    pairs = sorted({k["pair"] for k in key},
                   key=lambda p: -sum(1 for k in key if k["pair"] == p))
    names = [a["arm"] for a in arms]
    head = "".join(f"{n[:8]:>10}" for n in names)
    print(f"{'对':<8}{'n':>4}{head}")
    for pk in pairs:
        idx = {k["n"] for k in key if k["pair"] == pk}
        cells = ""
        for a in arms:
            sub = [r for r in a["rows"] if r["n"] in idx]
            cells += f"{sum(r['correct'] for r in sub) / len(sub):>10.0%}"
        print(f"{pk:<8}{len(idx):>4}{cells}")

    if args.out:
        Path(args.out).write_text(json.dumps(arms, ensure_ascii=False,
                                             indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
