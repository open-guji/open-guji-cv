"""人裁事件文件（`feedback/events/*.jsonl`）的底层读口，和换图源后的「页表 rev 判据」。

为什么放在 core（GUJI-748 殿本换图源，设计稿 `doc/design/殿本换图源-siku-qiefen-v2.md` §六）：
`groups`、`clustering` 在 L2，不能 import `feedback`（L3）。所以凡是要读人裁事件文件的地方，
`feedback.events.EventLog` 也好、L2 里直接扫文件的也好，都经这里，判据只写一处。

**判据**：册 yaml 写了 `source_rev`（这册已换图源）时，指向这册某一页的事件，锚里的
`anchor.source_rev` 必须等于它才采信。没有这个字段、或不相等的，一律不采信，不看 ts。
原因是换源后页号重编，旧页号的事件会落到新页的同号格上；还开着旧页面的控制台写出来的事件，
ts 是新的，页号却是旧的。迁移事件锚里写的是新 rev，照常采信。

不受判据管的：
- 没切的册（yaml 没有 `source_rev`）：行为不变；
- 不指向页的事件（`unit=book` 之类，key 里没有页号）；
- `glyph_audit`：按字形库实例 id 寻址，换源时由 `guji rekey-cells` 改键，不看页表。
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

#: 不按页寻址、不受页表 rev 判据管的事件种类。
GATE_EXEMPT_KINDS = frozenset({"glyph_audit", "ctx_ruling"})   # 裁定按窗口内容键，不按页号锚，换图源不影响它（2026-10-31）


_REV_CACHE: dict[str, tuple[tuple[int, int], int | None]] = {}


def book_source_rev(book: str, books_dir: Path | None = None) -> int | None:
    """册 yaml 的 `source_rev`；没写、找不到册、读不了一律 None（= 不设判据）。

    事件读口每读一批都要问一遍，所以按 yaml 文件的 (mtime_ns, 大小) 记住结果，只 stat 不重解析。"""
    try:
        from .book import _book_yaml_path
        p = _book_yaml_path(book, books_dir)
        st = p.stat()
    except OSError:                     # 没设工作区（FileNotFoundError）、没有这册
        return None
    sig, key = (st.st_mtime_ns, st.st_size), str(p)
    hit = _REV_CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1]
    import yaml
    try:
        with open(p, encoding="utf-8") as f:
            d = yaml.safe_load(f)
        v = d.get("source_rev") if isinstance(d, dict) else None
        rev = None if v is None else int(v)
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        rev = None
    _REV_CACHE[key] = (sig, rev)
    return rev


def _book_page(target: dict) -> tuple[str | None, int | None]:
    book, page = target.get("book"), target.get("page")
    if book and page is not None:
        return book, page
    key = str(target.get("key") or "").removeprefix("v2:")
    parts = key.split(":")
    if len(parts) >= 2 and parts[1].isdigit():
        return book or parts[0], int(parts[1])
    return book, page


class RevGate:
    """一次读取用一个：按册记住 yaml 的 `source_rev`，并数下不采信的条数（按册）。"""

    def __init__(self, books_dir: Path | None = None):
        self.books_dir = books_dir
        self._rev: dict[str, int | None] = {}
        self.dropped: dict[str, int] = {}

    def rev(self, book: str) -> int | None:
        if book not in self._rev:
            self._rev[book] = book_source_rev(book, self.books_dir)
        return self._rev[book]

    def admits(self, kind: str | None, target: dict) -> bool:
        if kind in GATE_EXEMPT_KINDS:
            return True
        book, page = _book_page(target or {})
        if not book or page is None:
            return True
        want = self.rev(book)
        if want is None:
            return True
        got = ((target or {}).get("anchor") or {}).get("source_rev")
        try:
            ok = got is not None and int(got) == want
        except (TypeError, ValueError):
            ok = False
        if not ok:
            self.dropped[book] = self.dropped.get(book, 0) + 1
        return ok

    def admits_dict(self, e: dict) -> bool:
        return self.admits(e.get("kind"), e.get("target") or {})

    def note(self) -> str:
        """「N 条因页表 rev 不符不采信」的提示；没丢就是空串。"""
        if not self.dropped:
            return ""
        return "；".join(f"{b} {n} 条" for b, n in sorted(self.dropped.items())) + \
            "：事件锚里的页表 rev 与册 yaml 的 source_rev 不符（换图源前的旧页号），不采信"


def sibling_books_dir(feedback_dir: Path) -> Path | None:
    """事件和册 yaml 同在一个数据目录里（`<数据>/feedback/events`、`<数据>/books`）：
    给定 `feedback/` 或 `feedback/events/`，找同一数据目录的 `books/`；找不到返回 None（= 用工作区的）。"""
    d = Path(feedback_dir)
    for up in (d.parent, d.parent.parent):
        if (up / "books").is_dir():
            return up / "books"
    return None


def iter_event_dicts(events_dir: Path, *, gate: RevGate | bool = True,
                     pattern: str = "*.jsonl") -> Iterator[dict]:
    """按文件名顺序逐行读事件（dict）；坏行跳过。`gate=False` 只给维护工具（普查、迁移）用。"""
    for _f, e in iter_event_records(events_dir, gate=gate, pattern=pattern):
        yield e


def iter_event_records(events_dir: Path, *, gate: RevGate | bool = True,
                       pattern: str = "*.jsonl") -> Iterator[tuple[Path, dict]]:
    """同 `iter_event_dicts`，另给出事件所在的文件。"""
    d = Path(events_dir)
    g = gate if isinstance(gate, RevGate) else (RevGate(sibling_books_dir(d)) if gate else None)
    if not d.is_dir():
        return
    for f in sorted(d.glob(pattern)):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if g is not None and not g.admits_dict(e):
                    continue
                yield f, e
