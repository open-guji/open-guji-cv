# -*- coding: utf-8 -*-
"""Step9 结果整理 · 坐标转字符位：把 Step3/Step7 产物拼成 guji-markdown 文本。

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step9-结果整理/01-结果排版.md`
（下称"设计档"）。只做设计档 §四 定的范围：单页/多页拼出 guji-markdown 文本，
不做整册体检表、不做与整理本比对——那是 Step9 另外两件事。

命令行入口在 `scripts/render_guji_markdown.py`；控制台路由
（`console/routers/step9.py`）直接 import 本模块的 `render_page`。

## 字位流来自 `report/slots.py`（2026-09-13 改）

join（Step3 `cells` × Step7 `seed_admit`、`sort_by_reading` 读序、blank/excluded/
阙文三分）**已挪去 `report/slots.py`**，9.3 比对与本模块共用同一份——两边各写
一套的后果见那个模块头。本模块现在只负责**字位流 → guji-markdown 记号**这一层
映射（抬头 `^`、挪抬 `.`、雙行夹注 `<a|b>`、單行小注 `<注>`、阙文 `[[]]`）。
單行小注写成指令式 `:jz[小注]{type=单行}`（2026-09-24 起；此前写不带 `|` 的
`<小注>`，与只剩一半的雙行夹注分不开，维基文库导出要区分二者）。

## 为什么不是 core.step.Step

跟 Step8 同一个理由（见 `open_guji_cv/feedback/step8.py`）：输入是**跨列跨页**
的汇总（一页的完整文本要等这一页所有列都读完才能拼），产物是给人看的 md 文件，
不是 `<book>/<step>/<page>/` 下的一份 `ProductKindSpec`。不进 `core.step.STEPS`，
不出现在 `pipelines/*.yaml` 里。同理**也不进任何管线自动跑**——用户 2026-09-11
明确要求："审阅完了再一起做"是常态，但也要"允许审阅一半时直接输出看看效果"，
这正是"随时可现场调用、不是排队等整册跑完"的意思，控制台路由现场调用本模块，
不落盘、不进队列。

## 四处已知边界（设计档 §三，未验先说清楚，别指望这版就是终版）

1. **抬头级数**优先读 `ColumnCells.n_raised`（离散、可靠，见设计档 §三·1 的
   实测：3419 列零例外）。本模块读的是 Step3 产物，不会撞上"Step7 产物里
   抬头区空白格不出现导致数负数 slot 低估"那个坑——但如果以后有人改成只读
   Step7 产物，要重新看这条。
2. **挪抬 `.` 不产出真正的"挪抬语义"**——记的是「字前空出 n 格」这个版面事实
   本身，不判定是不是敬语（用户 2026-09-11 裁）。
3. **阙文 `[[…]]`**：`admit=False and char is None` **且不是 excluded** 时才输出
   ——2026-09-11 用户核实 vol02 p1-20 时发现最初版本把"排除名单"（切坏图块/
   非字）也标成了 `[[]]`：20 处里 19 处其实是 excluded。现在 excluded 跟
   `blank` 一样直接跳过，不占位（判据在 `report/slots.py`）。
4. `<…>` 夹注转行 `|` 与后缀属性 `{k=v}`（本模块目前只用到夹注 `|`）已在
   `guji-markdown` 分支 `claude/attrs-and-jz-break-0911` 实现并测试通过，
   但**尚未合并到 guji-markdown main**——用这份输出去跑下游解析器之前，
   确认对方用的是哪个版本。
"""
from __future__ import annotations

from ..core.spec import page_key
from ..errors import ProductMissing
from ..products.kinds.cells import PageCells
from ..products.store import ProductStore
from ..report.slots import CELLS_KIND, SlotRec, cells_step, page_slots


def render_column(slots: list[SlotRec], n_raised: int, n_lead_blank: int) -> str:
    """把一列的字位流（已按阅读顺序）拼成一行 guji-markdown 源文本（不含结尾换行）。

    `n_raised`：抬头级数（`ColumnCells.n_raised`）→ 行首 `^` 的个数。
    `n_lead_blank`：行首连续空白格数 → 行首 `.` 的个数（见 `slots.blank_lead_count`
    的模块注释：这个量必须从 Step3 数，Step7 对 blank 格不产出记录）。
    """
    prefix = ("^" * n_raised if n_raised > 0 else "") + "." * n_lead_blank

    out: list[str] = []
    i = 0
    while i < len(slots):
        rec = slots[i]

        if rec.kind in ("jiazhu_a", "jiazhu_b"):
            # 收集这一段连续夹注：sort_by_reading 已经把同一段的 a 全部排在 b 全部
            # 之前，顺着走、按 sub 分桶即可，不用重新判断相邻性。
            # excluded 的格子（切坏/非字）在夹注段里同样直接丢弃，不占位。
            a_chars: list[str] = []
            b_chars: list[str] = []
            while i < len(slots) and slots[i].kind in ("jiazhu_a", "jiazhu_b"):
                r = slots[i]
                if not r.excluded:
                    (a_chars if r.kind == "jiazhu_a" else b_chars).append(_char_text(r))
                i += 1
            if a_chars and b_chars:
                out.append("<" + "".join(a_chars) + "|" + "".join(b_chars) + ">")
            elif a_chars or b_chars:
                out.append("<" + "".join(a_chars) + "".join(b_chars) + ">")
            # a、b 都空（整段夹注全被排除）——整段不输出，连 <> 都不留
            continue

        if rec.kind == "jiazhu_solo":
            # 單行小注（2026-09-20 起 Step3 自成一类，sub=None）：连续几格并成
            # 一条 `<…>`（「梁監門<叔玠>」），没有 `|`——它本来就只有一行。
            # excluded / 阙文的处理与正文一致。整段全被排除则连 <> 都不留。
            chars: list[str] = []
            while i < len(slots) and slots[i].kind == "jiazhu_solo":
                r = slots[i]
                if not r.excluded:
                    chars.append(_char_text(r))
                i += 1
            if chars:
                # 用指令式写 type=单行（guji-markdown spec/directives.md：jz 的 type
                # 取 双行|单行|尾注，缺省双行）。`<…>` 简写带不了属性，而下游
                # 要靠它分开「人名小字」和「注文」（维基文库前者出 {{small}}、后者 {{*}}）。
                # 指令 label 里不能有裸 `[`/`]`（会提前闭合）：阙文 `[[]]` 在这里改写 □。
                out.append(":jz[" + "".join("□" if c == "[[]]" else c for c in chars) + "]{type=单行}")
            continue

        if rec.kind == "blank":
            # 行首连续 blank 已经量进 prefix 的挪抬 `.` 里；这里遇到的
            # ——不管行首那几个还是行中偶尔出现的——一律只是"跳过不占位"，
            # 不重复计数，也不把行中 blank 误当挪抬。
            i += 1
            continue

        if rec.excluded:
            # 排除名单：这一格根本不是字（切坏图块/墨污），不是「缺一个字」，
            # 跟 blank 一样直接跳过，不能标 [[]]——那会把「本不存在的格」和
            # 「确实是字但认不出」混成同一件事（2026-09-11 vol02 p1-20 教训）。
            i += 1
            continue

        out.append(_char_text(rec))
        i += 1

    return prefix + "".join(out)


def _char_text(rec: SlotRec) -> str:
    """一个字位的输出文本，只在**不是** excluded 时调用。
    阙文（`unreadable`）出 `[[]]`；否则出**字形**（`char`）。

    2026-09-26 起只出字形，不再「文意优先」（用户：「读法彻底取消，所有地方都用字形，
    包括字形库、输出文本」）。此前出 `reading or char`，bxgb 有 27 处把刻本的 𠀉/宐/呂
    输出成整理本的 丘/宜/吕，与人裁定的字形相反。老产物里的 `reading` 字段忽略。"""
    if rec.unreadable:
        return "[[]]"
    text = rec.char or "[[]]"
    # 原刻残（damaged）：Step7 给 □ 占位，人裁时填的「最像哪个字」挂在 guess 上，
    # 用 guji-markdown 的后缀属性 `{k=v}` 括注（用户 2026-09-20：「识别成缺字方框，
    # 但标出像某字」）。属性语法在 guji-markdown 分支 claude/attrs-and-jz-break-0911，
    # 尚未合并 main——与模块头第 4 条同一个注意事项。
    if text == "□" and rec.guess:
        return f"□{{guess={rec.guess}}}"
    return text


def render_page(store: ProductStore, book: str, page: int, stale: list[str],
                keep_empty_cols: bool = False) -> str:
    """`stale`：本页发现的「Step7 有记录但 Step3 cells 查不到」条目，
    格式 `p{page}col{col}:slot{n}{a|b}`，追加进这个列表，不在这一层报告。

    `keep_empty_cols`：没有字的列（版心、空列）也占一行、出空行，使「第 k 行 = 第 k 列」。
    维基文库导出要它（用户 2026-09-24：版心那一行应当空出来）；缺省关，9.2 等不受影响。
    """
    slots = page_slots(store, book, page, stale)

    step = cells_step(book)
    cells: PageCells | None = store.read(book, step, page_key(page), CELLS_KIND)  # type: ignore[assignment]
    if cells is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {step} 产物（先跑到 Step3）")
    n_raised_by_col = {c.col: c.n_raised for c in cells.columns}
    lead_blank_by_col = {c.col: _lead_blank(c) for c in cells.columns}

    by_col: dict[int, list[SlotRec]] = {}
    for s in slots:
        by_col.setdefault(s.col, []).append(s)

    lines: list[str] = []
    cols = sorted(set(by_col) | ({c.col for c in cells.columns} if keep_empty_cols else set()))
    for col in cols:
        if col not in by_col:
            lines.append("")
            continue
        lines.append(render_column(by_col[col], n_raised_by_col.get(col, 0),
                                   lead_blank_by_col.get(col, 0)))
    return "\n".join(lines)


def _lead_blank(col_cells) -> int:
    """行首连续空白格数。`slots.blank_lead_count` 的内联版——这里已经有整份
    `PageCells` 在手，不必为每一列再读一次产物。"""
    by_key = {(c.slot, c.sub or ""): c for c in col_cells.cells}
    n, slot = 0, 1
    while by_key.get((slot, "")) is not None and by_key[(slot, "")].kind == "blank":
        n += 1
        slot += 1
    return n
