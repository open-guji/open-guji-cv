"""参考文本对齐评测：整理本 vs 转写，量真实字准确率。

"CJK 比例"（转写出的字符里有多少落在汉字 Unicode 区间）不是准确率——
一个全错但形似的候选照样是汉字。真准确率需要一份独立的参考真值逐字
比对。用户提供的《总目》整理本（corpus/）就是这份真值，但它是**连续
长文本、按卷排列**，不知道某一页对应文本里的哪一段——要先"锚定"。

两步法（见 .claude/doc/char_clustering_design.md 18.11）：

1. **页内 n-gram 投票锚定**：取页转写文本的所有 GRAM 连续子串，在参考
   语料里查重复出现位置，每次命中给 (语料位置 - 页内位置) 投一票——
   同一页的字符在语料里理应连续排列，正确偏移会被反复投中，误差各不
   相同、噪声自动摊平。多数偏移不够票数就判定「定不了位」（常见于
   职名/目录页——整理本未必收录）。
2. **偏移已知后局部序列对齐**：`difflib.SequenceMatcher` 在锚定窗口内
   逐字比对，matching blocks 的总长度 = 命中字数。用 SequenceMatcher
   而不是简单地按位比较，是因为切分错误可能让转写整体错位一两个字符
   （漏字/多字），按位比较会把这一页余下的字全部误判成错。

只比字形层（`text/`，与语料同为传承字形），绝不比语义层——语义层是
辅助视图，参考文本无权改写字形层判断（19.1 / 20.3 纪律）。
"""

from __future__ import annotations

import difflib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

GRAM = 8              # 锚定用 n-gram 长度
MIN_VOTES = 5          # 最高票偏移的绝对票数下限
MIN_VOTE_FRAC = 0.15   # 或者：最高票占可投票 n-gram 总数的比例达到此值
MIN_DOMINANCE = 2.0    # 或者：最高票是次高票的这么多倍（次高=0 时自动通过）
WINDOW_PAD = 60        # 对齐窗口在页文本长度基础上的余量（容纳漏字/多字）
POOL_RADIUS = 3        # 相邻偏移合并半径：一次漏字/多字只把偏移挪 1~2 位


@dataclass
class PageAlign:
    page: str
    anchored: bool
    ref_offset: int | None
    text_len: int
    matched: int
    accuracy: float


def build_ngram_index(corpus: str, gram: int = GRAM) -> dict[str, list[int]]:
    """语料 → {n-gram: [出现位置...]}，供批量锚定复用（避免逐页重扫全文）。"""
    index: dict[str, list[int]] = {}
    for i in range(len(corpus) - gram + 1):
        index.setdefault(corpus[i:i + gram], []).append(i)
    return index


def anchor_page(text: str, corpus_index: dict[str, list[int]],
                gram: int = GRAM) -> int | None:
    """页文本在语料里的起始偏移；投票不过关（含语料未收录该页）返回 None。

    双重判据，任一成立即接受（都要求先过 MIN_VOTES 绝对下限）：

    - **占比**：最高票占全部可投票 n-gram 的比例达标。适用于识别质量好、
      成功窗口密集的页面；
    - **优势**：最高票是次高票的数倍。适用于单字错误率偏高、成功窗口
      占比因此走低的页面——只要没有第二个候选偏移能与之抗衡，占比再
      低也是可靠锚点（伪命中会在各偏移间近乎均匀打散，凑不出优势）。

    只看其中一条都会误杀另一类页面，两条曾各自验证过对方漏掉的例子。

    **投票先按 ±POOL_RADIUS 合并成簇再比。** 页内有一处漏字/多字时，
    前后两半的偏移差 1~2 位，票会劈成相邻的两堆（实测 book9/2 是
    14 票 vs 13 票）——那本是同一个锚点的两半，孤立比较却让它们互相
    "抵消"：占比各自不达标、优势又互相压制，整页被判定不到位。实测
    book9 十页里有三页因此被误杀（2/4/7），合并后全部回收，页面对齐率
    6/10 → 9/10。真正的伪命中会在各偏移间近乎均匀打散，合并半径 3 位
    凑不出一堆。
    """
    if len(text) < gram:
        return None
    votes: Counter[int] = Counter()
    n_grams = len(text) - gram + 1
    for i in range(n_grams):
        for pos in index_lookup(corpus_index, text[i:i + gram]):
            votes[pos - i] += 1
    if not votes:
        return None
    peak = votes.most_common(1)[0][0]
    near = [o for o in votes if abs(o - peak) <= POOL_RADIUS]
    n_votes = sum(votes[o] for o in near)
    if n_votes < MIN_VOTES:
        return None
    # 次高票同样按簇算：孤立地取第二名会把「同一锚点的另一半票」误当竞争者
    rest = {o: v for o, v in votes.items() if abs(o - peak) > POOL_RADIUS}
    runner_up = 0
    if rest:
        peak2 = max(rest, key=rest.get)
        runner_up = sum(v for o, v in rest.items()
                        if abs(o - peak2) <= POOL_RADIUS)
    by_frac = n_votes >= MIN_VOTE_FRAC * n_grams
    by_dominance = runner_up == 0 or n_votes >= MIN_DOMINANCE * runner_up
    if not (by_frac or by_dominance):
        return None
    # 取簇内最小偏移：窗口宁可起得早一点，右侧有 WINDOW_PAD 兜住长度差；
    # 起得晚会把页首几个字挤出窗口，那几个字会被整段判为不可对齐。
    return min(near)


def index_lookup(index: dict[str, list[int]], gram: str) -> list[int]:
    return index.get(gram, ())


def align_page(text: str, corpus: str, offset: int,
               window_pad: int = WINDOW_PAD) -> tuple[int, int]:
    """锚定偏移已知后的逐字比对，返回 (命中字数, 页文本总字数)。"""
    lo = max(0, offset)
    hi = min(len(corpus), offset + len(text) + window_pad)
    window = corpus[lo:hi]
    sm = difflib.SequenceMatcher(None, text, window, autojunk=False)
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched, len(text)


def _page_sort_key(path: Path):
    return (0, int(path.stem)) if path.stem.isdigit() else (1, path.stem)


def evaluate_book(text_dir: str | Path, corpus: str,
                  corpus_index: dict[str, list[int]] | None = None) -> dict:
    """整册评测：text_dir 下每页一个 {page}.txt（labeling/refine 产出的字形层转写）。"""
    text_dir = Path(text_dir)
    corpus_index = corpus_index if corpus_index is not None else build_ngram_index(corpus)
    pages = sorted(text_dir.glob("*.txt"), key=_page_sort_key)

    results: list[PageAlign] = []
    for p in pages:
        text = p.read_text(encoding="utf-8").replace("\n", "")
        offset = anchor_page(text, corpus_index)
        if offset is None:
            results.append(PageAlign(p.stem, False, None, len(text), 0, 0.0))
            continue
        matched, total = align_page(text, corpus, offset)
        results.append(PageAlign(p.stem, True, offset, total, matched,
                                 round(matched / total, 4) if total else 0.0))

    anchored = [r for r in results if r.anchored]
    total_chars = sum(r.text_len for r in anchored)
    total_matched = sum(r.matched for r in anchored)
    return {
        "n_pages": len(results),
        "n_anchored": len(anchored),
        "total_chars": total_chars,
        "total_matched": total_matched,
        "accuracy": round(total_matched / total_chars, 4) if total_chars else 0.0,
        "pages": [asdict(r) for r in results],
    }


def evaluate_books(text_dirs: dict[str, str | Path], corpus_path: str | Path) -> dict:
    """多册合并评测：{册名: text_dir}，语料索引只建一次。"""
    corpus = Path(corpus_path).read_text(encoding="utf-8")
    index = build_ngram_index(corpus)
    per_book = {name: evaluate_book(d, corpus, index)
                for name, d in text_dirs.items()}
    total_chars = sum(b["total_chars"] for b in per_book.values())
    total_matched = sum(b["total_matched"] for b in per_book.values())
    return {
        "books": per_book,
        "overall": {
            "total_chars": total_chars,
            "total_matched": total_matched,
            "accuracy": round(total_matched / total_chars, 4) if total_chars else 0.0,
        },
    }


def top_confusions(text_dir: str | Path, corpus: str, corpus_index: dict,
                   top_k: int = 20) -> list[tuple[str, int]]:
    """锚定页上「转写字 → 参考字」的替换统计，降序——定位系统性混淆头部。

    只统计 SequenceMatcher 判定为 'replace' 的等长子块（逐字对齐），
    插入/删除（切分多切/漏切）不计入——那是分段问题，不是识字问题。
    """
    text_dir = Path(text_dir)
    counter: Counter[tuple[str, str]] = Counter()
    for p in sorted(text_dir.glob("*.txt"), key=_page_sort_key):
        text = p.read_text(encoding="utf-8").replace("\n", "")
        offset = anchor_page(text, corpus_index)
        if offset is None:
            continue
        lo = max(0, offset)
        hi = min(len(corpus), offset + len(text) + WINDOW_PAD)
        window = corpus[lo:hi]
        sm = difflib.SequenceMatcher(None, text, window, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace" and (i2 - i1) == (j2 - j1):
                for a, b in zip(text[i1:i2], window[j1:j2]):
                    counter[(a, b)] += 1
    return [(f"{a}→{b}", n) for (a, b), n in counter.most_common(top_k)]
