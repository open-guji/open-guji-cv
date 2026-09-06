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
    pages: list[int] = field(default_factory=list)   # 空 = 扫目录
    # Step0 预清理：{页号: [规则, ...]}。默认空 = 不做任何处理。
    # 只对手工登记过的页生效，不改磁盘原图，见 utils/preclean.py。
    preclean: dict[int, list[dict]] = field(default_factory=dict)
    notes: str = ""

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
        pages: set[int] = set()
        for part in str(selector).split(","):
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
            "preclean_pages": sorted(self.preclean), "notes": self.notes,
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
        raw_dir = _repo_root() / raw_dir
    return BookSpec(
        id=d.get("id", book_id), title=d.get("title", book_id), raw_dir=raw_dir,
        raw_pattern=d.get("raw_pattern", "{page}.png"),
        expected_cols=int(d.get("expected_cols", 9)),
        chars_per_line=int(d.get("chars_per_line", 21)),
        edition=d.get("edition", "keben"),
        dev_set=[int(p) for p in d.get("dev_set", [])],
        sets={str(k): [int(p) for p in v]
              for k, v in (d.get("sets") or {}).items()},
        pages=[int(p) for p in d.get("pages", [])],
        preclean=_load_preclean(d.get("preclean")),
        notes=d.get("notes", ""),
    )


def list_books(books_dir: Path | None = None) -> list[str]:
    d = books_dir or BOOKS_DIR
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))
