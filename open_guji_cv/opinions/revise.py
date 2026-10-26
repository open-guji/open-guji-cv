"""修订工具（设计第三节 ``revise.py``、D1a）：把已采纳意见的 A／B／B′ 类修订套到 book-text 冻结册上，出 1.x 新版本。

| 类 | 改什么 |
|---|---|
| A | 同格改字：char 该格 ``c`` 换掉（有 ``zi`` 的一并去掉） |
| B | □↔字：阙文补字（去掉 ``lacuna``），或字改成阙文（``c=□``、``lacuna: true``） |
| B′ | cord 里 ``excluded``／``blank`` 的 mark 变成格：cord 删 mark、加 cell（沿用框与 id）；char 在 ``after`` 那格之后插新格 |
| C | 切分变了（拆格、并格、整列），第一阶段不做，跳过并列出 |

伴生层跟着改：标点 ``pre_char``、实体 ``text`` 按新字重算；B′ 插格后各条 ``char_offset``／``span`` 按锚点重算；
锚在 ``after`` 那格、``pos: after`` 的点号与分段符挪到新格（插进来的字接在前一个字后面，「卷」+「一」后才分段）。

升版本一律调 book-text 的 ``scripts/book-text/bump_original.py``（不手改版本号）：先文本线 patch，
再对改过的标点、实体线各升 patch（它会把 text_version 跟到新文本）。CHANGES 的说明里列意见 id。

阙文带推测字的写法（``guess_style``）：
- ``guess-c``（缺省，guji-char v0.2，GUJI-717 用户 10-20 定）：``{"c": "□", "lacuna": true, "guess_c": "一"}``，
  阅读器照阙文显示 □、悬停给推测字；用到它的章 ``$schema`` 写 char v0.2（guji-format#21）；
- ``lacuna``（guji-char v0.1）：``{"c": "□", "lacuna": true}``，推测字只记在 CHANGES 与意见池；
- ``guess-char``（v0.1 的残字写法）：``{"c": "一", "guess": true}``，阅读器显示灰字加点线。
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .schema import norm_class
from .textsrc import BookText, vol_key

LACUNA = "□"
GUESS_STYLES = ("guess-c", "lacuna", "guess-char")
CHAR_SCHEMA_V02 = "https://open-guji.org/schema/char/v0.2.json"
CELL_KEYS = ("a", "c", "lane", "lacuna", "guess", "guess_c", "zi")
APPLY_CLASSES = ("A", "B", "B′")


class ReviseError(RuntimeError):
    pass


# ---- 写盘格式（与 book-text original_version 一致：char／cord 一格一行，其余 indent=2）----

def _flat(v) -> bool:
    if isinstance(v, dict):
        return all(not isinstance(x, dict) and _flat(x) for x in v.values())
    if isinstance(v, list):
        return all(not isinstance(x, dict) and _flat(x) for x in v)
    return True


def dumps_compact(obj, indent: int = 0) -> str:
    pad, pad1 = "  " * indent, "  " * (indent + 1)
    if _flat(obj) or not isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))
    if isinstance(obj, dict):
        items = [f"{pad1}{json.dumps(k, ensure_ascii=False)}: {dumps_compact(v, indent + 1)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}" if items else "{}"
    items = [pad1 + dumps_compact(v, indent + 1) for v in obj]
    return "[\n" + ",\n".join(items) + "\n" + pad + "]" if items else "[]"


def dump_like(original_text: str | None, obj, default: str = "compact") -> str:
    """按原文件的写法写回：一格一行或 indent=2。"""
    style = default
    if original_text is not None:
        o = json.loads(original_text)
        if dumps_compact(o) + "\n" == original_text:
            style = "compact"
        elif json.dumps(o, ensure_ascii=False, indent=2) + "\n" == original_text:
            style = "indent"
    if style == "compact":
        return dumps_compact(obj) + "\n"
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


# ---- 字流 ----

def slots(char: dict) -> list[tuple[str, str]]:
    return [(c["a"], c["c"]) for p in char.get("pages") or [] for col in p.get("columns") or []
            for c in col.get("cells") or []]


def _find_cell(char: dict, a: str):
    for p in char.get("pages") or []:
        for col in p.get("columns") or []:
            for i, c in enumerate(col.get("cells") or []):
                if c["a"] == a:
                    return col, i, c
    return None, None, None


def anchor_mismatches(char: dict, line: str, data: dict) -> list[str]:
    """伴生层锚点校验字与 char 逐个核对（与 book-text ``original_version.anchor_mismatches`` 同口径，F-OV-02）。"""
    sl = slots(char)
    pos = {a: i for i, (a, _c) in enumerate(sl)}
    bad = []
    if line == "punct":
        for i, p in enumerate(data.get("punctuations") or []):
            a = p.get("anchor")
            if not a:
                continue
            if a not in pos:
                bad.append(f"标点 #{i} 锚点 {a} 已不存在")
            elif "pre_char" in p and sl[pos[a]][1] != p["pre_char"]:
                bad.append(f"标点 #{i} {a} 校验字 {p['pre_char']!r} ≠ {sl[pos[a]][1]!r}")
    else:
        for i, e in enumerate(data.get("entities") or []):
            anc = e.get("anchor") or {}
            s, t = anc.get("start"), anc.get("end")
            if not s or not t:
                continue
            if s not in pos or t not in pos or pos[t] < pos[s]:
                bad.append(f"实体 #{i} 锚点 {s}–{t} 已不存在")
                continue
            got = "".join(c for _a, c in sl[pos[s]:pos[t] + 1])
            if "text" in e and got != e["text"]:
                bad.append(f"实体 #{i} {s}–{t} 校验字 {e['text']!r} ≠ {got!r}")
    return bad


# ---- 套修订 ----

@dataclass
class Applied:
    opinion: str
    cls: str
    cells: list
    notes: list = field(default_factory=list)


def apply_one(char: dict, cord: dict, op_id: str, rev: dict, guess_style: str = "guess-c") -> Applied:
    """在内存里把一条修订套到 char／cord 上。校验字对不上就报错，不改。"""
    k = norm_class(rev.get("class"))
    if k not in APPLY_CLASSES:
        raise ReviseError(f"{op_id}：{k} 类第一阶段不做")
    if guess_style not in GUESS_STYLES:
        raise ReviseError(f"guess_style 应为 {GUESS_STYLES}")
    out = Applied(op_id, k, [])
    for c in rev.get("cells") or []:
        a = c["a"]
        if k in ("A", "B"):
            col, i, cell = _find_cell(char, a)
            if cell is None:
                raise ReviseError(f"{op_id}：char 里没有 {a}")
            if c.get("from") is not None and cell["c"] != c["from"]:
                raise ReviseError(f"{op_id}：{a} 现为「{cell['c']}」，修订说原是「{c['from']}」，版本对不上")
            before = dict(cell)
            to = c["to"]
            if to == LACUNA:
                cell["c"] = LACUNA
                cell["lacuna"] = True
                cell.pop("zi", None)
                cell.pop("guess", None)
                cell.pop("guess_c", None)
                g = c.get("guess")
                if g and guess_style == "guess-char":
                    cell.update(c=g, guess=True)
                    cell.pop("lacuna", None)
                elif g and guess_style == "guess-c":
                    cell["guess_c"] = g
            else:
                cell["c"] = to
                cell.pop("lacuna", None)
                cell.pop("guess", None)
                cell.pop("guess_c", None)
                if "zi" in cell:
                    out.notes.append(f"{a} 原有组字 zi={cell['zi']!r}，改字后去掉")
                    cell.pop("zi")
            col["cells"][i] = {key: cell[key] for key in CELL_KEYS if key in cell}
            out.cells.append({"a": a, "before": before, "after": col["cells"][i]})
        else:   # B′
            after, mark_id = c.get("after"), c.get("mark")
            if not after or not mark_id:
                raise ReviseError(f"{op_id}：B′ 要给 after 与 mark")
            if _find_cell(char, a)[2] is not None:
                raise ReviseError(f"{op_id}：新格号 {a} 已有字")
            col, i, prev = _find_cell(char, after)
            if prev is None:
                raise ReviseError(f"{op_id}：char 里没有 {after}")
            if a.split(":")[:2] != after.split(":")[:2]:
                raise ReviseError(f"{op_id}：新格 {a} 与 {after} 不在同一列")
            page = int(a.split(":")[0])
            pg = next((p for p in cord.get("pages") or [] if p.get("page") == page), None)
            mk = next((m for m in (pg or {}).get("marks") or [] if m.get("id") == mark_id), None)
            if mk is None:
                raise ReviseError(f"{op_id}：cord 第 {page} 页没有 mark {mark_id}")
            if c.get("from") and mk.get("kind") != c["from"]:
                raise ReviseError(f"{op_id}：mark {mark_id} 是 {mk.get('kind')}，修订说是 {c['from']}")
            new = {"a": a, "c": c.get("to") or LACUNA}
            if "lane" in prev and prev.get("lane") == "solo":
                new["lane"] = "solo"
            if c.get("lacuna", new["c"] == LACUNA):
                new["c"], new["lacuna"] = LACUNA, True
                g = c.get("guess")
                if g and guess_style == "guess-char":
                    new = {"a": a, "c": g, "guess": True}
                elif g and guess_style == "guess-c":
                    new["guess_c"] = g
            col["cells"].insert(i + 1, new)
            pg["marks"] = [m for m in pg["marks"] if m.get("id") != mark_id]
            cells = pg.setdefault("cells", [])
            j = next((n for n, x in enumerate(cells) if x.get("a") == after), len(cells) - 1)
            cells.insert(j + 1, {"a": a, "box": mk["box"], **({"id": mk["id"]} if mk.get("id") else {})})
            if mk.get("slot") is not None and str(mk["slot"]) != a.split(":")[2].rstrip("ab"):
                out.notes.append(f"mark slot {mk['slot']} ≠ 新格号 {a}（marks 的 slot 与 char 格号口径不同，按「前一格＋1」取号）")
            out.cells.append({"a": a, "after_cell": after, "mark": mk, "new": new, "guess": c.get("guess")})
    return out


def follow_companions(old_char: dict, new_char: dict, punct: dict | None, entity: dict | None,
                      moves: dict[str, str]) -> dict:
    """伴生层跟着新文本改：返回 {"punct": n, "entity": n, "notes": [...]}，就地改 punct／entity。

    ``moves``：B′ 的 {after 格: 新格}，锚在 after、``pos: after`` 的点号与分段符挪到新格。"""
    old_pos = {a: i for i, (a, _c) in enumerate(slots(old_char))}
    nsl = slots(new_char)
    new_pos = {a: i for i, (a, _c) in enumerate(nsl)}
    ch = {a: c for a, c in nsl}
    res = {"punct": 0, "entity": 0, "notes": []}
    if punct:
        for p in punct.get("punctuations") or []:
            a = p.get("anchor")
            if not a:
                continue
            before = json.dumps(p, sort_keys=True, ensure_ascii=False)
            inv = p.get("char_offset") == old_pos.get(a)
            kind, pos = p.get("kind") or "point", p.get("pos") or "after"
            if a in moves and pos == "after" and kind in ("point", "break"):
                p["anchor"] = a = moves[a]
            if "pre_char" in p and a in ch and p["pre_char"] != ch[a]:
                p["pre_char"] = ch[a]
            if inv and a in new_pos:
                p["char_offset"] = new_pos[a]
            elif not inv and "char_offset" in p:
                res["notes"].append(f"标点 {a} 的 char_offset 原本就和锚点对不上，未动")
            if json.dumps(p, sort_keys=True, ensure_ascii=False) != before:
                res["punct"] += 1
    if entity:
        for e in entity.get("entities") or []:
            anc = e.get("anchor") or {}
            s, t = anc.get("start"), anc.get("end")
            if not s or not t or s not in new_pos or t not in new_pos:
                continue
            before = json.dumps(e, sort_keys=True, ensure_ascii=False)
            sp = e.get("span") or {}
            if sp.get("start_offset") == old_pos.get(s) and sp.get("end_offset") == (old_pos.get(t, -2) + 1):
                sp["start_offset"], sp["end_offset"] = new_pos[s], new_pos[t] + 1
            got = "".join(c for _a, c in nsl[new_pos[s]:new_pos[t] + 1])
            if "text" in e and e["text"] != got:
                res["notes"].append(f"实体 {e.get('id')} {s}–{t}「{e['text']}」→「{got}」")
                e["text"] = got
            if json.dumps(e, sort_keys=True, ensure_ascii=False) != before:
                res["entity"] += 1
    return res


def check_chapter(char: dict, cord: dict | None, punct: dict | None, entity: dict | None, index_ch: dict | None) -> list[str]:
    """本工具自己的出口检查（对应 book-text F-OV-01、F-OV-02，加 cord 与 char 对得上）。真仓另跑 ``scripts/local_check.py``。"""
    probs = []
    keys = [a for a, _c in slots(char)]
    if len(keys) != len(set(keys)):
        probs.append("char 格位重复")
    if index_ch is not None:
        if index_ch.get("text_version") != char.get("version"):
            probs.append(f"F-OV-01 index text_version {index_ch.get('text_version')} ≠ char {char.get('version')}")
        for line, d in (("punct", punct), ("entity", entity)):
            if d is not None and index_ch.get(f"{line}_version") not in (None, d.get("version")):
                probs.append(f"F-OV-01 index {line}_version ≠ {line}.json version")
    for line, d in (("punct", punct), ("entity", entity)):
        if d is None:
            continue
        probs += [f"F-OV-02 {x}" for x in anchor_mismatches(char, line, d)]
    if cord is not None:
        ks = set(keys)
        ids = []
        for p in cord.get("pages") or []:
            for c in p.get("cells") or []:
                if c["a"] not in ks:
                    probs.append(f"cord 格 {c['a']} 在 char 里没有")
                if c.get("id"):
                    ids.append(c["id"])
            ids += [m["id"] for m in p.get("marks") or [] if m.get("id")]
        if len(ids) != len(set(ids)):
            probs.append("cord 框 id 重复")
    return probs


# ---- 计划与执行 ----

def plan(store, vol: str) -> tuple[list, list]:
    """该章已采纳（用户采纳或自动采纳）、还没进文本、带 A／B／B′ 修订的意见；另返回跳过的（C 类、没修订）。"""
    stat = store.statuses()
    todo, skipped = [], []
    for op in store.opinions.values():
        if op.vol != vol_key(vol) or stat[op.id] not in ("accepted", "auto_accepted"):
            continue
        tri = store.last(op.id, "triaged")
        rev = (tri.data.get("revision") if tri else None)
        if not rev:
            skipped.append((op.id, "没有修订（已改或只回复）"))
            continue
        if norm_class(rev.get("class")) not in APPLY_CLASSES:
            skipped.append((op.id, f"{rev.get('class')} 类，第一阶段不做"))
            continue
        todo.append((op, rev))
    todo.sort(key=lambda x: x[0].ts)
    return todo, skipped


def change_note(applied: list[Applied], vol: str, guess_style: str) -> str:
    parts = []
    for ap in applied:
        for c in ap.cells:
            if ap.cls == "B′":
                n = c["new"]
                g = c.get("guess")
                desc = f"{c['a']} 录 □" if n.get("lacuna") or n.get("guess") is True else f"{c['a']} 补「{n['c']}」"
                if g:
                    desc += f"（推测「{g}」，图上无字按磨损缺字）"
                desc += f"，原 cord {c['mark'].get('kind')} 框转为格"
            else:
                desc = f"{c['a']} {c['before']['c']}→{c['after']['c']}"
            parts.append(f"{desc}［{ap.cls}，意见 {ap.opinion}］")
    return f"读者意见修订 {len(parts)} 格：" + "；".join(parts)


def bump(bump_script: Path, vdir: Path, line: str, chapter: str, note: str, pr: str) -> str:
    cmd = [sys.executable, str(bump_script), str(vdir), "--line", line, "--level", "patch", "--chapter", chapter,
           "--note", note, "--pr", str(pr).lstrip("#")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ReviseError(f"bump_original.py {line} 失败：{r.stderr.strip() or r.stdout.strip()}")
    return (r.stdout + r.stderr).strip()


@dataclass
class Result:
    vol: str
    applied: list
    skipped: list
    old_version: str
    new_version: str | None
    companions: dict
    problems: list
    note: str
    bump_log: list = field(default_factory=list)
    files: list = field(default_factory=list)


def revise(bt_root: str | Path, book: str, vol: str, todo: list, *, dry_run: bool = True, pr: str | None = None,
           guess_style: str = "guess-c", bump_script: str | Path | None = None, skipped: list | None = None) -> Result:
    """对一章套 ``todo``（[(op, revision)]）。dry_run 只算不写。"""
    bt = BookText(book, bt_root)
    v3 = vol_key(vol)
    vdir = bt.path("")
    names = {k: f"{v3}.{k}.json" for k in ("char", "cord", "punct", "entity")}
    texts = {k: bt.text(n) for k, n in names.items()}
    if texts["char"] is None:
        raise ReviseError(f"{vdir} 没有 {names['char']}")
    if bt.text(f"{v3}.char-edits.json") is not None:
        raise ReviseError(f"{vdir} 有未清的改字清单 {v3}.char-edits.json（0.x 精校期专用，book-text docs/design/2026-10-改字清单.md）："
                          "先让 A33 用 char_edits.py sync 清空，再走 revise")
    old_char = json.loads(texts["char"])
    char, cord = copy.deepcopy(old_char), json.loads(texts["cord"]) if texts["cord"] else {"pages": []}
    applied = [apply_one(char, cord, op.id, rev, guess_style) for op, rev in todo]
    if any("guess_c" in c for p in char.get("pages") or [] for col in p.get("columns") or [] for c in col.get("cells") or []):
        char["$schema"] = CHAR_SCHEMA_V02          # guess_c 只有 char v0.2 认（guji-format#21）
    moves = {c["after_cell"]: c["a"] for ap in applied if ap.cls == "B′" for c in ap.cells}
    punct = json.loads(texts["punct"]) if texts["punct"] else None
    entity = json.loads(texts["entity"]) if texts["entity"] else None
    comp = follow_companions(old_char, char, punct, entity, moves)
    note = change_note(applied, v3, guess_style)
    old_v = old_char.get("version")
    res = Result(v3, applied, skipped or [], old_v, None, comp, [], note)
    index = json.loads(bt.text("index.json") or "{}")
    ich = next((c for c in index.get("chapters") or [] if str(c.get("file")) == v3), None)
    if dry_run or not applied:
        ich_sim = dict(ich or {}, text_version=old_v)
        res.problems = [p for p in check_chapter(char, cord, punct, entity, None)] + \
            [p for p in check_chapter(char, None, None, None, ich_sim)]
        return res
    if not pr:
        raise ReviseError("要 --pr（book-text 的规矩：未开 PR 时先开草稿 PR 再升版本）")
    script = Path(bump_script) if bump_script else Path(bt_root) / "scripts" / "book-text" / "bump_original.py"
    if not script.is_file():
        raise ReviseError(f"找不到 {script}")
    # 1) 写 char／cord（版本号不手改），2) 文本线升 patch
    (vdir / names["char"]).write_text(dump_like(texts["char"], char), encoding="utf-8", newline="\n")
    (vdir / names["cord"]).write_text(dump_like(texts["cord"], cord), encoding="utf-8", newline="\n")
    res.files += [names["char"], names["cord"]]
    res.bump_log.append(bump(script, vdir, "text", v3, note, pr))
    char_now = json.loads((vdir / names["char"]).read_text(encoding="utf-8"))
    res.new_version = char_now.get("version")
    # 3) 伴生层：在 bump 之后的文件上重做一遍跟随（bump 可能已把 text_version 跟上），有改动的再升 patch
    for line in ("punct", "entity"):
        p = vdir / names[line]
        if not p.is_file():
            continue
        t = p.read_text(encoding="utf-8")
        d = json.loads(t)
        r = follow_companions(old_char, char_now, d if line == "punct" else None, d if line == "entity" else None, moves)
        if r[line]:
            p.write_text(dump_like(t, d, default="indent"), encoding="utf-8", newline="\n")
            res.files.append(names[line])
            res.bump_log.append(bump(script, vdir, line, v3, f"跟随文本 {res.new_version}：{r[line]} 处锚点校验字／偏移随改字更新", pr))
    final = {k: (json.loads((vdir / n).read_text(encoding="utf-8")) if (vdir / n).is_file() else None)
             for k, n in names.items()}
    index = json.loads((vdir / "index.json").read_text(encoding="utf-8"))
    ich = next((c for c in index.get("chapters") or [] if str(c.get("file")) == v3), None)
    res.problems = check_chapter(final["char"], final["cord"], final["punct"], final["entity"], ich)
    res.files += ["index.json", "CHANGES.md"]
    return res


def pr_body(res: Result, book: str) -> str:
    rows = []
    for ap in res.applied:
        for c in ap.cells:
            if ap.cls == "B′":
                rows.append(f"| {c['a']} | （{c['mark'].get('kind')} 框） | {json.dumps(c['new'], ensure_ascii=False)} | {ap.cls} | `{ap.opinion}` |")
            else:
                rows.append(f"| {c['a']} | {c['before']['c']}→{c['after']['c']} | {json.dumps(c['after'], ensure_ascii=False)} | {ap.cls} | `{ap.opinion}` |")
    lines = [f"四庫總目 {book}/{res.vol} 读者意见修订：文本线 {res.old_version}→{res.new_version or '（dry-run）'}", "",
             "由 open-guji-cv `guji opinions revise` 生成（M11，GUJI-715）。", "",
             "| 格 | 改动 | 新格（char） | 类 | 意见 |", "|---|---|---|---|---|", *rows, "",
             f"伴生层：标点 {res.companions.get('punct', 0)} 处、实体 {res.companions.get('entity', 0)} 处随改字更新。"]
    for ap in res.applied:
        lines += [f"- 注：{n}" for n in ap.notes]
    lines += [f"- 注：{n}" for n in res.companions.get("notes") or []]
    if res.skipped:
        lines += ["", "跳过：" + "；".join(f"{i}（{w}）" for i, w in res.skipped)]
    lines += ["", f"出口检查（F-OV-01／02、cord 对 char）：{'通过' if not res.problems else '；'.join(res.problems)}",
              "合并前另跑 `python3 scripts/local_check.py`，结果贴这里。"]
    return "\n".join(lines)
