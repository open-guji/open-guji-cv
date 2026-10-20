# -*- coding: utf-8 -*-
"""`guji exit-check <册>`：一册文本出 1.0 时，出口动作逐项核（只读）。

M10 总设计 G8（`doc/design/M10-精校流程-总设计.md` §6；GUJI-685）。vol01 出 1.0.0 时漏了关 `proofing`、文本线
`review`、decision.json、残留阙文标记、冻结登记这几样；用户 10-20 定出口动作做成检查项，不写成说明文字。

查的是 **book-text 本章文件＋册 yaml 的冻结段**，不碰产物（产物新鲜由 close-check 1a 管）。各项：

| 号 | 查什么 |
|---|---|
| E1 | 文本线 ≥1.0.0 时，index 章条目的 `proofing` 不是 true |
| E2 | 文本线 ≥1.0.0 时，char.json 顶层有 `review`，含 date、signed_by、sample（M10 口径；VERSIONING 现只要求 ≥2） |
| E3 | 有 `NNN.decision.json`（可以没有条目） |
| E4 | char 里没有「标了 lacuna 却有字」的格 |
| E5 | 册 yaml 有 `freeze:`，写了 snapshot（或 manifest）、cv_commit、cv_version |
| E6 | 册 yaml 顶层 `cv_version` 与 `freeze.cv_version` 相同（版本护栏只认顶层） |
| E7 | `freeze.at` 等于当前文本版本（文本改了就要重新冻结，别只改 yaml 指针） |
| E8 | `freeze.cv_commit` 在某个 tag（`v*` 或 `freeze/*`）上，删分支后仍取得到 |

文本线 <1.0.0 时 E1、E2、E7 记「不适用」（`ok=None`），不算失败。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def _ver(s: str | None) -> tuple[int, ...]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(s or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _item(eid: str, name: str, ok: bool | None, detail: str = "") -> dict:
    return {"id": eid, "name": name, "ok": ok, "detail": detail}


def find_chapter(index: dict, chapter: str) -> dict | None:
    for ch in index.get("chapters", []):
        if str(ch.get("file")) == chapter or f"{int(ch.get('n', -1)):03d}" == chapter:
            return ch
    return None


def lacuna_with_char(char_doc: dict) -> list[str]:
    bad = []
    for page in char_doc.get("pages", []):
        for col in page.get("columns", []):
            for c in col.get("cells", []):
                if c.get("lacuna") and c.get("c") not in (None, "", "□", "〓"):
                    bad.append(f"{c.get('a')}={c.get('c')}")
    return bad


def tags_containing(repo: Path, commit: str) -> list[str] | None:
    """包含该提交、而且远端 origin 也有的 `v*`、`freeze/*` tag（只在本地打、没推上去的不算）；
    git 不可用或连不上远端返回 None。"""
    def git(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
    try:
        local = git("tag", "--contains", commit)
        remote = git("ls-remote", "--tags", "origin")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if remote.returncode != 0:
        return None
    if local.returncode != 0:
        return []
    on_remote = {ln.split("refs/tags/", 1)[1].removesuffix("^{}") for ln in remote.stdout.splitlines()
                 if "refs/tags/" in ln}
    return [t for t in local.stdout.split() if t.startswith(("v", "freeze/")) and t in on_remote]


def run(text_dir: Path, chapter: str, freeze: dict | None, cv_version: str | None,
        repo: Path | None = None, tag_lookup=tags_containing) -> dict:
    """返回 {chapter, text_version, items:[{id,name,ok,detail}], ok}。ok：没有一项是 False。"""
    text_dir = Path(text_dir)
    items: list[dict] = []
    index = json.loads((text_dir / "index.json").read_text(encoding="utf-8"))
    ch = find_chapter(index, chapter)
    if ch is None:
        raise FileNotFoundError(f"{text_dir}/index.json 里没有章 {chapter}")
    tv = ch.get("text_version")
    final = _ver(tv) >= (1, 0, 0)
    char_doc = json.loads((text_dir / ch.get("char_file", f"{chapter}.char.json")).read_text(encoding="utf-8"))

    if final:
        items.append(_item("E1", "proofing 已关", ch.get("proofing") is not True,
                           "" if ch.get("proofing") is not True else "index 章条目仍是 proofing: true"))
        rv = char_doc.get("review") or {}
        miss = [k for k in ("date", "signed_by", "sample") if not rv.get(k)]
        items.append(_item("E2", "文本线 review 记录", not miss,
                           "" if not miss else f"char.json 顶层 review 缺 {'、'.join(miss)}"))
    else:
        items.append(_item("E1", "proofing 已关", None, f"文本 {tv} <1.0.0，不适用"))
        items.append(_item("E2", "文本线 review 记录", None, f"文本 {tv} <1.0.0，不适用"))

    dec = text_dir / f"{chapter}.decision.json"
    items.append(_item("E3", "decision.json 存在", dec.exists(), "" if dec.exists() else f"没有 {dec.name}"))

    bad = lacuna_with_char(char_doc)
    items.append(_item("E4", "阙文标记与字一致", not bad,
                       "" if not bad else f"{len(bad)} 格标了 lacuna 却有字：{'、'.join(bad[:10])}"))

    fz = freeze or {}
    miss = [k for k in ("cv_commit", "cv_version") if not fz.get(k)]
    if not (fz.get("snapshot") or fz.get("manifest")):
        miss.insert(0, "snapshot")
    items.append(_item("E5", "冻结段完整", bool(fz) and not miss,
                       "册 yaml 没有 freeze:" if not fz else ("" if not miss else f"freeze 缺 {'、'.join(miss)}")))

    same = bool(fz.get("cv_version")) and str(cv_version or "") == str(fz.get("cv_version"))
    items.append(_item("E6", "顶层 cv_version 与冻结一致", same,
                       "" if same else f"顶层 cv_version={cv_version!r}，freeze.cv_version={fz.get('cv_version')!r}"))

    if final:
        at = str(fz.get("at") or "")
        items.append(_item("E7", "冻结对应当前文本版本", at == str(tv),
                           "" if at == str(tv) else f"freeze.at={at or '（空）'}，文本是 {tv}：文本改过就要重新冻结"))
    else:
        items.append(_item("E7", "冻结对应当前文本版本", None, f"文本 {tv} <1.0.0，不适用"))

    commit = fz.get("cv_commit")
    if not commit:
        items.append(_item("E8", "冻结代码在 tag 上", False, "freeze 没写 cv_commit"))
    else:
        tags = tag_lookup(repo or Path(__file__).resolve().parents[2], commit)
        if tags is None:
            items.append(_item("E8", "冻结代码在 tag 上", None, "git 或远端不可用，没查"))
        else:
            items.append(_item("E8", "冻结代码在 tag 上", bool(tags),
                               "、".join(tags[:5]) if tags else
                               f"{commit[:12]} 不在任何 v*／freeze/* tag 上（先 git fetch --tags；没有就打 freeze/ tag）"))

    return {"chapter": chapter, "text_version": tv, "items": items,
            "ok": all(it["ok"] is not False for it in items)}


def print_report(res: dict) -> None:
    print(f"出口检查 章 {res['chapter']}（文本 {res['text_version']}）")
    for it in res["items"]:
        mark = {True: "✓", False: "✗", None: "·"}[it["ok"]]
        print(f"  {mark} {it['id']} {it['name']}" + (f"：{it['detail']}" if it["detail"] else ""))
    print("机器项全过" if res["ok"] else "有未过的项")
