# -*- coding: utf-8 -*-
"""册级先验的标定与复核：把 `measure_*` 跑一遍，和册 yaml 里的现值对照。

## 为什么要有这个

`BookSpec` 上那批「标定出来的数值」（`period_prior` / `bottom_gap` / `pitch_prior`…）
是**人在 REPL 里跑一次 `measure_*`、把数抄进 yaml** 的。这条链有三个毛病：

1. **没人跑** —— `measure_book_period` / `measure_book_bottom_gap` 写好放在那里，
   全仓没有任何调用者（2026-09-16 实测），全靠人自己想起来；
2. **抄错没人知道** —— yaml 里写 119.0 还是 191.0，没有任何东西会说话；
3. **没人记得什么时候该重标** —— 换了 Step1 的算法，`period_prior` 其实该重标，
   但它连「过期」都不会报（册配置要靠 `StepSpec.book_deps` 才进指纹，
   而那个白名单当前只有 `border_detect` 一条声明）。

这个模块就是把 1 接上、让 2 看得见、给 3 一个复核手段。

## 不做什么：**不自动写回 yaml**

只印对照表，改不改由人定。理由是 `measure_book_period` 自己那条注释——
兜底来的 period 不能再参与标定，**拿先验算先验是循环论证**。自动回写会让一次
坏标定悄悄固化；更要紧的是 yaml 里那些人写的 note（如 vol01 p48 反色带那段）
往往比数值本身更值钱，自动改文件很容易把它们冲掉。

## 口径

- **`period_prior`**：读现成的闸2 产物（不重跑管线），取正文页 period 的中位数。
  `measure_book_period` 内部已经排掉 `period_from_prior` 的页（防循环论证）。
  能拿到页型就只用 `page_type == "body"` 的页——职名/目录页字距本来就不同，
  混进来会把中位数拉偏十几个 px。
- **`bottom_gap`**：要读整册**原图**现算（`find_horizontal_border` 逐页跑），
  比上面那条慢得多，所以默认不测，`--with-bottom-gap` 才做。
- **`pitch_prior`**：读闸2 产物里的 `ref_w`（列内容宽度）中位数。注意这**不是**
  `pitch_prior` 的严格定义（列距 = 界行间距，含界行本身），两者差一个界行宽度，
  所以它只当**量级参照**，不作为建议值——判定列是 `参考`，不是 `建议改`。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

#: 实测值与 yaml 现值相差超过这个比例就标「漂了」。
#: 3% 是按现有标定的稳定度定的：正文页 period 的册内 std 实测 vol01 1.67px /
#: vol02 2.37px（约 1.5~2%），bottom_gap 三册 325/327/326（差 0.6%）。
#: 取 3% 让正常抖动不报警，真漂了（如本轮 bxgb 的 106.5 vs 70.6 = 51%）一眼看见。
DRIFT_FRAC = 0.03


@dataclass
class Row:
    """一个先验的对照结果。`measured is None` = 这次没量出来（样本不足/产物缺）。"""
    field: str
    current: float | None      # 册 yaml 里的现值
    measured: float | None     # 这次实测
    note: str = ""

    @property
    def verdict(self) -> str:
        if self.measured is None:
            return "未测出"
        if self.current is None:
            return "未配"
        if self.current == 0:
            return "漂了"
        return "漂了" if abs(self.measured - self.current) / abs(self.current) > DRIFT_FRAC else "一致"

    @property
    def drift_pct(self) -> float | None:
        if self.measured is None or not self.current:
            return None
        return (self.measured - self.current) / abs(self.current) * 100.0


def _body_pages(store, book_id: str, pages: list[int]) -> set[int] | None:
    """闸1 判为正文的页。拿不到页型产物就返回 None（让 measure_* 走它的粗筛兜底）。"""
    from ..core.spec import page_key
    from ..products import kinds as _k  # noqa: F401  (side effect: 注册产物种类)
    # `kinds/__init__` 没有 import 这一个模块，得显式引（闸1 产物种类在它里面注册）
    from ..products.kinds import border_detect_gate as _bg  # noqa: F401

    out: set[int] = set()
    seen_any = False
    for pg in pages:
        g = store.read(book_id, "border_detect_gate", page_key(pg),
                       "border_detect_gate_manifest")
        if g is None:
            continue
        seen_any = True
        if getattr(g, "page_type", "body") == "body":
            out.add(pg)
    return out if seen_any else None


def _measured_ref_w(store, book_id: str, pages: list[int],
                    body: set[int] | None) -> tuple[float | None, int]:
    """闸2 产物里 `ref_w` 的中位数 + 参与的页数。见模块头「口径」：只作量级参照。"""
    from ..core.spec import page_key
    from ..products import kinds as _k  # noqa: F401  (side effect: 注册产物种类)
    # `kinds/__init__` 没有 import 这一个模块，得显式引（闸1 产物种类在它里面注册）
    from ..products.kinds import border_detect_gate as _bg  # noqa: F401

    vals: list[float] = []
    for pg in pages:
        if body is not None and pg not in body:
            continue
        g = store.read(book_id, "column_gate", page_key(pg), "gate_manifest")
        if g is None or not getattr(g, "ref_w", None):
            continue
        vals.append(float(g.ref_w))
    if len(vals) < 5:
        return None, len(vals)
    return round(statistics.median(vals), 2), len(vals)


def calibrate(book, store, pages: list[int] | None = None,
              with_bottom_gap: bool = False) -> tuple[list[Row], dict]:
    """跑标定，返回 `(对照表, 诊断)`。**只读，不改任何文件。**

    `pages` 不给时用 `book.pages`。`with_bottom_gap` 要读整册原图，慢。
    """
    from ..products import kinds as _k  # noqa: F401  (side effect: 注册产物种类)
    # `kinds/__init__` 没有 import 这一个模块，得显式引（闸1 产物种类在它里面注册）
    from ..products.kinds import border_detect_gate as _bg  # noqa: F401
    from ..utils.row_boundaries import measure_book_period

    # `pages` 不给时：yaml 写了 `pages:` 就用它，没写就扫 raw_dir（`all_pages`）。
    # 不能只认 `book.pages`——四庫總目那十册都没写 `pages:`，会得到 0 页而静默什么都没测。
    pgs = list(pages) if pages is not None else (list(book.pages) or book.all_pages())
    body = _body_pages(store, book.id, pgs)
    diag = {
        "pages": len(pgs),
        "body_pages": (len(body) if body is not None else None),
        "body_source": ("闸1 page_type" if body is not None else "无页型产物，用 measure_* 的粗筛兜底"),
    }

    rows: list[Row] = []

    # period_prior —— 读闸2 产物，measure_book_period 自己排掉兜底页
    per = measure_book_period(store, book.id, pages=pgs, body_pages=body)
    rows.append(Row("period_prior", book.period_prior, per,
                    "正文页 period 中位；已排除 period_from_prior 的页（防循环论证）"))

    # pitch_prior —— 只作量级参照（ref_w 是列内容宽，不含界行；与列距差一个界行宽）
    rw, n_rw = _measured_ref_w(store, book.id, pgs, body)
    rows.append(Row("pitch_prior", book.pitch_prior, None,
                    f"未直接量；闸2 ref_w 中位 {rw}（{n_rw} 页）= 列内容宽，"
                    f"比列距小一个界行宽，仅作量级参照"
                    if rw is not None else "闸2 产物不足，无参照"))

    if with_bottom_gap:
        from ..utils.border_geometry import measure_book_bottom_gap
        grays = []
        for pg in pgs:
            try:
                grays.append(_read_gray(book, pg))
            except FileNotFoundError:
                continue
        gap = measure_book_bottom_gap(grays) if grays else None
        rows.append(Row("bottom_gap", book.bottom_gap,
                        (round(float(gap), 2) if gap is not None else None),
                        f"整册「页高 − 下版框 y」中位（读原图现算，{len(grays)} 页）"))
    else:
        rows.append(Row("bottom_gap", book.bottom_gap, None,
                        "未测（要读整册原图，慢）；加 --with-bottom-gap 才量"))

    return rows, diag


def _read_gray(book, page: int):
    """读一页灰度原图。走与 RunContext 相同的 preclean 改写规则。"""
    import numpy as np
    from ..utils.image_io import imread
    from ..utils.preclean import effective_raw_path

    path = effective_raw_path(book, page)
    img = imread(str(path), 0)
    if img is None:
        raise FileNotFoundError(f"原图缺失: {path}")
    if img.ndim == 3:
        import cv2
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if getattr(book, "writing_mode", "vertical-rl") == "horizontal-tb":
        img = np.rot90(img, -1).copy()
    return img


def format_table(rows: list[Row], diag: dict, book_id: str) -> str:
    """对照表。**现值在前、实测在后**——这张表是拿来复核 yaml 的，不是拿来抄的。"""
    out = [f"册 {book_id}：{diag['pages']} 页"
           + (f"，正文 {diag['body_pages']} 页" if diag["body_pages"] is not None else "")
           + f"（页型来源：{diag['body_source']}）", ""]
    head = f"{'字段':<16}{'yaml 现值':>12}{'实测':>12}{'偏差':>10}  {'判定':<8}说明"
    out.append(head)
    out.append("-" * 100)
    for r in rows:
        cur = "—" if r.current is None else f"{r.current:g}"
        mea = "—" if r.measured is None else f"{r.measured:g}"
        pct = "—" if r.drift_pct is None else f"{r.drift_pct:+.1f}%"
        out.append(f"{r.field:<16}{cur:>12}{mea:>12}{pct:>10}  {r.verdict:<8}{r.note}")
    out.append("")
    drifted = [r for r in rows if r.verdict == "漂了"]
    compared = [r for r in rows if r.verdict in ("漂了", "一致")]
    if drifted:
        out.append(f"⚠️ {len(drifted)} 个先验与实测不符（阈值 {DRIFT_FRAC:.0%}）："
                   + "、".join(r.field for r in drifted))
        out.append("   **不会自动改 yaml**——先看清是先验过期了，还是这次量得不对"
                   "（产物陈旧？页型混了职名/目录页？），再手改。")
    elif compared:
        out.append(f"✅ 实际比对上的 {len(compared)} 个先验都与 yaml 一致。")
    else:
        # 一个都没测出来时**不许报成功**——「没测出来」和「测了没问题」是两回事，
        # 混为一谈会让人以为复核过了。四庫總目那十册没写 `pages:`，早期版本
        # 在这里得 0 页却照印 ✅，正是这个坑。
        out.append("⚠️ 一个先验都没测出来——不是「都对」，是**没比**。")
        out.append("   常见原因：闸2 产物还没跑（先 guji pipeline 或 guji step column_gate）；"
                   "或 --pages 选中的页没有产物。")
    return "\n".join(out)
