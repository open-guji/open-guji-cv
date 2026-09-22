# -*- coding: utf-8 -*-
"""对勘报告：已整理页面的转写 × 整理本，逐字比对，出可分享的单文件 HTML。

    python scripts/build_collation_report.py --book vol01 [--pages 4-60,63-88]
        [--out output/collation_vol01.html] [--strip 5] [--thumb-h 40] [--limit-strips 1500]

回答两个问题（用户 2026-09-06 定）：
1. **异体字**：哪些字位刻本形与整理本形不同但是同一个字（卽/即、厯/歷）——按对汇总、
   附例图；
2. **增删改**：同位置不同字（改）、刻本多出（整理本无）、整理本多出（刻本缺）——每条
   截出**原图上下 5 格的竖条**（目标格红框）+ 转写与整理本各 ±5 字的文字上下文，复核的
   人一眼能看。

## 转写取哪个字（按可信度降序）

人裁（confirm 事件的 shape）> 自动放行的 `AdmitRec.char` > Step6 定字 > 库 top1 > OCR top1 > □。
每条差异都标明来源——**机器猜的差异与人裁过的差异，复核时权重完全不同**。

## 对齐怎么做

整理本先只留汉字（抬头码 ⏎b1/c3/a1、全角空格、行末「-」都会让锚点漂），
页文本用 8-gram 投票锚到整理本（`align_eval.anchor_page`），窗口 = 页长 + WINDOW_PAD，
`difflib.SequenceMatcher` 走 opcode。与 `label_page` 的区别：那边只收 equal 与等长 replace
（为了出干净金标），**这里 insert / delete / 不等长 replace 都要**——增删正是复核要看的。
窗口尾部的余量必然表现为一段 insert，按「贴着页文本末尾」识别并丢弃。

## 分类

- `variant`：hyp ≠ ref 但互为异体（关系图有边，或语义层同一代表字，见 `round_check._same_char`）
- `substitution`：hyp ≠ ref 且不是异体
- `extra`：刻本有、整理本无（opcode delete）
- `missing`：整理本有、刻本无（opcode insert）——多半是漏切 / 两字合一格
- `unreadable`：转写是 □（无任何候选）而整理本有字
- 排除名单里的格（`doubts` 含 excluded）不进比对，单列计数

产出还带一份同名 `.json`（不含图），给后续脚本读。
"""

from __future__ import annotations

import argparse
import base64
import difflib
import html
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.clustering.align_eval import WINDOW_PAD, anchor_page, build_ngram_index  # noqa: E402
from open_guji_cv.clustering.align_label import is_han  # noqa: E402
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import cell_key, page_key  # noqa: E402
from open_guji_cv.core.workspace import corpus_path  # noqa: E402
from open_guji_cv.eval.round_check import DATASET, _same_char, load_verdicts  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.report.collation_grade import GRADE_LABEL, summarize  # noqa: E402
from open_guji_cv.utils.image_io import imread  # noqa: E402

#: 每一层在报告里写明判据——分层是给人看的排序，人得能不同意它。
GRADE_NOTE = {
    "suspect": "只出现一两次、无已知关系——最该先看这批",
    "gap": "刻本多出或整理本多出，多半是漏切/两字并一格，或整理本据他本补字",
    "taboo": "清刻本避諱改字，整理本回改原字；录刻本形是对的",
    "systematic": "同一字对全书反复出现（≥3 次），是版本用字差异而非识别错",
    "variant": "异体关系图已收，同字异形",
}

# ⚠️ 走 core.workspace.corpus_path，不要写死相对路径——见 steps/align_ref.py
# 模块头「2026-09-11」一节，硬编码相对路径曾导致读到仓内过期样本。
DEFAULT_CORPUS = str(corpus_path("zongmu_wuyingdian_reference.txt"))
KINDS = ("substitution", "missing", "extra", "unreadable", "variant")
KIND_LABEL = {"variant": "异体（同字异形）", "substitution": "改（同位置不同字）",
              "extra": "刻本多出（整理本无）", "missing": "整理本多出（刻本缺）",
              "unreadable": "无法辨认（转写为 □）"}


# ── 转写 ─────────────────────────────────────────────────

def body_pages(book: str, st: ProductStore) -> list[int]:
    f = DATASET / "page-type" / "items.jsonl"
    body = set()
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            a = r.get("anchor") or {}
            if str(a.get("book")) == book and (r.get("expected") or {}).get("page_type") == "body":
                body.add(int(a["page"]))
    return sorted(p for p in body if st.exists(book, "seed_admit", page_key(p)))


def page_slots(book: str, page: int, st: ProductStore, truth: dict[str, str]) -> list[dict]:
    """→ 阅读顺序的字位列表，每格 {id,col,slot,sub,char,source,admit,excluded}。"""
    a = st.read(book, "seed_admit", page_key(page), "seed_admit")
    m = st.read(book, "glyph_match", page_key(page), "glyph_match")
    o = st.read(book, "ocr_candidates", page_key(page), "ocr_candidates")
    d = st.read(book, "context_decide", page_key(page), "context_decision")
    if a is None:
        return []
    mm = {r.id: r for cc in (m.columns if m else []) for r in cc.chars}
    om = {r.id: r for cc in (o.columns if o else []) for r in cc.chars}
    dm = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
    out = []
    for cc in a.columns:
        if not cc.ok:
            continue
        for r in _reading_order(cc.chars):
            excluded = "excluded" in (r.doubts or [])
            h = truth.get(r.id)
            if h:
                ch, src = h, "human"
            elif r.admit and r.char:
                ch, src = r.char, f"auto:{r.channel or '?'}"
            else:
                dr, mr, orr = dm.get(r.id), mm.get(r.id), om.get(r.id)
                if dr and dr.char:
                    ch, src = dr.char, "ctx"
                elif mr and mr.candidates:
                    ch, src = mr.candidates[0][0], "lib"
                elif orr and orr.topk:
                    ch, src = orr.topk[0][0], "ocr"
                else:
                    ch, src = "□", "none"
            out.append({"id": r.id, "col": cc.col, "slot": r.slot, "sub": r.sub or "",
                        "char": ch if not excluded else "□", "source": "excluded" if excluded else src,
                        "admit": bool(r.admit), "excluded": excluded,
                        "doubts": [x.split("(")[0] for x in (r.doubts or [])]})
    return out


def _reading_order(chars) -> list:
    """一列内的阅读顺序。夹注（双行小字）的格带 sub：a = 右行、b = 左行，读法是右行
    从上到下读完再读左行——按 (slot, sub) 排会把两行交错成 a1 b1 a2 b2，p146 一段
    夹注就此冒出 11 条假「刻本多」。连着的一串夹注格算一段，段内先 a 后 b。"""
    out, run = [], {}

    def flush():
        for sub in sorted(run):
            out.extend(run[sub])
        run.clear()

    for r in sorted(chars, key=lambda x: (x.slot, x.sub or "")):
        if r.sub:
            run.setdefault(r.sub, []).append(r)
        else:
            flush()
            out.append(r)
    flush()
    return out


# ── 对齐与分类 ──────────────────────────────────────────────

def classify(hyp: str, ref: str) -> str:
    if hyp == "□":
        return "unreadable"
    if hyp == ref:
        return "equal"
    return "variant" if _same_char(hyp, ref) else "substitution"


_VM: VariantMap | None = None


def _vm() -> VariantMap:
    global _VM
    if _VM is None:
        _VM = VariantMap.load()
    return _VM


def diff_page(slots: list[dict], corpus: str, index: dict, pad: int = WINDOW_PAD,
              vm: VariantMap | None = None) -> tuple[list[dict], dict]:
    """→ (差异条目, 统计)。锚不上时返回 ([], {"anchored": False})。"""
    text = "".join(s["char"] for s in slots)
    offset = anchor_page(text, index)
    stat = {"anchored": offset is not None, "n_slots": len(slots), "equal": 0,
            "excluded": sum(1 for s in slots if s["excluded"])}
    if offset is None:
        return [], stat
    # 窗口头尾各留 pad：投票偏移会被页内多出/漏掉的格带偏几字（页首两格空着的纪年行、
    # 整列没切出来），余量让 difflib 自己找回对齐；余量本身不是刻本缺字——
    # 凡**贴着页文本头/尾**的 op，窗口侧的剩余一律丢掉。它不一定表现为纯 insert：
    # 页末最后一格若与整理本不一致，difflib 会给「1 字 vs 61 字」的不等长 replace
    # （dev_set 实测 p11/p33 各冒出 50+ 条假 missing）。代价：页首/页末真缺的字看不见。
    lo, hi = max(0, offset - pad), min(len(corpus), offset + len(text) + pad)
    window = corpus[lo:hi]
    # 先归到语义层再对齐：刻本「厯」对整理本「一歷」，按原字 difflib 会配成 厯→一 + 缺 歷；
    # 归一后 厯≡歷 才配得上，「一」才正确记成整理本多。分类仍按原字（异体不算一致）。
    vm = vm or _vm()
    text_n, window_n = vm.normalize_text(text), vm.normalize_text(window)
    if len(text_n) != len(text) or len(window_n) != len(window):
        text_n, window_n = text, window
    sm = difflib.SequenceMatcher(None, text_n, window_n, autojunk=False)
    ops = sm.get_opcodes()
    entries: list[dict] = []

    def ctx_text(i: int, k: int = 5) -> str:
        return text[max(0, i - k):i] + "【" + (text[i] if i < len(text) else "") + "】" + text[i + 1:i + 1 + k]

    def ctx_ref(j: int, k: int = 5, n: int = 1) -> str:
        # 按语料绝对位置取，上下文不受窗口边界限制；n>1 时括起整段（整理本多出的一串）
        a = lo + j
        return corpus[max(0, a - k):a] + "【" + corpus[a:a + n] + "】" + corpus[a + n:a + n + k]

    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            # 语义层相等 ≠ 字形相等：块内逐字看原字，卽/即 这类要记成异体
            for k in range(i2 - i1):
                s, ref = slots[i1 + k], window[j1 + k]
                if s["excluded"] or s["char"] == ref:
                    stat["equal"] += 1
                    continue
                entries.append({**_pos(s), "kind": classify(s["char"], ref), "hyp": s["char"], "ref": ref,
                                "source": s["source"], "admit": s["admit"], "doubts": s["doubts"],
                                "hyp_ctx": ctx_text(i1 + k), "ref_ctx": ctx_ref(j1 + k)})
            continue
        at_head, at_tail = i1 == 0, i2 >= len(text)
        if tag == "insert" and (at_head or i1 >= len(text)):
            continue
        L = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        # 页首的不等长 replace：窗口侧前面那截是余量，等长部分要跟窗口段的**末尾** L 字配对
        jb = (j2 - L) if at_head else j1
        # 等长部分逐字比
        for k in range(L):
            s = slots[i1 + k]
            ref = window[jb + k]
            if not is_han(ref) or s["excluded"]:
                continue
            kind = classify(s["char"], ref)
            if kind == "equal":
                stat["equal"] += 1
                continue
            entries.append({**_pos(s), "kind": kind, "hyp": s["char"], "ref": ref,
                            "source": s["source"], "admit": s["admit"], "doubts": s["doubts"],
                            "hyp_ctx": ctx_text(i1 + k), "ref_ctx": ctx_ref(jb + k)})
        # 剩余：刻本多（text 侧，每格一条——图就是证据）
        for k in range(L, i2 - i1):
            s = slots[i1 + k]
            if s["excluded"]:
                continue
            entries.append({**_pos(s), "kind": "extra" if s["char"] != "□" else "unreadable",
                            "hyp": s["char"], "ref": "", "source": s["source"], "admit": s["admit"],
                            "doubts": s["doubts"], "hyp_ctx": ctx_text(i1 + k),
                            "ref_ctx": ctx_ref(min(jb + L, len(window) - 1))})
        # 整理本多（window 侧）：一串合成一条，挂到前一个字位上（刻本缺的字，图上只能看邻位）。
        # 整列没切出来时是连着 21 个字，拆成 21 条只会把同一张截条图重复 21 遍。
        if at_head or at_tail:
            continue
        run = "".join(c for c in window[jb + L:j2] if is_han(c))
        if run:
            anchor_i = min(max(i1 + L - 1, 0), len(slots) - 1)
            s = slots[anchor_i]
            entries.append({**_pos(s), "kind": "missing", "hyp": "", "ref": run, "n": len(run),
                            "source": s["source"], "admit": s["admit"], "doubts": s["doubts"],
                            "hyp_ctx": ctx_text(anchor_i), "ref_ctx": ctx_ref(jb + L, n=len(run)),
                            "attached": True})
    return entries, stat


def _pos(s: dict) -> dict:
    return {"id": s["id"], "col": s["col"], "slot": s["slot"], "sub": s["sub"]}


# ── 图 ───────────────────────────────────────────────────

def _load_cell(cache: ImageCache, book: str, page: int, col: int, slot: int, sub: str, h: int):
    p = cache.get(book, "char_patch", cell_key(page, col, slot) + sub)
    if p is None:
        return None
    # ⚠️ 必须走 utils.image_io.imread（np.fromfile + imdecode），不能用 cv2.imread：
    # OpenCV 在 Windows 下按 ANSI 编码传路径，工作区目录名一带中文就恒返回 None
    # （2026-09-22 实测：`988g7gsqhd-北行日錄…` 下 545 条截条图**全部为空**，
    # 报告里每条差异旁边都是「无图」，而生成过程一句错都不报）。
    img = imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    w = max(1, int(round(img.shape[1] * h / img.shape[0])))
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def strip_b64(cache: ImageCache, book: str, page: int, col_slots: list[dict], k: int,
              radius: int, h: int) -> str | None:
    """目标格前后各 radius 格，**横排**成一条，目标格红框。→ WebP base64。

    ## 为什么横排、为什么只截 ±2

    旧版是竖排 ±5 格：11 个字块each 40px 叠起来近 500px 高，一条差异占掉整屏，
    545 条就是 545 屏，「看得很累」（用户 2026-09-22）。古籍是竖排，所以竖着截
    看似天经地义——但**报告不是书**：报告要的是「一眼看清这个字长什么样、左右
    邻字是什么」，上下文有文字那两行管够，图只需要认字。

    横排后一条高 ~48px、宽 ~5 格，正好嵌在文字行旁边，一屏能排十几条；同一个
    `radius` 下，竖排占的是**高度**（稀缺，决定翻多少屏），横排占的是**宽度**
    （富余，1100px 版心放得下 5 格还有余）。

    ±2 而不是 ±5：定字要的是紧邻上下文，隔 5 个字的邻居对认字没有帮助，只是
    把图撑大。真要看长上下文，条目下面的两行文字转写给的是 ±5 字，比图好读。

    竖排的字块横过来拼，读序仍是原来的阅读序（从右到左是刻本行序，这里按
    从左到右排，与下面的文字转写同向——两者对照时不用在脑子里翻转）。
    """
    lo, hi = max(0, k - radius), min(len(col_slots), k + radius + 1)
    cells = []
    for i in range(lo, hi):
        s = col_slots[i]
        img = _load_cell(cache, book, page, s["col"], s["slot"], s["sub"], h)
        if img is None:
            img = np.full((h, h), 235, np.uint8)
        cells.append((i == k, img))
    if not cells:
        return None
    gap, pad = 4, 3
    total_w = sum(c.shape[1] for _, c in cells) + gap * (len(cells) - 1) + pad * 2
    canvas = np.full((h + pad * 2, total_w, 3), 255, np.uint8)
    x = pad
    for is_t, c in cells:
        y = pad + (h - c.shape[0]) // 2
        canvas[y:y + c.shape[0], x:x + c.shape[1]] = cv2.cvtColor(c, cv2.COLOR_GRAY2BGR)
        if is_t:
            cv2.rectangle(canvas, (x - 2, y - 2), (x + c.shape[1] + 1, y + c.shape[0] + 1), (30, 38, 179), 2)
        x += c.shape[1] + gap
    return _b64(canvas)


def _b64(img) -> str | None:
    """WebP q70：字块是二值图，WebP 比 PNG 小 4–5 倍；全册上千条截条才装得进一个 HTML。"""
    ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 70])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None


def thumb_b64(cache: ImageCache, book: str, page: int, s: dict, h: int) -> str | None:
    img = _load_cell(cache, book, page, s["col"], s["slot"], s["sub"], h)
    return None if img is None else _b64(img)


# ── HTML ─────────────────────────────────────────────────

def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _src_badge(src: str) -> str:
    # `auto:human` 是 seed_admit 的 human **通道**（这格因为有人裁记录才放行），
    # 与顶层 `human`（本次转写直接取人裁 shape）是两回事，但对读报告的人是同一件事：
    # 这个字人看过。都标「人裁」，别端出「自动·human」这种内部通道名。
    human_like = src in ("human", "auto:human")
    cls = "human" if human_like else ("auto" if src.startswith("auto") else "guess")
    label = {"human": "人裁", "auto:human": "人裁", "ctx": "上下文猜", "lib": "库猜",
             "ocr": "OCR猜", "none": "无候选", "excluded": "排除"}.get(src, src.replace("auto:", "自动·"))
    return f'<span class="src {cls}">{_e(label)}</span>'


def render(book: str, pages: list[int], page_stats: dict, entries: list[dict],
           variant_pairs: dict, variant_examples: dict, unanchored: list[int],
           meta: dict) -> str:
    kc = Counter(e["kind"] for e in entries)
    n_slots = sum(s["n_slots"] for s in page_stats.values())
    n_equal = sum(s["equal"] for s in page_stats.values())
    n_excl = sum(s["excluded"] for s in page_stats.values())
    n_src = Counter(e["source"].split(":")[0] for e in entries if e["kind"] != "variant")

    def kind_rows():
        return "".join(f"<tr><td>{_e(KIND_LABEL[k])}</td><td class='num'>{kc.get(k, 0)}</td></tr>" for k in KINDS)

    # 页表
    prow = []
    for p in pages:
        s = page_stats[p]
        pk = Counter(e["kind"] for e in entries if e["page"] == p)
        if not s["anchored"]:
            prow.append(f"<tr><td class='num'>p{p}</td><td class='num'>{s['n_slots']}</td><td colspan='6' class='warn'>8-gram 锚定失败——整理本里找不到这一页</td></tr>")
            continue
        prow.append("<tr><td class='num'>p%d</td><td class='num'>%d</td><td class='num'>%d</td>%s<td class='num muted'>%d</td></tr>" % (
            p, s["n_slots"], s["equal"],
            "".join(f"<td class='num'>{pk.get(k, 0) or ''}</td>" for k in KINDS), s["excluded"]))

    # 异体
    vrows = []
    for (hy, rf), n in sorted(variant_pairs.items(), key=lambda kv: -kv[1]):
        ex = "".join(f'<img class="th" src="data:image/webp;base64,{b}" title="{_e(i)}">'
                     for i, b in variant_examples.get((hy, rf), [])[:3])
        vrows.append(f"<tr><td class='gl'>{_e(hy)}</td><td class='gl'>{_e(rf)}</td><td class='num'>{n}</td><td>{ex}</td></tr>")

    # 增删改条目
    def entry_html(e: dict) -> str:
        img = (f'<img class="strip" src="data:image/webp;base64,{e["strip"]}" alt="">' if e.get("strip")
               else '<div class="strip nop">无图</div>')
        doubts = " ".join(f"<span class='dbt'>{_e(d)}</span>" for d in e.get("doubts", [])[:3])
        return f"""<div class="ent" data-kind="{e['kind']}" data-page="{e['page']}">
  {img}
  <div class="body">
    <div class="head"><span class="pair"><span class="gl big">{_e(e['hyp']) or '—'}</span><span class="arr">→</span><span class="gl big">{_e(e['ref']) or '—'}</span></span>
      <span class="mono">{_e(e['id'])}</span> {_src_badge(e['source'])} {doubts}</div>
    <div class="ctx"><span class="k">转写</span><span class="gl">{_e(e['hyp_ctx'])}</span></div>
    <div class="ctx"><span class="k">整理本</span><span class="gl">{_e(e['ref_ctx'])}</span></div>
  </div>
</div>"""

    # 分层：把「我们录错了」从「两个本子本来就不同」里分出来（见 report/collation_grade.py）。
    # 平表按 kind 排，答的是「字面一不一样」；按 grade 排，答的是「这条要不要人去看」——
    # 后者才是看报告的人真正要问的。存疑那层排最前，成果那几层折叠起来。
    gsum = summarize(entries)
    counts, by = gsum["counts"], gsum["by_grade"]

    def grade_section(g: str, *, open_: bool) -> str:
        es = by.get(g) or []
        if not es:
            return ""
        note = GRADE_NOTE.get(g, "")
        inner = "".join(entry_html(e) for e in es)
        return (f'<details id="g-{g}"{" open" if open_ else ""}><summary>'
                f'<span class="gname">{_e(GRADE_LABEL[g])}</span>'
                f'<span class="cnt">{len(es)}</span>'
                f'<span class="gnote">{_e(note)}</span></summary>'
                f'<div class="ents">{inner}</div></details>')

    sections = [grade_section("suspect", open_=True)]
    sections += [grade_section(g, open_=False) for g in ("gap", "taboo", "systematic", "variant")]

    unanch = (f"<p class='warn'>锚定失败 {len(unanchored)} 页：{', '.join('p%d' % p for p in unanchored)}"
              f"——转写与整理本对不上号（整理本缺这段，或这页转写噪声太大），不在下表内。</p>" if unanchored else "")
    trunc = (f"<p class='warn'>截条图只出了前 {meta['strips']} 条（--limit-strips），其余只有文字上下文。</p>"
             if meta.get("truncated") else "")

    return f"""<title>{_e(book)} 对勘</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@500;700;900&family=Noto+Sans+TC:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root {{ --paper:#F4F4F1; --panel:#EBECE7; --ink:#1B1F24; --mute:#6A7383; --rule:#D3D6D1; --indigo:#2B4C7E; --indigo-soft:#DCE5F2; --zhu:#B3261E; --zhu-soft:#F5E1DE; --ok:#2F7D4F;
          --serif:"Noto Serif TC","Source Han Serif TC","PMingLiU",serif; --sans:"Noto Sans TC","Microsoft JhengHei",sans-serif; --mono:"IBM Plex Mono",Consolas,monospace; color-scheme:light; }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --paper:#15181D; --panel:#1D2127; --ink:#E4E3DD; --mute:#9AA3B2; --rule:#2C323B; --indigo:#8FB0E0; --indigo-soft:#22314A; --zhu:#E57368; --zhu-soft:#3A2220; --ok:#7CC29A; color-scheme:dark; }} }}
  :root[data-theme="dark"] {{ --paper:#15181D; --panel:#1D2127; --ink:#E4E3DD; --mute:#9AA3B2; --rule:#2C323B; --indigo:#8FB0E0; --indigo-soft:#22314A; --zhu:#E57368; --zhu-soft:#3A2220; --ok:#7CC29A; color-scheme:dark; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:var(--sans); font-size:15.5px; line-height:1.75; font-variant-numeric:tabular-nums; }}
  .page {{ max-width:1100px; margin:0 auto; padding:2rem 1.4rem 5rem; }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:1rem; margin-bottom:1.4rem; }}
  .eyebrow {{ font-family:var(--mono); font-size:.76rem; letter-spacing:.06em; color:var(--mute); }}
  h1 {{ font-family:var(--serif); font-weight:900; font-size:2.2rem; margin:.3rem 0 .4rem; line-height:1.2; }}
  h2 {{ font-family:var(--serif); font-weight:700; font-size:1.35rem; margin:2.2rem 0 .8rem; padding-top:.5rem; border-top:1px solid var(--rule); }}
  h2 .cnt {{ font-family:var(--mono); font-weight:500; font-size:.9rem; color:var(--indigo); margin-left:.5rem; }}
  nav {{ display:flex; flex-wrap:wrap; gap:.3rem 1.2rem; font-size:.88rem; margin:0 0 1.2rem; }}
  nav a {{ color:var(--indigo); text-decoration:none; border-bottom:1px solid var(--rule); }}
  .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(11rem,1fr)); gap:.6rem 1.2rem; margin:0 0 1rem; }}
  .stat {{ border-top:2px solid var(--ink); padding:.4rem 0; }}
  .stat b {{ display:block; font-family:var(--serif); font-size:1.5rem; line-height:1.2; }}
  .stat span {{ font-size:.8rem; color:var(--mute); }}
  .stat.todo {{ border-top-color:var(--zhu); }}  .stat.todo b {{ color:var(--zhu); }}
  .stat.ok {{ border-top-color:var(--ok); }}
  .lede {{ font-size:1.05rem; line-height:1.85; margin:.2rem 0 1.1rem; max-width:62ch; }}
  .lede b {{ font-family:var(--serif); }}
  details {{ border-top:1px solid var(--rule); margin:0; }}
  details[open] {{ padding-bottom:1.2rem; }}
  summary {{ cursor:pointer; padding:.85rem 0; display:flex; align-items:baseline; gap:.7rem; flex-wrap:wrap; font-family:var(--serif); }}
  summary::marker {{ color:var(--mute); }}
  .gname {{ font-size:1.15rem; font-weight:700; }}
  #g-suspect .gname {{ color:var(--zhu); }}
  .gnote {{ font-family:var(--sans); font-size:.82rem; color:var(--mute); font-weight:400; }}
  .tw {{ overflow-x:auto; margin:0 0 1rem; border-top:2px solid var(--ink); border-bottom:1px solid var(--rule); }}
  table {{ border-collapse:collapse; width:100%; font-size:.86rem; }}
  th,td {{ text-align:left; vertical-align:middle; padding:.32rem .6rem; border-bottom:1px solid var(--rule); }}
  th {{ font-size:.76rem; letter-spacing:.04em; color:var(--mute); background:var(--panel); white-space:nowrap; }}
  .num {{ font-family:var(--mono); font-size:.84em; white-space:nowrap; }}
  .gl {{ font-family:var(--serif); font-size:1.2em; }}
  .gl.big {{ font-size:1.7rem; line-height:1.1; }}
  .th {{ height:44px; border:1px solid var(--rule); background:#fff; margin-right:.25rem; vertical-align:middle; }}
  .muted {{ color:var(--mute); }} .warn {{ color:var(--zhu); }}
  /* 截条横排后条目改成上下堆叠：图一条（~48px 高）压在文字上面，整条不到 8rem。
     旧版竖条 ~500px 高、图文左右并排，一条就是一屏（用户 2026-09-22「看的很累」）。
     两列布局在 1100px 版心下每列 ~30rem，一屏能排 6–8 条。 */
  .ents {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(26rem,1fr)); gap:0 2.5rem; }}
  .ent {{ padding:.6rem 0; border-bottom:1px solid var(--rule); min-width:0; }}
  .ent .strip {{ background:#fff; border:1px solid var(--rule); display:block; max-width:100%; margin:0 0 .35rem; }}
  .ent .strip.nop {{ height:2.6rem; color:var(--mute); font-size:.7rem; display:flex; align-items:center; padding:0 .5rem; }}
  /* 「刻本 X → 整理本 Y」并进 id 那一行：旧版它独占一行、两个大字中间还夹着两个
     标签，一条条目因此多占一行半。图上已有红框指明是哪一格，两行文字上下文也带
     【】标记，这里只要把两个字并排摆出来就够，不必再写「刻本」「整理本」四个字。 */
  .ent .head {{ font-size:.8rem; color:var(--mute); display:flex; gap:.45rem; flex-wrap:wrap; align-items:baseline; }}
  .ent .pair {{ display:inline-flex; align-items:baseline; gap:.3rem; margin-right:.25rem; }}
  .ent .pair .big {{ word-break:break-all; font-size:1.35rem; }}
  .ent .arr {{ color:var(--mute); font-size:.85rem; }}
  .ent .k {{ font-size:.72rem; color:var(--mute); letter-spacing:.06em; margin-right:.3rem; }}
  .ent .ctx {{ font-size:.95rem; }}
  .src {{ font-family:var(--mono); font-size:.68rem; padding:.05em .45em; border-radius:2px; border:1px solid var(--rule); }}
  .src.human {{ border-color:var(--indigo); color:var(--indigo); font-weight:600; }}
  .src.auto {{ border-color:var(--ok); color:var(--ok); }}
  .src.guess {{ border-color:var(--zhu); color:var(--zhu); }}
  .dbt {{ font-size:.68rem; color:var(--mute); }}
  .filters {{ display:flex; gap:.6rem; flex-wrap:wrap; align-items:center; font-size:.85rem; margin:.6rem 0 1rem; position:sticky; top:0; background:var(--paper); padding:.5rem 0; border-bottom:1px solid var(--rule); z-index:2; }}
  .filters label {{ display:inline-flex; gap:.25rem; align-items:center; }}
  .filters input[type=text] {{ font-family:var(--mono); font-size:.82rem; width:8rem; }}
  .foot {{ margin-top:2.5rem; padding-top:.8rem; border-top:1px solid var(--rule); font-family:var(--mono); font-size:.74rem; color:var(--mute); }}
  @media (max-width:640px) {{ .ent {{ grid-template-columns:1fr; }} }}
</style>
<div class="page">
<header>
  <div class="eyebrow">open-guji-cv · 对勘 · {_e(meta['built_at'])} · 转写 = 人裁 &gt; 自动放行 &gt; 上下文 &gt; 库 &gt; OCR</div>
  <h1>{_e(book)} 对勘</h1>
  <p class="lede">全书 <b>{n_slots:,}</b> 字位，与整理本一致 <b>{n_equal:,}</b>（{n_equal / max(1, n_slots) * 100:.1f}%）。
    其余 <b>{len(entries)}</b> 处差异里，<b>{gsum['n_settled']}</b> 处是两个本子的真实不同（避諱改字、正俗、异体，<b>转写忠于刻本，不用改</b>），
    真正<b>存疑待覈的 {gsum['n_todo']} 处</b>。</p>
  <div class="summary">
    <div class="stat todo"><b>{counts.get('suspect', 0)}</b><span>存疑·待覈</span></div>
    <div class="stat"><b>{counts.get('gap', 0)}</b><span>增删（脱衍）</span></div>
    <div class="stat ok"><b>{counts.get('taboo', 0)}</b><span>避諱改字</span></div>
    <div class="stat ok"><b>{counts.get('systematic', 0)}</b><span>正俗·异体（系统性）</span></div>
    <div class="stat ok"><b>{counts.get('variant', 0)}</b><span>异体（{len(variant_pairs)} 对）</span></div>
  </div>
  <p class="muted" style="font-size:.82rem">分层判据：避諱字表 + 同一字对全书重复 ≥3 次 + 异体关系图（见 <code>report/collation_grade.py</code>）。
    <b>分层是排序不是闸</b>——落进「存疑」不等于错，落进「版本差异」也不等于一定对。
    {len(pages)} 页（锚定 {len(pages) - len(unanchored)}）· 排除名单 {n_excl} 格不进比对 ·
    转写来源：人裁 {n_src.get('human', 0)} · 自动 {n_src.get('auto', 0)} · 机器猜 {n_src.get('ctx', 0) + n_src.get('lib', 0) + n_src.get('ocr', 0) + n_src.get('none', 0)}</p>
  {unanch}{trunc}
</header>
<nav><a href="#g-suspect">存疑 {counts.get('suspect', 0)}</a>{"".join(f'<a href="#g-{g}">{_e(GRADE_LABEL[g])} {counts.get(g, 0)}</a>' for g in ("gap", "taboo", "systematic", "variant") if counts.get(g))}<a href="#pages">按页</a><a href="#variants">异体字</a></nav>

<section id="pages"><h2>按页</h2>
<div class="tw"><table><thead><tr><th>页</th><th>字位</th><th>一致</th>{"".join(f"<th>{_e(KIND_LABEL[k].split('（')[0])}</th>" for k in KINDS)}<th>排除</th></tr></thead>
<tbody>{"".join(prow)}</tbody></table></div>
<p class="muted" style="font-size:.82rem">「一致」含转写等于整理本的字位；异体不算一致也不算错，单列。排除 = 人判过切坏/非字的格，不进比对。</p>
</section>

<section id="variants"><h2>异体字 <span class="cnt">{len(variant_pairs)} 对 · {kc.get('variant', 0)} 次</span></h2>
<p class="muted" style="font-size:.85rem">刻本形 ≠ 整理本形，但按关系图/语义层是同一个字。这是字形库该保留的（忠于刻本），不是错。例图是刻本原格。</p>
<div class="tw"><table><thead><tr><th>刻本形</th><th>整理本形</th><th>次数</th><th>例</th></tr></thead><tbody>{"".join(vrows)}</tbody></table></div>
</section>

<div class="filters">
  <span class="k">筛</span>
  {"".join(f'<label><input type="checkbox" class="fk" value="{k}" checked> {_e(KIND_LABEL[k].split("（")[0])}</label>' for k in ("substitution", "missing", "extra", "unreadable"))}
  <label>页 <input type="text" id="fp" placeholder="如 71,79"></label>
  <label><input type="checkbox" id="fh"> 只看非人裁</label>
  <span class="muted" id="fc"></span>
</div>
{"".join(sections)}

<div class="foot">整理本 {_e(meta['corpus'])} · 锚定 8-gram + WINDOW_PAD {WINDOW_PAD} · 异体判定 = variants.json 有边 或 VariantMap 语义相同 · 生成 scripts/build_collation_report.py · {_e(meta['built_at'])}</div>
</div>
<script>
(function(){{
  const ents=[...document.querySelectorAll('.ent')];
  const fk=[...document.querySelectorAll('.fk')], fp=document.getElementById('fp'), fh=document.getElementById('fh'), fc=document.getElementById('fc');
  function apply(){{
    const kinds=new Set(fk.filter(c=>c.checked).map(c=>c.value));
    const pages=new Set(fp.value.split(/[,，\\s]+/).filter(Boolean));
    let n=0;
    for(const e of ents){{
      const ok=kinds.has(e.dataset.kind)&&(!pages.size||pages.has(e.dataset.page))&&(!fh.checked||!e.querySelector('.src.human'));
      e.hidden=!ok; if(ok)n++;
    }}
    fc.textContent='显示 '+n+' / '+ents.length;
    // 分层用 <details id="g-…">，不再是 section[id^=k-]；整层空了就藏掉，
    // 并把层标题上的计数改成「当前显示数」，否则筛完标题还写着全量数，对不上。
    document.querySelectorAll('details[id^=g-]').forEach(s=>{{
      const vis=[...s.querySelectorAll('.ent')].filter(e=>!e.hidden).length;
      s.hidden=!vis;
      const c=s.querySelector('summary .cnt'); if(c) c.textContent=vis;
    }});
  }}
  fk.forEach(c=>c.onchange=apply); fp.oninput=apply; fh.onchange=apply; apply();
}})();
</script>
"""


# ── 主流程 ───────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="对勘报告")
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--pages", default="", help="页表达式；空 = 全部有产物的正文页")
    ap.add_argument("--corpus", default="",
                    help="整理本语料路径；空 = 按 books/<book>.yaml 的 references[0] 取本册自己那份")
    ap.add_argument("--out", default=None, help="HTML 输出（默认 output/collation_<book>.html）")
    ap.add_argument("--strip", type=int, default=2, help="截条目标格前后各几格（横排，见 strip_b64）")
    ap.add_argument("--thumb-h", type=int, default=44, help="每格缩放到多高（px）")
    ap.add_argument("--limit-strips", type=int, default=1500, help="最多出多少条截条图（控体积）")
    ap.add_argument("--variant-examples", type=int, default=3)
    a = ap.parse_args()

    t0 = time.time()
    st = ProductStore()
    bk = load_book(a.book)
    pages = bk.resolve_pages(a.pages) if a.pages else body_pages(a.book, st)
    # 只留汉字再锚定/对齐：整理本里夹着抬头码（⏎b1 / c3 / a1）、全角空格、行末连字符「-」，
    # 8-gram 投票按原文位置数偏移，页内一有这些标记，页首就会锚晚几字，
    # 开头那几格全成「刻本多」（dev_set p26「乾隆四十一年七」×7 就是这么来的）
    # 语料按册取（`steps/align_ref.book_corpus`，读 books/<id>.yaml 的 references[0]），
    # 不再缺省指向刻本链那份总目语料。缺省值写死 + `REPO / a.corpus` 锚 cv 仓，是两个
    # 叠一起的老毛病：北行日錄的语料在**工作区** corpus/ 下，两条路都够不着，于是
    # `--book bxgb` 直接 FileNotFoundError；真凑巧撞上同名文件则更糟——拿别册的
    # 整理本对勘，差异表会整片虚高而不报错（与 Step5-b、context_decide 的同型坑一样）。
    # 显式给 --corpus 的照用，相对路径仍按 cv 仓解析（老用法不破）。
    from open_guji_cv.steps.align_ref import book_corpus
    corpus_file = Path(a.corpus) if a.corpus else Path(book_corpus(a.book))
    if not corpus_file.is_absolute():
        corpus_file = REPO / corpus_file
    raw = corpus_file.read_text(encoding="utf-8")
    corpus = "".join(c for c in raw if is_han(c))
    index = build_ngram_index(corpus)
    truth = load_verdicts(a.book)
    cache = ImageCache()

    entries: list[dict] = []
    page_stats: dict[int, dict] = {}
    unanchored: list[int] = []
    variant_pairs: Counter = Counter()
    variant_examples: dict[tuple, list] = defaultdict(list)
    for p in pages:
        slots = page_slots(a.book, p, st, truth)
        ents, stat = diff_page(slots, corpus, index)
        page_stats[p] = stat
        if not stat["anchored"]:
            unanchored.append(p)
            continue
        by_col: dict[int, list[dict]] = defaultdict(list)
        for s in slots:
            by_col[s["col"]].append(s)
        pos_in_col = {s["id"]: i for col in by_col.values() for i, s in enumerate(col)}
        for e in ents:
            e["page"] = p
            if e["kind"] == "variant":
                key = (e["hyp"], e["ref"])
                variant_pairs[key] += 1
                if len(variant_examples[key]) < a.variant_examples:
                    b = thumb_b64(cache, a.book, p, e, a.thumb_h + 4)
                    if b:
                        variant_examples[key].append((e["id"], b))
            else:
                e["_col_slots"] = by_col[e["col"]]
                e["_k"] = pos_in_col[e["id"]]
        entries.extend(ents)

    order = {"substitution": 0, "missing": 1, "extra": 2, "unreadable": 3, "variant": 9}
    entries.sort(key=lambda e: (order[e["kind"]], e["page"], e["col"], e["slot"], e["sub"]))
    n_strip = 0
    truncated = False
    for e in entries:
        if e["kind"] == "variant":
            continue
        if n_strip >= a.limit_strips:
            truncated = True
            e.pop("_col_slots", None); e.pop("_k", None)
            continue
        e["strip"] = strip_b64(cache, a.book, e["page"], e.pop("_col_slots"), e.pop("_k"), a.strip, a.thumb_h)
        n_strip += 1

    meta = {"built_at": time.strftime("%Y-%m-%d %H:%M"), "corpus": str(corpus_file),
            "strips": n_strip, "truncated": truncated}
    out = Path(a.out) if a.out else REPO / "output" / f"collation_{a.book}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(a.book, pages, page_stats, entries, variant_pairs, variant_examples, unanchored, meta),
                   encoding="utf-8")
    side = out.with_suffix(".json")
    side.write_text(json.dumps({
        "book": a.book, "pages": pages, "unanchored": unanchored, "meta": meta,
        "page_stats": page_stats,
        "variant_pairs": [[h, r, n] for (h, r), n in variant_pairs.most_common()],
        "entries": [{k: v for k, v in e.items() if k != "strip"} for e in entries],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    kc = Counter(e["kind"] for e in entries)
    print(f"{a.book}：{len(pages)} 页（锚定失败 {len(unanchored)}：{unanchored}），字位 {sum(s['n_slots'] for s in page_stats.values()):,}")
    print("  一致 %s · 异体 %d（%d 对）· 改 %d · 整理本多 %d 处/%d 字 · 刻本多 %d · 无法辨认 %d" % (
        f"{sum(s['equal'] for s in page_stats.values()):,}", kc.get("variant", 0), len(variant_pairs),
        kc.get("substitution", 0), kc.get("missing", 0), sum(e.get("n", 1) for e in entries if e["kind"] == "missing"),
        kc.get("extra", 0), kc.get("unreadable", 0)))
    print(f"  异体 top：" + "  ".join(f"{h}→{r}×{n}" for (h, r), n in variant_pairs.most_common(8)))
    print(f"  截条图 {n_strip} 条{'（已截断）' if truncated else ''}；HTML {out.stat().st_size / 1e6:.1f} MB → {out}；明细 {side.name}；{time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
