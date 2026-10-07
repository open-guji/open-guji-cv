"""字组测试集建集：己已巳 / 日曰 / 入人八 三组，vol02–vol10 全量（overview#437，G0，2026-10-06）。

在 N1 `research/near_form/build_samples.py`（overview#428）的基础上扩成**全量**：凡落在组里的格全收，
不只难例；每格带现行产物、真值档、上下文（刻本读序 + 整理本对应位）、字块图。

只读：guji-workspace 快照（`git archive <snap> | tar -x` 解到沙箱，目录名＝`<册>_<时间>`）、
工作区 `feedback/events`（人裁）与 `feedback/vision`（看图结论事件）、`data_full/` 原图、
overview 各册看图清单、cv `research/ri_yue/samples.jsonl`（#352）、dataset `confusable-context`。
不碰正式 products，不写工作区。

一格进某组：放行字 / 整理本对位字 / 坐标证人字 / 库首位 / 真值 任一属于该组 → `core=True`；
只因库第二候选或上下文首选落在组里 → `core=False`（外围，基线不计，留给分类器看召回）。
一格可同属两组（如 已/日），每组各一行，按 `id` 去重做总数。

真值档（`gold_tier`），一格多个来源都记在 `golds` 里，`gold` 取优先级最高的：
  A_human   用户审查页人裁（G1，`review/<批>_verdicts.jsonl`，src=`user_review_<批>`，排最前）；
            人裁事件（`human_chars`，后到覆盖）；`label_origin=human`
  B_vision  看图：`feedback/vision` 事件（后到覆盖）、overview 看图清单、#426 3 格、muse 试点里模型判的；
            `label_origin=vision`
  C_weak    已放行、非人裁、放行字＝整理本对位字＝坐标证人字（**对 match_ref 是循环的**，只作参考；
            己已巳不给这一档，这一族证人常讹）；`label_origin=witness`
用法：python research/char_groups/build.py <snap_root> <dataset>/char-groups [--no-crops] [--ctx N]
  --ctx：上下文前后各取几个字，默认 30（G1 用户 10-06 定：先多放，以后按测试结果再定；G0 是 8）
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import GROUPS, SETS, SNAPS, SPLIT, TIER_HUMAN, TIER_VISION, TIER_WEAK  # noqa: E402

SNAP, OUT = sys.argv[1], sys.argv[2]
CROPS = "--no-crops" not in sys.argv
WS = glob.glob("/home/user/guji-workspace/96mid1ogzk-*")[0]
OV = "/home/user/overview/项目进展/新书整理/书"
CV = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATASET = os.environ.get("GUJI_DATASET", "/home/user/open-guji-dataset")
ALL = set().union(*SETS.values())
# 前后各取几个字（读序，跨列连读；未放行格用整理本字补，再没有记「□」）。G0 取 8，G1 起 30
CTX = int(sys.argv[sys.argv.index("--ctx") + 1]) if "--ctx" in sys.argv else 30
PRIO = {TIER_HUMAN: 0, TIER_VISION: 1, TIER_WEAK: 2, "X_stale": 3, "X_unclear": 4}   # X_ 开头的不当真值，只记一笔


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ── 真值来源 ────────────────────────────────────────────────────────
def parse_look(path, tag, col_char, col_verdict):
    """overview 看图清单（markdown 表）→ {id: (gold, tag, note)}。只收「对…」「X 对」「错→X」。（同 N1）"""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        if not line.startswith("| `vol"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cid = cells[0].strip("`")
        if col_verdict is None:   # vol03 v1：「图上是」一栏直接写字（可带括注）
            # 只收「单字」或「单字(括注)」。N1 取首字，会把「同形」「同上」「封口形…」「印章遮挡」「横条墨块」
            # 读成 同/封/印/横（vol03 己已巳 9 格因此丢了真值）；这 9 格的文意判由 parse_v03_jys 收。
            m = re.fullmatch(r"(\S)(?:[（(].*[)）])?", cells[5]) if len(cells) > 6 else None
            if m and m.group(1) not in "?？—-":
                out[cid] = (m.group(1), tag, f"{cells[5]} / {cells[6]}")
            continue
        v, cur = cells[-1], cells[col_char]
        m = re.match(r"错→(.)", v)
        if m:
            out[cid] = (m.group(1), tag, v)
        elif v.startswith("对") or re.match(r"^. 对", v):
            g = v[0] if re.match(r"^. 对", v) else cur
            if g:
                out[cid] = (g, tag, v)
    return out


def parse_v03_jys(path):
    """vol03 放行错穷举-v1 §四·3「全族逐格文意建议」48 格：| `页:列:格` | 状态 | 现放行 | dzg | 杳冥 | **X** | 上下文 |。
    另外 §四·1/2 的 9 格（文意＝已 / 放行对）也在这张表里，一并收。"""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\| `(\d+:\d+:\d+[ab]?)` \|[^|]*\|[^|]*\|[^|]*\|[^|]*\| \*\*(.)\*\* \| `([^`]*)`", line)
        if m:
            out[f"vol03:{m.group(1)}"] = (m.group(2), "look_v03_jys", f"文意建议 {m.group(2)}：{m.group(3)}")
    return out


def vision_events():
    """`feedback/vision/*.jsonl`（V1 通道，kind=vision_check）→ {id: (gold|None, tag, note, v)}，同格按 ts 取最新。"""
    out = {}
    rows = []
    for p in sorted(glob.glob(f"{WS}/feedback/vision/*.jsonl")):
        rows += [(r, os.path.basename(p)) for r in jl(p)]
    rows.sort(key=lambda x: x[0].get("ts") or "")
    for r, fn in rows:
        if r.get("kind") != "vision_check":
            continue
        p, t = r["payload"], r["target"]
        v = p.get("v")
        g = p.get("char") if v == "wrong" else (p.get("shown") if v == "ok" else None)
        if v == "wrong" and g and len(g) != 1:
            g = None           # 「非字」之类，不是一个字
        out[t["key"]] = (g, f"vision_event:{r.get('batch')}", f"[{p.get('judge')}] {v}: {p.get('note')}", v)
    return out


def look_tables():
    """所有看图来源（label_origin=vision）→ {id: [(gold, tag, note)]}。"""
    out = defaultdict(list)
    srcs = [
        parse_look(f"{OV}/四庫vol03/放行错穷举-v1.md", "look_v03_s8", 1, None),
        parse_v03_jys(f"{OV}/四庫vol03/放行错穷举-v1.md"),
        parse_look(f"{OV}/四庫vol04/放行错穷举-v1.md", "look_v04_s8", 1, -1),
        parse_look(f"{OV}/四庫vol04/己已巳-v1.md", "look_v04_jys", 1, 5),
        {cid: (ch, "card426", "overview#426 看图") for cid, ch in
         (("vol04:40:2:2", "日"), ("vol04:60:9:6", "日"), ("vol04:188:2:20", "八"))},
    ]
    for s in srcs:
        for cid, x in s.items():
            out[cid].append(x)
    for cid, (g, tag, note, v) in vision_events().items():
        if g:
            out[cid].append((g, tag, note))
    return out


def muse_truth():
    """vol03 己已巳 muse 试点 truth.jsonl：truth_src=human → 人裁；claude_z39 → 看图（Z39 会话按文意判）。"""
    out = {}
    p = f"{OV}/四庫vol03/muse-己已巳试点/truth.jsonl"
    for r in jl(p):
        tier = TIER_HUMAN if r["truth_src"] == "human" else TIER_VISION
        out[r["id"]] = (r["truth"], tier, f"muse_truth:{r['truth_src']}")
    return out


def ri_yue_352():
    """#352 日曰研究样本（cv research/ri_yue/samples.jsonl）：tier=human 的当人裁来源记一笔（应与事件一致）。"""
    out = {}
    for r in jl(f"{CV}/research/ri_yue/samples.jsonl"):
        out[r["id"]] = (r["label"], r["tier"])
    return out


def user_reviews():
    """用户亲自人裁的审查页（G1，`review_pages.py` 出页，`harvest_verdicts.py` 收回到 `<OUT>/review/<批>_verdicts.jsonl`）
    → {id: (char|None, src, note)}。成员字 / `other:<字>` 记 A 档，src＝`user_review_<批>`；
    「看不清」与没填字的「别的字」记 `X_unclear`（不当真值，留着看扎堆在哪）。"""
    out = {}
    for p in sorted(glob.glob(f"{OUT}/review/*_verdicts.jsonl")):
        batch = os.path.basename(p)[:-len("_verdicts.jsonl")]
        for r in jl(p):
            v = r.get("verdict") or ""
            ch = v[6:] if v.startswith("other:") else (None if v in ("other", "unclear") else v)
            out[r["id"]] = (ch if ch and len(ch) == 1 else None, f"user_review_{batch}", f"{v} @{r.get('t')}")
    return out


def human_events(book):
    """人裁：`human_chars(book, bind=False)`（不走绑定表——快照不在工作区里，绑定表算不出来；
    按编号取，再在下面用快照里的 channel=human 复核）。"""
    os.environ["GUJI_WORKSPACE"] = WS
    from open_guji_cv.feedback.events import EventLog, counts_as_human
    from open_guji_cv.feedback.lookup import human_chars
    chars = human_chars(book, bind=False)
    last_ts = {}
    for e in EventLog().iter_all():
        p = e.payload or {}
        if (e.kind == "confirm" and e.target.unit == "cell" and e.target.key.startswith(book + ":")
                and counts_as_human(e) and p.get("v") in ("confirm", "seg_defect") and p.get("shape")):
            last_ts[e.target.key] = max(last_ts.get(e.target.key, ""), e.ts)
    return {k: (ch, last_ts.get(k, "")) for k, ch in chars.items()}


# ── 页型 ────────────────────────────────────────────────────────────
def page_types():
    """正文/非正文：workspace 裁决表 page-type 分片（vol01/vol02 有人裁）；其余册 p1 封面、p2 书名签按非正文，
    再加书 yaml 里点名的签页（vol04 p129）。"""
    out = {}
    for r in jl(f"{WS}/feedback/verdicts/page-type/items.jsonl"):
        a = r["anchor"]
        out[(a["book"], int(a["page"]))] = ((r.get("expected") or {}).get("page_type"), "page-type 裁决表")
    return out


EXTRA_NONBODY = {("vol04", 129): "label"}


def page_type(pt, book, page):
    if (book, page) in pt:
        t, s = pt[(book, page)]
        return t, s
    if (book, page) in EXTRA_NONBODY:
        return EXTRA_NONBODY[(book, page)], "书 yaml notes"
    if page <= 2:
        return "front", "推定（p1 封面 / p2 书名签）"
    return "body", "推定（无 page-type 裁决）"


# ── 主流程 ──────────────────────────────────────────────────────────
def cols_of(path, key):
    if not os.path.exists(path):
        return {}
    d = load(path)[key]
    return {ch["id"]: ch for c in d.get("columns", []) for ch in c["chars"]}


def check_upstream(s_seed, s_up, book):
    """seed_admit 的 _manifest.jsonl 里 upstream sha256 与所取上游快照逐页比对。"""
    m = {}
    for r in jl(f"{SNAP}/{s_seed}/products/{book}/seed_admit/_manifest.jsonl"):
        m[r["key"]] = r.get("upstream", {})
    ok = bad = 0
    for st, k in (("align_ref", "align_ref"), ("glyph_match", "glyph_match"),
                  ("context_decide", "context_decision")):
        mf = f"{SNAP}/{s_up}/products/{book}/{st}/_manifest.jsonl"
        if not os.path.exists(mf):
            continue
        sha = {r["key"]: r.get("sha256") for r in jl(mf)}
        for key, u in m.items():
            if k in u and key in sha:
                ok += sha[key] == u[k]
                bad += sha[key] != u[k]
    return ok, bad


def main():
    import cv2
    import numpy as np
    from open_guji_cv.core.anchor import crop_patch
    from open_guji_cv.utils.jiazhu_order import order_keys

    looks = look_tables()
    ureview = user_reviews()
    muse = muse_truth()
    r352 = ri_yue_352()
    pt = page_types()
    rows = []
    snap_info = {}
    for book, (s_seed, s_up, s_cut) in SNAPS.items():
        ok, bad = check_upstream(s_seed, s_up, book)
        snap_info[book] = {"seed_admit": s_seed, "upstream": s_up, "cell_shrink": s_cut,
                           "upstream_sha_match": ok, "upstream_sha_mismatch": bad,
                           "cv_commit": load(f"{SNAP}/{s_seed}/manifest.json")["cv"]["commit"][:10]}
        print(book, "upstream sha", ok, bad, file=sys.stderr)
        hum = human_events(book)
        snap_ts = load(f"{SNAP}/{s_seed}/manifest.json")["created"]
        base = lambda s, st: f"{SNAP}/{s}/products/{book}/{st}"   # noqa: E731
        pages = sorted(os.path.basename(p)[:-5] for p in glob.glob(base(s_seed, "seed_admit") + "/p*.json"))
        for key in pages:
            page = int(key[1:])
            sa = load(f"{base(s_seed, 'seed_admit')}/{key}.json")["seed_admit"]
            arp = f"{base(s_up, 'align_ref')}/{key}.json"
            ar = load(arp)["align_ref"] if os.path.exists(arp) else {}
            amap = {c["id"]: c.get("align_char") for c in ar.get("chars", [])}
            aop = {c["id"]: c.get("align_op") for c in ar.get("chars", [])}
            coord = {c["id"]: c.get("ref_char") for c in ar.get("coord", [])}
            gmap = cols_of(f"{base(s_up, 'glyph_match')}/{key}.json", "glyph_match")
            cmap = cols_of(f"{base(s_up, 'context_decide')}/{key}.json", "context_decision")
            rmap = cols_of(f"{base(s_up, 'rare_candidates')}/{key}.json", "rare_candidates")
            bmap = cols_of(f"{base(s_cut, 'cell_shrink')}/{key}.json", "char_index")
            ptype, ptsrc = page_type(pt, book, page)
            seq = []
            for c in sorted(sa.get("columns", []), key=lambda c: c["col"]):
                chs = c["chars"]
                okk = order_keys((r["slot"], r.get("sub")) for r in chs)
                for r in sorted(chs, key=lambda r: okk[(r["slot"], r.get("sub") or "")]):
                    if "excluded" in (r.get("doubts") or []):
                        continue
                    seq.append((c["col"], r))
            img = None

            def show(r):
                return r.get("char") or amap.get(r["id"]) or coord.get(r["id"]) or "□"

            def ref_show(r):
                return amap.get(r["id"]) or coord.get(r["id"]) or "□"

            for i, (col, r) in enumerate(seq):
                cid = r["id"]
                g = gmap.get(cid, {})
                cands = [x[0] for x in (g.get("candidates") or [])[:2]]
                cx = cmap.get(cid, {})
                ctx_top = cx.get("char") or ((cx.get("ranked") or [[None]])[0][0])
                # 真值：所有来源都记，取优先级最高者
                golds = []
                if cid in ureview:
                    # 用户亲自人裁（G1 审查页）排在 A 档最前：同档按出现先后取，它比工作区事件更新、更有意为之
                    uch, usrc, unote = ureview[cid]
                    golds.append({"char": uch, "tier": TIER_HUMAN if uch else "X_unclear", "src": usrc, "note": unote})
                if cid in hum:
                    hch, hts = hum[cid]
                    # 快照之前的人裁，Step7 当时已按绑定表采信：快照里这格不是 channel=human 且同字，
                    # 说明绑定表把它挪走了/作废了（切分改过，编号对不上）→ 不当真值，只记一笔。
                    if hts < snap_ts and not (r.get("channel") == "human" and r.get("char") == hch):
                        golds.append({"char": hch, "tier": "X_stale", "src": "human_event_unbound",
                                      "note": f"事件 {hts} 早于快照 {snap_ts}，快照未采信（编号可能已漂）"})
                    else:
                        golds.append({"char": hch, "tier": TIER_HUMAN, "src": "human_event", "note": hts})
                for gch, tag, note in looks.get(cid, []):
                    golds.append({"char": gch, "tier": TIER_VISION, "src": tag, "note": note})
                if cid in muse:
                    gch, tier, tag = muse[cid]
                    golds.append({"char": gch, "tier": tier, "src": tag})
                if r.get("channel") == "human" and r.get("char"):
                    # 快照里 Step7 认的人裁（含字形库 `_human_shapes`）；与事件不同时以事件为准（事件后到）
                    golds.append({"char": r["char"], "tier": TIER_HUMAN, "src": "snap_channel_human"})
                if cid in r352 and r352[cid][1] == "human":
                    golds.append({"char": r352[cid][0], "tier": TIER_HUMAN, "src": "r352_human"})
                admitted_char = r.get("char") if r.get("admit") else None
                core_set = {admitted_char, amap.get(cid), coord.get(cid), cands[0] if cands else None,
                            *(x["char"] for x in golds if not x["tier"].startswith("X_"))} - {None}
                peri_set = core_set | {ctx_top, *cands, r.get("char"), *(x["char"] for x in golds)} - {None}
                grp_core = [k for k, s in SETS.items() if core_set & s]
                grp = [k for k, s in SETS.items() if peri_set & s]
                if not grp:
                    continue
                if (r.get("admit") and r.get("channel") not in (None, "human")
                        and r.get("char") and r["char"] == amap.get(cid) == coord.get(cid)
                        and r["char"] not in SETS["jys"]):
                    golds.append({"char": r["char"], "tier": TIER_WEAK, "src": "witness_agree"})
                golds.sort(key=lambda x: PRIO[x["tier"]])
                top = golds[0] if golds and not golds[0]["tier"].startswith("X_") else None
                strong_chars = {x["char"] for x in golds if x["tier"] in (TIER_HUMAN, TIER_VISION)}
                left = "".join(show(x[1]) for x in seq[max(0, i - CTX):i])
                right = "".join(show(x[1]) for x in seq[i + 1:i + 1 + CTX])
                rleft = "".join(ref_show(x[1]) for x in seq[max(0, i - CTX):i])
                rright = "".join(ref_show(x[1]) for x in seq[i + 1:i + 1 + CTX])
                ev = r.get("evidence") or {}
                bx = bmap.get(cid)
                crop = None
                if CROPS and bx and bx.get("bbox_page"):
                    if img is None:
                        img = cv2.imdecode(np.fromfile(f"{WS}/data_full/zongmu/{book}/{page}.png", np.uint8), 0)
                    p = crop_patch(img, tuple(bx["bbox_page"])) if img is not None else None
                    if p is not None and p.size:
                        crop = f"crops/{cid.replace(':', '_')}.png"
                        for gk in grp:
                            os.makedirs(f"{OUT}/{gk}/crops", exist_ok=True)
                            cv2.imwrite(f"{OUT}/{gk}/{crop}", p, [cv2.IMWRITE_PNG_COMPRESSION, 9])
                rare = rmap.get(cid, {})
                for gk in grp:
                    rows.append(dict(
                        id=cid, book=book, page=page, col=col, slot=r["slot"], sub=r.get("sub"),
                        group=gk, core=gk in grp_core, split=SPLIT[book],
                        page_type=ptype, page_type_src=ptsrc, kind=(bx or {}).get("step3_kind"),
                        gold=top["char"] if top else None,
                        gold_tier=top["tier"] if top else None,
                        label_origin={TIER_HUMAN: "human", TIER_VISION: "vision",
                                      TIER_WEAK: "align"}.get(top["tier"]) if top else None,
                        gold_src=top["src"] if top else None,
                        gold_conflict=len(strong_chars) > 1,
                        golds=golds,
                        admit=bool(r.get("admit")), channel=r.get("channel"), char=r.get("char"),
                        provenance=r.get("provenance"), doubts=r.get("doubts") or [],
                        ref=amap.get(cid), ref_op=aop.get(cid), coord_ref=coord.get(cid),
                        lib=(g.get("candidates") or [])[:3], lib_verdict=g.get("verdict"), lib_cov=g.get("cov"),
                        rare=[[x["char"], x["score"]] for x in (rare.get("candidates") or [])[:3]],
                        ctx=cx.get("char"), ctx_ranked=(cx.get("ranked") or [])[:3], ctx_source=cx.get("source"),
                        ctx_margin=cx.get("margin"),
                        ocr=(ev.get("ocr") or [])[:3], ji_yi_si=ev.get("ji_yi_si"),
                        left=left, right=right, ref_left=rleft, ref_right=rright,
                        word=f"{left[-2:]}【{show(r)}】{right[:2]}",
                        ink=(bx or {}).get("ink_ratio"),
                        wh=[(bx or {}).get("width"), (bx or {}).get("height")], crop=crop,
                        snap=s_seed,
                    ))
        print(book, sum(1 for x in rows if x["book"] == book), file=sys.stderr)
    rows += confusable_vol01()
    by_g = defaultdict(list)
    for x in rows:
        by_g[x["group"]].append(x)
    for gk, rs in by_g.items():
        os.makedirs(f"{OUT}/{gk}", exist_ok=True)
        rs.sort(key=lambda x: (x["book"], x["page"] or 0, x["col"] or 0, x["slot"] or 0, str(x["sub"])))
        with open(f"{OUT}/{gk}/items.jsonl", "w", encoding="utf-8") as f:
            for x in rs:
                if x.get("label_origin") is None:
                    x.pop("label_origin", None)     # 无真值的格不写这个键（cv GoldItem 只认枚举值，不认 null）
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    json.dump({"snapshots": snap_info, "workspace_main": ws_head(), "built_by": "open-guji-cv research/char_groups/build.py"},
              open(f"{OUT}/_build_info.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    c = Counter((x["group"], x["book"], x["gold_tier"]) for x in rows if x["core"])
    for k in sorted(c, key=str):
        print(k, c[k], file=sys.stderr)


def ws_head():
    import subprocess
    try:
        return subprocess.check_output(["git", "-C", WS, "rev-parse", "--short=10", "HEAD"], text=True).strip()
    except Exception:
        return None


def confusable_vol01():
    """dataset confusable-context 里属于三组的题（全在 vol01，没有快照）：只有文本上下文与人裁金标。"""
    out = []
    arms = load(f"{DATASET}/confusable-context/baseline_r1.json")      # 各臂（多数类/字形/OCR/n-gram/大模型）首轮答案
    for r in jl(f"{DATASET}/confusable-context/items.jsonl"):
        c = r["input"]["case"]
        opts = set(c["options"])
        gk = next((k for k, s in SETS.items() if opts <= s), None)
        if gk is None:
            continue
        b, p, col, slot = r["id"].split(":")
        txt, ref, pos = c["col_masked"], c["col_ref_masked"], c["pos"]
        out.append(dict(
            id=r["id"], book=b, page=int(p), col=int(col), slot=int(slot), sub=None,
            group=gk, core=True, split=SPLIT[b], page_type=None, page_type_src=None, kind=None,
            gold=c["gold"], gold_tier=TIER_HUMAN, label_origin="human", gold_src="confusable_context",
            gold_conflict=False, golds=[{"char": c["gold"], "tier": TIER_HUMAN, "src": "confusable_context",
                                         "note": c.get("tier")}],
            admit=None, channel=None, char=c.get("ocr_char"), provenance=None, doubts=[],
            ref=c.get("ref_at_pos"), ref_op=None, coord_ref=None, lib=[], lib_verdict=None, lib_cov=None,
            rare=[], ctx=None, ctx_ranked=[], ctx_source=None, ctx_margin=None, ocr=[[c.get("ocr_char"), c.get("ocr_prob")]],
            ji_yi_si=None, left=txt[max(0, pos - CTX):pos], right=txt[pos + 1:pos + 1 + CTX],
            ref_left=ref[max(0, pos - CTX):pos], ref_right=ref[pos + 1:pos + 1 + CTX],
            word=f"{txt[max(0, pos - 2):pos]}【△】{txt[pos + 1:pos + 3]}", ink=None, wh=[None, None], crop=None,
            snap=None, cc_tier=c.get("tier"), cc_options=c["options"],
            cc_arms={k: v.get(r["id"]) for k, v in arms.items()},
        ))
    return out


if __name__ == "__main__":
    main()
