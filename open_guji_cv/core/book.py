"""BookSpec：一册书的图源、页集合、dev_set 与版式常量。来自 books/<id>.yaml。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

#: 引擎仓内的 `books/`——**已退役**（2026-09-15 用户裁定：「以后都要读 workspace
#: 下的定义，完全不应该读 open-guji-cv 下面的」）。十册四庫的配置已全部迁进
#: `siku-zongmu-workspace/books/`。这里只留一个空目录兜底与一条报错提示：
#: 万一有人往这儿放 yaml，`load_book` 会明确告诉他放错地方了，而不是静默生效
#: ——那正是「books.yaml 有两份」那条坑的根源（工作区改了没反应，因为读的是这份）。
BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"
_NUM_RE = re.compile(r"(\d+)")


@dataclass
class BookSpec:
    id: str
    title: str
    raw_dir: Path                     # 原始扫描目录
    raw_pattern: str = "{page}.png"   # 页号 → 文件名
    #: Step1 的列数先验。**现代链可以是 None**——列/行数由 `line_detect` 探出，
    #: 册配置写 `expected_cols: null`（三模式方案 §六.1）。刻本链仍是版式常量，
    #: 闸 `count_mode=exact` 拿它当硬判据；现代链走 `count_mode=detected` 不读它。
    expected_cols: int | None = 9
    #: Step3 的正文格数先验。同上，现代链是 None（由块宽 ÷ pitch 推）。
    chars_per_line: int | None = 21
    edition: str = "keben"
    dev_set: list[int] = field(default_factory=list)
    #: 命名页集（yaml 的 `sets:`）：`{名字: [页号…]}`，用 `--pages <名字>` 选。
    #: dev_set 是切分链的分层集，历史数字都挂在它上面，**不要往里塞新页**；
    #: 要专项集（如夹注 jz）就在这里新开一个，见 vol02.yaml。
    sets: dict[str, list[int]] = field(default_factory=dict)
    #: 夹注（雙行小注）的**本书文字约定**（yaml 的 `jiazhu:`）。默认全空 = 不启用。
    #:
    #: ⚠️ **探测夹注本身不看文字**（`utils/jiazhu_split` 纯几何：墨迹跨度、缝中心、
    #: 段连缀），换书照样能用。这里放的只是「这一套书的注文长什么样」这类**书级先验**：
    #:
    #: - `note_suffixes`：版本注的收尾词（《四庫全書總目》是「…採進本 / …藏本」）。
    #:   给了才启用闭集短语通道与 T1/T2 分型；不给就整册按开放文本算，不会误判。
    #: - `note_max_len`：闭集短语的长度上限（超过就当开放文本）。
    #: - `title_split`：书名与注文的分界正则（总目是「N卷 / 無卷數」）。
    #:
    #: 用户 2026-09-06 定的口径：**依赖文字可以，但必须「这套书用、下套书不用」**——
    #: 所以一律进 Book 配置，不写死在 eval / 通道代码里。
    jiazhu: dict = field(default_factory=dict)
    #: 下版框跨页先验的基准：整册「页高 − 下版框 y」的中位数（yaml 的
    #: `bottom_gap:`）。给了才启用 Step1 的下版框救援，不给则行为与加这套
    #: 机制之前逐位相同。
    #:
    #: **怎么标定**：`utils/border_geometry.measure_book_bottom_gap(整册灰度图)`
    #: 跑一次，把数写进 yaml。不在流水线里现算是因为 `border_detect` 是逐页
    #: step，现算等于每页重跑一遍全书。**不需要金标**：三册实测，整册算法
    #: 输出中位数与金标真基准只差 0~1px。
    #:
    #: ⚠️ 换书必须重新标定，别抄。三册恰好都落在 325~327px，但那是同一套
    #: 《四庫全書總目》武英殿本的版式，换一种版式没有理由仍是这个数。
    bottom_gap: float | None = None
    #: 页级字格高（period）的书级先验（yaml 的 `period_prior:`）。给了才启用
    #: 闸2 的**空栏页兜底**：栏内没有字的页推不出纵向节律，`estimate_shared_period`
    #: 必然抛错（vol01 p62/p158/p206 就是这样整页被拦的）。这类页界行是齐的、
    #: 九列切得出来，该正常产出一个"各格皆空"的页，不该算异常。
    #:
    #: **只在估不出来时兜底**，能估出来的页一律用当场估的值——所以给了这个数
    #: 也不会改变任何正常页的产物（有单测守着）。
    #:
    #: **怎么标定**：`utils/row_boundaries.measure_book_period()`，或直接取整册
    #: 已有产物里正文页 period 的中位数。**不需要金标**：正文页的 period 是
    #: 书级常量，vol01 正文 108 页实测 115.0±1.67px、vol02 186 页 113.0±2.37px。
    #:
    #: ⚠️ 别拿全书页混着算——职名/目录页的字距本来就不同（vol01 roster 中位
    #: 70、std 15.6），混进来会把中位数拉偏。只用 page_type == body 的页。
    #: 换书必须重新标定。
    period_prior: float | None = None
    #: 这册书有哪些页。空 = 扫 `raw_dir` 目录。yaml 里可写整数，也可写区间
    #: 字符串 `pages: ["10-380"]`（见 `_expand_pages`）——一卷书里装了多种著作时，
    #: 几本册配置共用同一批原图、各自用 `pages:` 划范围，不必复制图像。
    pages: list[int] = field(default_factory=list)
    # Step0 预清理：{页号: [规则, ...]}。默认空 = 不做任何处理。
    # 只对手工登记过的页生效，不改磁盘原图，见 utils/preclean.py。
    preclean: dict[int, list[dict]] = field(default_factory=dict)
    notes: str = ""
    #: Step5-c OCR候选（yaml 的 `ocr_candidates:`）。**默认关闭**——用户
    #: 2026-09-11 定的口径：整理本已经足够准，主要靠 5-a 库匹配 + 5-b 生僻字
    #: 候选，5-c 只在个别书需要时按需显式打开（`ocr_candidates: true`）。
    #: 关闭只是 Engine 执行时跳过这一步，不改 pipeline 拓扑——`context_decide`
    #: 本来就要处理「这一位没有 OCR 候选」（见 context_decide.py run_page）。
    ocr_candidates: bool = False
    #: Step9-9.3 对勘的**证人**（整理本）清单（yaml 的 `references:`）。
    #: 每项 `{file, quality: best|mid|low, label, line_is_column}`。
    #: 空 = 退回单证人（与 `align_ref` 同一份默认语料）。
    #:
    #: `quality` 用于多证人不一致时**加权**，不是简单多数——三份整理本来历与
    #: 质量分级见 overview 仓 `Step9-结果整理/05-整理本清单.md`（唯一真相源）。
    #: `line_is_column` 标记「这份证人的一行 ＝ 我们刻本的一列」：四库光盘版
    #: 实测如此（vol01 列首命中行首 94.7%、命中者列长相等 87.2%），据此可以做
    #: **独立于字符对齐**的丢格检测，见 `report/witness.py::col_verdict`。
    references: list[dict] = field(default_factory=list)
    #: ── 三模式（古籍 / 现代竖排 / 现代横排）的版式属性（2026-09-14 加，见 overview
    #: `图片初步数字化/进度/总览/05-三模式管线方案.md` §二、§六）。旧册 yaml 不写就是
    #: 默认值，行为与加这些字段之前逐位相同。
    #:
    #: `writing_mode`：`vertical-rl`（竖排，默认）| `horizontal-tb`（横排——页面在
    #: 原图入口顺时针旋转 90° 后按竖排处理，见方案 §三）。
    #:
    #: 2026-09-15：**旋转已实现**（`core/step.py::RunContext.raw_page`），算法链
    #: 跑得动；但 `core/anchor.py` 的 `to_original()` 还没有，所以产物坐标是
    #: 读序空间、控制台叠图看着是横躺的。面向人的三处（叠图/金标/Step9 导出）
    #: 要等那一半补上，见方案 §三与 §九.10。
    writing_mode: str = "vertical-rl"
    #: `frame`：`ruled`（有版框界行，Step1 走 `border_detect`，默认）|
    #: `none`（无版框，Step1 走 `line_detect`）。管线 yaml 决定实际跑哪个 Step，
    #: 这个字段只用来选默认管线与给控制台看。
    frame: str = "ruled"
    #: `script`：`trad`（繁体，默认）| `simp`（简体）——字表/语料/OCR 字典按它选。
    script: str = "trad"
    #: 字距（沿列方向的字身 pitch）像素先验；现代模式 Step3 `runs` 切分估不出
    #: 字身大小时兜底。同 `period_prior` 只在估不出来时用。
    pitch_prior: float | None = None
    #: Step0 分页（yaml 的 `page_split:`）：一张扫描页含多页原书时（上下两栏拼一页、
    #: 对开等），先裁成逻辑页再进管线。见 `utils/page_split.py`。空 = 不分页。
    page_split: dict = field(default_factory=dict)
    #: 上 / 下版框的**搜索带占页高的比例**（yaml 的 `top_band_frac` /
    #: `bottom_band_frac`）。不写 = 用 `find_horizontal_border` 的默认 0.15。
    #:
    #: ⚠️ **天头（或地脚）比页高的 15% 还宽的书必须调大**，否则真版框根本不在
    #: 搜索窗口里。探测器**不会报错**——它只是在天头空白里挑一个峰，给出偏上
    #: 几百 px 的 `top`，下游列窗整体上移、列图切歪，最后表现成闸2 大批列
    #: `side_floor` 超标（看着像「界行没剥干净」，其实是窗口压根没对）。
    #:
    #: **怎么标定**：量整册「版框上沿 y / 页高」的最大值，再留一截余量。
    #: 北行日錄刻本（筒子页，天头 ≈585px / 页高 2343px = 25%）实测：0.15 时
    #: 54/54 页全部落空、误差中位 440px；0.26 起误差中位 12px，且一直到 0.40
    #: 结果逐页不变——**不是卡在临界值上**，所以取 0.30 留足余量。
    #: 换书要重标；一页一个半叶的书天头窄，默认 0.15 就够。
    top_band_frac: float | None = None
    bottom_band_frac: float | None = None
    #: `leaf_layout`：`single`（一页 = 一个半叶，默认）| `folio`（**筒子页**：一页 =
    #: 一整版 = 两个半叶，中间夹版心/书口）。
    #:
    #: 筒子页**不必先分页**（beixing-guben 实测：Step2 一行没改就跑通）——
    #: `page_column_windows` 把列定义成相邻两条 `verticals` 之间，版心两侧的书口栏线
    #: 在它眼里就是普通界行；上下版框虽名义上左右半叶各一条，实测两半几乎共线
    #: （版心处 y 差 0.1~8.9px，远小于 `column_bounds` 已在处理的 14.5px 锚点漂移），
    #: 一条 `HLine` 够用。
    #:
    #: 代价是**版心占掉一个列位**：`expected_cols` 要按整版填（北行日錄刻本：
    #: 9 + 版心 + 9 = **19**，版心是第 10 列；版心宽 117px vs 正文 119px，只窄 2px，
    #: **不能**靠宽度认它，只能靠位置），且下游必须把版心那一列排除在正文之外——
    #: 这就是 `border_detect` 产 `line_index` 把它标成 `margin` 的原因。
    #: ⚠️ 这个数曾被写成 20（多算了页边那条假线），Step1 因此每页被迫多收一条线。
    leaf_layout: str = "single"
    #: `column_grid`（yaml 同名）：Step1 竖线走**网格模式**——版框定死、列距均匀、
    #: 逐槽验线、探不到的槽位按几何插值（`peak_line_search.find_vertical_lines_grid`）。
    #: 给**界行没印全**的书用：北行日錄刻本 972 个槽位里 120 个（12.3%）没有线，
    #: 自由模式在这些槽只能拿字身假峰凑数。前提是 `expected_cols` 是真值。
    #: 默认 False = 自由模式，四庫總目那批不受影响。
    column_grid: bool = False
    #: `col_pitch`（yaml 同名）：**列距**（相邻界行间距，含界行本身）像素先验，
    #: 网格模式用它过滤版框对。量法：版框宽 / 列数，逐页取中位。北行日錄刻本 119。
    #: ⚠️ 与 `pitch_prior` 不是一回事——那个是沿列方向的**字距**，给现代链 Step3 用。
    col_pitch: float | None = None
    #: `vline_polyline`（yaml 同名，默认 True）：Step1 界行要不要按弯度做三段折线拟合。
    #: **界行淡而断的书要关**：折线的判弯量 w80 在那种书上量的是"线有多断"，平直页
    #: 也被判成弯页，折点在淡线上找不到墨就整页齐刷刷平移几十 px（北行日錄刻本
    #: p40/p41 实测 33~39px，闸2 只剩 1/19 列）。关了只量 w80 不拟合，整页直线。
    #: 四庫總目那批界行实黑、w80 3~6，默认 True 行为不变。
    vline_polyline: bool = True
    #: 字体判定结果（yaml 的 `font:`，`calibrate font` 写回；**尚未实现**）。
    font: dict = field(default_factory=dict)

    # ── 页 ───────────────────────────────────────────────────────────
    def raw_path(self, page: int) -> Path:
        return self.raw_dir / self.raw_pattern.format(page=page)

    def all_pages(self) -> list[int]:
        if self.pages:
            return list(self.pages)
        if not self.raw_dir.exists():
            return []
        suffix = Path(self.raw_pattern).suffix
        found = []
        for p in self.raw_dir.iterdir():
            if p.suffix.lower() != suffix.lower():
                continue
            m = _NUM_RE.search(p.stem)
            if m and self.raw_pattern.format(page=int(m.group(1))) == p.name:
                found.append(int(m.group(1)))
        return sorted(found)

    def resolve_pages(self, selector: str | list[int] | None) -> list[int]:
        """'dev_set' / 'all' / 命名集 / '3-6,9' / [3, 4] → 页号列表（升序去重）。

        命名集来自 yaml 的 `sets:`（如 vol02 的 `jz`）。名字优先于页号表达式，
        但 `dev_set` / `all` 是保留名。
        """
        if selector is None or selector == "dev_set":
            return list(self.dev_set) or self.all_pages()
        if selector == "all":
            return self.all_pages()
        if isinstance(selector, list):
            return sorted(set(int(p) for p in selector))
        if isinstance(selector, str) and selector in self.sets:
            return sorted(set(int(p) for p in self.sets[selector]))
        # 中文输入法下全角逗号/连字符/空格极常见（控制台页码框实测踩到：
        # 输入 "161，51" 直接 500）。切分前统一归一化，顺带把空格也当分隔符。
        expr = (str(selector).replace("，", ",").replace("、", ",")
                .replace("－", "-").replace("—", "-").replace("~", "-")
                .replace("　", " "))
        expr = ",".join(expr.split())          # 空格分隔也认
        pages: set[int] = set()
        for part in expr.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                pages.update(range(int(a), int(b) + 1))
            else:
                pages.add(int(part))
        return sorted(pages)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "raw_dir": str(self.raw_dir),
            "raw_pattern": self.raw_pattern, "expected_cols": self.expected_cols,
            "chars_per_line": self.chars_per_line, "edition": self.edition,
            "dev_set": list(self.dev_set), "n_pages": len(self.all_pages()),
            "sets": {k: list(v) for k, v in self.sets.items()},
            "jiazhu": dict(self.jiazhu),
            "preclean_pages": sorted(self.preclean),
            "preclean": {str(k): v for k, v in sorted(self.preclean.items())},
            "notes": self.notes,
            "ocr_candidates": self.ocr_candidates,
            "writing_mode": self.writing_mode, "frame": self.frame, "script": self.script,
            # 只给个数，不外泄路径——控制台判「Step5-d 整理本锚定有没有意义」够用了
            "n_references": len(self.references),
            "pitch_prior": self.pitch_prior,
            "page_split": dict(self.page_split), "leaf_layout": self.leaf_layout,
            "top_band_frac": self.top_band_frac, "bottom_band_frac": self.bottom_band_frac,
            "column_grid": self.column_grid, "col_pitch": self.col_pitch,
            "vline_polyline": self.vline_polyline,
            "font": dict(self.font),
            "pipeline": self.default_pipeline_id(),
            "in_workspace": self.in_workspace(),
        }

    def in_workspace(self) -> bool:
        """这册书的**原图**在不在当前 `GUJI_WORKSPACE` 下。

        `list_books()` 取的是「引擎仓 books/ ∪ 工作区 books/」的并集，于是**每个**
        工作区下都会看见引擎仓自带的那十册四庫（vol01–vol10），而切到北行日錄工作区
        后它们的原图并不在那里——页数 0、所有产物全空。控制台的册选择器要能把这类
        册标出来，否则切完工作区满屏都是点开全空的册（2026-09-15）。

        判据用**原图目录存不存在**，不用「工作区 books/ 有没有这份 yaml」——
        四庫十册里只有 vol01/vol02 的 yaml 迁进了工作区，vol03–vol10 的 yaml 仍在
        引擎仓，但原图和产物都在工作区里、是能正常跑的册。按 yaml 判会把这八册
        误标成「不属于本工作区」。"""
        try:
            return self.raw_dir.exists()
        except Exception:
            return True

    def default_pipeline_id(self) -> str:
        """这册书默认走哪条管线。控制台按它选后端 Step id 与状态矩阵的管线
        （2026-09-15）：前端此前硬编码 `keben_body_v2`，现代印刷本在台上
        每一步都显示「没有产物」——它的产物在 `line_detect/column_crop/
        row_segment_runs` 名下。循环导入：`core.pipeline` 反过来要 `Book`，
        所以在方法里 import。"""
        try:
            from .pipeline import default_pipeline_id
            return default_pipeline_id(self)
        except Exception:
            return "keben_body_v2"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _expand_pages(raw) -> list[int]:
    """页号表达式 → 页号列表。整数照收，字符串支持 `"10-380"` 与 `"3,9,12-15"`。

    2026-09-15 加。起因：一卷书里装了五种著作（考補萃編第二十卷），五本册配置
    **共用同一批原图**、靠 `pages:` 划分页范围——最长的一本 371 页，
    直接写成整数列表是 371 个数字铺满一行，人没法核对也没法改。
    写 `pages: ["10-380"]` 就一眼看得出边界。

    与 `--pages` 的页号表达式**不是同一套**（那个还支持 `dev_set` 等命名页集，
    见 `cli_v2._parse_pages`）；这里只认数字与区间，因为册配置里不该出现
    「集合名」这种需要回头查自己的东西。
    """
    out: list[int] = []
    for item in raw or []:
        if isinstance(item, int):
            out.append(item)
            continue
        for part in str(item).replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part[1:]:                      # 负号不算区间符
                a, _, b = part.partition("-")
                lo, hi = int(a), int(b)
                if hi < lo:
                    raise ValueError(f"pages 区间倒置: {part!r}")
                out.extend(range(lo, hi + 1))
            else:
                out.append(int(part))
    seen: set[int] = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def _load_preclean(raw) -> dict[int, list[dict]]:
    """yaml 的 preclean 段 → {页号: [规则, ...]}。

    写法（vol02.yaml 里就有一例）：

        preclean:
          151:
            - kind: horizontal_bar
              y0: 648
              y1: 693
              note: 扫描件上压着的粗黑横条

    坐标是**原图像素**（raw_dir 里那张的尺度），不是任何下游产物的坐标。
    """
    if not raw:
        return {}
    out: dict[int, list[dict]] = {}
    for page, rules in raw.items():
        if isinstance(rules, dict):
            rules = [rules]
        out[int(page)] = [dict(r) for r in rules]
    return out


def _workspace_books_dir() -> Path | None:
    """工作区里的 `books/`（有 `GUJI_WORKSPACE` 才有）。

    2026-09-14 起优先于引擎仓；**2026-09-15 起是唯一来源**（用户裁定）。
    册配置是「这本书的数据」，按数据边界（overview `数据边界-三仓各管什么.md`）
    该落工作区。十册四庫的 yaml 已迁进 `siku-zongmu-workspace/books/`。
    """
    from .workspace import workspace_root
    ws = workspace_root()
    if ws is None:
        return None
    d = ws / "books"
    return d if d.is_dir() else None


def _book_yaml_path(book_id: str, books_dir: Path | None = None) -> Path:
    """显式 `books_dir` > 工作区 `books/`。**不再回退引擎仓**（2026-09-15）。

    册配置是「这本书的数据」，按三仓数据边界该落工作区。此前引擎仓 `books/`
    是兜底，结果两边同名 yaml 打架：四庫工作区那份 vol01 是 18 行精简版，
    盖住引擎仓 59 行的完整版，`references` 段静默丢掉——而它的 `align_ref`
    产物明明跑出来了。这种「改了没反应 / 声明莫名其妙少一块」的坑不该留。
    """
    if books_dir is not None:
        return books_dir / f"{book_id}.yaml"
    ws_dir = _workspace_books_dir()
    if ws_dir is None:
        raise FileNotFoundError(
            f"没设 GUJI_WORKSPACE，找不到册 {book_id} 的定义。"
            f"册配置只读工作区的 books/（2026-09-15 起），"
            f"跑真书前先 export GUJI_WORKSPACE=/path/to/<书>-workspace")
    return ws_dir / f"{book_id}.yaml"


def load_book(book_id: str, books_dir: Path | None = None) -> BookSpec:
    path = _book_yaml_path(book_id, books_dir)
    if not path.exists():
        raise FileNotFoundError(f"没有这册书的定义: {path}")
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    raw_dir = Path(d["raw_dir"])
    if not raw_dir.is_absolute():
        # 相对路径优先按工作区解释（原图已随书迁到 siku-zongmu-workspace），
        # 没设 GUJI_WORKSPACE 时退回仓根——引擎自带的小样本仍在仓内。
        from .workspace import raw_root
        raw_dir = raw_root() / raw_dir
    return BookSpec(
        id=d.get("id", book_id), title=d.get("title", book_id), raw_dir=raw_dir,
        raw_pattern=d.get("raw_pattern", "{page}.png"),
        # yaml 里显式写 null = 现代链「由探测给」，不是「没写、用默认」——两者要分开：
        # 没写走刻本默认（9 / 21），写了 null 就是 None。2026-09-15 加，见三模式方案 §六.1。
        expected_cols=(None if "expected_cols" in d and d["expected_cols"] is None
                       else int(d.get("expected_cols", 9))),
        chars_per_line=(None if "chars_per_line" in d and d["chars_per_line"] is None
                        else int(d.get("chars_per_line", 21))),
        edition=d.get("edition", "keben"),
        dev_set=[int(p) for p in d.get("dev_set", [])],
        sets={str(k): [int(p) for p in v]
              for k, v in (d.get("sets") or {}).items()},
        jiazhu=dict(d.get("jiazhu") or {}),
        bottom_gap=(None if d.get("bottom_gap") is None else float(d["bottom_gap"])),
        period_prior=(None if d.get("period_prior") is None else float(d["period_prior"])),
        pages=_expand_pages(d.get("pages")),
        preclean=_load_preclean(d.get("preclean")),
        notes=d.get("notes", ""),
        ocr_candidates=bool(d.get("ocr_candidates", False)),
        references=[dict(r) for r in (d.get("references") or [])],
        writing_mode=str(d.get("writing_mode", "vertical-rl")),
        frame=str(d.get("frame", "ruled")),
        script=str(d.get("script", "trad")),
        pitch_prior=(None if d.get("pitch_prior") is None else float(d["pitch_prior"])),
        page_split=dict(d.get("page_split") or {}),
        leaf_layout=str(d.get("leaf_layout", "single")),
        top_band_frac=(None if d.get("top_band_frac") is None else float(d["top_band_frac"])),
        bottom_band_frac=(None if d.get("bottom_band_frac") is None
                          else float(d["bottom_band_frac"])),
        column_grid=bool(d.get("column_grid", False)),
        col_pitch=(None if d.get("col_pitch") is None else float(d["col_pitch"])),
        vline_polyline=bool(d.get("vline_polyline", True)),
        font=dict(d.get("font") or {}),
    )


def list_books(books_dir: Path | None = None) -> list[str]:
    """工作区 `books/` 里的册（显式传 `books_dir` 则只看它）。

    2026-09-15 起**不再并上引擎仓那份**：并集会让每个工作区都看见别的工作区的册
    （切到北行日錄还列着十册四庫，页数全 0、产物全空），也是两份 yaml 打架的由来。
    """
    d = books_dir if books_dir is not None else _workspace_books_dir()
    if d is None or not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


_OCR_CANDIDATES_LINE_RE = re.compile(r"^ocr_candidates:\s*(true|false)\s*$", re.MULTILINE)


def set_ocr_candidates(book_id: str, enabled: bool, books_dir: Path | None = None) -> None:
    """定向文本编辑 book yaml 的顶层 `ocr_candidates:` 字段，写控制台的
    开关用。这份 yaml 满是手写中文注释（版本考据、专项集来由等），用
    `yaml.safe_dump` 整体重写会把这些注释全部冲掉，所以只在原文里
    改/插这一行，不碰其余内容。"""
    path = _book_yaml_path(book_id, books_dir)
    if not path.exists():
        raise FileNotFoundError(f"没有这册书的定义: {path}")
    text = path.read_text(encoding="utf-8")
    line = f"ocr_candidates: {'true' if enabled else 'false'}"
    if _OCR_CANDIDATES_LINE_RE.search(text):
        text = _OCR_CANDIDATES_LINE_RE.sub(line, text, count=1)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")
