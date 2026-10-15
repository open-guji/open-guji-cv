#!/usr/bin/env python3
"""窗口后新放行格看图清单（GUJI-72，Emi，2026-10-14；按 Elena 评审 208el §四 P1–P6 改，再按 208fb 复审三条改）。

输入：两份 cell table（`volNN_*.jsonl[.gz]`，首行是册头，之后每格一行；字段见 `项目进展/CV放行规则/计划/数据位置.md`）。
  --base   基线 = Eden 口径的零臂产物（A0／A-br：同 main yaml、同缓存、同 cv commit），不用沙箱 `volNN_base` 原件。
  --arm    窗口 A 臂产物（main yaml 原样）。
  --remap  可选；hint_ignore_dash 等改格框的页用。TSV，每行「旧格号⇥新格号」，新格号留空＝已删。
           基线格号先经它映射，再与 A 臂对位。多个旧号映到同一新号（多对一）时取「任一为放行则放行」，碰撞数写进摘要。
           同号碰撞（208ho）：新号同时被改号的旧格和 B 里未映射的同号格占用时不合并，未映射的那格去掉，对应 A 格按无对位进清单，摘要单列「同号碰撞」并打印格号。
           208ix：逐条状态写进 同号碰撞.tsv（旧号、未映射同号格各自基线放行、A 臂放行、是否进看图清单）；
           remap 自检报警：新号被改号旧格占用、而 B 未映射同号格也占用（且 N 不在旧键里）时 stderr 报警。
           同号碰撞的 A 格一律进全看层。
           cell table 没有 bbox 字段，位置对位须由产出 remap 的一方给出（hint 页：Ethan 或 Eden 的 remap_gold）。

新放行格 = A 臂 admit 为真，且（对位后的）基线 admit 不为真。
  A 臂有、对不上基线的格：记为「无对位」，**仍进看图清单**，不静默丢。
  无对位超线即停（退出码 4）：阈值 = min(20, 5% × A 臂放行格数)，超过则要先补 remap 再跑。
红线（Eden 全局 2，十格，v2.14.2）：只检查 A 臂表里出现的册（红线格的册在 A 臂里有任一格即算「本册」）：
  · 本册的红线格有任一在 A 臂或（对位后的）基线里找不到 → 停（退出码 3），逐个列出，不静默通过；
  · 本册的红线格有任一在基线里已是放行（不是待审）→ 停（退出码 3）；
  · 本册的红线格有任一从待审变放行 → 停（退出码 3）。
  不在 A 臂册内的红线格不停线，逐条列为「本次未检」；只要有未检的，摘要首行写「红线未全覆盖，不得报 0」。
  合并总跑必须覆盖十格全部，才能报「红线 0」。红线集合为空＝停线（退出码 3），不回落到全局十格。
  其余新放行格的停线只有一条：看图为错 → 该规则（该册）退出，不由脚本判。
分层：`--force-all` 名单里的格归「force」层（强制全看，不抽）；否则 provenance 含 hint／juan_rule 归该层；都不含归 other。
  force、hint 与 juan_rule 层**全看**（不抽）；other 层按册各取 `--quota` 格，按 sha256(seed|格号) 升序。
  注：208gc 干跑核实，vol05 A 臂 provenance 里**没有** hint 标记（只有 match／rare_ref／context／witness3／seal／iron／coord_fallback 等），
  hint 格要靠 `--force-all` 名单进全看层，不能只靠 provenance。
  `--force-all` 名单（每行一个格号，`#` 开头为注释）里不在新放行总体的格不计入：基线同号未放行的列为「已忽略」；基线同号已放行的单列为「强制名单但基线同号已放行：对位待核」（208gk），逐格列出。
  other 层里来源串非空的格计为「未认出」（provenance 写法可能没认上），摘要里逐串列出。
variant_tie 不在新放行总体里；基线带 variant_tie、A 臂待审的格另列「回退集」（退出 variant_tie 时的看图对象）。
取法：总体 ≤ --max-total（缺省 60）则全看；超过则 force＋hint＋juan_rule 全进清单、other 按册抽 quota；
  force＋hint＋juan_rule 本身超过上限，或抽样后总数仍超上限，退出码 2（需人定：调高上限或收窄规则）。抽样只是超上限时的补充，不替代逐格看图。

输出（`--out` 目录）：
  抽样.tsv        模式｜层｜秩｜册｜格号｜对位｜红线｜放行字｜来源串（模式为「全看」或「抽样」）
  cells.txt       每行一格，格式同 overlay_review.py 的 `--cells`，可直接喂它出联系页
  回填.tsv        表头：格号｜放行字｜看图判读（对／错／不定）｜备注；判读列留空
  回退.tsv        回退集（variant_tie 退出时待审的格），表头同 抽样.tsv 的格式去掉模式列
  回退cells.txt   回退集的 cells 文件
  摘要.md         总体、分层分册计数、对位、无对位阈值、多对一碰撞、红线、回退集、other 未认出串、种子、输入路径、脚本路径

用法：
  python sample_newadmit.py --base <零臂表> --arm <A臂表> --out <目录> \\
        [--remap <对位表.tsv>] [--force-all <格号名单.txt>] [--seed 20261014] [--quota 5] [--max-total 60] [--source-field provenance]
  python sample_newadmit.py --selftest     # 造假数据自测，不读真书

退出码：0 正常；1 自测失败；2 超上限；3 红线停线（本册缺失／已放行／从待审变放行，或红线集合为空）；4 无对位超线（先补 remap）。
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LAYERS = ("force", "hint", "juan_rule", "other")
RULE_NAMES = ("hint", "juan_rule")
FULL_LAYERS = ("force",) + RULE_NAMES  # 全看（不抽）的层
RETREAT_RULE = "variant_tie"
# Eden 全局 2，红线十格（窗口甲当日剧本 v2.14.2：原九格＋第十格 vol05:108:2:20；Ezio 208lu、Ethan 208lt 再补二；以剧本原文为准）
# 与 S26_force名单.py 的 REDLINE 同集合；自测十六之二守住两边不漂
RED_LINE = frozenset({
    "vol02:15:9:20", "vol02:188:4:20", "vol05:154:8:21", "vol06:149:1:21", "vol04:217:2:15",
    "vol06:18:9:21", "vol04:220:4:4", "vol04:23:1:3", "vol04:79:7:11",
    "vol05:108:2:20",
})
SEED_DEFAULT = 20261014
QUOTA_DEFAULT = 5
MAX_TOTAL_DEFAULT = 60
NOMATCH_CAP = 20          # 无对位报警线的绝对上限（格）
NOMATCH_RATE = 0.05       # 无对位报警线的比例：A 臂放行格数的 5%；取两者较小者
COLLIDE_SHOW = 20         # 摘要里逐个列出的碰撞新号上限


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def read_table(path: Path) -> dict:
    rows = {}
    with open_text(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "id" not in obj:  # 册头行
                continue
            rows[obj["id"]] = obj
    return rows


def load_remap(path) -> dict:
    remap = {}
    if not path:
        return remap
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        old, _, new = line.partition("\t")
        remap[old.strip()] = new.strip()
    return remap


def cell_states(pairs) -> str:
    return "、".join(f"{i}={'放行' if a else '待审'}" for i, a in pairs)


def collision_detail(base: dict, remap: dict) -> list:
    """208ix：逐条列出同号碰撞，判定与 apply_remap 相同。同时作为 remap 自检：
    某新号 N 被 remap 的旧号（旧≠N）占用，而 B 基线里另有未映射的同号格 N（N 不在旧键里）→ 一条。
    每条：{"new": N, "olds": [(旧号, 基线放行)], "plain": [(B 未映射同号格, 基线放行)]}。
    remap 里把 N 也列为旧键（含空映射＝已删）则不报，因为 B 的 N 已被显式处理。"""
    by_new = collections.defaultdict(list)
    for cid, row in base.items():
        new = remap.get(cid, cid)
        if new:
            by_new[new].append(row)
    detail = []
    for new in sorted(by_new):
        rows = by_new[new]
        remapped = [r for r in rows if r["id"] in remap and r["id"] != new]
        plain = [r for r in rows if r["id"] not in remap]
        if remapped and plain:
            detail.append({"new": new,
                           "olds": [(r["id"], bool(r.get("admit"))) for r in remapped],
                           "plain": [(r["id"], bool(r.get("admit"))) for r in plain]})
    return detail


def apply_remap(base: dict, remap: dict):
    """返回 (映射后的表, 多对一新号列表, 同号碰撞格号列表)。
    多对一：任一旧格放行则新格放行；取放行的那条的字段。
    同号碰撞（208ho）：新号 N 同时被「remap 到它的旧号」与「B 里不在 remap 键中的同号格 N」占用。
    这是两个物理格，不合并：保留 remap 那条，未映射的 N 格从表中去掉，列入碰撞格号；
    调用方须把对应 A 臂格按「无对位」处理、进看图清单。"""
    groups = collections.defaultdict(list)
    for cid, row in base.items():
        new = remap.get(cid, cid)
        if not new:  # 已删
            continue
        groups[new].append(row)
    out, collided = {}, []
    for new, rows in groups.items():
        remapped = [r for r in rows if r["id"] in remap and r["id"] != new]
        plain = [r for r in rows if r["id"] not in remap]  # 未映射的同号格（plain 的 id 必等于 new）
        if remapped and plain:
            rows = remapped
        if len(rows) > 1:
            collided.append(new)
        admitted = [r for r in rows if r.get("admit")]
        src = admitted[0] if admitted else rows[0]
        out[new] = dict(src, id=new, admit=bool(admitted))
    colliding = sorted(p[0] for d in collision_detail(base, remap) for p in d["plain"])
    return out, sorted(collided), colliding


FORCE_CID = re.compile(r"vol\d{2}:\d+:\d+:-?\d+[ab]?")  # 208kg：与红线集合、S26 输出的格号形态一致；208kq 再补七：与 feedback/anchor.py 的 _KEY 一致，允许 a/b 后缀（hint 27 格的 remap 形态）


def read_force(path):
    """返回 (合法格号集合, 格式不合的行 [(行号, 原文)])。`#` 之后为行内注释（208kd）。"""
    cids, bad = set(), []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        cid = s.split("#", 1)[0].split("\t")[0].strip()
        if FORCE_CID.fullmatch(cid):
            cids.add(cid)
        else:
            bad.append((n, s))
    return frozenset(cids), bad


def layer_of(row: dict, field: str, cid: str = "", force=frozenset()) -> str:
    if cid in force:
        return "force"
    text = str(row.get(field) or "")
    for name in RULE_NAMES:
        if name in text:
            return name
    return "other"


def vol_of(cid: str) -> str:
    return cid.split(":", 1)[0]


def sort_key(seed: int, cell_id: str) -> str:
    return hashlib.sha256(f"{seed}|{cell_id}".encode("utf-8")).hexdigest()


def classify(base: dict, arm: dict, field: str, red, force=frozenset(), colliding=frozenset()) -> tuple:
    pop = []
    for cid in sorted(arm):
        row = arm[cid]
        if not row.get("admit"):
            continue
        b = base.get(cid)
        if cid in colliding:  # 同号碰撞（208ho）：不沿用基线同号状态，一律无对位、进清单
            b = None
        elif b is not None and b.get("admit"):
            continue
        pop.append({
            "cid": cid,
            "layer": layer_of(row, field, cid, force),
            "vol": vol_of(cid),
            "matched": b is not None,
            "red": cid in red,
            "char": row.get("char", ""),
            "src": str(row.get(field) or ""),
        })
    retreat = []
    for cid in sorted(base):
        b = base[cid]
        if b.get("admit") and RETREAT_RULE in str(b.get(field) or "") and not arm.get(cid, {}).get("admit"):
            retreat.append({"cid": cid, "char": b.get("char", ""), "src": str(b.get(field) or "")})
    return pop, retreat


def red_check(base: dict, arm: dict, red) -> tuple:
    """红线格的停线检查（只管 A 臂表里出现的册）。返回 (需停线的说明行, 本次未检的红线格)。空说明行＝通过。"""
    problems, unchecked = [], []
    arm_vols = {vol_of(c) for c in arm}
    for cid in sorted(red):
        if vol_of(cid) not in arm_vols:
            unchecked.append(cid)
            continue
        if cid not in arm or cid not in base:
            where = "A 臂" if cid not in arm else "基线（对位后）"
            problems.append(f"{cid}：{where}表里找不到，无法核是否从待审变放行（须人工确认）")
        elif base[cid].get("admit"):
            problems.append(f"{cid}：基线里已是放行，不是待审（须人工确认）")
        elif arm[cid].get("admit"):
            problems.append(f"{cid}：从待审变放行")
    return problems, unchecked


def pick(pop: list, seed: int, quota: int, max_total: int):
    order = lambda p: (LAYERS.index(p["layer"]), p["vol"], p["cid"])
    if len(pop) <= max_total:
        return "全看", sorted(pop, key=order)
    full = [p for p in pop if p["layer"] in FULL_LAYERS]
    if len(full) > max_total:
        raise OverflowError(f"force＋hint＋juan_rule 全看需 {len(full)} 格，超过上限 {max_total}（需人定：调高上限或收窄规则）")
    strata = collections.defaultdict(list)
    for p in pop:
        if p["layer"] == "other":
            strata[p["vol"]].append(p)
    chosen = list(full)
    for vol in sorted(strata):
        cells = sorted(strata[vol], key=lambda p: sort_key(seed, p["cid"]))
        chosen.extend(cells[:quota])
    if len(chosen) > max_total:
        raise OverflowError(f"分层抽样后仍有 {len(chosen)} 格，超过上限 {max_total}；请调低 --quota")
    return "抽样", sorted(chosen, key=order)


def nomatch_limit(arm: dict) -> float:
    a_admit = sum(1 for r in arm.values() if r.get("admit"))
    return min(NOMATCH_CAP, NOMATCH_RATE * a_admit)


def write_outputs(out: Path, args, mode, chosen, pop, retreat, paths, info):
    out.mkdir(parents=True, exist_ok=True)
    ranks = collections.Counter()
    tsv = ["模式\t层\t秩\t册\t格号\t对位\t红线\t放行字\t来源串"]
    cells, back = [], ["格号\t放行字\t看图判读(对/错/不定)\t备注"]
    for p in chosen:
        ranks[p["layer"]] += 1
        rank = ranks[p["layer"]]
        tsv.append("\t".join([
            mode, p["layer"], str(rank), p["vol"], p["cid"],
            "有" if p["matched"] else "无", "是" if p["red"] else "否", p["char"], p["src"],
        ]))
        cells.append(f"{p['cid']}  # {mode} {p['layer']} #{rank}")
        back.append(f"{p['cid']}\t{p['char']}\t\t")
    (out / "抽样.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
    (out / "cells.txt").write_text("\n".join(cells) + "\n", encoding="utf-8")
    (out / "回填.tsv").write_text("\n".join(back) + "\n", encoding="utf-8")

    rt = ["格号\t放行字\t来源串"] + [f"{r['cid']}\t{r['char']}\t{r['src']}" for r in retreat]
    (out / "回退.tsv").write_text("\n".join(rt) + "\n", encoding="utf-8")

    # 208ix：同号碰撞逐条进看图清单伴随表（旧号们与各自基线放行状态、A 臂状态、是否已进清单）
    cl = ["新号\t映到它的旧号（基线状态）\tB 未映射同号格（基线状态）\tA 臂放行\t进看图清单"]
    for d, arm_adm, listed in info["detail_rows"]:
        cl.append("\t".join([d["new"], cell_states(d["olds"]), cell_states(d["plain"]),
                             "是" if arm_adm else "否", "是" if listed else "否"]))
    (out / "同号碰撞.tsv").write_text("\n".join(cl) + "\n", encoding="utf-8")
    (out / "回退cells.txt").write_text(
        "".join(f"{r['cid']}  # 回退 variant_tie\n" for r in retreat), encoding="utf-8")

    other_pop = [p for p in pop if p["layer"] == "other"]
    unrec = [p for p in other_pop if p["src"]]
    unrec_count = collections.Counter(p["src"] for p in unrec)
    limit = info["limit"]
    collided = info["collided"]

    red_unchecked = info["red_unchecked"]
    md = (["红线未全覆盖，不得报 0：本次未检 " + "、".join(red_unchecked)] if red_unchecked else []) + [
        "# 看图清单摘要",
        "",
        f"- 模式：**{mode}**（总体 {len(pop)}，上限 {args.max_total}）"
        + ("：全看，每个新放行格都看" if mode == "全看"
           else "：超上限，force／hint／juan_rule 全看，other 按册抽样，不替代逐格看图"),
        f"- 进看图清单：{len(chosen)} 格",
        f"- 种子：{args.seed}；other 层每册上限：{args.quota}（仅抽样模式用）",
        f"- 来源字段：`{args.source_field}`",
        f"- 基线：`{paths['base']}`（须为零臂产物，见方案 §一）",
        f"- A 臂：`{paths['arm']}`",
        f"- 对位表：`{paths['remap'] or '（未给，按格号对位）'}`",
        f"- 强制全看名单：`{paths['force_all'] or '（未给）'}`",
        f"- 多对一碰撞（多个旧号映到同一新号，取「任一为放行则放行」）：{len(collided)} 个新号"
        + (f"：{', '.join(collided[:COLLIDE_SHOW])}" + ("…" if len(collided) > COLLIDE_SHOW else "") if collided else ""),
        f"- 同号碰撞（208ho）：{len(info['colliding'])} 格"
        + (f"：{', '.join(info['colliding'])}（未合并；B 侧未映射的同号格已去掉，对应 A 格按无对位进清单；"
           f"逐条状态与是否进清单见 同号碰撞.tsv）" if info["colliding"] else "")
        + "；计入停线（208hv 方案 A）",
        f"- 无对位格（A 臂放行，按格号／对位表对不上基线，不含同号碰撞）：{info['n_nomatch']}，报警线 {limit:.1f}",
        f"- 停线合计（无对位＋同号碰撞）：{info['unmatched']}，报警线 {limit:.1f}（超线才停，阈值 min(20, 5%×放行数) 不变）"
        f"（min({NOMATCH_CAP}, {NOMATCH_RATE:.0%}×A 臂放行格数)；超线即停，退出码 4）。已计入总体、进看图清单，不算错",
        f"- 红线：{'本册内齐全，且均为待审、未从待审变放行' if not info['red_problems'] else '有问题，见下'}"
        + ("" if not info["red_problems"] else "：" + "；".join(info["red_problems"]))
        + (f"；本次未检 {len(red_unchecked)} 格（不在 A 臂册内，不停线）：{'、'.join(red_unchecked)}" if red_unchecked else ""),
        f"- 强制全看名单（--force-all）：{info['force_n']} 格；其中不在新放行总体、已忽略 {len(info['force_ignored'])} 格"
        + (f"：{'、'.join(info['force_ignored'][:COLLIDE_SHOW])}" if info["force_ignored"] else ""),
        f"- 格式不合（--force-all）：{len(info['force_bad'])} 行，未计入名单，须修正后重跑（退出码 5）"
        + (f"：{'；'.join('第 ' + str(n) + ' 行「' + s + '」' for n, s in info['force_bad'][:COLLIDE_SHOW])}" if info["force_bad"] else ""),
        f"- 回退集（variant_tie 退出时：基线带 variant_tie 放行、A 臂待审）：{len(retreat)} 格，另列，不计入新放行总体（见 回退.tsv）",
        f"- 脚本：`{Path(__file__).as_posix()}`",
        "",
        "| 层 | 册 | 新放行总数 | 进看图清单 |",
        "|---|---|---|---|",
    ]
    pop_c = collections.Counter((p["layer"], p["vol"]) for p in pop)
    chosen_c = collections.Counter((p["layer"], p["vol"]) for p in chosen)
    for key in sorted(pop_c, key=lambda k: (LAYERS.index(k[0]), k[1])):
        md.append(f"| {key[0]} | {key[1]} | {pop_c[key]} | {chosen_c[key]} |")
    md += [
        "",
        f"- other 层 {len(other_pop)} 格：来源串为空 {len(other_pop) - len(unrec)}；"
        f"来源串非空但未含 hint／juan_rule（**provenance 写法可能没认出，须核**）{len(unrec)}",
    ]
    for src, n in unrec_count.most_common(20):
        md.append(f"  - `{src}` × {n}")
    if info["force_base_admit"]:
        md += ["", "## 强制名单但基线同号已放行：对位待核", "",
               "以下格在 --force-all 名单里，基线同号已是放行，不在新放行总体，未进看图清单；须人核对位后再定去留：", ""]
        md += [f"- `{c}`" for c in info["force_base_admit"]]
    (out / "摘要.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return len(unrec)


def run(args) -> int:
    base_raw = read_table(Path(args.base))
    arm = read_table(Path(args.arm))
    remap = load_remap(args.remap)
    detail = collision_detail(base_raw, remap)
    base, collided, colliding = apply_remap(base_raw, remap)
    if colliding:
        print(f"同号碰撞 {len(colliding)} 格（未合并，按无对位进看图清单）：{', '.join(colliding)}", file=sys.stderr)
    for d in detail:
        print(f"remap 自检报警（208ix）：新号 {d['new']} 被 remap 旧号 {cell_states(d['olds'])} 占用，"
              f"B 基线未映射的同号格 {cell_states(d['plain'])} 也占用；已按同号碰撞处理（未合并，对应 A 格进无对位）",
              file=sys.stderr)
    red = RED_LINE if getattr(args, "red", None) is None else args.red
    if not red:
        print("停线：红线集合为空，不得跳过红线检查（不回落到全局十格，也不放行）。", file=sys.stderr)
        return 3

    red_problems, red_unchecked = red_check(base, arm, red)
    if red_problems:
        print("停线：红线检查未过：", file=sys.stderr)
        for line in red_problems:
            print("  " + line, file=sys.stderr)
        return 3

    force, force_bad = read_force(args.force_all) if getattr(args, "force_all", None) else (frozenset(), [])
    for n, text in force_bad:
        print(f"force 第 {n} 行格式不合：{text}", file=sys.stderr)
    # 208ix：同号碰撞的 A 格一律进全看层（看图清单必有），不靠抽样
    pop, retreat = classify(base, arm, args.source_field, red, force | frozenset(colliding), frozenset(colliding))
    pop_ids = {p["cid"] for p in pop}
    force_missing = sorted(force - pop_ids)
    # 强制名单里基线同号已放行的格：不算「已忽略」，单列待对位核（208gk）
    force_base_admit = [c for c in force_missing if base.get(c, {}).get("admit")]
    force_ignored = [c for c in force_missing if not base.get(c, {}).get("admit")]
    unmatched = [p for p in pop if not p["matched"]]
    # 208hv（Mila 定方案 A）：同号碰撞计入停线分子，无对位与碰撞合计过线即停；阈值不改
    n_collide = sum(1 for p in unmatched if p["cid"] in colliding)
    n_nomatch = len(unmatched) - n_collide
    limit = nomatch_limit(arm)
    if len(unmatched) > limit:
        kinds = f"无对位 {n_nomatch} 格、同号碰撞 {n_collide} 格，合计 {len(unmatched)}"
        print(f"停线：{kinds}，超过报警线 {limit:.1f}。"
              "请由 remap 产出方（Ethan／Eden）补对位表后重跑，不得默认放进清单。", file=sys.stderr)
        return 4
    try:
        mode, chosen = pick(pop, args.seed, args.quota, args.max_total)
    except OverflowError as e:
        print(str(e), file=sys.stderr)
        return 2
    in_list = {p["cid"] for p in chosen}
    detail_rows = [(d, bool(arm.get(d["new"], {}).get("admit")), d["new"] in in_list) for d in detail]
    paths = {"base": args.base, "arm": args.arm, "remap": args.remap, "force_all": getattr(args, "force_all", None)}
    info = {"unmatched": len(unmatched), "n_nomatch": n_nomatch, "n_collide": n_collide,
            "limit": limit, "collided": collided, "colliding": colliding,
            "red_problems": red_problems,
            "red_unchecked": red_unchecked, "force_n": len(force), "force_ignored": force_ignored,
            "force_base_admit": force_base_admit, "detail_rows": detail_rows,
            "force_bad": force_bad}
    unrec = write_outputs(Path(args.out), args, mode, chosen, pop, retreat, paths, info)
    print(f"已写入 {args.out}：模式 {mode}，总体 {len(pop)}，进清单 {len(chosen)} 格，回退集 {len(retreat)} 格，"
          f"无对位 {n_nomatch}、同号碰撞 {n_collide}（合计 {len(unmatched)}，报警线 {limit:.1f}），多对一碰撞 {len(collided)} 个新号，"
          f"同号碰撞 {len(colliding)} 格")
    if unrec:
        print(f"提示：other 层有 {unrec} 格来源串非空但未含规则名，请核 provenance 写法（摘要.md 列出）", file=sys.stderr)
    if force_bad:
        print(f"停线：强制名单有 {len(force_bad)} 行格式不合，已写出但不可直接用，修正名单后重跑（退出码 5）。", file=sys.stderr)
        return 5
    return 0


def selftest() -> int:
    import types

    st = [7]  # 造数据用的伪随机，只为可重复；与抽样用的哈希无关

    def rnd():
        st[0] = (st[0] * 1103515245 + 12345) % (2**31)
        return st[0] / (2**31)

    tags = ["hint:oversplit", "juan_rule", "variant_tie:21", "match_ref", ""]
    base_rows, arm_rows = {}, {}
    for i in range(300):
        cid = f"vol0{i % 2}:{i // 20 + 1}:{i % 20 + 1}:{i % 7 + 1}"
        b = rnd() < 0.3
        a = (rnd() < 0.95) if b else (rnd() < 0.9)
        base_rows[cid] = {"id": cid, "admit": b, "char": "甲", "provenance": tags[int(rnd() * 5)] if b else ""}
        arm_rows[cid] = {"id": cid, "admit": a, "char": "甲", "provenance": tags[int(rnd() * 5)]}
    for k in range(3):  # 只在 A 臂出现的格（无对位）
        cid = f"vol00:99:{k + 1}:1"
        arm_rows[cid] = {"id": cid, "admit": True, "char": "乙", "provenance": "juan_rule"}
    base_rows["vol00:99:9:9"] = {"id": "vol00:99:9:9", "admit": False, "char": "丙", "provenance": ""}

    # 假红线十格：基线与 A 臂都是待审（真红线格在基线里也是待审），让停线检查通过；造假数据，不是真书的红线格。
    # 取末尾十个 vol01 格，避开小总体会放行的前十个 vol00 基线待审格
    pending_both = sorted(c for c in arm_rows if c in base_rows and not base_rows[c]["admit"] and not arm_rows[c]["admit"])
    FAKE_RED = frozenset(pending_both[-10:])
    TEST_MAX = 150  # 假数据新放行约 196 格：超过 TEST_MAX 才会走抽样

    # 小总体：A 臂只在前 10 个基线待审格上放行，其余基线待审格不放行
    small_rows = {}
    base_false = sorted(c for c in base_rows if not base_rows[c]["admit"] and c in arm_rows)
    keep = set(base_false[:10])
    for cid, row in arm_rows.items():
        r = dict(row)
        if cid in base_false:
            r["admit"] = cid in keep
        small_rows[cid] = r

    # 无对位超线：在 A 臂再加 40 个只在 A 臂放行的格
    over_rows = dict(arm_rows)
    for k in range(40):
        cid = f"vol00:97:{k + 1}:1"
        over_rows[cid] = {"id": cid, "admit": True, "char": "丁", "provenance": "hint:oversplit"}

    ok_all = True

    def check(label, cond):
        nonlocal ok_all
        print(f"  {label}：{'OK' if cond else 'FAIL'}")
        ok_all = ok_all and cond

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)

        def dump(name, rows, gz=False):
            lines = [json.dumps({"GUJI_PRODUCTS_DIR": "FAKE", "params_hash": "FAKE"})]
            lines += [json.dumps(r, ensure_ascii=False) for _, r in sorted(rows.items())]
            text = "\n".join(lines) + "\n"
            p = tdp / name
            if gz:
                p.write_bytes(gzip.compress(text.encode("utf-8")))
            else:
                p.write_text(text, encoding="utf-8")
            return str(p)

        base_p = dump("base.jsonl", base_rows)
        arm_p = dump("arm.jsonl.gz", arm_rows, gz=True)
        small_p = dump("arm_small.jsonl.gz", small_rows, gz=True)
        over_p = dump("arm_over.jsonl.gz", over_rows, gz=True)
        remap_p = tdp / "remap.tsv"
        remap_p.write_text("vol00:99:9:9\tvol00:99:1:1\n", encoding="utf-8")

        # 多对一：两个旧号映到同一新号；c1 基线放行、c2 基线待审 → 合并后应放行
        c1 = next(c for c in sorted(base_rows) if base_rows[c]["admit"] and c not in FAKE_RED)
        c2 = next(c for c in sorted(base_rows) if not base_rows[c]["admit"] and c not in FAKE_RED and c != c1)
        coll_p = tdp / "remap_coll.tsv"
        coll_p.write_text(f"{c1}\tvol01:98:1:1\n{c2}\tvol01:98:1:1\n", encoding="utf-8")

        def args_for(out, **kw):
            d = dict(base=base_p, arm=arm_p, out=str(tdp / out), remap=None, seed=SEED_DEFAULT,
                     quota=QUOTA_DEFAULT, max_total=TEST_MAX, source_field="provenance", red=FAKE_RED)
            d.update(kw)
            return types.SimpleNamespace(**d)

        base_tbl = read_table(Path(base_p))
        arm_tbl = read_table(Path(arm_p))
        print("== 自测一：大总体（约 200 格新放行，超上限，应抽样）；造假数据，非真书")
        print("  无对位格（仅 A 臂有）：应为 3")
        pop, retreat = classify(apply_remap(base_tbl, {})[0], arm_tbl, "provenance", FAKE_RED)
        unmatched = sum(1 for p in pop if not p["matched"])
        check(f"无对位计数 {unmatched}", unmatched == 3)
        check(f"总体 {len(pop)} 超过上限 {TEST_MAX}", len(pop) > TEST_MAX)
        rc = run(args_for("run1"))
        check("退出码 0", rc == 0)
        chosen = [l.split("\t") for l in (tdp / "run1" / "抽样.tsv").read_text(encoding="utf-8").splitlines()[1:]]
        check("模式为抽样", all(r[0] == "抽样" for r in chosen))
        base_map = apply_remap(base_tbl, {})[0]
        check("抽中的格都在新放行集合内（基线待审、A 臂放行）",
              all(not base_map.get(r[4], {}).get("admit") and arm_tbl[r[4]].get("admit") for r in chosen))
        others = [r for r in chosen if r[1] == "other"]
        per_vol = collections.Counter(r[3] for r in others)
        check("other 层每册不超过 quota", all(v <= QUOTA_DEFAULT for v in per_vol.values()))
        check("hint／juan_rule 层全部进清单",
              sum(1 for p in pop if p["layer"] in RULE_NAMES) == sum(1 for r in chosen if r[1] in RULE_NAMES))
        check("每个非空（层，册）至少 1 格", set((r[1], r[3]) for r in chosen) == {(p["layer"], p["vol"]) for p in pop})
        check("仅 A 臂有的格（无对位）也进清单", any(r[5] == "无" for r in chosen))
        for name in ("抽样.tsv", "cells.txt", "回填.tsv", "回退.tsv", "回退cells.txt", "摘要.md"):
            run(args_for("run2"))
            same = (tdp / "run1" / name).read_bytes() == (tdp / "run2" / name).read_bytes()
            check(f"复跑逐字节一致 {name}", same)
        check("回退集条数与 回退.tsv 一致", len(retreat) == len((tdp / "run1" / "回退.tsv").read_text(encoding="utf-8").splitlines()) - 1)
        check("回退集都是基线放行、带 variant_tie、A 臂待审",
              all(base_map[r["cid"]].get("admit") and "variant_tie" in str(base_map[r["cid"]].get("provenance"))
                  and not arm_tbl.get(r["cid"], {}).get("admit") for r in retreat))

        print("== 自测二：小总体（≤上限，应全看）＋对位表")
        rc = run(args_for("run3", arm=small_p, remap=str(remap_p)))
        check("退出码 0", rc == 0)
        pop2, _ = classify(apply_remap(base_tbl, load_remap(str(remap_p)))[0], read_table(Path(small_p)),
                           "provenance", FAKE_RED)
        mode_line = (tdp / "run3" / "摘要.md").read_text(encoding="utf-8").splitlines()[2]
        check("模式为全看", "全看" in mode_line)
        check("全看时清单＝总体", len(pop2) == sum(1 for _ in (tdp / "run3" / "抽样.tsv").read_text(encoding="utf-8").splitlines()) - 1)
        check("对位表把基线 vol00:99:9:9 对到 vol00:99:1:1（不再算无对位）",
              all(p["matched"] for p in pop2 if p["cid"] == "vol00:99:1:1") and
              not any(p["cid"] == "vol00:99:1:1" and not p["matched"] for p in pop2))

        print("== 自测三：红线缺失（本册内）→ 退出码 3（假红线里混一个 vol00 册内不存在的 id）")
        rc = run(args_for("run7", red=set(FAKE_RED) | {"vol00:1:999:1"}))
        check("退出码 3", rc == 3)

        print("== 自测四：多对一映射碰撞有计数；任一为放行则放行")
        merged, collided_ids, _ = apply_remap(base_tbl, load_remap(str(coll_p)))
        check(f"碰撞新号数 {len(collided_ids)}（应为 1）", collided_ids == ["vol01:98:1:1"])
        check("合并后新号放行（c1 基线放行，c2 待审）", merged["vol01:98:1:1"].get("admit") is True)
        rc = run(args_for("run8", remap=str(coll_p)))
        check("退出码 0", rc == 0)
        sm = (tdp / "run8" / "摘要.md").read_text(encoding="utf-8")
        check("摘要写出多对一碰撞计数 1", "多对一碰撞（多个旧号映到同一新号，取「任一为放行则放行」）：1 个新号" in sm)

        print("== 自测十三（208ho）：同号碰撞——未映射的同号格不合并，对应 A 格进无对位清单")
        def row(cid, admit):
            return {"id": cid, "admit": admit, "char": "字", "provenance": "match"}
        cb = {"v:1:1:1": row("v:1:1:1", True), "v:1:1:2": row("v:1:1:2", False),
              "v:1:1:3": row("v:1:1:3", True)}
        # (a) 碰撞：v:1:1:2 改号到 v:1:1:3，而 B 自有 v:1:1:3 已放行
        cm, cl, cc = apply_remap(cb, {"v:1:1:2": "v:1:1:3"})
        check("(a) 碰撞格列出未映射的 v:1:1:3", cc == ["v:1:1:3"])
        check("(a) 碰撞时不合并：新号保留 remap 那条（待审），不沿用 B 自有的放行", cm["v:1:1:3"]["admit"] is False)
        check("(a) 无碰撞的旧格不受影响", cm["v:1:1:1"]["admit"] is True)
        arm_c = {"v:1:1:3": {"admit": True, "provenance": "match", "char": "字"}}
        pc, _ = classify(cm, arm_c, "provenance", set(), frozenset(cc), frozenset(cc))
        check("(a) 碰撞格进看图清单，且按无对位（matched 为假）",
              len(pc) == 1 and pc[0]["cid"] == "v:1:1:3" and pc[0]["matched"] is False)
        pc0, _ = classify(cm, arm_c, "provenance", set())
        check("(a) 不给碰撞集合时，按对位后的基线算（remap 那条待审，故为对位上的新放行）",
              len(pc0) == 1 and pc0[0]["matched"] is True)
        # (b) 无碰撞：与原来逐格相同（多对一、已删、一对一）
        nb = {"v:1:1:1": row("v:1:1:1", True), "v:1:1:2": row("v:1:1:2", False)}
        nm, nl, nc = apply_remap(nb, {"v:1:1:2": "v:1:1:9", "v:1:1:1": ""})
        check("(b) 无碰撞：碰撞集合为空、多对一为空", nc == [] and nl == [])
        check("(b) 无碰撞：已删格不进表，改号格保留原字段",
              "v:1:1:1" not in nm and nm["v:1:1:9"] == dict(nb["v:1:1:2"], id="v:1:1:9", admit=False))
        mm, ml, mc = apply_remap(cb, {"v:1:1:1": "v:1:1:3", "v:1:1:3": "v:1:1:4"})
        check("(b) 链式改号（1→3、3→4）：无碰撞，3 的旧格已在 remap 键中", mc == [] and mm["v:1:1:4"]["admit"] is True)
        # (c) 恒等行（同号）不算碰撞
        ib = {"v:1:1:1": row("v:1:1:1", True), "v:1:1:2": row("v:1:1:2", False)}
        im, il, ic = apply_remap(ib, {"v:1:1:1": "v:1:1:1", "v:1:1:2": "v:1:1:2"})
        check("(c) 恒等行不误判为碰撞", ic == [] and il == [] and im["v:1:1:1"]["admit"] is True)
        print("== 自测十四（208hv）：同号碰撞计入停线（方案 A），与无对位合计过线即停；摘要两项分列")

        def write_tbl(name, rows):
            p = tdp / name
            p.write_text("\n".join([json.dumps({"book": "t"})] + [json.dumps(r, ensure_ascii=False) for r in rows]) + "\n",
                         encoding="utf-8")
            return str(p)

        def stop_case(tag, n_coll, n_unm):
            # 200 格基线一致的放行格：限额 = min(20, 5%×A 放行数) = 10 + 0.05×(碰撞＋无对位)
            brows = [R_(f"vol00:1:{i}:1", False) for i in range(200)]
            arows = [R_(f"vol00:1:{i}:1", True) for i in range(200)]
            rm = []
            for j in range(n_coll):
                brows += [R_(f"vol00:5:{j}:1", False), R_(f"vol00:5:{j}:2", True)]
                arows.append(R_(f"vol00:5:{j}:2", True))
                rm.append(f"vol00:5:{j}:1\tvol00:5:{j}:2")
            arows += [R_(f"vol00:9:{j}:1", True) for j in range(n_unm)]
            rp = tdp / f"{tag}_remap.tsv"
            rp.write_text("\n".join(rm) + ("\n" if rm else ""), encoding="utf-8")
            a = types.SimpleNamespace(base=write_tbl(f"{tag}_base.jsonl", brows), arm=write_tbl(f"{tag}_arm.jsonl", arows),
                                      out=str(tdp / tag), remap=str(rp), seed=SEED_DEFAULT, quota=QUOTA_DEFAULT,
                                      max_total=TEST_MAX, source_field="provenance", red=frozenset({"vol99:1:1:1"}))
            return run(a), tdp / tag

        def R_(cid, admit):
            return {"id": cid, "admit": admit, "char": "字", "provenance": "match"}

        rc, d = stop_case("s10", 10, 0)
        check("碰撞 10 格（刚好压线，10 ≤ 10.5）→ 不停", rc == 0)
        check("摘要写出同号碰撞 10 格，且说明计入停线", "同号碰撞（208ho）：10 格" in (d / "摘要.md").read_text(encoding="utf-8")
              and "计入停线" in (d / "摘要.md").read_text(encoding="utf-8"))
        rc, d = stop_case("s11", 11, 0)
        check("碰撞 11 格（超线）→ 停（退出码 4）", rc == 4 and not d.exists())
        rc, d = stop_case("s0u11", 0, 11)
        check("无对位 11 格（超线，无碰撞）→ 停（退出码 4，与改前一致）", rc == 4 and not d.exists())
        rc, d = stop_case("s6u5", 6, 5)
        check("碰撞 6＋无对位 5＝11（合计超线）→ 停", rc == 4 and not d.exists())
        rc, d = stop_case("s6u4", 6, 4)
        check("碰撞 6＋无对位 4＝10（合计未超线）→ 不停", rc == 0)
        sm14 = (d / "摘要.md").read_text(encoding="utf-8")
        check("两项分列：无对位 4 与 同号碰撞 6 各自单列", "无对位格" in sm14 and "：4，" in sm14 and "同号碰撞（208ho）：6 格" in sm14)
        check("合计行写出 10", "停线合计（无对位＋同号碰撞）：10" in sm14)

        print("== 自测五：无对位超线 → 退出码 4（停，不写输出）")
        rc = run(args_for("run9", arm=over_p))
        check("退出码 4", rc == 4)
        check("未写输出目录", not (tdp / "run9").exists())

        print("== 自测六：红线格从待审变放行 → 退出码 3")
        red_cid = next(p["cid"] for p in classify(base_map, arm_tbl, "provenance", FAKE_RED)[0] if p["matched"])
        rc = run(args_for("run4", red={red_cid}))
        check("退出码 3", rc == 3)

        print("== 自测七：hint＋juan_rule 超上限 → 退出码 2")
        rc = run(args_for("run5", max_total=3))
        check("退出码 2", rc == 2)

        print("== 自测八：强制全看（--force-all）：名单格全进 force 层、不被抽样；名单外的格忽略")
        pop_other = [p["cid"] for p in classify(base_map, arm_tbl, "provenance", FAKE_RED)[0] if p["layer"] == "other"]
        force_two = pop_other[:2]
        force_p = tdp / "force.txt"
        force_p.write_text("# 测试名单\n" + "\n".join(force_two) + "\nvol09:9:9:9\n", encoding="utf-8")
        rc = run(args_for("run11", force_all=str(force_p)))
        check("退出码 0", rc == 0)
        fr = [l.split("\t") for l in (tdp / "run11" / "抽样.tsv").read_text(encoding="utf-8").splitlines()[1:]]
        forced = [r for r in fr if r[1] == "force"]
        check("强制名单两格都进 force 层", sorted(r[4] for r in forced) == sorted(force_two))
        check("名单外的格不进 force 层（vol09:9:9:9 不在新放行总体）", not any(r[4] == "vol09:9:9:9" for r in fr))
        check("摘要写出强制名单忽略 1 格", "已忽略 1 格" in (tdp / "run11" / "摘要.md").read_text(encoding="utf-8"))
        print("== 自测九：force＋hint＋juan_rule 超上限 → 退出码 2（force 格不能被抽掉）")
        rc = run(args_for("run12", max_total=1, force_all=str(force_p)))
        check("退出码 2", rc == 2)

        print("== 自测十：红线按册——不在 A 臂册内的红线格不停线，列为本次未检，摘要首行写「红线未全覆盖，不得报 0」")
        rc = run(args_for("run13", red=set(FAKE_RED) | {"vol09:1:1:1"}))
        check("退出码 0（不停线）", rc == 0)
        head = (tdp / "run13" / "摘要.md").read_text(encoding="utf-8").splitlines()[0]
        check("摘要首行为未全覆盖警告，且点名 vol09:1:1:1", head.startswith("红线未全覆盖，不得报 0") and "vol09:1:1:1" in head)
        print("== 自测十一：红线集合为空 → 退出码 3（不回落到全局十格，也不放行）")
        rc = run(args_for("run14", red=set()))
        check("退出码 3", rc == 3)

        print("== 自测十六之二（208lx）：RED_LINE 恰十格，且与 S26_force名单.py --s23 out 的输出集合相等（读它的输出，不抄第二份）")
        check("RED_LINE 恰十格", len(RED_LINE) == 10)
        s26_py = Path(__file__).resolve().parent.parent / "重绑脚本-Eden" / "S26_force名单.py"
        s26_out = tdp / "s26_force.txt"
        r26 = subprocess.run([sys.executable, "-I", str(s26_py), "--s23", "out", "--out", str(s26_out)],
                             capture_output=True, text=True)
        check("S26 --s23 out 退出码 0", r26.returncode == 0)
        s26_cells = {l.strip() for l in s26_out.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")}
        check("RED_LINE 与 S26 输出集合相等", s26_cells == set(RED_LINE))
        check("第十格 vol05:108:2:20 在 RED_LINE 内", "vol05:108:2:20" in RED_LINE)

        print("== 自测十二：强制名单里基线同号已放行的格 → 不计「已忽略」，单列「对位待核」")
        adm_both = next(c for c in sorted(base_rows) if base_rows[c]["admit"] and arm_tbl.get(c, {}).get("admit") and c not in FAKE_RED)
        force2_p = tdp / "force2.txt"
        force2_p.write_text(adm_both + "\nvol09:9:9:9\n", encoding="utf-8")
        rc = run(args_for("run15", force_all=str(force2_p)))
        check("退出码 0", rc == 0)
        sm12 = (tdp / "run15" / "摘要.md").read_text(encoding="utf-8")
        parts12 = sm12.split("## 强制名单但基线同号已放行：对位待核", 1)
        check("对位待核节列出基线已放行的格", len(parts12) == 2 and f"`{adm_both}`" in parts12[1])
        check("对位待核节不列未入基线的 vol09:9:9:9", len(parts12) == 2 and "vol09:9:9:9" not in parts12[1])
        check("已忽略只计 vol09:9:9:9 1 格", "已忽略 1 格：vol09:9:9:9" in sm12)

        print("== 自测十五（208ix）：hint 重绑表 3 例（Elena 208hc §2）：不补空行必报警，补空行后不报警")
        def R2(cid, admit):
            return {"id": cid, "admit": admit, "char": "字", "provenance": "match"}
        eb = {c: R2(c, a) for c, a in [("vol05:54:7:18", False), ("vol05:54:7:19", True),
                                       ("vol05:78:1:18", False), ("vol05:78:1:19", False),
                                       ("vol05:96:7:10", False), ("vol05:96:7:11", True)]}
        v1 = {"vol05:54:7:18": "vol05:54:7:19", "vol05:78:1:18": "vol05:78:1:19", "vol05:96:7:10": "vol05:96:7:11"}
        blanks = {"vol05:54:7:19": "", "vol05:78:1:19": "", "vol05:96:7:11": ""}
        al = collision_detail(eb, v1)
        check("不补空行：3 例全部报警（新号按序为 54:7:19、78:1:19、96:7:11）",
              [d["new"] for d in al] == ["vol05:54:7:19", "vol05:78:1:19", "vol05:96:7:11"])
        check("不补空行：被挤占的 B 号（放行的 54:7:19、96:7:11）列为未映射同号格，且基线放行",
              al[0]["plain"] == [("vol05:54:7:19", True)] and al[2]["plain"] == [("vol05:96:7:11", True)])
        check("补空行后不报警", collision_detail(eb, {**v1, **blanks}) == [])
        arm_e = {c: R2(c, True) for c in ["vol05:54:7:19", "vol05:96:7:11"]}
        coll_e = frozenset(apply_remap(eb, v1)[2])
        pe_no, _ = classify(apply_remap(eb, v1)[0], arm_e, "provenance", set(), frozenset(), coll_e)
        check("不补空行：A 臂放行的 54:7:19、96:7:11 进无对位清单，不被同号旧格吞掉",
              {p["cid"]: p["matched"] for p in pe_no} == {"vol05:54:7:19": False, "vol05:96:7:11": False})
        pe_yes, _ = classify(apply_remap(eb, {**v1, **blanks})[0], arm_e, "provenance", set())
        check("补空行后：A 臂放行的 54:7:19、96:7:11 对位到基线待审、是有效新放行",
              {p["cid"]: p["matched"] for p in pe_yes} == {"vol05:54:7:19": True, "vol05:96:7:11": True})

        print("== 自测十六（208kg）：强制名单格式校验：错写格号 → 退出码 5、摘要单列；行内注释的合法格照常进 force 层")
        bad_p = tdp / "force_bad.txt"
        bad_p.write_text(pop_other[0] + "  # 行内注释\nvol5:154:8:21\nvol05:154:8\nvol05:154:8:21x\n", encoding="utf-8")
        rc = run(args_for("run16", force_all=str(bad_p)))
        check("错写格号 → 退出码 5", rc == 5)
        sm16 = (tdp / "run16" / "摘要.md").read_text(encoding="utf-8")
        check("摘要单列「格式不合（--force-all）：3 行」", "格式不合（--force-all）：3 行" in sm16)
        check("摘要列出错写原文 vol5:154:8:21", "第 2 行「vol5:154:8:21」" in sm16)
        fr16 = [l.split("\t") for l in (tdp / "run16" / "抽样.tsv").read_text(encoding="utf-8").splitlines()[1:]]
        check("行内注释的合法格仍进 force 层", any(r[1] == "force" and r[4] == pop_other[0] for r in fr16))
        print("== 自测十七（208kg）：正常名单（含空行、注释、行内注释）→ 退出码 0，无格式不合")
        ok_p = tdp / "force_ok.txt"
        ok_p.write_text("# 名单\n\n" + pop_other[0] + "  # 行内\n", encoding="utf-8")
        rc = run(args_for("run17", force_all=str(ok_p)))
        check("退出码 0", rc == 0)
        check("摘要写「格式不合（--force-all）：0 行」", "格式不合（--force-all）：0 行" in (tdp / "run17" / "摘要.md").read_text(encoding="utf-8"))

        print("== 自测十八（208kq 再补七）：带 a／b 后缀的格号（真 hint 名单形态）合法；非法后缀／空槽位 → 退出码 5")
        b_p = tdp / "force_b.txt"
        b_p.write_text(pop_other[0] + "\nvol05:115:2:5b\nvol05:115:2:-3a\n", encoding="utf-8")
        rc = run(args_for("run18", force_all=str(b_p)))
        check("带 a／b 后缀的格号 → 退出码 0", rc == 0)
        check("摘要写「格式不合（--force-all）：0 行」", "格式不合（--force-all）：0 行" in (tdp / "run18" / "摘要.md").read_text(encoding="utf-8"))
        bad_b = tdp / "force_badb.txt"
        bad_b.write_text(pop_other[0] + "\nvol05:115:2:5c\nvol05:115:2:\n", encoding="utf-8")
        rc = run(args_for("run19", force_all=str(bad_b)))
        check("非法后缀 5c 与空槽位 → 退出码 5", rc == 5)
        sm19 = (tdp / "run19" / "摘要.md").read_text(encoding="utf-8")
        check("摘要单列「格式不合（--force-all）：2 行」", "格式不合（--force-all）：2 行" in sm19)

        print("--- 摘要.md（run1）---")
        print((tdp / "run1" / "摘要.md").read_text(encoding="utf-8").replace(str(tdp), "<tmp>"))

    print("自测结果：" + ("通过" if ok_all else "失败"))
    return 0 if ok_all else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base")
    p.add_argument("--arm")
    p.add_argument("--out")
    p.add_argument("--remap", default=None)
    p.add_argument("--seed", type=int, default=SEED_DEFAULT)
    p.add_argument("--quota", type=int, default=QUOTA_DEFAULT)
    p.add_argument("--max-total", dest="max_total", type=int, default=MAX_TOTAL_DEFAULT)
    p.add_argument("--source-field", dest="source_field", default="provenance")
    p.add_argument("--force-all", dest="force_all", default=None, help="强制全看格号名单（每行一个格号）")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    if not (args.base and args.arm and args.out):
        p.error("需要 --base、--arm、--out（或 --selftest）")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
