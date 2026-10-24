"""取 book-text 的 char／cord／punct／entity／CHANGES（设计第三节 ``textsrc.py``、A3）。

来源：本地 book-text 检出（``--book-text`` 或环境变量 ``GUJI_BOOK_TEXT``），否则 GitHub raw（只读）。
条目目录 ``Book|Work/<c1>/<c2>/<c3>/<书>/``，``c1..c3`` 是书 id 末三位；版本目录取 manifest 里 ``is_original`` 的那个（缺省 ``default``）。

``parse_changes`` 把 ``CHANGES.md`` 里文本线升版的行解析成 ``text_versions.json``（设计 2.5）：
``{"<章>": [{"text_version", "date", "pr", "rev", "cv_version", "cv_commit", "snapshot", "kind", "note"}]}``；
散文里解析不出的字段留空（``None``），``locate`` 报「缺」。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

GH_RAW = "https://raw.githubusercontent.com/open-guji/book-text/main"

_SPLIT = re.compile(r"(?<!\\)\|")
_VER = r"\d+\.\d+\.\d+"
_CHANGE = re.compile(rf"^(?:(?P<old>{_VER}))?→(?P<new>{_VER})$")
_REV = re.compile(r"(?:本册|rev)\s*(\d{3}-r\d+)")
#: 正式版 `v0.5.9`；dev 跑的整段带上（`0.5.10.dev12+g<hash>`、`dev+g<hash>`），免得截成 `0.5.10` 冒充正式版
_CV_VER = re.compile(r"cv\s*(rc/v\d+\.\d+\.\d+|v?\d+\.\d+\.\d+(?:\.dev\d+)?(?:\+[0-9a-z.]+)?|dev\+g[0-9a-f]+(?:\.dirty)?)")
_CV_COMMIT = re.compile(r"(?:cv|commit)\s+([0-9a-f]{7,40})\b")
_SNAP = re.compile(r"(snap/[\w./-]+?)(?=[（）()，,；;\s]|$)")
_SNAP_SHA = re.compile(r"快照\s*([0-9a-f]{7,40})\b")
_OP_ID = re.compile(r"\bop_[a-z0-9-]+_[0-9a-f]{10}(?:_\d+)?\b")


def vol_key(v) -> str:
    m = re.search(r"(\d+)$", str(v))
    return f"{int(m.group(1)):03d}" if m else str(v)


def parse_changes(text: str, book: str) -> dict[str, list[dict]]:
    """CHANGES.md → 每章文本线各版本一行（按出现顺序）。只收「线」含「文本」且「旧→新」真升了版的行。"""
    out: dict[str, list[dict]] = {}
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip().replace("\\|", "|") for c in _SPLIT.split(line.strip())[1:-1]]
        if len(cells) < 6 or cells[0] == "日期":
            continue
        date, bv, lines_, change, note, pr = cells[:6]
        if "文本" not in lines_ or not bv.startswith(book + "/"):
            continue
        m = _CHANGE.match(change.replace(" ", ""))
        if not m:
            continue                      # 「0.1.1（不变）」这类不是新版本
        vol = vol_key(bv.split("/", 1)[1])
        new, old = m.group("new"), m.group("old")
        rev = _REV.search(note)
        cvv = _CV_VER.search(note)
        cvc = _CV_COMMIT.search(note)
        snap = _SNAP.search(note) or _SNAP_SHA.search(note)
        ops = _OP_ID.findall(note)
        if ops:
            kind = "revise"
        elif old is None or re.search(r"粗校完|首次|全册从原图重跑|单页重跑|重跑：", note):
            kind = "cv_export"
        else:
            kind = "manual"
        out.setdefault(vol, []).append({
            "text_version": new, "from": old, "date": date, "pr": pr or None,
            "rev": rev.group(1) if rev else None,
            "cv_version": cvv.group(1) if cvv else None,
            "cv_commit": cvc.group(1) if cvc else None,
            "snapshot": snap.group(1) if snap else None,
            "kind": kind, "opinions": ops or None, "note": note})
    return out


class BookText:
    """一本书在 book-text 里的文件。``root`` 是本地检出；为 None 时走 GitHub raw。"""

    def __init__(self, book: str, root: str | Path | None = None):
        self.book = book
        self.root = Path(root).expanduser() if root else None
        self._entry: str | None = None
        self._vdir: str | None = None

    def describe(self) -> str:
        return str(self.root) if self.root else GH_RAW

    def _read(self, rel: str) -> str | None:
        if self.root:
            p = self.root / rel
            return p.read_text(encoding="utf-8") if p.is_file() else None
        try:
            req = urllib.request.Request(f"{GH_RAW}/{rel}", headers={"user-agent": "open-guji-cv-opinions"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except Exception:          # noqa: BLE001 —— 404 或网络错都当没有
            return None

    def entry(self) -> str:
        if self._entry:
            return self._entry
        tail = "/".join(self.book[-3:]) + "/" + self.book
        for top in ("Book", "Work"):
            rel = f"{top}/{tail}"
            if self._read(f"{rel}/manifest.json") is not None:
                self._entry = rel
                return rel
        raise FileNotFoundError(f"book-text（{self.describe()}）里找不到条目 {self.book}")

    def version_dir(self) -> str:
        if self._vdir:
            return self._vdir
        man = json.loads(self._read(f"{self.entry()}/manifest.json") or "{}")
        key = next((v.get("key") for v in man.get("versions") or [] if v.get("is_original")), "default")
        self._vdir = f"{self.entry()}/{key}"
        return self._vdir

    def path(self, name: str) -> Path:
        if not self.root:
            raise RuntimeError("要本地 book-text 检出（--book-text）")
        return self.root / self.version_dir() / name

    def text(self, name: str) -> str | None:
        return self._read(f"{self.version_dir()}/{name}")

    def json(self, name: str):
        t = self.text(name)
        return json.loads(t) if t is not None else None

    def char(self, vol: str):
        return self.json(f"{vol_key(vol)}.char.json")

    def cord(self, vol: str):
        return self.json(f"{vol_key(vol)}.cord.json")

    def changes(self) -> str:
        return self.text("CHANGES.md") or ""

    def index(self) -> dict:
        return self.json("index.json") or {}


# ---- char／cord 的小工具 ----

def char_cells(char: dict) -> list[dict]:
    """按读序展开：[{a, c, page, col, lacuna?, guess?…}]。"""
    out = []
    for p in char.get("pages") or []:
        for col in p.get("columns") or []:
            for c in col.get("cells") or []:
                out.append(dict(c, page=p["page"], col=col["col"]))
    return out


def cord_page(cord: dict, page: int) -> dict | None:
    return next((p for p in cord.get("pages") or [] if p.get("page") == page), None)


def locate(op, store_versions: dict, bt: BookText | None) -> dict:
    """格号＋版本 → 当前格号、text_version、rev、快照（设计第三节 ``locate``）。

    第一阶段不做格号迁移：中间没有升过文本版本就原样；升过的，看校验字在当前文本里还对不对得上，
    对不上记 ``drift``，交人。字段缺的列进 ``missing``。"""
    t = op.target or {}
    vol = op.vol
    rows = store_versions.get(vol) or []
    res = {"opinion": op.id, "vol": vol, "cell": t.get("start"), "end": t.get("end"), "asked_at": None,
           "text_version": None, "current_version": None, "rev": None, "cv_version": None, "cv_commit": None,
           "snapshot": None, "since": [], "check": t.get("check"), "current_text": None, "drift": None, "missing": []}
    at = t.get("text_version")
    if not at and t.get("rev"):
        hit = next((r for r in rows if r.get("rev") == t["rev"]), None)
        at = hit["text_version"] if hit else None
        res["rev"] = t["rev"]
    res["asked_at"] = at
    # 该版本及以前最近一次有 rev／快照／cv 的行（手改版本沿用它所基于的那次导出）
    idx = next((i for i, r in enumerate(rows) if r["text_version"] == at), None)
    if idx is None and at:
        res["missing"].append(f"text_versions 里没有 {vol} {at}")
    upto = rows[: idx + 1] if idx is not None else []
    for k in ("rev", "cv_version", "cv_commit", "snapshot"):
        if not res.get(k):
            res[k] = next((r[k] for r in reversed(upto) if r.get(k)), None)
    if bt is not None:
        char = bt.char(vol)
        if char:
            res["current_version"] = char.get("version")
            cells = {c["a"]: c for c in char_cells(char)}
            seq = [c["a"] for c in char_cells(char)]
            s, e = t.get("start"), t.get("end")
            if s in cells and e in cells:
                i, j = seq.index(s), seq.index(e)
                res["current_text"] = "".join(cells[a]["c"] for a in seq[i:j + 1])
            if s and s in cells:
                page = cells[s]["page"]
                cord = bt.cord(vol)
                pg = cord_page(cord, page) if cord else None
                prod = ((pg or {}).get("producers") or {}).get("cv") or {}
                res["cord_producer"] = {k: prod.get(k) for k in ("rev", "pipeline", "snapshot") if prod.get(k)} or None
    res["text_version"] = res["current_version"] or (rows[-1]["text_version"] if rows else None)
    if idx is not None:
        res["since"] = [r["text_version"] for r in rows[idx + 1:]]
    if res["since"]:
        ok = res["check"] is None or res["current_text"] == res["check"]
        res["drift"] = None if ok else f"中间升过 {', '.join(res['since'])}，校验字 {res['check']} ≠ 现文 {res['current_text']}"
    elif res["check"] and res["current_text"] is not None and res["current_text"] != res["check"]:
        res["drift"] = f"校验字 {res['check']} ≠ 现文 {res['current_text']}（读者看到的不是这一版？）"
    prop = (op.proposal or {}).get("text")
    res["already"] = bool(prop and res["current_text"] == prop and res["check"] != prop)
    if res["already"]:
        res["drift"] = f"现文已是建议的「{prop}」（已改）"
    for k in ("rev", "snapshot", "cv_version"):
        if not res.get(k):
            res["missing"].append(k)
    return res


def default_book_text(arg: str | None) -> str | None:
    return arg or os.environ.get("GUJI_BOOK_TEXT")
