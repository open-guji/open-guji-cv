"""IDS 路在线判别（字组统一流程 `group_flow` 的 `ids` 解法，方案 S7，2026-10-18 sheldon 定接进流水线）。

一格字块灰度图 → 自动缝切开 → 决定字的那一段在**冻结模板库**里最近邻 → margin 够、该类刻例够才给字，否则弃权。
算法就是离线评测用的 `ids_two.solve_two`（參㕘叅 ⿱厽X 一刀），本模块只做三件事：

1. **每组判法**（`SPECS`）：切向、缝先验、拼 IDS 的框、门槛（`min_margin`、每类至少 `min_class` 个刻例才许给该类）。
   门槛由人标池留一评测定（`python -m open_guji_cv.groups.ids_online loo <组> --dataset <dataset>`），目标给字格 0 错。
   没在这里登记的组（或登记了但没有模板库）→ 一律弃权 `abstain:no_bank`，流程照旧往下走。
2. **模板库冻结成文件**：从 dataset 人标池（`char-groups/variant/<组>/labels.jsonl` ＋ `crops/`）离线建，
   每个模板是归一化 32×32 墨迹图量化成 uint8，存 json（base64，键排序，可复现）。位置按顺序找：
   工作区 `config/groups/ids/<组>.json`（某书自己的池）→ 仓里 `config/groups/<组>/ids_bank.json`（殿本池）。
   建库是一次显式动作：`python -m open_guji_cv.groups.ids_online build <组> --dataset <dataset>`。
3. **指纹**：`fingerprint(组…)` ＝ 每组「判法参数＋模板库内容哈希＋`ids_override.tsv`＋`ids_lv1.txt`」的哈希，
   进 `seed_admit.group_flow_fingerprint`；扩池重建模板库 → 开了的册判过期，不开的册不受影响。

输入的字块与人标池同源：池里的 `crops/` 是二值页按 `bbox_page` 重裁，在线是 Step4 `char_patch`（灰度），
两边过 `ink_of`（<128）后墨迹几乎一致（vol04 同格实测 IoU 0.997–1.0），所以模板直接复用。
分层 L2：只依赖 numpy、PIL（经 `ids_parts`）与 `core.workspace`。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .protocol import GroupVerdict

VERSION = 1
_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class IdsSpec:
    """一组的在线 IDS 判法（两段版，见 `ids_two`）。"""
    frame: str                  # 拼 IDS 的框，如 `⿱厽{}`
    orient: str                 # "h" 上下切／"v" 左右切
    prior: float                # 自动缝的先验位置（占图高／宽）
    which: int = 1              # 决定字的是第几段（1＝下／右）
    min_margin: float = 0.02    # 第一名减第二名不到这个数就弃权
    min_class: int = 8          # 某类模板（真实刻例）少于这个数，判成它也弃权
    by_form: bool = False       # True：模板按成员字分类（不经 IDS 拼字），切下的那一段直接和各字的同段比；
                                # 用于两字差别不落在同一 IDS 部件上的异体对（叙敘、冊册、教敎，2026-10-20）
    three: bool = False         # True：彝组三段版（`ids_solver.solve`）：自动缝切上／中／下三段、中段再竖切取右半，
                                # 每段二选一后拼 `⿳上⿰米X下` 交 IdsResolver；任一段 margin 不够整格弃权
    top_hog: float | None = None  # 三段版：给了数，上段（彑／彐）改用窗口 HOG＋岭回归（不依赖上／中缝），|判别值| 不到它弃权
    nearest_ok: bool = False      # 三段版：IDS 无对应码位只能归近似字（nearest_variant 旗）时照样给字（彝：彑米糸大 ≡ 𢑴，sheldon 10-20 定）
    bot_hog: float | None = None  # 三段版：同上，下段（廾／大）用下部窗口 HOG＋岭回归
    mid_hog: float | None = None  # 三段版：给了数，中段（糸／分）改用 HOG＋岭回归判别，|判别值| 不到它弃权（上下段仍用 min_margin）
    unet: str = ""              # 三段版：给了文件名（如 `unet.npz`，在组的 config_dir），三条缝改用 U-Net 切（纯 numpy 推理，不要 torch），
                                # 三段都用 HOG＋岭回归认切出的部件，不用窗口；权重缺失 → 整格弃权 abstain:no_model（2026-10-21：按册留出 U-Net 错 1／窗口法错 5）
    whole: str = ""             # "pix"|"hog"：整字二类岭回归（`ids_whole`，不切缝；差别不在缝两侧的两字异体：呂吕、徵徴），
                                # `min_margin` 当作判别值绝对值的门槛；非空时 frame/orient/prior/which 不用
    region: tuple = (0.0, 1.0, 0.0, 1.0)  # 整字版：取归一字块的哪一块（占宽高的 x0,x1,y0,y1）
    lam: float = 1.0            # 整字版：岭回归的 L2 系数
    size: int = 32              # 整字版：模板与在线字块归一后的边长（模板库里也写一份）
    clean: bool = False         # 整字版：判之前先去邻格碎墨（`ids_whole.clean_patch`）；模板建库时须同样清理（2026-10-22）
    aspect: tuple = ()          # 整字版：字块宽高比须在 (lo, hi) 内，否则弃权 abstain:aspect（连进邻字的块）
    give: str = ""              # 整字版：非空＝只许给这几个字；判成其余成员也弃权 abstain:not_given（成员只当入口，库本来就认得的字不由本组给；
                                # 广宀族只给 賔賓，2026-10-24）
    generic: bool = False       # True：通用判法（`ids_generic`）：切法与判别叶子由成员 IDS 导出（`ids_plan`），缺省形状先验折线切、
                                # 给了 `unet` 改用 U-Net；模板与在线格同一切法切，最近邻；frame/orient/prior/which/by_form 不用（2026-10-22）
    sub_prior: float | None = None  # 两段版：给了数＝第二刀（`ids_two.part_of`）：切下的段再在墨迹框内按这个先验找缝，只比缝后一小块
                                # （參㕘叅 去掉「人」只比 彡／小／𠇍，2026-10-26）；模板库须同样取法
    dual: float = 0.0           # 两段版：>0＝两路一致才给字（2026-10-26，參㕘叅）：IDS 给了字，还要整字 HOG 岭回归（模板库 `whole_bank.json`，
                                # 与 ids_bank.json 同目录，参数用本行的 size/region/lam/clean）判成同一字、判别值 ≥ 这个数，否则弃权


#: 已过离线评测、允许在线给字的组。每组的门槛与评测数字写在该行注释里（重评：`loo` 子命令）。
SPECS: dict[str, IdsSpec] = {
    # 參㕘叅：人标池 74 格（參 35／㕘 37／叅 2），自动缝。留一：margin 0.02 → 65 对／9 弃权／0 错，0.04 → 59／15／0；
    # 留一册（模板不含本册）：0.02 → 64／10／0，0.04 → 57／17／0；不设门槛时两格错（vol04 參→㕘），池图 margin 0.019、0.004，
    # 换成线上 char_patch 是 0.026、0.022（同格两种图 margin 差可到 ±0.018）。所以取 0.04（宁可弃权）。叅不足 8 例，永不给。
    # 2026-10-26（A24「压低參㕘叅送审」）：vol21 起刻 叅（钩右一点一撇两笔）的格多，旧库只 2 例 叅，把它们判成 㕘 降审（vol21–99 共 126 格）。
    #   全书小族 722 格看图补标（dataset variant/can/claude_labels_1026.jsonl：㕘 258／叅 364）＋已放行 參 80（库压在 1MB 内），字块用线上 char_patch，
    #   单一方法按册留出都有高把握错（整字 HOG 错例到 1.5、IDS 一刀 0.1），改两刀（第二刀去「人」只比最下块）＋整字 HOG 两路一致：
    #   按册留出 702 格，整字 ≥0.4 且 IDS ≥0.03 起 0 错（两路同判错的最高 整字 1.38 但 IDS 只 0.011、IDS 最高 0.050 但整字 0.37）；
    #   取 整字 0.55、IDS 0.04 → 给 503（叅 273／㕘 155／參 75）、0 错。
    #   建库 research/m7/glyph_expand/build_can_dual.py。见 doc/字组/can.md。
    "can": IdsSpec(frame="⿱厽{}", orient="h", prior=0.52, min_margin=0.04, sub_prior=0.45, dual=0.55, size=32, clean=True),
    # 以下几组（2026-10-20）：模板＝sheldon 合审裁过的殿本 vol04–10 格（中心库 confirm 事件），按字分类（by_form）。
    # 教敎（2026-10-21，sheldon 提示「差别在左上角」）：**整字里只取左上角一块做 HOG**（region 左 0–55%、上 0–46%，sheldon 在取框页调的）＋岭回归，
    #   整字／U-Net 切部件／自动缝三法此前都不行（给字格 0 错覆盖 ≤8%）。dataset `jiao/labels.jsonl` 93 格（教 68／敎 25，含 vol01 四格教→敎更正）按册 5 折留出：
    #   margin 0.4 → 87 对／6 弃／0 错（0.3 → 89／4／0，唯一错例 margin 0.23）。字块归一到 48×48 再取框（32 太小，框内取不到 HOG 块）。
    #   **2026-10-22 改通用判法**（`ids_generic`，叙敘、絕絶 同）：计划导出 ⿰{}攵、判别叶子在左部里，先验折线切左右、再切到叶子，模板＝全部 93 格同法切出，最近邻。
    #   按册 5 折留出（先验形状与模板都不含留出册）：margin 0.02 → 92 对／1 弃／0 错，0.03 → 91／2／0（唯一错例 margin 0.0199），取 0.03。
    "jiao": IdsSpec(frame="", orient="v", prior=0.5, min_margin=0.03, min_class=8, generic=True),
    # 旨㫖（2026-10-22）：整字 HOG＋岭回归。模板取自 R2 整册产物（殿本 vol01、04–10）的对位文字，其中 18 个标成旨的被 sheldon 更正为㫖（对位文字旨/㫖有错），
    #   裁坏的 3 格已去掉。dataset `zhi/labels.jsonl` 353 格（㫖 283／旨 70）按册 5 折留出 353 对／0 错。
    "zhi": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=0.3, size=32),
    # 叙敘（2026-10-21，sheldon 指出旧窗口法不对）：真正的差别在右部（又／攵），旧规格取的是「上 40%」。改成 **U-Net 切左右、取右部**（by_form）：
    #   dataset `xu/labels.jsonl` 30 格人标切线（叙 11／敘 19）；U-Net 用叙敘＋教敎＋絕絶 共 106 格左右切线一起训（同是「两部件之间一刀」，
    #   `unet.npz`，纯 numpy 推理）。按册 5 折留出（U-Net 与模板都不含留出册）：墨迹像素归段准确率 0.992（旧自动缝 0.965）；
    #   识别给字格 0 错时覆盖率 87%（旧自动缝 33%，整字 hog 87%）；门槛 0.075 刚好 0 错，取 0.1 留余量。
    #   **2026-10-22 改通用判法**：计划导出 ⿰余{}，先验折线切（不用 U-Net）、取右部，模板与在线格同一切法。按册 5 折留出 30 格：
    #   不设门槛 0 错（21 对，9 格因留出后 叙 模板不足 8 例弃权；全库 叙 11 例，线上不受此限）；旧 U-Net 在同口径下 0 错覆盖 57%。取 0.02 留余量。
    "xu": IdsSpec(frame="", orient="v", prior=0.5, min_margin=0.02, generic=True),
    # 絕絶（2026-10-21）：差别在右部笔画细节，旧窗口 23%、U-Net 部件 31%、**整字 hog 44%**（按册 5 折留出，0 错覆盖率）→ 整字 hog；
    #   门槛：0 错门槛 0.50，取 0.6。39 格（絕 15／絶 24）。
    #   **2026-10-22 改通用判法＋细 IDS**（sheldon 定：絕 ⿰糸⿱刀巴、絶 ⿰糸⿱⺈巴，`ids_fine.tsv`）：判别叶子＝右部「色」的上半（刀／⺈），
    #   U-Net（只用本组 39 格人标切线训，`unet.npz`）切左右、自动缝再切到叶子，最近邻。按册 5 折留出：margin 0.04 → 24 对／15 弃／0 错
    #   （最大错例 margin 0.033；先验折线版 0.06 才 0 错、19 对），取 0.05 → 23／16／0（0 错覆盖 59%，旧整字 hog 44%）。
    "jue": IdsSpec(frame="", orient="v", prior=0.5, min_margin=0.05, min_class=8, generic=True, unet="unet.npz"),
    # 厯歴（2026-10-21）：差别在下部（心 vs 止），旧左右窗口按册留一有错一直没登记；整字 hog 按册留出 122 格错 3，0 错覆盖率 81%（pix 71%）。
    #   0 错门槛 0.50，取 0.6。
    "lih": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.25, min_class=8, whole="hog", region=(0.0, 1.0, 0.5, 1.0), lam=1.0, size=48),
    # 啓啟（2026-10-21）：啓是「户攵」在上口在下，啟是「启」在左攵在右，结构不同、整字分布差得大，不切。整字 pix：24 格（啓 8／啟 16，只 vol01、vol04 两册）
    #   留一格 24/24、按册留出也全对；样本少，取 0.5，啓 刚好 8 例，待补采。
    "qik": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="pix", lam=1.0, size=32),
    # 冊册：独体字，IDS 切不开（sheldon 2026-10-21 定）→ 不在 IDS 路，另想办法。
    # 彝彛彜彞𢑱𢑴（2026-10-20，sheldon 定上线）：42 格人标三段读法（dataset yi_560/user_parts_labels），自动缝（band 0.08、pull 2.0）。
    # 留一：margin 0.04 → 23 对／19 弃权／0 错（覆盖 55%）；0.02 有 5 错、0.0 有 8 错，所以取 0.04。
    # 第二轮（sheldon 10-20 追问「剩下的为什么分不开」）：13 个弃权里 11 个三段其实读对了，只是 margin 不够——
    # 上段 彑／彐 只差左上一个小钩，自动缝常把上段笔画从中间切开（近邻 margin 0.00–0.04）；中段 糸／分 近邻留一 5/42 错。
    # 改法：三段都用 HOG＋岭回归（ids_parts.choose_hog，模板即训练集）；上段、下段不用缝，取墨迹外框的比例窗口
    # （ids_solver.TOP_WIN／BOT_WIN，bank 的 4|、5| 槽）。留一：34 对／8 弃权／0 错（覆盖 81%）；
    # 8 个弃权中 6 个是读对了但 Unicode 无此组合（彑米糸大，nearest 旗）；sheldon 10-20 定「彑米糸大 ≡ 𢑴，不用人审」→ nearest_ok：
    # 加上后 40 对／2 弃权／0 错（覆盖 95%）。
    # 第三轮（10-20 sheldon 补点 40 格部件读法，共 82 格）：中段也改比例窗口（MID_WIN，bank 的 6| 槽），不再依赖任何缝；
    # 三段都是「窗口＋HOG＋岭回归」，82 格留一**三个槽全部读对**（竖缝版中段 1–3 错）。门槛取 0.05（全对，只是给新数据留保护）：
    # 82 对里 79 格给字、3 格 margin<0.05 弃权，0 错；0.1 → 77 格，0.2 → 71 格。
    # 第四轮（10-21，sheldon 指出窗口法的参数和模板都在同一批 82 格上选，留一偏乐观）：改**按册留出**——留出一册，窗口参数／U-Net／模板
    # 都只用其余九册：窗口法错 5 格（上段 4、中段 1，多数把握不低），**U-Net 切分 + HOG 岭回归只错 1 格**（vol05:74:7:10 极黑，把握 0.018 < 0.05 会弃权）。
    # 所以线上改 U-Net 切三段（unet.npz，约 1.1MB，纯 numpy 推理）；窗口槽不再进库。
    # 第五轮（A24 2026-10-26，全 99 册）：下段（廾／大，看图最好认）门槛 0.05 → 0.3。整理本有字的 651 格逐格对照，
    #   下段读错的只 vol45:59:4:20（大 读成 廾，margin 0.16，整理本 彛 也跟错）；其余对不上的下段看图都是 U-Net 对。
    "yi_560": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.04, min_class=2, three=True,
                         top_hog=0.05, mid_hog=0.05, bot_hog=0.3, nearest_ok=True, unet="unet.npz"),
    # 呂吕、徵徴（2026-10-20，道 1 续）：按字分类（缝两侧无差别）改整字岭回归（`ids_whole`），模板＝殿本 vol01–10 人裁 confirm 事件格
    # （吕 48／呂 22、徵 34／徴 41；建库见 research/m7/lane1/build_whole_bank.py，评测同脚本，按册留一＝判某册时模板不含该册）：
    # 呂吕 pix 32×32、λ=1：|d|≥0.5 → 62 对／8 弃权／0 错（≥0.3 68 对 2 弃权 0 错，不设门槛也 0 错；取 0.5 留余量）。
    #   模板里 vol07:4:4:21 按 sheldon 复看改为呂（原人裁吕，墨浓两口被粗笔连上；更正写在建库脚本 CORRECTIONS）。
    # 徵徴 hog（取字块 x 0.28–0.78、y 0.15–0.65）80×80、λ=3：|d|≥0.6 → 38 对／37 弃权／0 错（≥0.5 46 对 0 错，≥0.4 55 对 0 错，≥0.3 1 错；
    #   换尺寸、λ、区域，0.6 处都是 0 错，所以取 0.6）。徵徴 不设门槛只有 87–92% 对，别放宽。
    # 2026-10-22 放低（sheldon 同意）：判别台复核（research/m7/bench/check_prod.py）发现的两格线上门槛之上的「错」是原人裁错
    #   （vol02:125:8:4 实为吕、vol01:70:7:10 实为徴，sheldon 看图定，数据集与中心库已更正）。更正后按册留一：
    #   呂吕 0.3 → 68 对／2 弃／0 错（无错例）；徵徴 0.45 → 49 对／26 弃／0 错（错例最大 0.336，留 0.11 余量）。
    # —— 文意组的字形第二路（2026-10-22，sheldon「能不能再进一步优化算法」）：整字／取框 HOG＋岭回归，`clean`＋`aspect`。
    #   模板＝数据集人裁格＋殿本 vol04–10 已放行格（每册每字 ≤20，放行字当标签），字块全是线上同款 char_patch、去碎墨后建库
    #   （research/m7/bench/build_ctx_bank.py）；尺寸与取框由判别台按册嵌套留出选（bench.py --only-crops）。
    #   门槛（research/m7/bench/ctx_glyph2.py，按册留一）：人裁格 0 错、且已放行格上与放行字不同的 ≤0.2%，取两者较高者 ×1.1，最低 0.4。
    #   注释里「人裁 a/b、放行 同 c/d 异 e」是该门槛下按册留一的数（放行异议逐格读过上下文，多为字形错判）。
    #   不上的组：大太 未末 王玉 目自 千干 十卜（差一小笔，留出覆盖太低）、戊戌戍（戍 不足 8 例，会把戍判成戊／戌）、木本（人裁不足）。
    "rr": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.66, min_class=8, whole="hog", region=(0.0, 1.0, 0.0, 0.5),
                  size=48, clean=True, aspect=(0.45, 2.2)),          # 人裁 42/48，放行 同 1817/1846 异 2
    "ts": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.44, min_class=8, whole="hog", region=(0.0, 0.5, 0.0, 1.0),
                  size=32, clean=True, aspect=(0.45, 2.2)),          # 人裁 17/29，放行 同 409/414 异 0
    "ly": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.66, min_class=8, whole="hog", region=(0.25, 0.75, 0.5, 1.0),
                  size=32, clean=True, aspect=(0.45, 2.2)),          # 人裁 21/40，放行 同 518/614 异 0
    "wj": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.59, min_class=8, whole="hog", region=(0.25, 1.0, 0.25, 1.0),
                  size=48, clean=True, aspect=(0.45, 2.2)),          # 人裁 29/37，放行 同 225/268 异 0
    "zh": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.4, min_class=8, whole="hog", region=(0.25, 1.0, 0.0, 0.5),
                  size=32, clean=True, aspect=(0.45, 2.2)),          # 人裁 104/104，放行 同 77/77 异 0（只判 曾／會 族；會㑹 形判不用它）
    "yh": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.4, min_class=8, whole="hog", size=32, clean=True,
                  aspect=(0.45, 2.2)),                               # 人裁 21/24，放行 同 61/61 异 0
    "yt": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.51, min_class=8, whole="hog", region=(0.25, 1.0, 0.0, 1.0),
                  size=32, clean=True, aspect=(0.45, 2.2)),          # 人裁 19/32，放行 同 608/693 异 1
    "js": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", size=32, clean=True,
                  aspect=(0.45, 2.2)),                               # 人裁 40/40，放行 同 120/120 异 0；抽样页 vol06:15:6:13（组外字，sheldon 判其他）判申 0.454，故 0.4→0.5
    "em": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.4, min_class=8, whole="hog", region=(0.0, 1.0, 0.5, 1.0),
                  size=32, clean=True, aspect=(0.45, 2.2)),          # 人裁 21/21，放行 同 1718/1719 异 1
    "fc": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.8, min_class=8, whole="hog", region=(0.0, 1.0, 0.25, 0.75),
                  size=48, clean=True, aspect=(0.45, 2.2)),          # 人裁 9/30，放行 同 1034/1473 异 0
    "yr": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.87, min_class=8, whole="hog", size=32, clean=True),
                                                                     # 人裁 17/21，放行 同 2633/2794 异 5；不查宽高比（「一」本来就扁）
    # 象／𧰼（2026-10-22，sheldon 指「中间这一块有明显区别」）：只用于 象彖𧰼 组「象族」的形判（族内 象／𧰼），不进组级方法。
    #   判别区＝左半中段 (x 0–0.5, y 0.125–0.625)，64×64；模板只用人裁（象 153／𧰼 13，不收已放行格：里面混着约 1.5% 𧰼）。
    #   按册留一：𧰼 判成象的最大 margin 0.92 → 取 1.0，象 约四成给字、0 错；𧰼 不足 20 例（min_class=20）永不自动给，一律人审。
    #   2026-10-26（A24 全册任务 08）：sheldon 在标注页点了 173 格（vol11–99 送审格＋已放行疑似放错格），模板改为 象 129／𧰼 178
    #   （人裁表 dataset variant/xz/sheldon_labels.jsonl，线上同款 char_patch）。字形单判按册留出仍过不了 0 错（最大错 1.47），
    #   所以组里加 `lift_ref_agree`：字形与整理本（缺位用坐标对位字）同字才补放。一致格按册留出：λ=3 错 1（vol05:89:1:10
    #   整理本作象、人裁 𧰼、判象 0.20），门槛取 0.3 → 给 象 59／𧰼 118、0 错（research/m7/glyph_expand/eval_xz.py）。
    "xz": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.3, min_class=20, whole="hog", region=(0.0, 0.5, 0.125, 0.625),
                  lam=3.0, size=64, clean=True, aspect=(0.45, 2.2)),
    "lv": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.3, min_class=8, whole="pix", lam=1.0, size=32),
    # 徵徴 zheng 2026-10-27 撤下（sheldon 定暂归一到 徴，改码位组）；模板库 config/groups/zheng/ids_bank.json 留作日后拆分
    # 子于、山由出（2026-10-21，未覆盖形近字长尾线）：整字 HOG＋岭回归，模板＝殿本 vol04–10 seed_admit 放行格（match_ref、无疑问，
    # 建库与评测见 research/m7/long_tail/build_bank.py）；组外的 干／曲 也进库（判成它们＝abstain:slot），免得真干、真曲被硬判进组。
    # 子于：按册留一 0 错（|d|≥0.3 起；子 250／于 91／干 若干；唯一的错是 3 个予，予不进组、也不进 tolerate）；门槛取 0.4。
    # 山由出：一对多岭回归（判别值＝与第二名得分差），|d|≥0.8 → 0 错，覆盖约 97%（≥0.5 起出现 1 错）；门槛取 0.8。
    "zy": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.4, min_class=8, whole="hog", lam=1.0, size=32),
    "sy": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.8, min_class=8, whole="hog", lam=1.0, size=40),
    "sz": IdsSpec(frame="", orient="h", prior=0.5, min_margin=1.0, min_class=8, whole="hog", lam=1.0, size=40),
    "gm": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.8, min_class=8, whole="hog", lam=1.0, size=40),
    "xb": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.4, min_class=8, whole="hog", lam=1.0, size=32),
    # 衛衞、刪删、扺抵（2026-10-22，字形判法扩面）：模板＝dataset `labels/unified.jsonl` 里 sheldon 人裁刻形（衛41／衞14、刪111／删5、抵90／扺10，
    # 字块图来自 `variant/{wei,shan,di}/crops`），取框 HOG＋岭回归，按册留出（判某册时模板不含该册）。次形太少，只当「放主形」用：
    # 次形（衞／删／扺）在留出里几乎都落在门槛下弃权，不会被放成主形（0 错），要靠人审。框与参数在 0.25 网格上扫、取 0 错覆盖最高处的邻近稳健值：
    # 衛衞 取框 x0.25–0.75、y0.5–1（0 错门槛 0.55，取 0.7 → 衛 37／55 给对）；刪删 取左下 x0–0.5、y0.5–1（册／冊 的下半，0 错门槛 0.74，取 0.85 → 97／116）；
    # 扺抵 取 x0–0.75、y0.5–1（0 错门槛 0.41，取 0.55 → 78／100，其中扺 0）。
    # 禽會俞命舍（2026-10-22）：曾會㑹 里 sheldon 点「其他」的 14 格多半是禽（库形把它当會）。一对多整字 HOG（不取框，48×48，λ=0.3），
    #   模板＝殿本 vol04–10 seed_admit 放行格（命／會／合 各取 60，曾 37、愈 28、舍 25、俞 13）＋禽 11（放行里 witness3 的 10 格＋看图预填 1，sheldon 10-22 已确认，
    #   dataset variant/glyph_expand_1022）；曾 合 愈 进库但不是组员，判成它们＝弃权。含 与 舍 在放行里混用，不进库。按册留出：成员格 150 对／19 弃／0 错（0 错门槛 0.18，取 0.5）。
    "qin": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=0.3, size=48),
    # 口框族 國圖圍園固圓圜（2026-10-24，A24）：模板＝殿本 vol04–20 已放行格（每册每字 ≤12、每字总共 ≤30，放行字当标签）＋人裁刻形，
    #   圃 圈 囿 当陪衬；看图剔掉切坏的 4 格和标签错的 1 格（`build_shape_pair.PLAN["kou"]`）。字块是线上同款 char_patch（`--char-patch`）。
    #   只取框内（x 0.12–0.88、y 0.1–0.9），64×64：试过整字 32／40／48 和框内 40／48，圓→圖、圜→園 的错例都更多。
    #   评测：vol04–20 全部已放行成员格 2,996 格按册留出（判某册时模板不含该册）：0 错门槛 0.90，取 1.0 → 给字 2,304（77%）、0 错。
    #   清楚的 國 也偶有 0.7–0.9 判成 圓，所以组里另加 `lift_ref_agree`（须与整理本同字才补放）。
    "kou": IdsSpec(frame="", orient="h", prior=0.5, min_margin=1.0, min_class=8, whole="hog", region=(0.12, 0.88, 0.1, 0.9), lam=1.0, size=64,
                   clean=True, aspect=(0.45, 2.2)),
    "weiw": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.7, min_class=8, whole="hog", region=(0.25, 0.75, 0.5, 1.0), lam=1.0, size=48),
    "shan": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.85, min_class=8, whole="hog", region=(0.0, 0.5, 0.5, 1.0), lam=1.0, size=48),
    "di": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.55, min_class=8, whole="hog", region=(0.0, 0.75, 0.5, 1.0), lam=3.0, size=64),
    "shang": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.95, min_class=8, whole="hog", lam=1.0, size=32, clean=True),
    "gai": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=32, clean=True),
    "ba": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", region=(0.5, 1.0, 0.0, 1.0), lam=1.0, size=48, clean=True),
    # 凖準、宻密（2026-10-24，长尾异体对）：模板同上（已放行格＋人裁，看图剔出码位错的格），建库 build_shape_pair.py。
    # 凖準 只看左半（冫 点＋长提斜穿／氵 三笔竖排），48×48：按册留出不设门槛也 0 错；宻密 整字 48×48（中部 㐅 交叉／必 带两点）：同样 0 错。门槛沿用 0.5。
    "zhun": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", region=(0.0, 0.5, 0.0, 1.0), lam=1.0, size=48, clean=True),
    "mi": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    # 䘮喪（2026-10-25，A24「按 IDS 重核䘮喪㣲微變𠮓」）：中部 从（䘮）／吅（喪），整字 48×48。模板＝殿本 vol04–20 已放行格（每册每字 ≤12）
    #   ＋看图改标（放行成 喪、刻 䘮 的 2 格，送审格 6 格），建库 build_shape_pair.py。按册留出 110 格（喪77 䘮33）不设门槛也 0 错，门槛沿用 0.5。
    #   㣲微 同时试过（中下 口／几）：看图只十几格作 口，取框／整字 HOG 三种设置按册留出 口 都被高把握判成 微（错例 0.9–1.4），分不开，保留码位归一。
    "sang": IdsSpec(frame="", orient="h", prior=0.5, min_margin=1.25, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    # 變𠮓（2026-10-25，A24）：下部 攵（左上多一短撇）对 又。工作区码位归一 變→𠮓 让放行字全成 𠮓，放行字不当标签；
    #   标签全是 sheldon 看图（dataset variant/bian/sheldon_labels.jsonl：變 107、𠮓 624，后者 565 格是「其余下边都是又」未逐格点），
    #   建库 build_shape_pair.py --labels（𠮓 每册 ≤12 → 238）。按册留出 345 格：判成 變 的 0 错（𠮓 从没被判成 變），
    #   判成 𠮓 的有 9 格其实是 變（margin 到 1.1，取区域／尺寸／λ 试了 13 种都 7–43 错）→ 只给 變（give），判 𠮓 弃权＝维持码位归一。
    #   门槛 0.5：按册留出 變 给对 82／107。
    "bian": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True,
                    region=(0.0, 1.0, 0.5, 1.0), give="變"),
    # 广宀族 廣實賔賓宸（2026-10-24，A24）：送审的「蕤賔」賔 库里没有字形，被排成 實廣墳須。整字 HOG 一对多（32×32，λ=1），
    #   类＝成员＋陪衬 17 字（寶寳寅賞墳須煩裒盧資質贋寫竇賁責貴）＋「〇」其他池（35 字），每册每字 ≤3（賔賓 全收），
    #   模板＝殿本 vol04–20 放行格＋人裁＋送审格看图补标（research/m7/glyph_expand/build_guang.py）。只给 賔／賓（`give`）：
    #   按册留出 賔41／賓50，判成 賔賓 的错例最高 0.16（寳→賔），取 0.3 → 给 79（賔36 賓43）、错 0；陪衬与其他池判成 實廣 的不给字。
    "guang": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.3, min_class=8, whole="hog", lam=1.0, size=32, clean=True, give="賔賓"),
    # 部首族（2026-10-24，A24「门族、辶族」）：一对多整字 HOG，模板＝殿本 vol04–20 已放行格（无疑问，每册每字 ≤4、每字 ≤30），
    #   组外常见陪衬字（刪 圖 固 同 國…）也进库，判成它们＝弃权（research/m7/glyph_expand/build_family.py）。补放还须与整理本同字（`lift_ref_agree`）。
    #   門族 整字 48×48，λ=1：按册留出组员格 429，不设门槛错例最大 0.56（閑→閔），取 0.62 → 给字 269、0 错。
    #   辶族 取右上框 x0.25–1、y0–0.8（避开走之底，整字版 邊→選 0.84 高把握错），48×48，λ=1：组员格 870，错例最大 0.59（邊→選），取 0.65 → 给字约 355、0 错。
    "men": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.62, min_class=8, whole="hog", lam=1.0, size=48, clean=True,
                   aspect=(0.45, 2.2)),
    # 形近不同字对族 xjz（2026-10-26，A24「组外异体对未定码位」）：整字 HOG 一对多（每字 ≤12 格），按册留出（组员格 457）不设门槛
    # 错例最大 0.59（熟→孰），门槛取 0.7（0 错，给字 119）。字宇 刻形分不开（错例 1.18）不进族；釆 的刻例全是 采，不进库。补放还须与整理本同字。
    "xjz": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.7, min_class=8, whole="hog", lam=1.0, size=48, clean=True,
                   aspect=(0.45, 2.2)),
    "chuo": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.65, min_class=8, whole="hog", region=(0.25, 1.0, 0.0, 0.8), lam=1.0,
                    size=48, clean=True, aspect=(0.45, 2.2)),
    # 撰𢰅（2026-10-24，3–4 格异体对）：差别在右下（共／丌，𢰅 长撇长捺大开），整字 48×48 按册留出 0 错（取右半反而错多）；门槛沿用 0.5。
    "zhuan": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    # 瑣𤨏（2026-10-25，A24 GUJI-719「异体组纳入形近比对」）：差别在右上（⺌／巛），只取右上框 48×48。
    "suo": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=5, whole="hog", region=(0.4, 1.0, 0.0, 0.5), lam=1.0, size=48,
                   clean=True),
    # 隱𨼆、算𮅕、闗關（2026-10-25，A24 vol21–50 首跑 V 类）：字形库没有少的一形，库排成常见形或别的字；模板＝殿本 vol21–50 已放行格
    #   （每册每字 ≤12）＋送审格看图补标，建库 build_shape_pair.py。门槛与区域见 doc/字组/ 同名卡。
    "yin": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.85, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "suan": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.95, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "guanm": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    # 派𣲖、奇竒、歲嵗（2026-10-26，A24 vol51–99 首跑 V 类）：模板＝殿本 vol51–99 已放行格（每册每字 ≤12）＋陪衬，首轮留出错例看图改标；
    #   按册留出 派𣲖 歲嵗 0.5 起 0 错；奇竒 陪衬 苛 判成 竒 最高 0.91 → 1.0（放行格每字 ≤160）。见 doc/字组/ 同名卡。
    "xuan": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.35, min_class=8, whole="hog", region=(0.25, 1.0, 0.0, 0.8), lam=1.0,
                    size=48, clean=True),
    "fu": IdsSpec(frame="", orient="h", prior=0.5, min_margin=1.2, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "pai": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "qi": IdsSpec(frame="", orient="h", prior=0.5, min_margin=2.0, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "sui": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "mn": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "li": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    # 组外异体对（2026-10-26，A24 全册任务 01，sheldon 定「留人审」＝建组按刻形分）：标签＝HOG 两类聚类、去掉低把握 15% 后看图；门槛见卡。
    "yinv": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "xian": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "shu": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "ning": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "yao": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "jim": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "xun": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "jian": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "chi": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "bi": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "huiq": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    # 勢𫝑、發𤼵（2026-10-26，A24，sheldon 定按刻形分拆）：放行格两形混放，标签全是 sheldon 在标注页逐格过的（dataset variant/{shi,fa}）。
    #   勢𫝑 只差左上 坴／幸，整字 48：按册留出 167 格 0.4 起 0 错，取 0.5（给 122）。
    #   發𤼵 右下 殳／矢，取右下框：按册留出 505 格（含陪衬 登務條）0.5 起 0 错（𤼵 给对 77／80）。见 doc/字组/shi.md、fa.md。
    #   10-26 补 vol51–99：勢𫝑 310 格 0.4 起 0 错，仍取 0.5；發𤼵 660 格最高错例 0.89（vol87:127:7:8 刻 矢、判 殳），门槛提到 0.9。
    "shi": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "fa": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.9, min_class=8, whole="hog", region=(0.4, 1.0, 0.4, 1.0), lam=1.0,
                  size=48, clean=True),
    # 码位已定仍送审的形近族（2026-10-26，A24 全册任务 04）：整理本作 鄉鄕／㣲微／別别／鎭鎮、库首位是形近的另一个字（卿 徵徴 刖則所 鍾愼…）。
    #   两码位并一类，形近字当陪衬进库（判成它们＝弃权），整字 48×48 一对多。门槛按册留出定，见 doc/字组/ 同名卡。
    "xiang": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "weim": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", region=(0.2, 0.75, 0.2, 1.0), lam=1.0,
                    size=48, clean=True),
    "bie": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.4, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
    "zhen": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="hog", lam=1.0, size=48, clean=True),
}


def bank_path(g: str) -> Path | None:
    """组 `g` 的模板库文件：工作区 `config/groups/ids/<g>.json` 优先，其次仓里 `<config_dir>/ids_bank.json`；都没有 → None。"""
    from ..core.workspace import ws_config_dir
    from .registry import FLOW_GROUPS as GROUPS
    cfg = ws_config_dir()
    if cfg is not None and (cfg / "groups" / "ids" / f"{g}.json").exists():
        return cfg / "groups" / "ids" / f"{g}.json"
    spec = GROUPS.get(g)
    if spec is not None and spec.config_dir and (_ROOT / spec.config_dir / "ids_bank.json").exists():
        return _ROOT / spec.config_dir / "ids_bank.json"
    return None


def whole_bank_path(g: str) -> Path | None:
    """两路一致（`IdsSpec.dual`）的整字模板库：工作区 `config/groups/ids/<g>.whole.json` 优先，其次仓里 `<config_dir>/whole_bank.json`。"""
    from ..core.workspace import ws_config_dir
    from .registry import FLOW_GROUPS as GROUPS
    cfg = ws_config_dir()
    if cfg is not None and (cfg / "groups" / "ids" / f"{g}.whole.json").exists():
        return cfg / "groups" / "ids" / f"{g}.whole.json"
    spec = GROUPS.get(g)
    if spec is not None and spec.config_dir and (_ROOT / spec.config_dir / "whole_bank.json").exists():
        return _ROOT / spec.config_dir / "whole_bank.json"
    return None


def has_bank(g: str) -> bool:
    return g in SPECS and bank_path(g) is not None


# —— 模板库文件 ——

def _enc(t: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(t, dtype=np.uint8).tobytes()).decode("ascii")


def _dec(s: str, size: int) -> np.ndarray:
    a = np.frombuffer(base64.b64decode(s), dtype=np.uint8).reshape(size, size)
    return a.astype(np.float32) / 255.0


def quantize(t: np.ndarray) -> np.ndarray:
    """归一部件图（0–1 float）→ uint8；评测与建库同一量化，线上读回来与评测时一模一样。"""
    return np.clip(np.round(np.asarray(t, dtype=np.float32) * 255), 0, 255).astype(np.uint8)


def dump_bank(group: str, templates: dict, source: dict, size: int = 32) -> dict:
    """`templates = {部件名: [归一部件图,…]}` → 可写盘的 dict（部件名排序，模板保持输入顺序）。"""
    return {"version": VERSION, "group": group, "size": size, "source": source,
            "templates": {k: [_enc(quantize(t)) for t in templates[k]] for k in sorted(templates)}}


def write_bank(d: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")


@lru_cache(maxsize=16)
def _load_cached(path: str, digest: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("version") != VERSION:
        raise ValueError(f"IDS 模板库 {path} 版本 {d.get('version')!r}，要的是 {VERSION}")
    size = int(d.get("size") or 32)
    return {k: [_dec(s, size) for s in v] for k, v in (d.get("templates") or {}).items()}


def load_bank(path: str | Path) -> dict:
    """→ `{部件名: [模板图(float 0–1),…]}`。按内容哈希缓存，文件换了自动重读。"""
    p = Path(path)
    return _load_cached(str(p), hashlib.sha256(p.read_bytes()).hexdigest())


@lru_cache(maxsize=16)
def _resolver(g: str):
    from .ids import IdsResolver
    from .registry import FLOW_GROUPS as GROUPS
    spec = GROUPS[g]
    return IdsResolver(sorted(spec.members), _ROOT / (spec.config_dir or f"config/groups/{g}"))


# —— 指纹 ——

def _sha(p: Path | None) -> str:
    if p is None or not p.exists():
        return "missing"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def fingerprint(groups) -> str:
    """点名组里登记了在线判法的，各取「判法参数＋模板库＋覆盖表＋IDS 总表」哈希；没有就空串（不改旧指纹）。"""
    from .ids import IDS_TABLE
    from .registry import FLOW_GROUPS as GROUPS
    parts = []
    for g in sorted(set(groups)):
        if g not in SPECS or g not in GROUPS:
            continue
        sp = GROUPS[g]
        ov = _ROOT / (sp.config_dir or f"config/groups/{g}") / "ids_override.tsv"
        d = asdict(SPECS[g])
        if not d["generic"]:
            d.pop("generic")            # 新字段缺省值不进哈希：不用通用判法的组指纹不变
        if not d["give"]:
            d.pop("give")
        if d["sub_prior"] is None:
            d.pop("sub_prior")
        if not d["dual"]:
            d.pop("dual")
        spec = hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
        fine = _ROOT / (sp.config_dir or f"config/groups/{g}") / "ids_fine.tsv"
        parts.append(f"{g}={spec}.{_sha(bank_path(g))}.{_sha(ov)}" + (f".u{_sha(unet_path(g))}" if SPECS[g].unet else "")
                     + (f".f{_sha(fine)}" if SPECS[g].generic else "") + (f".w{_sha(whole_bank_path(g))}" if SPECS[g].dual else ""))
    if not parts:
        return ""
    return "ids:" + ",".join(parts) + f",lv1={_sha(IDS_TABLE)}"


# —— 判 ——

def judge_with(g: str, gray: np.ndarray, bank: dict, spec: IdsSpec | None = None, net=None, whole: dict | None = None) -> GroupVerdict:
    """用给定模板库判一格（评测与线上共用）。给字条件：IDS 对上组内成员、margin ≥ `min_margin`、该类模板 ≥ `min_class`；
    `spec.dual` 时另要整字库（`whole`，缺省读 `whole_bank_path`）判成同一字。"""
    from .ids_two import solve_two
    from .registry import FLOW_GROUPS as GROUPS
    spec = spec or SPECS[g]
    members = GROUPS[g].members
    if spec.generic:
        return _judge_generic(g, gray, bank, spec, members, net=net)
    if spec.three:
        return _judge_three(g, gray, bank, spec)
    if spec.whole:
        return _judge_whole(gray, bank, spec, members)
    if spec.by_form:
        return _judge_by_form(gray, bank, spec, members, g=g, net=net)
    arr = np.asarray(gray)
    pl = None
    if spec.unet:
        pl, why = _unet_cut2(g, arr, spec, net)
        if why:
            return GroupVerdict(None, why=why, via="ids")
    v = solve_two(arr, bank, _resolver(g), spec.frame, spec.orient, spec.prior, polyline=pl,
                  which=spec.which, min_margin=0.0, sub_prior=spec.sub_prior)
    m = float(v.margins[0]) if v.margins else 0.0
    slot = v.slots[0] if v.slots else None
    extra = {"ids": v.ids, "slot": slot, "margin": round(m, 4), "kind": v.kind,
             "scores": {k: round(float(s), 4) for k, s in (v.extra.get("scores") or {}).items()}}
    if v.kind == "abstain_blank":
        return GroupVerdict(None, why="abstain:blank", via="ids", extra=extra)
    if v.char is None or v.char not in members:
        return GroupVerdict(None, why="abstain:" + v.kind.removeprefix("abstain_"), via="ids", extra=extra)
    if m < spec.min_margin:
        return GroupVerdict(None, conf=m, why="abstain:low_margin", via="ids", extra=extra)
    n = len(bank.get(slot) or ())
    if n < spec.min_class:
        return GroupVerdict(None, conf=m, why="abstain:few_templates", via="ids", extra={**extra, "n_templates": n})
    if spec.dual:
        return _dual_check(g, gray, v.char, m, spec, members, extra, whole)
    return GroupVerdict(v.char, conf=m, why="agree", via="ids", extra=extra)


def _dual_check(g: str, gray, ch: str, m: float, spec: IdsSpec, members, extra: dict, whole: dict | None) -> GroupVerdict:
    """两路一致（`IdsSpec.dual`）：IDS 已给 `ch`，整字 HOG 岭回归也须判成 `ch` 且判别值 ≥ `spec.dual`。"""
    from dataclasses import replace
    if whole is None:
        p = whole_bank_path(g)
        if p is None:
            return GroupVerdict(None, conf=m, why="abstain:no_whole_bank", via="ids", extra=extra)
        whole = load_bank(p)
    w = _judge_whole(gray, whole, replace(spec, whole="hog", min_margin=spec.dual), members)
    extra = {**extra, "whole": w.char or (w.extra or {}).get("form"), "whole_margin": (w.extra or {}).get("margin")}
    if w.char is None:
        return GroupVerdict(None, conf=m, why="abstain:dual_" + w.why.removeprefix("abstain:"), via="ids", extra=extra)
    if w.char != ch:
        return GroupVerdict(None, conf=m, why="abstain:dual_disagree", via="ids", extra=extra)
    return GroupVerdict(ch, conf=m, why="agree", via="ids", extra=extra)


def _auto_three(gray):
    """彝组自动切：上／中、中／下两条缝（先取直线基线作先验）＋中段竖缝。无墨迹 → None。"""
    from .ids_segment import ink_of, polylines_to_mask, seam_polyline, straight_baseline, vertical_seam
    ink = ink_of(gray)
    if not ink.any():
        return None
    y1, y2 = straight_baseline(ink, 3)
    pl = (seam_polyline(ink, y1, band=0.08, pull=2.0), seam_polyline(ink, y2, band=0.08, pull=2.0))
    return pl, vertical_seam(ink, polylines_to_mask(ink.shape, *pl))


@lru_cache(maxsize=8)
def _load_unet_cached(path: str, sha: str):
    from .ids_unet import NpNet
    return NpNet(path)


def unet_path(g: str) -> Path | None:
    """组 `g` 的 U-Net 权重：工作区 `config/groups/ids/<g>.unet.npz` 优先，其次仓里 `<config_dir>/<spec.unet>`。"""
    from ..core.workspace import ws_config_dir
    from .registry import FLOW_GROUPS as GROUPS
    spec = SPECS.get(g)
    if spec is None or not spec.unet:
        return None
    cfg = ws_config_dir()
    if cfg is not None and (cfg / "groups" / "ids" / f"{g}.unet.npz").exists():
        return cfg / "groups" / "ids" / f"{g}.unet.npz"
    gs = GROUPS.get(g)
    if gs is not None and gs.config_dir and (_ROOT / gs.config_dir / spec.unet).exists():
        return _ROOT / gs.config_dir / spec.unet
    return None


def _load_unet(g: str):
    p = unet_path(g)
    return None if p is None else _load_unet_cached(str(p), hashlib.sha256(p.read_bytes()).hexdigest())


def _unet_three(net, gray):
    """U-Net 切：→ ((上/中折线, 中/下折线), 中段竖缝)。无墨迹 → None。"""
    from .ids_segment import ink_of, polylines_to_mask, vertical_seam
    from .ids_unet import predict_prob_np, prob_to_polylines
    ink = ink_of(gray)
    if not ink.any():
        return None
    pl = tuple(prob_to_polylines(predict_prob_np(net, gray)))
    return pl, vertical_seam(ink, polylines_to_mask(ink.shape, *pl))


def _unet_cut2(g: str, arr: np.ndarray, spec: IdsSpec, net=None):
    """两段版：U-Net 切一条线 → (折线, None)；权重缺失 → (None, 'abstain:no_model')；无墨迹 → (None, 'abstain:blank')。"""
    from .ids_segment import ink_of
    from .ids_unet import predict_prob_np, prob_to_polyline2
    net = net or _load_unet(g)
    if net is None:
        return None, "abstain:no_model"
    if not ink_of(arr).any():
        return None, "abstain:blank"
    return prob_to_polyline2(predict_prob_np(net, arr), spec.orient), None


def _slot_bank(bank: dict) -> dict:
    """彝组模板库的键是 `位置|部件名`（如 `1|米糸`、`3|糸`＝中段竖切右半）→ `{位置: {部件名: [图,…]}}`。"""
    out: dict = {}
    for k, v in bank.items():
        slot, name = k.split("|", 1)
        out.setdefault(int(slot), {})[name] = v
    return out


def _judge_three(g: str, gray, bank: dict, spec: IdsSpec, net=None) -> GroupVerdict:
    from .ids_solver import solve
    arr = np.asarray(gray)
    if spec.unet:
        net = net or _load_unet(g)
        if net is None:
            return GroupVerdict(None, why="abstain:no_model", via="ids")
        cut = _unet_three(net, arr)
    else:
        cut = _auto_three(arr)
    if cut is None:
        return GroupVerdict(None, why="abstain:blank", via="ids")
    pl, vc = cut
    b = _slot_bank(bank)
    v = solve(arr, b, _resolver(g), pl, min_margin=spec.min_margin, vcut=vc, mid_hog=spec.mid_hog, top_hog=spec.top_hog, bot_hog=spec.bot_hog, windows=not spec.unet)
    ms = [float(x) for x in v.margins]
    extra = {"ids": v.ids, "slots": list(v.slots), "margins": [round(x, 4) for x in ms], "kind": v.kind, "flag": v.flag}
    if v.char is None or v.char not in _members(g):
        return GroupVerdict(None, conf=min(ms) if ms else 0.0, why="abstain:" + v.kind.removeprefix("abstain_"), via="ids", extra=extra)
    if v.flag and not spec.nearest_ok:      # nearest_variant：Unicode 没有这个组合，只能近似 → 缺省不放，送人审
        return GroupVerdict(None, conf=min(ms), why="abstain:nearest", via="ids", extra=extra)
    for k, name in enumerate(v.slots):
        key = 3 if (k == 1 and b.get(3)) else k
        tname = name[1:] if key == 3 and name.startswith("米") else name
        if len(b.get(key, {}).get(tname) or ()) < spec.min_class:
            return GroupVerdict(None, conf=min(ms), why="abstain:few_templates", via="ids", extra=extra)
    return GroupVerdict(v.char, conf=min(ms), why="agree", via="ids", extra=extra)


def _members(g: str):
    from .registry import FLOW_GROUPS as GROUPS
    return GROUPS[g].members


def _judge_by_form(gray, bank: dict, spec: IdsSpec, members, g: str = "", net=None) -> GroupVerdict:
    """按字分类：自动缝切开，取第 `which` 段，与各成员字的同段模板比最近邻（`ids_two._choose_norm`）。"""
    from .ids_segment import ink_of
    from .ids_two import _choose_norm, auto_cut, part_of
    grp, g = g, np.asarray(gray)
    if not ink_of(g).any():
        return GroupVerdict(None, why="abstain:blank", via="ids")
    if spec.unet:
        pl, why = _unet_cut2(grp, g, spec, net)
        if why:
            return GroupVerdict(None, why=why, via="ids")
    else:
        pl = auto_cut(g, spec.orient, spec.prior)
    x = part_of(g, pl, spec.orient, spec.which) if pl is not None else None
    if x is None:
        return GroupVerdict(None, why="abstain:slot", via="ids")
    best, m, scores = _choose_norm(x, bank, 0.0)
    extra = {"form": best, "margin": round(float(m), 4), "scores": {k: round(float(v), 4) for k, v in scores.items()}}
    if best is None or best not in members:
        return GroupVerdict(None, why="abstain:slot", via="ids", extra=extra)
    if m < spec.min_margin:
        return GroupVerdict(None, conf=m, why="abstain:low_margin", via="ids", extra=extra)
    n = len(bank.get(best) or ())
    if n < spec.min_class:
        return GroupVerdict(None, conf=m, why="abstain:few_templates", via="ids", extra={**extra, "n_templates": n})
    return GroupVerdict(best, conf=m, why="agree", via="ids", extra=extra)


@lru_cache(maxsize=16)
def _meta_cached(path: str, digest: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8")).get("generic") or {}


def generic_meta(g: str) -> dict:
    """通用判法模板库里的 `generic` 段（先验形状等）；没有 → {}。"""
    p = bank_path(g)
    return _meta_cached(str(p), hashlib.sha256(p.read_bytes()).hexdigest()) if p is not None else {}


def _gdir(g: str) -> str:
    from .registry import GROUPS
    return str(_ROOT / (GROUPS[g].config_dir or f"config/groups/{g}"))


def _judge_generic(g: str, gray, bank: dict, spec: IdsSpec, members, net=None, meta: dict | None = None) -> GroupVerdict:
    """通用判法（`ids_generic`）：计划 → 切（先验折线／U-Net）→ 判别叶子 → 最近邻。"""
    from . import ids_generic as G
    plan = G.plan_of("".join(sorted(members)), _gdir(g))
    if not G.usable(plan):
        return GroupVerdict(None, why="abstain:no_plan", via="ids")
    arr = np.asarray(gray)
    if not ink_of_any(arr):
        return GroupVerdict(None, why="abstain:blank", via="ids")
    meta = meta if meta is not None else generic_meta(g)
    if spec.unet and net is None:
        net = _load_unet(g)
        if net is None:
            return GroupVerdict(None, why="abstain:no_model", via="ids")
    if not spec.unet and not meta.get("shape"):
        return GroupVerdict(None, why="abstain:no_bank", via="ids")
    pl = G.cut(plan, arr, meta.get("shape"), net=net if spec.unet else None)
    x = G.leaf_of(plan, arr, pl) if pl is not None else None
    if x is None:
        return GroupVerdict(None, why="abstain:slot", via="ids")
    best, m, scores = G.choose(x, bank)
    extra = {"form": best, "margin": round(m, 4), "plan": plan.frame,
             "scores": {k: round(float(v), 4) for k, v in scores.items()}}
    if best is None or best not in members:
        return GroupVerdict(None, why="abstain:slot", via="ids", extra=extra)
    if m < spec.min_margin:
        return GroupVerdict(None, conf=m, why="abstain:low_margin", via="ids", extra=extra)
    n = len(bank.get(best) or ())
    if n < spec.min_class:
        return GroupVerdict(None, conf=m, why="abstain:few_templates", via="ids", extra={**extra, "n_templates": n})
    return GroupVerdict(best, conf=m, why="agree", via="ids", extra=extra)


def ink_of_any(arr) -> bool:
    from .ids_segment import ink_of
    return bool(ink_of(arr).any())


def _generic_cutter(g: str, spec: IdsSpec, cut_rows, epochs: int = 60):
    """用人标切线建一折的切法：→ (shape, net)。`cut_rows=[(id, 字, 图, 切线)]`。U-Net 需要 torch。"""
    from . import ids_generic as G
    from .registry import GROUPS
    plan = G.plan_of("".join(sorted(GROUPS[g].members)), _gdir(g))
    shape = G.mean_shape([c for *_x, c in cut_rows], plan.orient)
    net = None
    if spec.unet:
        from .ids_unet import NpNet
        tnet = _train_unet2([(img, c) for _i, _f, img, c in cut_rows], plan.orient, epochs=epochs)
        net = NpNet.from_torch(tnet)
        net._torch = tnet               # 建库时存权重用
    return plan, shape, net


def _generic_templates(plan, cells, shape, net) -> dict:
    from . import ids_generic as G
    bank: dict = {}
    for form, img, _v, _i in cells:
        pl = G.cut(plan, img, shape, net=net)
        x = G.leaf_of(plan, img, pl) if pl is not None else None
        if x is not None:
            bank.setdefault(form, []).append(quantize(x).astype(np.float32) / 255.0)
    return bank


def build_generic(g: str, dataset: Path, out_weights: Path | None = None) -> dict:
    """通用判法建库：先验形状取全部人标切线；模板＝组内全部人裁格（`labels.jsonl`）按同一切法切出的判别叶子。
    登记了 `unet` 的组同时训 U-Net（只用本组人标切线）存到 `out_weights`（需要 torch）。"""
    from . import ids_unet as U
    spec = SPECS[g]
    rows, src = _pool(g, dataset)
    plan, shape, net = _generic_cutter(g, spec, rows)
    if net is not None and out_weights is not None:
        U.save_weights(net._torch, out_weights)
    cells, _ = _whole_cells(g, dataset)
    d = dump_bank(g, _generic_templates(plan, cells, shape, net),
                  {"labels": f"char-groups/variant/{g}/labels.jsonl",
                   "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16],
                   "cells": len(cells), "cut_cells": len(rows),
                   "forms": dict(sorted(Counter(c[0] for c in cells).items()))})
    d["generic"] = {"frame": plan.frame, "orient": plan.orient, "shape": shape, "cutter": "unet" if spec.unet else "prior"}
    return d


def evaluate_generic(g: str, dataset: Path, margins=(0.0, 0.02, 0.05, 0.1), folds: int = 5, epochs: int = 60) -> dict:
    """通用判法按册留出（`folds` 折，按册号轮流分）：留出册既不进先验形状／U-Net，也不进模板。"""
    from .registry import GROUPS
    spec = SPECS[g]
    members = GROUPS[g].members
    rows, _ = _pool(g, dataset)
    cells, _ = _whole_cells(g, dataset)
    vols = sorted({c[2] for c in cells})
    fold_of = {v: k % folds for k, v in enumerate(vols)}
    out = {m: Counter() for m in margins}
    wrong = []
    for k in range(folds):
        test = [c for c in cells if fold_of[c[2]] == k]
        if not test:
            continue
        plan, shape, net = _generic_cutter(g, spec, [r for r in rows if fold_of.get(r[0].split(":")[0]) != k], epochs)
        bank = _generic_templates(plan, [c for c in cells if fold_of[c[2]] != k], shape, net)
        for form, img, _v, i in test:
            for m in margins:
                vd = _judge_generic(g, img, bank, IdsSpec(**{**asdict(spec), "min_margin": m}), members, net=net,
                                    meta={"shape": shape})
                kk = "abstain" if vd.char is None else "right" if vd.char == form else "wrong"
                out[m][kk] += 1
                if kk == "wrong":
                    wrong.append((m, i, form, vd.char, vd.extra.get("margin")))
    return {"by_margin": {m: dict(c) for m, c in out.items()}, "wrong": wrong, "cells": len(cells)}


def _judge_whole(gray, bank: dict, spec: IdsSpec, members) -> GroupVerdict:
    """整字二类岭回归（`ids_whole`）：判别值绝对值 ≥ `min_margin`、判成的字模板 ≥ `min_class` 才给字。"""
    from . import ids_whole
    if not ids_whole.aspect_ok(gray, tuple(spec.aspect)):
        return GroupVerdict(None, why="abstain:aspect", via="ids")
    if spec.clean:
        gray = ids_whole.clean_patch(gray)
    best, m, sc = ids_whole.score(np.asarray(gray), bank, spec.whole, tuple(spec.region), spec.lam, spec.size)
    extra = {"form": best, "margin": round(float(m), 4), "scores": {k: round(float(v), 4) for k, v in sc.items()}}
    if best is None:
        return GroupVerdict(None, why="abstain:blank", via="ids", extra=extra)
    if best not in members:
        return GroupVerdict(None, why="abstain:slot", via="ids", extra=extra)
    if spec.give and best not in spec.give:
        return GroupVerdict(None, why="abstain:not_given", via="ids", extra=extra)
    if m < spec.min_margin:
        return GroupVerdict(None, conf=m, why="abstain:low_margin", via="ids", extra=extra)
    n = len(bank.get(best) or ())
    if n < spec.min_class:
        return GroupVerdict(None, conf=m, why="abstain:few_templates", via="ids", extra={**extra, "n_templates": n})
    return GroupVerdict(best, conf=m, why="agree", via="ids", extra=extra)


_YI_NM = {"⺕": "彐", "彑": "彑", "糸": "米糸", "米+分": "米分", "廾": "廾", "大": "大"}


def _human_cuts(g: str, dataset: Path) -> dict:
    """dataset `cut_labels.jsonl` 里人标的上／中、中／下折线（去掉 `cut_recheck_lowmargin.jsonl` 判 bad 的格）→ {id: (折线1, 折线2)}。"""
    d = Path(dataset) / "char-groups" / "variant" / g
    f = d / "cut_labels.jsonl"
    if not f.exists():
        return {}
    bad = set()
    rc = d / "cut_recheck_lowmargin.jsonl"
    if rc.exists():
        bad = {r["id"] for r in map(json.loads, filter(str.strip, rc.read_text(encoding="utf-8").splitlines())) if r.get("verdict") == "bad"}
    out = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["id"] not in bad and len(r.get("hcuts") or ()) == 2:
                out[r["id"]] = tuple(tuple(tuple(pt) for pt in l) for l in r["hcuts"])
    return out


def _three_cells(g: str, dataset: Path, cutter=None):
    """→ [(id, 三段名, 灰度图, (折线, 竖缝))]。`cutter(id, gray)` 给了就用它切（U-Net 版），否则自动缝。"""
    from PIL import Image
    d = Path(dataset) / "char-groups" / "variant" / g
    src = d / "user_parts_labels.jsonl"
    cells = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        gray = np.asarray(Image.open(d / "crops" / (r["id"].replace(":", "_") + ".png")).convert("L"))
        cut = cutter(r["id"], gray) if cutter else _auto_three(gray)
        if cut is not None:
            cells.append((r["id"], tuple(_YI_NM[r[k]] for k in ("top", "mid", "bot")), gray, cut))
    return cells, src


def _three_bank(cells, skip: str | None = None, windows: bool = True) -> dict:
    from .ids_solver import add_real
    bank = {0: {}, 1: {}, 2: {}}
    for i, names, gray, (pl, vc) in cells:
        if i != skip:
            add_real(bank, gray, names, pl, vc)
    if not windows:
        bank = {k: v for k, v in bank.items() if k in (0, 1, 2, 3)}
    # 与线上同一量化
    return {f"{slot}|{name}": [quantize(t).astype(np.float32) / 255.0 for t in ts]
            for slot, names_ in bank.items() for name, ts in names_.items()}


def evaluate_three(g: str, dataset: Path, margins=(0.0, 0.02, 0.04, 0.06)) -> dict:
    """彝组留一：模板库只用其余格，切线用自动缝（同线上）。→ {margin: {right, abstain, wrong}}。"""
    cells, _ = _three_cells(g, dataset)
    out = {m: Counter() for m in margins}
    wrong = []
    for i, names, gray, _cut in cells:
        bank = _three_bank(cells, skip=i)
        for m in margins:
            v = _judge_three(g, gray, bank, IdsSpec(**{**asdict(SPECS[g]), "min_margin": m}))
            k = "abstain" if v.char is None else "right" if tuple(v.extra["slots"]) == names else "wrong"
            out[m][k] += 1
            if k == "wrong":
                wrong.append((m, i, names, v.char))
    return {"by_margin": {m: dict(c) for m, c in out.items()}, "wrong": wrong, "cells": len(cells)}


def _train_unet(g: str, dataset: Path, exclude_volume: str | None = None, epochs: int = 120, seed: int = 1):
    """用 dataset 里人标折线训 U-Net（需要 torch）；`exclude_volume` 给了就不用那一册的格（按册留出评测）。"""
    from PIL import Image
    from . import ids_unet as U
    from .ids_segment import polylines_to_mask
    d = Path(dataset) / "char-groups" / "variant" / g
    train = []
    for i, pl in _human_cuts(g, dataset).items():
        if exclude_volume and i.split(":")[0] == exclude_volume:
            continue
        gray = np.asarray(Image.open(d / "crops" / (i.replace(":", "_") + ".png")).convert("L"))
        train.append((gray, polylines_to_mask(gray.shape, *pl)))
    return U.train(train, epochs=epochs, seed=seed)


def _unet_cutter(net, human: dict, skip_volume: str | None = None):
    """建库用的切法：人标折线优先（该册被留出时不用），否则 U-Net 预测。"""
    from .ids_segment import ink_of, polylines_to_mask, vertical_seam
    from .ids_unet import predict_prob, prob_to_polylines

    def cut(i, gray):
        ink = ink_of(gray)
        if not ink.any():
            return None
        if i in human and i.split(":")[0] != skip_volume:
            pl = human[i]
        else:
            pl = tuple(prob_to_polylines(predict_prob(net, gray)))
        return pl, vertical_seam(ink, polylines_to_mask(ink.shape, *pl))
    return cut


def evaluate_three_unet(g: str, dataset: Path, margins=(0.0, 0.02, 0.05), epochs: int = 120) -> dict:
    """彝组 U-Net 版按册留出：留出一册，U-Net 与模板只用其余册，测这一册（设计者调参不在评测格上）。需要 torch。"""
    spec = SPECS[g]
    human = _human_cuts(g, dataset)
    probe, _ = _three_cells(g, dataset, cutter=lambda i, gr: ((((0, .3), (1, .3)), ((0, .65), (1, .65))), None))
    vols = sorted({c[0].split(":")[0] for c in probe})
    out = {m: Counter() for m in margins}
    wrong = []
    for v in vols:
        net = _train_unet(g, dataset, exclude_volume=v, epochs=epochs)
        cells, _ = _three_cells(g, dataset, cutter=_unet_cutter(net, human, skip_volume=v))
        from .ids_unet import NpNet
        npnet = NpNet.from_torch(net)
        for i, names, gray, _cut in cells:
            if i.split(":")[0] != v:
                continue
            bank = _three_bank([c for c in cells if c[0].split(":")[0] != v], windows=False)
            for m in margins:
                sp = IdsSpec(**{**asdict(spec), "top_hog": m, "mid_hog": m, "bot_hog": m})
                vd = _judge_three(g, gray, bank, sp, net=npnet)
                k = "abstain" if vd.char is None else "right" if tuple(vd.extra["slots"]) == names else "wrong"
                out[m][k] += 1
                if k == "wrong":
                    wrong.append((m, i, names, vd.char))
    return {"by_margin": {m: dict(c) for m, c in out.items()}, "wrong": wrong, "cells": sum(out[margins[0]].values())}


def build_three(g: str, dataset: Path, out_weights: Path | None = None) -> dict:
    """彝组：dataset `char-groups/variant/<g>/user_parts_labels.jsonl`（三段读法）＋ `crops/` → 模板库（自动缝，同线上）。
    `SPECS[g].unet` 非空：先用全部人标折线训 U-Net 存到 `out_weights`，模板按人标折线（没有的用 U-Net 预测）切，库里只留 0–3 槽。"""
    if SPECS[g].unet:
        from . import ids_unet as U
        net = _train_unet(g, dataset)
        U.save_weights(net, out_weights)
        cells, src = _three_cells(g, dataset, cutter=_unet_cutter(net, _human_cuts(g, dataset)))
        flat = _three_bank(cells, windows=False)
        return dump_bank(g, flat, {"labels": f"char-groups/variant/{g}/user_parts_labels.jsonl",
                                   "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16], "cells": len(cells),
                                   "cuts_sha256": hashlib.sha256((Path(dataset) / "char-groups" / "variant" / g / "cut_labels.jsonl").read_bytes()).hexdigest()[:16]})
    cells, src = _three_cells(g, dataset)
    flat = _three_bank(cells)
    n = len(cells)
    out = dump_bank(g, flat, {"labels": f"char-groups/variant/{g}/user_parts_labels.jsonl",
                              "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16], "cells": n})
    return out


def form_templates(cells, spec: IdsSpec) -> dict:
    """`cells = [(成员字, 灰度图), …]`（人裁过的真实刻例）→ by_form 模板 `{字: [归一段图,…]}`，与线上同一量化。"""
    from .ids_two import auto_cut, part_of
    bank: dict = {}
    for form, gray in cells:
        g = np.asarray(gray)
        pl = auto_cut(g, spec.orient, spec.prior)
        x = part_of(g, pl, spec.orient, spec.which) if pl is not None else None
        if x is not None:
            bank.setdefault(form, []).append(quantize(x).astype(np.float32) / 255.0)
    return bank


def judge(g: str, gray) -> GroupVerdict:
    """线上入口：组 `g` 没登记判法或没有模板库 → `abstain:no_bank`；没图 → `abstain:no_patch`。"""
    if g not in SPECS:
        return GroupVerdict(None, why="abstain:no_spec", via="ids")
    p = bank_path(g)
    if p is None:
        return GroupVerdict(None, why="abstain:no_bank", via="ids")
    if gray is None:
        return GroupVerdict(None, why="abstain:no_patch", via="ids")
    return judge_with(g, gray, load_bank(p))


# —— 离线：建库与留一评测 ——

def _pool(g: str, dataset: Path):
    """dataset 人标池 → [(id, 字形, 灰度图, 切线)]。只收 `form` 在组内、切线 ≥2 点的行。"""
    from PIL import Image
    from .registry import FLOW_GROUPS as GROUPS
    d = Path(dataset) / "char-groups" / "variant" / g
    mem = GROUPS[g].members
    rows = []
    for line in (d / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("form") in mem and len(r.get("cut") or ()) >= 2:
            img = np.asarray(Image.open(d / "crops" / (r["id"].replace(":", "_") + ".png")).convert("L"))
            rows.append((r["id"], r["form"], img, r["cut"]))
    return rows, d / "labels.jsonl"


def _templates(g: str, rows, skip: str | None = None) -> dict:
    from .ids_two import add_real, slot_name
    spec = SPECS[g]
    bank: dict = {}
    for i, form, img, cut in rows:
        if i != skip:
            add_real(bank, img, slot_name(_resolver(g), form, spec.which), cut, spec.orient, spec.which)
    return {k: [quantize(t).astype(np.float32) / 255.0 for t in v] for k, v in bank.items()}


#: 左右切的异体字组共用一个 U-Net（同是「两部件之间切一刀」）：训练时把这几组的人标切线放一起（2026-10-21，叙敘＋教敎＋絕絶 106 格）。
V_POOL = ("xu", "jiao", "jue")


def _pool_v(dataset: Path, exclude_volume: str | None = None):
    """V_POOL 各组 dataset 人标切线 → [(灰度图, 切线)]；`exclude_volume` 给了就不用那一册。"""
    out = []
    for g in V_POOL:
        rows, _ = _pool(g, dataset)
        out += [(img, cut) for i, _f, img, cut in rows if not (exclude_volume and i.split(":")[0] == exclude_volume)]
    return out


def _train_unet2(cells, orient: str, epochs: int = 100, seed: int = 1):
    """两段版：用人标的一条切线训 2 类 U-Net（需要 torch）。`cells = [(灰度图, 切线)]`。"""
    from . import ids_unet as U
    from .ids_two import cut_mask
    return U.train([(img, cut_mask(img.shape, cut, orient)) for img, cut in cells], epochs=epochs, seed=seed, n_out=2)


def _form_bank(rows, spec: IdsSpec) -> dict:
    """by_form 模板：按人标切线取第 `which` 段（与线上同一量化）→ `{字: [部件图,…]}`。"""
    from .ids_two import part_of
    bank: dict = {}
    for _i, form, img, cut in rows:
        p = part_of(img, cut, spec.orient, spec.which)
        if p is not None:
            bank.setdefault(form, []).append(quantize(p).astype(np.float32) / 255.0)
    return bank


def evaluate_unet2(g: str, dataset: Path, margins=(0.0, 0.05, 0.1, 0.2), epochs: int = 60, folds: int = 5) -> dict:
    """by_form＋U-Net 版按册留出（`folds` 折，按册号轮流分）：留出的册既不进 U-Net 训练也不进模板。需要 torch。"""
    from .ids_unet import NpNet
    rows, _ = _pool(g, dataset)
    spec = SPECS[g]
    vols = sorted({r[0].split(":")[0] for r in rows} | {c for c in ()})
    fold_of = {v: k % folds for k, v in enumerate(vols)}
    out = {m: Counter() for m in margins}
    wrong = []
    for k in range(folds):
        test = [r for r in rows if fold_of[r[0].split(":")[0]] == k]
        if not test:
            continue
        rest = [r for r in rows if fold_of[r[0].split(":")[0]] != k]
        held = {v for v in vols if fold_of[v] == k}
        cells = []
        for gg in V_POOL:
            rr, _ = _pool(gg, dataset)
            cells += [(img, cut) for i, _f, img, cut in rr if i.split(":")[0] not in held]
        net = NpNet.from_torch(_train_unet2(cells, spec.orient, epochs=epochs))
        bank = _form_bank(rest, spec)
        for i, form, img, _cut in test:
            for m in margins:
                vd = judge_with(g, img, bank, IdsSpec(**{**asdict(spec), "min_margin": m}), net=net)
                kk = "abstain" if vd.char is None else "right" if vd.char == form else "wrong"
                out[m][kk] += 1
                if kk == "wrong":
                    wrong.append((m, i, form, vd.char, vd.extra.get("margin")))
    return {"by_margin": {m: dict(c) for m, c in out.items()}, "wrong": wrong, "cells": len(rows)}


def build_by_form_unet(g: str, dataset: Path, out_weights: Path) -> dict:
    """by_form＋U-Net 版：用 V_POOL 全部人标切线训 U-Net（存到 `out_weights`），模板按该组人标切线取部件段。需要 torch。"""
    from . import ids_unet as U
    spec = SPECS[g]
    net = _train_unet2(_pool_v(dataset), spec.orient)
    U.save_weights(net, out_weights)
    rows, src = _pool(g, dataset)
    return dump_bank(g, _form_bank(rows, spec), {"labels": f"char-groups/variant/{g}/labels.jsonl",
                                                 "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16],
                                                 "cells": len(rows), "forms": dict(sorted(Counter(r[1] for r in rows).items())),
                                                 "unet_pool": list(V_POOL)})


def _whole_cells(g: str, dataset: Path):
    """整字版：dataset `variant/<g>/labels.jsonl`（`form` 在组内）＋ `crops/` → [(字, 灰度图, 册, 格 id)]。切线不用。"""
    from PIL import Image
    from .registry import FLOW_GROUPS as GROUPS
    d = Path(dataset) / "char-groups" / "variant" / g
    mem = GROUPS[g].members
    cells = []
    for line in (d / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("form") in mem:
            cells.append((r["form"], np.asarray(Image.open(d / "crops" / (r["id"].replace(":", "_") + ".png")).convert("L")),
                          r["id"].split(":")[0], r["id"]))
    return cells, d / "labels.jsonl"


def build_whole(g: str, dataset: Path) -> dict:
    from . import ids_whole
    cells, src = _whole_cells(g, dataset)
    return ids_whole.build(g, cells, SPECS[g].size, {"labels": f"char-groups/variant/{g}/labels.jsonl",
                                                     "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16]})


def build(g: str, dataset: Path) -> dict:
    rows, src = _pool(g, dataset)
    return dump_bank(g, _templates(g, rows), {"labels": f"char-groups/variant/{g}/labels.jsonl",
                                              "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16],
                                              "cells": len(rows), "forms": dict(sorted(Counter(r[1] for r in rows).items()))})


def evaluate(g: str, dataset: Path, margins=(0.0, 0.01, 0.02, 0.03, 0.05)) -> dict:
    """留一：模板库只用其余格、切线用自动缝（同线上）。→ {margin: {right, abstain, wrong}}，另附错例。"""
    rows, _ = _pool(g, dataset)
    out = {m: Counter() for m in margins}
    wrong = []
    for i, form, img, _cut in rows:
        bank = _templates(g, rows, skip=i)
        for m in margins:
            v = judge_with(g, img, bank, IdsSpec(**{**asdict(SPECS[g]), "min_margin": m}))
            k = "abstain" if v.char is None else "right" if v.char == form else "wrong"
            out[m][k] += 1
            if k == "wrong":
                wrong.append((m, i, form, v.char, v.extra.get("margin")))
    return {"by_margin": {m: dict(c) for m, c in out.items()}, "wrong": wrong, "cells": len(rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IDS 路模板库：建库／留一评测")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("group"); b.add_argument("--dataset", type=Path, required=True)
    b.add_argument("--out", type=Path, default=None, help="缺省 仓里 <config_dir>/ids_bank.json")
    e = sub.add_parser("loo"); e.add_argument("group"); e.add_argument("--dataset", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.group not in SPECS:
        raise SystemExit(f"组 {a.group!r} 没有登记在线判法（ids_online.SPECS）")
    if a.cmd == "build":
        from .registry import FLOW_GROUPS as GROUPS
        out = a.out or _ROOT / (GROUPS[a.group].config_dir or f"config/groups/{a.group}") / "ids_bank.json"
        sp = SPECS[a.group]
        d = (build_generic(a.group, a.dataset, out.with_name(sp.unet) if sp.unet else None) if sp.generic
             else build_three(a.group, a.dataset, out.with_name(sp.unet) if sp.unet else None) if sp.three
             else build_whole(a.group, a.dataset) if sp.whole
             else build_by_form_unet(a.group, a.dataset, out.with_name(sp.unet)) if sp.by_form and sp.unet
             else build(a.group, a.dataset))
        write_bank(d, out)
        print(f"写入 {out}：{d['source']}，各类模板 { {k: len(v) for k, v in d['templates'].items()} }")
    else:
        sp = SPECS[a.group]
        if sp.generic:
            r = evaluate_generic(a.group, a.dataset)
        elif sp.whole:
            from . import ids_whole
            from .registry import FLOW_GROUPS as GROUPS
            bank = json.loads(bank_path(a.group).read_text(encoding="utf-8"))
            r = ids_whole.evaluate(a.group, bank)
        elif sp.by_form and sp.unet:
            r = evaluate_unet2(a.group, a.dataset)
        else:
            r = (evaluate_three_unet if sp.unet else evaluate_three if sp.three else evaluate)(a.group, a.dataset)
        print(f"{a.group} {'按册留出（U-Net）' if sp.unet else '按册留出（整字）' if sp.whole else '留一（自动缝）'}{r['cells']} 格")
        for m, c in r["by_margin"].items():
            print(f"  margin {m:.2f}: {c}")
        for w in r["wrong"]:
            print("  错", *w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
