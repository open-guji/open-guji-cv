#!/usr/bin/env python3
"""精校进度写进网站后台「文本整理」栏目（A41 的 progress schema，kaiyuanguji-web docs/text-progress.md）。

每册算四样，写中心库 progress.volume 和 progress.metric（栏目 review「人审」）：
  - 待人审（pending_review）：线上待审单里还等人投的格（review≠human），连同单号、出单时间
  - 已人裁（human_judged）：定了字的人裁事件覆盖的格（口径同 pending_route.deciding：看不出、是图等也算定了），
    只数现行文本里还在的格；格号漂掉的另记在 detail
  - 人审率：已裁完的格 ÷（已裁 ∪ 待审）。还挂在线上单上的格不算裁完（复审格即使有旧人裁也算待审）
  - 备注（note）：自动一句「卡在哪」＋ `--note` 留的人写备注（存在 extra.a32_note，下次自动带上，`--note ''` 清掉）
另写 cells_total（全册格数，book-text dev 的 <章>.char.json）和 stage（≥1.0 或冻结＝released，否则 fine）。

数据全从真源取，不靠本机工作区：事件、待审单、册 yaml 读中心库；格数和文本版本读 book-text dev（raw.githubusercontent）。
写法只用 progress.put_volume／put_metric，覆盖写、幂等，看板数据不影响任何产物和文本。

  python scripts/zhengli/progress_report.py --books vol04,vol05,vol06            # 算并写库
  python scripts/zhengli/progress_report.py --books vol04 --dry-run              # 只算，打印要写的
  python scripts/zhengli/progress_report.py --books vol05 --note '148:2:14 等 GUJI-743 图片格'

proof_cycle apply 收尾、republish push 推库后会自动对本册跑一次（失败只记 ⚠，不影响精校流程）。
连库：GUJI_DATA_PG_DSN，或 NEON_DATABASE_URL（自动起 443 桥）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CV = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CV))
from pending_route import cell_of, deciding  # noqa: E402

WRITER = "A32"
SECTION = "review"
SECTION_DESC = ("人审（A32）：待人审＝线上待审单还等人投的格；已人裁＝有定字人裁的格（现行文本里还在的）；"
                "人审率＝已裁完 ÷（已裁 ∪ 待审），还挂在单上的格不算裁完")
DEFAULT_WS = "siku-zongmu"
DEFAULT_TEXT = "96mid1ogzk"
# 精校流程里自动写的册（A32 在跑的）；别的册要写就手动跑本脚本，或在这里加
A32_BOOKS = {"96mid1ogzk": {"vol04", "vol05", "vol06"}}
BOOK_TEXT_RAW = os.environ.get("BOOK_TEXT_RAW", "https://raw.githubusercontent.com/open-guji/book-text/dev")


def chapter_of(book: str) -> str:
    return re.sub(r"\D", "", book).zfill(3)


def text_base(text_id: str) -> str:
    """book-text 的条目目录：Book/<id 倒数第三>/<倒数第二>/<末字>/<id>/default。"""
    return f"Book/{text_id[-3]}/{text_id[-2]}/{text_id[-1]}/{text_id}/default"


def fetch_json(url: str, timeout: int = 60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def text_cells(char_doc: dict) -> set[str]:
    return {c["a"] for p in char_doc.get("pages") or [] for col in p.get("columns") or [] for c in col.get("cells") or []}


def judged_cells(events, book: str) -> set[str]:
    """events：可迭代的 dict（kind、target、payload）。返回定了字的格位集合。"""
    out = set()
    for e in events:
        if deciding(e):
            c = cell_of(e, book)
            if c:
                out.add(c)
    return out


def pending_cells(sheet: dict | None) -> set[str]:
    return {c["cell"] for c in (sheet or {}).get("cells") or [] if c.get("review") != "human" and c.get("cell")}


def version_ge_1(v: str | None) -> bool:
    m = re.match(r"(\d+)\.", v or "")
    return bool(m) and int(m[1]) >= 1


def auto_note(sheet: dict | None, pending: int, text_version: str | None, frozen: str | None) -> str:
    parts = []
    if frozen:
        parts.append(f"已冻结 {frozen}")
    elif version_ge_1(text_version):
        parts.append(f"文本 {text_version}")
    rev = (sheet or {}).get("rev")
    if pending:
        parts.append(f"等人审：线上单 {rev} 剩 {pending} 格")
    elif rev and not frozen:
        parts.append(f"线上单 {rev} 已无待投格，等落票或出下一单")
    return "；".join(parts) or "—"


def compute(book: str, sheet: dict | None, events, char_doc: dict | None, chapter_entry: dict | None,
            book_doc: dict | None, manual_note: str | None) -> dict:
    """纯函数：给定真源内容，算出要写的字段和指标（便于测试）。"""
    cells = text_cells(char_doc) if char_doc else set()
    judged_all = judged_cells(events, book)
    judged = judged_all & cells if cells else judged_all
    pend = pending_cells(sheet)
    done = judged - pend
    scope = judged | pend
    rate = round(len(done) / len(scope), 4) if scope else None
    tv = (chapter_entry or {}).get("text_version")
    frozen = ((book_doc or {}).get("freeze") or {}).get("at")
    note = auto_note(sheet, len(pend), tv, frozen)
    if manual_note:
        note += f"；{manual_note}"
    fields = {
        "stage": "released" if (frozen or version_ge_1(tv)) else "fine",
        "pending_review": len(pend),
        "pending_rev": (sheet or {}).get("rev"),
        "pending_at": (sheet or {}).get("routed_as_of"),
        "human_judged": len(judged),
        "note": note,
        "extra": {"a32_note": manual_note or None, "a32_judged_drifted": len(judged_all - judged) if cells else None},
    }
    if cells:
        fields["cells_total"] = len(cells)
    metrics = [
        ("pending_review", "待人审", len(pend), "格", None, 10),
        ("human_judged", "已人裁", len(judged), "格", {"drifted": len(judged_all - judged) if cells else None}, 20),
        ("review_rate", "人审率", rate, "%", {"done": len(done), "scope": len(scope)}, 30),
        ("judged_share", "人裁覆盖全册", round(len(judged) / len(cells), 4) if cells else None, "%",
         {"cells_total": len(cells) or None}, 40),
        ("note", "备注", None, None, None, 50),
    ]
    return {"fields": fields, "metrics": metrics, "note": note}


# ─── 读真源 ───────────────────────────────────────────────────────────

def load_db(conn, ws: str, book: str, text_id: str, chapter: str) -> tuple[dict | None, list[dict], dict | None, dict]:
    row = conn.execute("SELECT doc FROM files WHERE ws = %s AND src_path = %s",
                       (ws, f"feedback/lists/proofing/{text_id}/{chapter}.pending.json")).fetchone()
    sheet = row[0] if row else None
    evs = [{"kind": k, "target": t, "payload": p} for k, t, p in conn.execute(
        "SELECT kind, target, payload FROM events WHERE ws = %s AND kind = 'confirm' AND "
        "(book = %s OR (book IS NULL AND target->>'key' LIKE %s))", (ws, book, f"{book}:%")).fetchall()]
    row = conn.execute("SELECT doc FROM books WHERE ws = %s AND book = %s", (ws, book)).fetchone()
    book_doc = row[0] if row else None
    row = conn.execute("SELECT extra FROM progress.volume WHERE book_id = %s AND vol = %s", (text_id, chapter)).fetchone()
    extra = row[0] if row else {}
    return sheet, evs, book_doc, extra or {}


def load_book_text(text_id: str, chapter: str) -> tuple[dict | None, dict | None]:
    base = f"{BOOK_TEXT_RAW}/{text_base(text_id)}"
    try:
        idx = fetch_json(f"{base}/index.json")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 读不到 book-text index.json：{e}", file=sys.stderr)
        return None, None
    entry = next((c for c in idx.get("chapters") or [] if str(c.get("file")) == chapter), None)
    if not entry:
        return None, None
    try:
        char = fetch_json(f"{base}/{entry.get('char_file') or chapter + '.char.json'}", timeout=120)
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 读不到 {chapter}.char.json：{e}（cells_total 这次不写）", file=sys.stderr)
        char = None
    return entry, char


def write(conn, text_id: str, chapter: str, res: dict) -> None:
    conn.execute("UPDATE progress.section SET description = %s WHERE section = %s AND description IS DISTINCT FROM %s",
                 (SECTION_DESC, SECTION, SECTION_DESC))
    conn.execute("SELECT progress.put_volume(%s, %s, %s::jsonb, %s)",
                 (text_id, chapter, json.dumps(res["fields"], ensure_ascii=False), WRITER))
    for key, label, value, unit, detail, sort in res["metrics"]:
        vt = res["note"] if key == "note" else None
        conn.execute("SELECT progress.put_metric(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                     (text_id, chapter, SECTION, key, label, value, unit, WRITER, vt,
                      json.dumps(detail, ensure_ascii=False) if detail else None, sort))


def run(books: list[str], ws: str | None = None, text_id: str = DEFAULT_TEXT, note: str | None = None,
        dry_run: bool = False) -> int:
    from open_guji_cv.datastore.connect import connect
    with connect() as conn:
        if not ws:
            row = conn.execute("SELECT ws FROM workspaces WHERE dir = %s OR dir LIKE %s ORDER BY ws LIMIT 1",
                               (text_id, f"{text_id}-%")).fetchone()
            ws = row[0] if row else DEFAULT_WS
        for book in books:
            chapter = chapter_of(book)
            sheet, evs, book_doc, extra = load_db(conn, ws, book, text_id, chapter)
            entry, char = load_book_text(text_id, chapter)
            manual = extra.get("a32_note") if note is None else (note or None)
            res = compute(book, sheet, evs, char, entry, book_doc, manual)
            f = res["fields"]
            print(f"{book}（{text_id}/{chapter}）：待人审 {f['pending_review']}，已人裁 {f['human_judged']}，"
                  f"全册 {f.get('cells_total', '?')} 格，人审率 {res['metrics'][2][2]}，阶段 {f['stage']}；备注：{f['note']}")
            if not dry_run:
                write(conn, text_id, chapter, res)
        if dry_run:
            print("ⓘ --dry-run：没写库")
        else:
            conn.commit()
            print(f"✓ 已写 progress（{WRITER}）：{', '.join(books)}")
    return 0


def try_run(book: str, text_id: str = DEFAULT_TEXT, log=print) -> None:
    """精校流程里调（只对 A32_BOOKS 里的册）：失败只提示，不影响主流程。"""
    if book not in A32_BOOKS.get(text_id, set()):
        return
    try:
        run([book], text_id=text_id)
    except BaseException as e:  # noqa: BLE001  （connect 缺凭据会 SystemExit）
        log(f"⚠ 后台进度没写上（{book}）：{e}；可手动 python scripts/zhengli/progress_report.py --books {book}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--books", required=True, help="cv 册 id，逗号分隔，如 vol04,vol05,vol06")
    ap.add_argument("--ws", help="中心库工作区 id（缺省按 --text-id 查 workspaces.dir）")
    ap.add_argument("--text-id", default=DEFAULT_TEXT, help=f"book-text 条目 id（缺省 {DEFAULT_TEXT}）")
    ap.add_argument("--note", help="人写备注（卡在哪、等谁），存下来以后自动带上；给空串清掉")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    books = [b.strip() for b in a.books.split(",") if b.strip()]
    return run(books, a.ws, a.text_id, a.note, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
