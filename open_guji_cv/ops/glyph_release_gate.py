"""字形库出版护栏：出 g<N>（`guji glyph-db snapshot`）和共享刻例库 `glyphlib-*`（`guji glyphlib build`）前必过的两项。

Sheldon 2026-11-04 定（ai-team `domain/CV/字形领域/长期规划与总览.md` 第八节）：体检里这两项算硬错，有就拒出；
体检的其余各项（离群、本书他字、他书、字体…）照旧出卡给人看，不拦出版。

1. **多字头实例**（`multi_glyph`）：同一个实例（同一张图）同时是两个不同字头的刻例。史記 g1 有 70 例
   （机器播种在错字下、人裁改对后旧字头下的刻例没撤，cv#893），匹配时两字 cov 完全并列，放行闸过不去。
2. **人裁×人裁冲突**（`human_conflict`）：库里互相矛盾的人裁。两种：
   - `human_misfiled`：人裁实例的字形标签（instances.label，即 shape）与它所在字头不同；
     （己已巳这类释读与字形分岔的窄类，admissions.char 是释读、label 是字形，按 label 比才不误报）
   - `human_dup`：同一张图（patch 字节相同）有两例人裁、给了不同的字。
   体检 `glyph_selfcheck` 里的 ``human_conflict``（人裁刻例在度量上更像另一个人裁字，殿本 g19 443 例）是形近嫌疑，
   要人看图，不在这里拦。

只读库，不在任何 Step 的 `code_deps` 里，改它不让各册过期。借来的实例（`borrowed` 表）和字体域不查：
借来库的问题由出那个库的人修，这里只报个数（``borrowed_multi_glyph``）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

#: 每类最多列出多少条样例（全部条数照记）
SAMPLE = 20


def _has_table(c, name: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _same_char(a: str, b: str) -> bool:
    """两字算不算同一个字：只认码位相同。书级 `codepoints` 归一在册配置里，库这一层看不到，不猜。"""
    return a == b


def check(db_path: str | Path) -> dict:
    """查 ``db_path`` 这份 glyph.db。返回 ``{"ok", "multi_glyph", "human_misfiled", "human_dup", ...}``，
    每类是 ``{"n": 条数, "sample": [...]}``；``ok`` 为三类都是 0。"""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
        borrowed = _has_table(c, "borrowed")
        own = ("i.instance_id NOT IN (SELECT instance_id FROM borrowed)" if borrowed else "1")
        nofont = "s.kind != 'font'"
        multi = c.execute(
            f"""SELECT e.instance_id, group_concat(DISTINCT g.char) FROM exemplars e
                JOIN glyphs g USING(glyph_id) JOIN instances i USING(instance_id) JOIN sources s USING(source_id)
                WHERE {own} AND {nofont}
                GROUP BY e.instance_id HAVING count(DISTINCT g.char) > 1 ORDER BY e.instance_id""").fetchall()
        b_multi = 0
        if borrowed:
            b_multi = c.execute(
                """SELECT count(*) FROM (SELECT e.instance_id FROM exemplars e JOIN glyphs g USING(glyph_id)
                   WHERE e.instance_id IN (SELECT instance_id FROM borrowed)
                   GROUP BY e.instance_id HAVING count(DISTINCT g.char) > 1)""").fetchone()[0]
        misfiled_raw = c.execute(
            f"""SELECT a.instance_id, i.label, g.char FROM admissions a
                JOIN exemplars e USING(instance_id) JOIN glyphs g USING(glyph_id)
                JOIN instances i USING(instance_id) JOIN sources s USING(source_id)
                WHERE a.provenance = 'human' AND i.label != g.char AND {own} AND {nofont}
                ORDER BY a.instance_id""").fetchall()
        dup = c.execute(
            f"""SELECT group_concat(a.instance_id, ' '), group_concat(DISTINCT i.label) FROM admissions a
                JOIN instances i USING(instance_id) JOIN sources s USING(source_id)
                WHERE a.provenance = 'human' AND {own} AND {nofont}
                GROUP BY i.patch_png HAVING count(DISTINCT i.label) > 1""").fetchall()
    misfiled = [r for r in misfiled_raw if not _same_char(r[1], r[2])]
    dup = [r for r in dup if not all(_same_char(r[1].split(",")[0], x) for x in r[1].split(","))]
    out = {
        "multi_glyph": {"n": len(multi), "sample": [{"instance": i, "chars": ch} for i, ch in multi[:SAMPLE]]},
        "human_misfiled": {"n": len(misfiled),
                           "sample": [{"instance": i, "label": a, "filed_under": g} for i, a, g in misfiled[:SAMPLE]]},
        "human_dup": {"n": len(dup), "sample": [{"instances": i.split(" "), "chars": ch} for i, ch in dup[:SAMPLE]]},
        "borrowed_multi_glyph": int(b_multi),
    }
    out["ok"] = not (out["multi_glyph"]["n"] or out["human_misfiled"]["n"] or out["human_dup"]["n"])
    return out


def summary(res: dict) -> str:
    """一行说明（拒出时的报错、清单里的记录）。"""
    parts = [f"多字头实例 {res['multi_glyph']['n']}", f"人裁归错字头 {res['human_misfiled']['n']}",
             f"同图人裁给了不同字 {res['human_dup']['n']}"]
    if res.get("borrowed_multi_glyph"):
        parts.append(f"（借来库里多字头 {res['borrowed_multi_glyph']}，不拦）")
    return "，".join(parts)


def enforce(db_path: str | Path, *, waive: str = "", what: str = "出版") -> dict:
    """查一遍；不过就 ``SystemExit``，除非给了 ``waive``（放行理由，记进结果）。返回结果（带 ``waived``）。"""
    res = check(db_path)
    if res["ok"]:
        return res
    if waive:
        return {**res, "waived": waive}
    first = (res["multi_glyph"]["sample"] or res["human_misfiled"]["sample"] or res["human_dup"]["sample"])[:3]
    raise SystemExit(f"字形库{what}护栏没过：{summary(res)}。样例 {first}。"
                     f"先清理（见 ai-team domain/CV/经验.md「史記 g2：清理双字头刻例」），"
                     f"确要照出就加 --gate-waive \"理由\"")
