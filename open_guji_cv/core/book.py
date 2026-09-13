"""BookSpec：一册书的图源、页集合、dev_set 与版式常量。来自 books/<id>.yaml。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"
_NUM_RE = re.compile(r"(\d+)")


@dataclass
class BookSpec:
    id: str
    title: str
    raw_dir: Path                     # 原始扫描目录
    raw_pattern: str = "{page}.png"   # 页号 → 文件名
    expected_cols: int = 9            # Step1 的列数先验
    chars_per_line: int = 21          # Step3 的正文格数先验
    edition: str = "keben"
    dev_set: list[int] = field(default_factory=list)
    #: 命名页集（yaml 的 `sets:`）：`{名字: [页号…]}`，用 `--pages <名字>` 选。
    #: dev_set 是切分链的分层集，历史数字都挂在它上面，**不要往里塞新页**；
    #: 要专项集（如夹注 jz）就在这里新开一个，见 vol02.yaml。
    sets: dict[str, list[int]] = field(default_factory=dict)
    #: 夹注（雙行小注）的**本书文字约定**（yaml 的 `jiazhu:`）。默认全空 = 不启用。
    #:
    #: ⚠️ **探测夹注本身不看文字**（`utils/jiazhu_split` 纯几何：墨迹跨度、缝中心、
    #: 段连缀），换书照样能用。这里放的只是「这一套书的注文长什么样」这类**书级先验**：
    #:
    #: - `note_suffixes`：版本注的收尾词（《四庫全書總目》是「…採進本 / …藏本」）。
    #:   给了才启用闭集短语通道与 T1/T2 分型；不给就整册按开放文本算，不会误判。
    #: - `note_max_len`：闭集短语的长度上限（超过就当开放文本）。
    #: - `title_split`：书名与注文的分界正则（总目是「N卷 / 無卷數」）。
    #:
    #: 用户 2026-09-06 定的口径：**依赖文字可以，但必须「这套书用、下套书不用」**——
    #: 所以一律进 Book 配置，不写死在 eval / 通道代码里。
    jiazhu: dict = field(default_factory=dict)
    #: 下版框跨页先验的基准：整册「页高 − 下版框 y」的中位数（yaml 的
    #: `bottom_gap:`）。给了才启用 Step1 的下版框救援，不给则行为与加这套
    #: 机制之前逐位相同。
    #:
    #: **怎么标定**：`utils/border_geometry.measure_book_bottom_gap(整册灰度图)`
    #: 跑一次，把数写进 yaml。不在流水线里现算是因为 `border_detect` 是逐页
    #: step，现算等于每页重跑一遍全书。**不需要金标**：三册实测，整册算法
    #: 输出中位数与金标真基准只差 0~1px。
    #:
    #: ⚠️ 换书必须重新标定，别抄。三册恰好都落在 325~327px，但那是同一套
    #: 《四庫全書總目》武英殿本的版式，换一种版式没有理由仍是这个数。
    bottom_gap: float | None = None
    #: 页级字格高（period）的书级先验（yaml 的 `period_prior:`）。给了才启用
    #: 闸2 的**空栏页兜底**：栏内没有字的页推不出纵向节律，`estimate_shared_period`
    #: 必然抛错（vol01 p62/p158/p206 就是这样整页被拦的）。这类页界行是齐的、
    #: 九列切得出来，该正常产出一个"各格皆空"的页，不该算异常。
    #:
    #: **只在估不出来时兜底**，能估出来的页一律用当场估的值——所以给了这个数
    #: 也不会改变任何正常页的产物（有单测守着）。
    #:
    #: **怎么标定**：`utils/row_boundaries.measure_book_period()`，或直接取整册
    #: 已有产物里正文页 period 的中位数。**不需要金标**：正文页的 period 是
    #: 书级常量，vol01 正文 108 页实测 115.0±1.67px、vol02 186 页 113.0±2.37px。
    #:
    #: ⚠️ 别拿全书页混着算——职名/目录页的字距本来就不同（vol01 roster 中位
    #: 70、std 15.6），混进来会把中位数拉偏。只用 page_type == body 的页。
    #: 换书必须重新标定。
    period_prior: float | None = None
    pages: list[int] = field(default_factory=list)   # 空 = 扫目录
    # Step0 预清理：{页号: [规则, ...]}。默认空 = 不做任何处理。
    # 只对手工登记过的页生效，不改磁盘原图，见 utils/preclean.py。
    preclean: dict[int, list[dict]] = field(default_factory=dict)
    notes: str = ""
    #: Step5-c OCR候选（yaml 的 `ocr_candidates:`）。**默认关闭**——用户
    #: 2026-09-11 定的口径：整理本已经足够准，主要靠 5-a 库匹配 + 5-b 生僻字
    #: 候选，5-c 只在个别书需要时按需显式打开（`ocr_candidates: true`）。
    #: 关闭只是 Engine 执行时跳过这一步，不改 pipeline 拓扑——`context_decide`
    #: 本来就要处理「这一位没有 OCR 候选」（见 context_decide.py run_page）。
    ocr_candidates: bool = False

    # ── 页 ───────────────────────────────────────────────────────────
    def raw_path(self, page: int) -> Path:
        return self.raw_dir / self.raw_pattern.format(page=page)

    def all_pages(self) -> list[int]:
        if self.pages:
            return list(self.pages)
        if not self.raw_dir.exists():
            return []
        suffix = Path(self.raw_pattern).suffix
        found = []
        for p in self.raw_dir.iterdir():
            if p.suffix.lower() != suffix.lower():
                continue
            m = _NUM_RE.search(p.stem)
            if m and self.raw_pattern.format(page=int(m.group(1))) == p.name:
                found.append(int(m.group(1)))
        return sorted(found)

    def resolve_pages(self, selector: str | list[int] | None) -> list[int]:
        """'dev_set' / 'all' / 命名集 / '3-6,9' / [3, 4] → 页号列表（升序去重）。

        命名集来自 yaml 的 `sets:`（如 vol02 的 `jz`）。名字优先于页号表达式，
        但 `dev_set` / `all` 是保留名。
        """
        if selector is None or selector == "dev_set":
            return list(self.dev_set) or self.all_pages()
        if selector == "all":
            return self.all_pages()
        if isinstance(selector, list):
            return sorted(set(int(p) for p in selector))
        if isinstance(selector, str) and selector in self.sets:
            return sorted(set(int(p) for p in self.sets[selector]))
        # 中文输入法下全角逗号/连字符/空格极常见（控制台页码框实测踩到：
        # 输入 "161，51" 直接 500）。切分前统一归一化，顺带把空格也当分隔符。
        expr = (str(selector).replace("，", ",").replace("、", ",")
                .replace("－", "-").replace("—", "-").replace("~", "-")
                .replace("　", " "))
        expr = ",".join(expr.split())          # 空格分隔也认
        pages: set[int] = set()
        for part in expr.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                pages.update(range(int(a), int(b) + 1))
            else:
                pages.add(int(part))
        return sorted(pages)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "raw_dir": str(self.raw_dir),
            "raw_pattern": self.raw_pattern, "expected_cols": self.expected_cols,
            "chars_per_line": self.chars_per_line, "edition": self.edition,
            "dev_set": list(self.dev_set), "n_pages": len(self.all_pages()),
            "sets": {k: list(v) for k, v in self.sets.items()},
            "jiazhu": dict(self.jiazhu),
            "preclean_pages": sorted(self.preclean),
            "preclean": {str(k): v for k, v in sorted(self.preclean.items())},
            "notes": self.notes,
            "ocr_candidates": self.ocr_candidates,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_preclean(raw) -> dict[int, list[dict]]:
    """yaml 的 preclean 段 → {页号: [规则, ...]}。

    写法（vol02.yaml 里就有一例）：

        preclean:
          151:
            - kind: horizontal_bar
              y0: 648
              y1: 693
              note: 扫描件上压着的粗黑横条

    坐标是**原图像素**（raw_dir 里那张的尺度），不是任何下游产物的坐标。
    """
    if not raw:
        return {}
    out: dict[int, list[dict]] = {}
    for page, rules in raw.items():
        if isinstance(rules, dict):
            rules = [rules]
        out[int(page)] = [dict(r) for r in rules]
    return out


def load_book(book_id: str, books_dir: Path | None = None) -> BookSpec:
    path = (books_dir or BOOKS_DIR) / f"{book_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"没有这册书的定义: {path}")
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    raw_dir = Path(d["raw_dir"])
    if not raw_dir.is_absolute():
        # 相对路径优先按工作区解释（原图已随书迁到 siku-zongmu-workspace），
        # 没设 GUJI_WORKSPACE 时退回仓根——引擎自带的小样本仍在仓内。
        from .workspace import raw_root
        raw_dir = raw_root() / raw_dir
    return BookSpec(
        id=d.get("id", book_id), title=d.get("title", book_id), raw_dir=raw_dir,
        raw_pattern=d.get("raw_pattern", "{page}.png"),
        expected_cols=int(d.get("expected_cols", 9)),
        chars_per_line=int(d.get("chars_per_line", 21)),
        edition=d.get("edition", "keben"),
        dev_set=[int(p) for p in d.get("dev_set", [])],
        sets={str(k): [int(p) for p in v]
              for k, v in (d.get("sets") or {}).items()},
        jiazhu=dict(d.get("jiazhu") or {}),
        bottom_gap=(None if d.get("bottom_gap") is None else float(d["bottom_gap"])),
        period_prior=(None if d.get("period_prior") is None else float(d["period_prior"])),
        pages=[int(p) for p in d.get("pages", [])],
        preclean=_load_preclean(d.get("preclean")),
        notes=d.get("notes", ""),
        ocr_candidates=bool(d.get("ocr_candidates", False)),
    )


def list_books(books_dir: Path | None = None) -> list[str]:
    d = books_dir or BOOKS_DIR
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


_OCR_CANDIDATES_LINE_RE = re.compile(r"^ocr_candidates:\s*(true|false)\s*$", re.MULTILINE)


def set_ocr_candidates(book_id: str, enabled: bool, books_dir: Path | None = None) -> None:
    """定向文本编辑 book yaml 的顶层 `ocr_candidates:` 字段，写控制台的
    开关用。这份 yaml 满是手写中文注释（版本考据、专项集来由等），用
    `yaml.safe_dump` 整体重写会把这些注释全部冲掉，所以只在原文里
    改/插这一行，不碰其余内容。"""
    path = (books_dir or BOOKS_DIR) / f"{book_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"没有这册书的定义: {path}")
    text = path.read_text(encoding="utf-8")
    line = f"ocr_candidates: {'true' if enabled else 'false'}"
    if _OCR_CANDIDATES_LINE_RE.search(text):
        text = _OCR_CANDIDATES_LINE_RE.sub(line, text, count=1)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")
