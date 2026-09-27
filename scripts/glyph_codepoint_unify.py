# -*- coding: utf-8 -*-
"""书级码位统一：把库、人裁裁决里「书级指定」对（字形库 11 §〇：别/別、内/內
这类两形人几乎分不出的对）的另一码位改成本书 `codepoints` 配置指定的那个。

    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/glyph_codepoint_unify.py \
        --book <id> [--dry-run] [--out 对照表.json]

不带 `--apply` 一律 `--dry-run`（演练，不落地）——**云端只跑 dry-run**，
真落地（`--apply`）留给服务器执行（任务书 H·码位裁定落地 §用户裁定）。

## 改什么、不改什么

按本书 `codepoints`（`core/book.py::BookSpec.codepoints`，`{另一码位: 本书指定码位}`）
逐对处理，**只在本书范围内**（instance_id 前缀 = 本书；`v2:<book>:…` 也算本书）：

- **库**（`instances.label`／`semantic`／`unicode_cp`）：直接改字形层——这正是「两形
  人分不出，算法要把它们当一个字」，跟 `scripts/correct_admission.py` 改的是**释读**
  （字形不动）刚好相反，见该脚本 docstring 的字形/释读之辨。
- `glyphs`／`exemplars`：同一 `edition_tag` 下把「另一码位」那个字头并进目标字头
  （`n_confirmed` 相加、`exemplars` 改指），不留一个 `n_confirmed=0` 的死字头。
- `admissions.char`：释读层跟着改——这对字本身就是同一个字，没有独立于字形的释读。
- **人裁裁决**（事件日志）：`feedback.lookup.human_chars(book)` 当前解到「另一码位」的
  位置，追加一条新的 `confirm` 事件改判到目标码位（事件日志只追加、不改历史，见
  `feedback/events.py::EventLog`），未来的 `human_chars()` 读到的就是目标码位。
- **不改**：整理本语料（它是证人，码位差由对齐异体表吸收，见任务书用户裁定）；
  按形区分类的四对（强/強、却/卻、回/囘、并/幷，进 `config/confusable_human.json`，
  不进 `codepoints`）。

幂等：改完之后库里再也没有 `label = 另一码位` 的本书实例，重跑同一命令
对照表条数为 0——不需要额外的「已处理」标记。

写库、写事件都在 `feedback.lock.feedback_write_lock` 临界区内（任务书 H·人裁单写者
定的跨进程锁），与体检、控制台裁决互斥。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _belongs_to_book(instance_id: str, book: str) -> bool:
    """`instance_id` 是不是本书的（v1／播种前缀＝书名，或 `v2:<书名>:…`）。

    与 `scripts/glyph_codepoint_census.py::_src_kind` 用的是同一套前缀约定
    （见 `clustering/glyph_ledger.py` 模块头「实例 id 命名空间」）。字体渲染
    （`font:*`）永远不属于任何书。
    """
    parts = instance_id.split(":")
    if not parts or parts[0] in ("font", "modern"):
        return False
    if parts[0] == "v2":
        return len(parts) >= 2 and parts[1] == book
    return parts[0] == book


def _library_matches(conn: sqlite3.Connection, book: str, old_char: str) -> list[tuple[str, str]]:
    """本书里 `label = old_char` 的库实例 → `[(instance_id, source_id), ...]`。"""
    rows = conn.execute(
        "SELECT instance_id, source_id FROM instances WHERE label=?", (old_char,)).fetchall()
    return [(iid, sid) for iid, sid in rows if _belongs_to_book(iid, book)]


def _admission_matches(conn: sqlite3.Connection, book: str, old_char: str) -> list[str]:
    rows = conn.execute("SELECT instance_id FROM admissions WHERE char=?", (old_char,)).fetchall()
    return [iid for (iid,) in rows if _belongs_to_book(iid, book)]


def _human_matches(book: str, old_char: str) -> dict[str, str]:
    """`human_chars(book)` 里当前解到 `old_char` 的位置 → `{key: old_char}`。

    `bind=False`（与 `scripts/glyph_codepoint_census.py` 同一口径）：这个脚本
    改的是「字位当年裁的是哪个码位」，不依赖切分有没有挪动过——按绑定表重找
    现在的格号是另一件事（H 已有的重绑定通道），这里没有活产物时也不该因为
    绑不出锚点就把裁决全部丢空。"""
    from open_guji_cv.feedback.lookup import human_chars
    return {k: c for k, c in human_chars(book, bind=False).items() if c == old_char}


def scan(book: str, mapping: dict[str, str], db_path: Path) -> dict:
    """整本书、所有配置对的对照表（library / admissions / human 各自条数与样例）。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        report = {"book": book, "db": str(db_path), "pairs": {}}
        for old, new in mapping.items():
            lib = _library_matches(conn, book, old)
            adm = _admission_matches(conn, book, old)
            hum = _human_matches(book, old)
            report["pairs"][f"{old}→{new}"] = {
                "library": {"n": len(lib), "sample": [iid for iid, _ in lib[:10]]},
                "admissions": {"n": len(adm), "sample": adm[:10]},
                "human_chars": {"n": len(hum), "sample": list(hum)[:10]},
            }
        return report
    finally:
        conn.close()


def _merge_glyph_head(cur: sqlite3.Cursor, edition_tag: str, old: str, new: str) -> None:
    """把 `(edition_tag, old)` 字头并进 `(edition_tag, new)`：`exemplars` 改指、
    `n_confirmed` 相加，不留死字头。两边都没有就什么都不做（这本书这个字头本来
    就没进过 `glyphs`，多半只是 `no_glyph_lib` 刻例，库匹配层没有它，不必新造）。
    """
    old_row = cur.execute("SELECT glyph_id, n_confirmed FROM glyphs WHERE edition_tag=? AND char=?",
                          (edition_tag, old)).fetchone()
    if old_row is None:
        return
    old_gid, old_n = old_row
    new_row = cur.execute("SELECT glyph_id, n_confirmed FROM glyphs WHERE edition_tag=? AND char=?",
                          (edition_tag, new)).fetchone()
    if new_row is None:
        cur.execute("UPDATE glyphs SET char=?, updated_at=? WHERE glyph_id=?",
                   (new, _now(), old_gid))
        return
    new_gid, new_n = new_row
    cur.execute("UPDATE glyphs SET n_confirmed=?, status=?, updated_at=? WHERE glyph_id=?",
               (old_n + new_n, "stable" if old_n + new_n >= 3 else "sparse", _now(), new_gid))
    # exemplars 主键是 (glyph_id, instance_id)：old 里有的 instance 若 new 也有（同一实例
    # 曾经两边都留过 exemplar，不该发生但别让 UNIQUE 冲突炸脚本）先撤旧的再改指。
    cur.execute("DELETE FROM exemplars WHERE glyph_id=? AND instance_id IN "
               "(SELECT instance_id FROM exemplars WHERE glyph_id=?)", (old_gid, new_gid))
    cur.execute("UPDATE exemplars SET glyph_id=? WHERE glyph_id=?", (new_gid, old_gid))
    cur.execute("DELETE FROM glyphs WHERE glyph_id=?", (old_gid,))


def apply(book: str, mapping: dict[str, str], db_path: Path) -> dict:
    """真落地：改库＋改事件日志。走人裁写锁，与体检/控制台裁决互斥。"""
    from open_guji_cv.core.workspace import feedback_root
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    from open_guji_cv.feedback.harvest import parse_card_id
    from open_guji_cv.feedback.lock import feedback_write_lock

    result = {"book": book, "pairs": {}}
    with feedback_write_lock(feedback_root()):
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            now = _now()
            for old, new in mapping.items():
                lib = _library_matches(conn, book, old)
                for iid, sid in lib:
                    edition = cur.execute(
                        "SELECT edition_tag FROM sources WHERE source_id=?", (sid,)).fetchone()
                    edition = edition[0] if edition else sid
                    cur.execute(
                        "UPDATE instances SET label=?, semantic=?, unicode_cp=?, updated_at=?"
                        " WHERE instance_id=?", (new, new, ord(new), now, iid))
                    _merge_glyph_head(cur, edition, old, new)
                adm = _admission_matches(conn, book, old)
                for iid in adm:
                    cur.execute("UPDATE admissions SET char=?, admitted_at=? WHERE instance_id=?",
                               (new, now, iid))
                hum = _human_matches(book, old)
                events = []
                log = EventLog()
                batch = f"{book}-codepoint-unify-{datetime.now(timezone.utc):%Y%m%d}"
                base = log.latest_seq(batch)
                for i, key in enumerate(hum, 1):
                    target = EventTarget(step="H_codepoint_unify", unit="cell", key=key,
                                         **parse_card_id(key))
                    payload = {"v": "confirm", "shape": new, "conversion": 0,
                              "no_glyph_lib": False,
                              "note": f"书级码位统一（字形库11 §〇 用户裁定）：{old}→{new}"}
                    events.append(make_event(batch, base + i, "confirm", target, payload,
                                             actor="model"))
                n_events = log.append(events) if events else 0
                result["pairs"][f"{old}→{new}"] = {
                    "library": len(lib), "admissions": len(adm), "human_events": n_events}
            conn.commit()
        finally:
            conn.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", required=True)
    ap.add_argument("--apply", action="store_true", help="真落地；缺省只演练（dry-run）")
    ap.add_argument("--dry-run", action="store_true", help="显式声明演练（缺省行为，写给人看）")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.workspace import glyph_db_path

    book = load_book(a.book)
    if not book.codepoints:
        print(f"{a.book} 没有配置 codepoints，无事可做（见 core/book.py::BookSpec.codepoints）。")
        return 0

    db_path = glyph_db_path()
    if a.apply:
        rep = apply(a.book, book.codepoints, db_path)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        rep = scan(a.book, book.codepoints, db_path)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        print("\n（演练模式，未落地。加 --apply 执行，且要走人裁写锁。）")
    if a.out:
        a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
