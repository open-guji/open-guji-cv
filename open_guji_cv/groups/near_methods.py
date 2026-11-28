"""3b `glyph_near` 的字形方法登记表（2026-11-27，第三步重构）。

一个字组可以挂几个方法，写在书配置 `params.glyph_near.groups.<组>.methods` 里：`{方法名: 模型目录}`，或
`{方法名: {path: 模型文件, pair: [字, 字]}}`（一份模型文件挂多对的方法，如 part_shape，2026-11-28；`pair` 选其中一对）。
方法只回答「这张字块图在组内各字里更像哪个」，给组内每个字一个分，外加证据；**不定字、不放行**。
校准（分 → p）也由方法自己带的校准表做，但只在收尾 `glyph_analyzer` 里调，3b 产物里存的是原始分。

接口（以后的方法照这个写，第四步那些看图判字的方法迁过来也照这个）：

    m = load_method(name, spec)               # name 如 "cnn_small"；spec 是模型目录、单个模型文件，或 {path, pair}
    outs = score(m, patches, book_id, ctx=ctx, cells=cells)
                                              # 即 m.score(patches, book_id[, ctx=…, cells=…])
                                              # patches: 字块图（uint8，白底黑字，任意尺寸），哪种图见 m.patch
                                              # → [{"sims": {字: 分}, "evidence": {...}}, …]，与 patches 一一对应
    p = m.calibrate(sims)                     # {字: 校准后的 p} 或 None（没有校准表）
    m.fingerprint()                           # 模型目录（或文件）的 sha256 短哈希，进参数指纹；{path, pair} 时再并上 pair
    method_fingerprint(name, spec)            # "<方法>=<指纹>"，进 `methods_sha`；4d 拿同一个函数比对（spec 是字符串时与之前逐位相同）
    lib_fingerprint(库文件)                    # 书级刻例库（book_knn／near_knn）钉版指纹＝文件 sha256 前 16 位；这类方法（`lib = True`）
                                              # 的 method_fingerprint 就是它，与第四步参数指纹 bk／nk 段同值
    m.model_sha                               # 模型版本，写进 3b 产物 `PageNear.models` 与收尾 `near.methods.*.model`

- `m.patch`（类属性，可缺）：方法吃哪种字块图。`"raw"`（缺省）＝原图灰度按 `bbox_page` 裁块；`"char_patch"`＝第二步
  切字缓存里的字块图（`ctx.image("char_patch", patch_key)`，第四步 seed_admit 各判官读的就是这个）。
  3b 按它给图，方法自己不读图。
- **可选 ctx**（2026-11-28 加）：方法的 `score` 声明了 `ctx`／`cells` 参数（或 `**kwargs`）才传，老方法不认也照用（`score()` 用
  `inspect` 判）。`ctx` 是 `RunContext`（要读本书库、3a 候选的方法用，如以后的 book_knn／near_knn）；`cells` 与 patches
  一一对应，每格 `{id, page, col, slot, sub, patch_key, char, candidates}`（`char`／`candidates` 是 3a 的首位与候选）。
  **方法不许改 ctx 里的东西**，只读。

## cnn_small（宫／宮／官 是第一个）

殿本 ZM 11-26 训的四段卷积小 CNN，二分类，输入 64×64 灰度（原图按 `bbox_page` 裁、白底补成正方形、双线性缩放）。
模型目录：

    model.json   {"format": "near-cnn/1", "classes": ["官", "宫"], "merge": {"宮": "宫"},
                  "folds": ["fold0.pt", …], "fold_by": "vol_mod"}
    fold0.pt …   按册 5 折各训一个（册号 % 5 为留出折）
    calib.json   {"format": "near-calib/1", "knots": {"宫": [[原始分…], [p…]]}}（可缺）

`fold_by: vol_mod`：册 id 末尾的数字对折数取模，用**没见过这一册**的那个折模型打分（训练标签就是这些册的现行文本，
用全量模型给训练册打分会把它背过的错字原样吐回来）；册 id 里读不出数字（别的书）就各折取平均。
`merge`：异体不分的字（宮）和它归的字（宫）给同一个分（Sheldon 11-26：宫／宮 异体不分）。

## rr_shape（入人八，第四步 group_flow 的书级刻形判法搬来的样板，2026-11-28）

包的是 `groups.rr_shape.judge`（seed_admit `_rr_shape_pass` 用的同一个函数，同一张图同一个模型逐位同一结论同一分），
吃 `char_patch` 字块图。模型就是第四步那份书级模型文件（数据目录 `config/groups/rr_shape.json`，`schema: rr_shape/1`，
`research/char_groups/rr/qtw_shape_train.py` 导出），书配置直接指它：`methods: {rr_shape: config/groups/rr_shape.json}`；
也可以给目录，目录里放 `model.json`。

- `sims`：几何判成 八 → `{八: 1, 人: 0, 入: 0}`；走逻辑回归 → `{入: σ(s), 人: 1−σ(s), 八: 0}`（s＝`judge` 给的决策值，
  已按 3 位小数取整，同第四步 `evidence.rr_shape.score`）；弃权里没算出 s 的（无墨、组外字护栏、几何不明、NaN）→ `{}`。
  分差不够（`abstain:low_margin`）仍给 sims，弃权记在证据里。
- `evidence`：`{method: "rr_shape", char, why, nn, score, geo}`，后五键与第四步 `evidence.rr_shape` 同键同值（`char` 是现役判法的结论，弃权为 None）。**4d 的读口就是这里**（`seed_admit_shapes._rr_shape_from_3b`，开关 `group_flow_rr_shape_3b`，cv #1999）：按 `NearMethodOut.method` 冒号前是 `rr_shape` 取，证据带 `error` 的格不取；模型对不对比 `methods_sha` 里的 `rr_shape=<指纹>`。
- 校准：模型文件旁边的 `<文件名去 .json>.calib.json`（给目录时是目录里的 `calib.json`），格式
  `{"format": "near-calib/1", "knots": {"入": [[σ(s)…], [p…]]}, "rule": {"八": p}}`：逻辑回归那一路按 knots 映 `入` 的 p、`人`＝1−p；
  几何判 八 的那一路 p 取 `rule.八`。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）；要标就拿训练脚本按册留出那一遍的
  (s, 放行字) 做保序回归，或人裁样本。

## wu_shape（嗚鳴，第四步 group_flow 的书级刻形判法搬来，2026-11-28）

包的是 `groups.wu_shape.judge`（seed_admit `_wu_shape_pass` 用的同一个函数），吃 `char_patch` 字块图。模型就是第四步那份
书级模型文件（数据目录 `config/groups/wu_shape.json`，`schema: wu_shape/1`），书配置直接指它：
`wu: {ref: wu, trigger: cands, methods: {wu_shape: config/groups/wu_shape.json}}`；也可以给目录，目录里放 `model.json`。

- `sims`：`{鳴: p, 嗚: 1−p}`（p＝`judge` 给的 鳴 概率，已按 4 位小数取整，同第四步 `evidence.wu_shape.p`；1−p 也取 4 位）；
  取不出右半（`abstain:no_ink`）→ `{}`。p 在门槛中间（`abstain:low_p`）仍给 sims，弃权记在证据里。
- `evidence`：`{method: "wu_shape", char, why, p}`，后三键＝`judge()` 返回的整个 dict（第四步 `evidence.wu_shape` 存的就是它，
  无墨弃权没有 `p`）。4d 读时去掉 `method` 就是第四步要存的那份。模型对不对比 `methods_sha` 里的 `wu_shape=<指纹>`
  （`method_fingerprint("wu_shape", group_flow_wu_shape)`）；`model_sha` 与第四步参数指纹 `ws` 段同算法（`wu_shape.fingerprint`）。
- 现役第四步只判**本格字（库首位）是 嗚鳴** 的格（整理本／字组／库前几名有 嗚鳴 都不算）；3b 用 `trigger: cands` 罩住它
  （3a 首位或前 topk 名里有 嗚鳴 就跑），多跑的格 4d 不读。
- 校准：模型文件旁边的 `<文件名去 .json>.calib.json`（给目录时是目录里的 `calib.json`），格式
  `{"format": "near-calib/1", "knots": {"鳴": [[p…], [校准 p…]]}}`，`嗚`＝1−p。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。

## hou_shape（候𠋫，第四步 group_flow 的书级刻形判法搬来，2026-11-28）

包的是 `groups.hou_shape.judge`（seed_admit `_hou_shape_pass` 主遍与 `group_flow_hou_shape_late` 晚跑遍用的同一个函数），
吃 `char_patch` 字块图。模型就是第四步那份书级文件（数据目录 `config/groups/hou_shape.json`），书配置直接指它：
`hou: {ref: hou, trigger: cands, methods: {hou_shape: config/groups/hou_shape.json}}`；也可以给目录，目录里放 `model.json`。
两种 schema：

- `hou_shape/2`（小网）：`judge` 给 候 的概率 p（4 位）→ `sims`＝`{候: p, 𠋫: 1−p}`，同 wu_shape。
- `hou_shape/1`（几何量）：`judge` 给 亻 右边第二竖的相对长 v（4 位），`v < lo` 判 候、`v ≥ hi` 判 𠋫、其间弃权。v 不是概率，
  3b 用一个**与现役判定一致的单调映射**出分：`候 = σ(ln9 · (lo + hi − 2v) / (hi − lo))`、`𠋫 = 1 − 候`（各取 4 位）。
  v＝lo 时 候＝0.9、v＝(lo+hi)/2 时 0.5、v＝hi 时 0.1，所以现役判 候 的格 候 ≥ 0.9、判 𠋫 的格 候 ≤ 0.1，弃权的格在 (0.1, 0.9)，
  最高分的字总是现役判的那个字；v 越长越像 𠋫，保序（校准表可直接拿它做保序回归）。`hi − lo < 0.001`（几乎没有中间档）时按判出的字给 1／0（弃权 0.5）。
- 无墨弃权（`abstain:no_ink`）→ `{}`；弃权在中间（`abstain:mid`）仍给 sims。
- `evidence`：`{method: "hou_shape", char, why, v|p}`，后三键＝`judge()` 整个返回值（第四步 `evidence.hou_shape` 存的那份）。
  4d 读时去掉 `method`；`model_sha` 与第四步参数指纹 `hs` 段同算法（`hou_shape.fingerprint`），`methods_sha` 里是 `hou_shape=<指纹>`。
- 现役第四步只碰**已放行**、字是 候／𠋫 的非人裁格，只改字、不改放行；晚跑遍（`group_flow_hou_shape_late`，5c vis_ruling
  放行之后）判法同一个，只是补判主遍时还没放行、没 `evidence.hou_shape` 的格。3b 不知道放行，按 3a 候选触发（`trigger: cands`，
  登记表 hou 组是 侯俟候𠉀𠋫），给的是原样判法结论；哪些格用、主遍还是晚跑遍、改不改字，都留在 4d。
  3b 也会在 侯／俟 格上出分（方法只认 候／𠋫，那些分没意义），4d 不读这些格。
- 校准：`<模型去 .json>.calib.json`（给目录时 `calib.json`），`{"format": "near-calib/1", "knots": {"候": [[分…], [p…]]}}`，
  按 `sims.候` 映、𠋫＝1−p。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。

## part_shape（剌刺／疎踈／攢攅 等差在一块部件的字对，第四步 group_flow 的书级部件刻形判法搬来，2026-11-28）

包的是 `groups.part_shape.judge`（seed_admit `_part_shape_pass` 用的同一个函数，按这一对的部件框 `box` 截部件、同一组网），
吃 `char_patch` 字块图。模型是第四步那份书级文件（数据目录 `config/groups/part_shape.json`，`schema: part_shape/1`，**一份挂多对**），
所以书配置要写明是哪一对：

    ci: {ref: ci, trigger: cands, methods: {part_shape: {path: config/groups/part_shape.json, pair: [剌, 刺]}}}

`pair` 两个字须是模型里某一对的两个字（次序不论，sims 的方向按模型里的 `chars`）；文件里只有一对时可以只写路径字符串。
一个组挂一对；一份文件里的几对要各开一个组（各自的 `ref`）。

- `sims`：`{chars[1]: p, chars[0]: 1−p}`（p＝`judge` 给的 chars[1] 概率，已取 4 位，同第四步 `evidence.part_shape.p`），同 wu_shape；
  取不出部件（`abstain:no_ink`）→ `{}`；门槛中间（`abstain:low_p`）仍给 sims。
- `evidence`：`{method: "part_shape", char, why, p, pair}`，后几键＝`judge()` 整个返回值（第四步 `evidence.part_shape` 存的那份，
  `pair` 是两字拼起来，如 `剌刺`）。4d 读时去掉 `method`。
- 指纹：`method_fingerprint("part_shape", {path, pair})`＝`part_shape=<模型文件（＋同名校准表）指纹与 pair（按码位排）合起来的短哈希>`，
  `methods_sha` 里是 `<组>:part_shape=<指纹>`；4d 用 `group_flow_part_shape` 和本格所在那一对（`part_shape.pair_of(model, 字)["chars"]`）
  调同一个函数比对。`model_sha`＝`part_shape.fingerprint(模型文件)`，与第四步参数指纹 `pt` 段同算法。
- 现役第四步只判**本格字（库首位）落在某一对里**的格；3b 用 `trigger: cands` 罩住。登记表里 剌刺 是注册组 `ci`，
  疎踈、攢攅 是单立字对 `p:疎踈`、`p:攅攢`。
- 校准：模型文件旁边 `<去 .json>.calib.json`，`{"format": "near-calib/1", "knots": {chars[1]: [[p…], [校准 p…]]}}`，
  按字取，几对共用一份表也行。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。

## pair_shape（两字刻形二选一：史记 之矣 /1、全唐文 大太／王玉／還遺 /2，第四步 group_flow 的书级判法搬来，2026-11-28）

包的是 `groups.pair_shape.judge`（seed_admit `_pair_shape_pass` 用的同一个函数），吃 `char_patch` 字块图。模型是第四步那份书级文件，
**一对一个文件**（数据目录 `config/groups/pair_shape_<拼音>.json`；`group_flow_pair_shape` 单个，`group_flow_pair_shapes` 是 `{两字: 文件}`
可挂多对），两种 schema：`pair_shape/1`（48px HOG＋PCA 近邻组外护栏＋逻辑回归）、`pair_shape/2`（主笔画紧框墨量图＋逻辑回归，
组外判别 `other` 或多类 `multi`）。书配置照 part_shape 写 `{path, pair}`（`pair` 只用来核对是不是这个文件的两个字、并进指纹），
每对开一个组（登记表组 `dt` 大太、`wyu` 王玉、`yh` 還遺；之矣 是 11-28 为此补进登记表的 `p:之矣`）：

    dt: {ref: dt, trigger: cands, methods: {pair_shape: {path: config/groups/pair_shape_dt.json, pair: [大, 太]}}}
    zy: {ref: "p:之矣", trigger: cands, methods: {pair_shape: {path: config/groups/pair_shape_zhiyi.json, pair: [之, 矣]}}}

- `sims`：同 rr_shape，用 `judge` 给的决策值 s（已取 3 位，`score>0` 给 chars[1]）：`{chars[1]: σ(s), chars[0]: 1−σ(s)}`（各取 4 位；
  多类模型的 s＝log p(chars[1]) − log p(chars[0])，σ(s) 就是只看这两类时 chars[1] 的概率）。没算出 s 的弃权（无墨、/1 的近邻组外护栏、
  NaN）→ `{}`；算出了 s 的弃权（分差不够、/2 的组外判别或多类最像组外字）仍给 sims，弃权记在证据里。**`other`／`margin`／`top`
  只进证据、不进 sims**。
- `evidence`：`{method: "pair_shape", **judge()}`，即 `char, why` 加 `nn`（/1）、`score`、`other`（/2 组外判别）、`margin`／`top`（/2 多类），
  judge 出了哪几个键就是哪几个，与第四步 `evidence.pair_shape`（`_pair_shape_pass` 的 trail）逐键同值。4d 读时去掉 `method`；
  第四步另加的 `nm_5b`（护栏 never_match 格的 5-b 首位）是 4d 的事，3b 不出。
- **只搬判法**：现役第四步的触发（库首位或整理本字在这一对里、整理本是第三个字不判、字组流程已给字不越过）、`veto`（已放行格
  |s|≥`veto_thr` 降审，`group_flow_pair_shape_veto`）、`nm_5b`、坐标对位全部留在 4d。3b 用 `trigger: cands` 罩住
  （3a 首位或前 topk 名里有这两字之一就跑），多跑的格 4d 不读。
- 指纹：`method_fingerprint("pair_shape", {path, pair})`，同 part_shape（文件＋同名校准表的指纹并上 pair，按码位排）；`methods_sha`
  里是 `<组>:pair_shape=<指纹>`。4d 用书级参数里那个文件和它的 `chars` 调同一个函数比对。`model_sha`＝`pair_shape.fingerprint(文件)`，
  与第四步参数指纹 `ps`／`pp` 段里每个文件的那段同算法。
- 校准：`<去 .json>.calib.json`，`{"format": "near-calib/1", "knots": {chars[1]: [[σ(s)…], [p…]]}}`。**现在没有校准表**（收尾不出 p）。

## book_knn（字组书级刻形近邻：门族 閒間 等，第四步 group_flow 的 `_book_knn_pass` 搬来，2026-11-28）

包的是 `groups.book_knn`（本书已放行格当刻例、整字 HOG 投 PCA 做 k 近邻），吃 `char_patch` 字块图。库是第四步那份书级文件
（数据目录 `config/groups/book_knn/<组>.json`，`schema: book_knn/1`），一组一个，书配置直接指它：

    men: {ref: men, trigger: cands, methods: {book_knn: config/groups/book_knn/men.json}}

**拆成两段**（CV3／CV4 11-28 定）：现役 `book_knn.judge(图, 模型, ref)` 只在 B 档用整理本对位字 ref，3b 看不到整理本，所以

- 前段 `book_knn_measure(特征, 模型)`（3b 出）：＝`judge_feat(特征, 模型, None)`——票数 `votes`、距离比 `ratio`、`nn`、多数字 `pick`、
  A 档结论（`agree`／`tier: A`）或弃权（`no_ink`／`nan`／`out_of_group`／`background`／`low_margin`）；`low_margin` 时另给
  `b_ok`＝「整理本字若是 pick，B 档门槛过不过」（拿 `ref=pick` 再调一次 `judge_feat` 得，比的是未取整的距离比）。
- 后段 `book_knn_settle(前段, ref)`（4d 调）：`low_margin`＋`b_ok`＋`ref == pick` → `{char: pick, why: agree_ref, tier: B}`，其余原样；
  出来的 dict 与现役 `judge(图, 模型, ref)` 逐键同值、同舍入、键次序同第四步 `evidence.book_knn`（测试按 A／B／各弃权档逐键比，
  并跑 `_book_knn_pass` 比 `evidence.book_knn`）。**现役第四步判法一行没动**，仍走 `judge`。
- 本格自己若是库里的刻例（训练时它已放行），现役运行时不屏蔽（库里没有格 id，`judge_feat` 的 `exclude` 只给训练留出用），3b 照现役，也不屏蔽。

- `sims`：`{pick: 票数/k}`（4 位）；没有 pick 或 pick 是背景刻例 `~` → `{}`。没有校准表（`calibrate` 返回 None）。
- `evidence`：`{method: "book_knn", char, why, tier, pick, votes, ratio, nn[, b_ok]}`；4d 用 `book_knn_settle(evidence, 整理本字)` 得
  第四步要存的 `evidence.book_knn`（`method`／`b_ok` 自动去掉）。
- 指纹（库钉版）：`lib_fingerprint(库文件)`＝文件 sha256 前 16 位，与第四步参数指纹 `bk` 段（`book_knn.fingerprint`）同值；
  `method_fingerprint("book_knn", 路径)`＝`book_knn=<lib_fingerprint>`，`methods_sha` 里是 `<组>:book_knn=<指纹>`，`model_sha` 也是它。
  4d 拿 `group_flow_book_knn[组]` 调 `lib_fingerprint` 比，不一致本地现算并计数、不报错。
- 触发：现役第四步只判**字组流程归进这一组（`evidence.group.id`）且仍待审**的格；3b 用 `trigger: cands` 罩（3a 首位或前 topk 名里有
  组内任一字就跑）。罩不住的格（字组靠整理本字归组、3a 前 topk 名里没有组字），4d 本地现算并计数。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SIZE = 64


def resolve_dir(path: str) -> Path:
    """模型目录：绝对路径原样；相对路径先找数据目录（随中心库走），再找仓根（模型表 `repo` 类，`models/…`）。"""
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    from ..core.workspace import data_root
    droot = data_root()
    if droot is not None and (droot / p).exists():
        return droot / p
    return REPO / p


def prep_patch(gray: np.ndarray) -> np.ndarray:
    """灰度裁块 → 64×64（白底补成正方形再双线性缩放），与训练时的 `extract.py` 同一做法。"""
    from PIL import Image
    im = Image.fromarray(np.asarray(gray, dtype=np.uint8))
    w, h = im.size
    m = max(w, h)
    canvas = Image.new("L", (m, m), 255)
    canvas.paste(im, ((m - w) // 2, (m - h) // 2))
    return np.asarray(canvas.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8)


def vol_number(book_id: str) -> int | None:
    m = re.search(r"(\d+)\s*$", str(book_id or ""))
    return int(m.group(1)) if m else None


def _dir_fingerprint(d: Path) -> str:
    """模型目录里全部文件（名＋内容）的短哈希；给的是单个模型文件时只算它和同名校准表（`<去 .json>.calib.json`）。"""
    if d.is_file():
        h = hashlib.sha256()
        for f in (d, _sibling_calib(d)):
            if f.is_file():
                h.update(f.name.encode())
                h.update(hashlib.sha256(f.read_bytes()).digest())
        return h.hexdigest()[:16]
    h = hashlib.sha256()
    for f in sorted(d.iterdir()) if d.exists() else []:
        if f.is_file():
            h.update(f.name.encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16] if d.exists() else "missing"


def _sibling_calib(f: Path) -> Path:
    return f.with_name(f.name[:-5] + ".calib.json" if f.name.endswith(".json") else f.name + ".calib.json")


def _accepts(fn, name: str) -> bool:
    try:
        ps = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in ps or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values())


def score(m, patches: list, book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
    """调方法的 `score`：方法认 `ctx`／`cells` 才传（老方法只收 `patches, book_id`，照旧调）。"""
    kw = {}
    if _accepts(m.score, "ctx"):
        kw["ctx"] = ctx
    if _accepts(m.score, "cells"):
        kw["cells"] = cells
    return m.score(patches, book_id, **kw)


def _small_net():
    import torch.nn as nn

    class Net(nn.Module):
        def __init__(self, n_out: int = 2):
            super().__init__()

            def blk(i, o):
                return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(),
                                     nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(), nn.MaxPool2d(2))
            self.f = nn.Sequential(blk(1, 16), blk(16, 32), blk(32, 64), blk(64, 96))
            self.d = nn.Dropout(0.3)
            self.o = nn.Linear(96, n_out)

        def forward(self, x):
            return self.o(self.d(self.f(x).mean((2, 3))))
    return Net


class CnnSmall:
    """四段卷积小 CNN，组内 N 分类（现役只有 宫／官 二分类）。"""

    patch = "raw"

    def __init__(self, model_dir: Path):
        self.dir = Path(model_dir)
        meta = json.loads((self.dir / "model.json").read_text(encoding="utf-8"))
        if meta.get("format") != "near-cnn/1":
            raise ValueError(f"{self.dir}/model.json format 不是 near-cnn/1：{meta.get('format')!r}")
        self.classes: list[str] = list(meta["classes"])
        self.merge: dict[str, str] = dict(meta.get("merge") or {})
        self.folds: list[str] = list(meta["folds"])
        self.fold_by: str = str(meta.get("fold_by") or "")
        cal = self.dir / "calib.json"
        self.calib = json.loads(cal.read_text(encoding="utf-8")) if cal.exists() else None
        self._nets: dict[int, object] = {}

    def _net(self, k: int):
        net = self._nets.get(k)
        if net is None:
            import torch
            net = _small_net()(len(self.classes))
            net.load_state_dict(torch.load(self.dir / self.folds[k], map_location="cpu"))
            net.eval()
            self._nets[k] = net
        return net

    def _fold_of(self, book_id: str) -> int | None:
        if self.fold_by == "vol_mod":
            v = vol_number(book_id)
            return None if v is None else v % len(self.folds)
        return None

    def score(self, patches: list[np.ndarray], book_id: str) -> list[dict]:
        if not patches:
            return []
        import torch
        import torch.nn.functional as F
        x = np.stack([prep_patch(p) for p in patches])
        xt = torch.tensor(255 - x, dtype=torch.float32).unsqueeze(1) / 255.0      # 墨＝1，同训练
        k = self._fold_of(book_id)
        ks = [k] if k is not None else list(range(len(self.folds)))
        with torch.no_grad():
            prob = np.mean([F.softmax(self._net(i)(xt), 1).numpy() for i in ks], axis=0)
        fold = f"fold{k}" if k is not None else "mean"
        out = []
        for row in prob:
            sims = {c: round(float(v), 4) for c, v in zip(self.classes, row)}
            for a, b in self.merge.items():
                if b in sims:
                    sims[a] = sims[b]
            out.append({"sims": sims, "evidence": {"fold": fold}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        """二分类：按校准表把正类原始分映到 p，另一类取 1−p；异体（merge）跟它归的字同 p，但不重复算进总和。"""
        if not self.calib or len(self.classes) != 2:
            return None
        knots = self.calib.get("knots") or {}
        pos = next((c for c in self.classes if c in knots), None)
        if pos is None or pos not in sims:
            return None
        xs, ys = knots[pos]
        p_pos = float(np.interp(sims[pos], xs, ys))
        neg = next(c for c in self.classes if c != pos)
        out = {pos: round(p_pos, 4), neg: round(1.0 - p_pos, 4)}
        return out

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.dir)

    @property
    def model_sha(self) -> str:
        return self.fingerprint()


class RrShape:
    """入人八 书级刻形判法（`groups.rr_shape`）包成 3b 方法，见模块头「rr_shape」。"""

    patch = "char_patch"
    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        cal = p / "calib.json" if p.is_dir() else _sibling_calib(p)
        from . import rr_shape
        self.model = rr_shape.load(str(self.path))
        self.calib = json.loads(cal.read_text(encoding="utf-8")) if cal.is_file() else None
        if self.calib is not None and self.calib.get("format") != "near-calib/1":
            raise ValueError(f"{cal} format 不是 near-calib/1：{self.calib.get('format')!r}")

    @staticmethod
    def sims_of(v: dict) -> dict[str, float]:
        """`rr_shape.judge` 的结果 → 组内各字的分（只由 judge 的结论与决策值算，不另跑模型）。"""
        if v.get("char") == "八" and "score" not in v:
            return {"八": 1.0, "人": 0.0, "入": 0.0}
        s = v.get("score")
        if s is None:
            return {}
        q = round(1.0 / (1.0 + math.exp(-float(s))), 4)
        return {"入": q, "人": round(1.0 - q, 4), "八": 0.0}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import rr_shape
        out = []
        for g in patches:
            v = rr_shape.judge(g, self.model)
            trail = {"method": "rr_shape", **{k: v[k] for k in ("char", "why", "nn", "score", "geo") if k in v}}
            out.append({"sims": self.sims_of(v), "evidence": trail})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        if not self.calib or not sims:
            return None
        if sims.get("八") == 1.0:
            pb = (self.calib.get("rule") or {}).get("八")
            return None if pb is None else {"八": round(float(pb), 4)}
        kn = (self.calib.get("knots") or {}).get("入")
        if not kn or "入" not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims["入"], xs, ys))
        return {"入": round(p, 4), "人": round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `rs` 段同算法（`rr_shape.fingerprint`），4d 拿它对 `group_flow_rr_shape`。"""
        from . import rr_shape
        return rr_shape.fingerprint(str(self.path))


def _load_calib(p: Path) -> dict | None:
    """方法的校准表：给目录时是目录里的 `calib.json`，给文件时是同名 `<去 .json>.calib.json`；没有 → None。"""
    cal = p / "calib.json" if p.is_dir() else _sibling_calib(p)
    d = json.loads(cal.read_text(encoding="utf-8")) if cal.is_file() else None
    if d is not None and d.get("format") != "near-calib/1":
        raise ValueError(f"{cal} format 不是 near-calib/1：{d.get('format')!r}")
    return d


class WuShape:
    """嗚鳴 书级刻形判法（`groups.wu_shape`）包成 3b 方法，见模块头「wu_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from . import wu_shape
        self.model = wu_shape.load(str(self.path))
        self.chars = tuple(self.model.get("chars", ["嗚", "鳴"]))
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`wu_shape.judge` 的结果 → `{鳴: p, 嗚: 1−p}`（p 用 judge 已取整的那个值，不另跑模型）；没有 p → `{}`。"""
        q = v.get("p")
        if q is None:
            return {}
        wu, ming = self.chars
        return {ming: float(q), wu: round(1.0 - float(q), 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import wu_shape
        out = []
        for g in patches:
            v = wu_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "wu_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        wu, ming = self.chars
        kn = (self.calib or {}).get("knots", {}).get(ming)
        if not kn or ming not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[ming], xs, ys))
        return {ming: round(p, 4), wu: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `ws` 段同算法（`wu_shape.fingerprint`）。"""
        from . import wu_shape
        return wu_shape.fingerprint(str(self.path))


class HouShape:
    """候𠋫 书级刻形判法（`groups.hou_shape`，schema /1 几何量、/2 小网）包成 3b 方法，见模块头「hou_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from . import hou_shape
        self.model = hou_shape.load(str(self.path))
        self.chars = tuple(self.model.get("chars", ["候", "𠋫"]))
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`hou_shape.judge` 的结果 → `{候: q, 𠋫: 1−q}`（只用 judge 已取整的 p 或 v，不另跑模型）；都没有 → `{}`。"""
        hou, alt = self.chars
        if v.get("p") is not None:
            q = float(v["p"])
        elif v.get("v") is not None:
            lo, hi = float(self.model["lo"]), float(self.model["hi"])
            if hi - lo >= 1e-3:                 # v 已取 4 位：中间档够宽，取整挪不过 0.5
                z = math.log(9.0) * (lo + hi - 2.0 * float(v["v"])) / (hi - lo)
                q = round(1.0 / (1.0 + math.exp(-min(50.0, max(-50.0, z)))), 4)     # 截到 ±50：窄中间档时 exp 不溢出
            else:                               # 几乎没有中间档：按判出的字给分
                q = {hou: 1.0, alt: 0.0}.get(v.get("char"), 0.5)
        else:
            return {}
        return {hou: q, alt: round(1.0 - q, 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import hou_shape
        out = []
        for g in patches:
            v = hou_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "hou_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        hou, alt = self.chars
        kn = (self.calib or {}).get("knots", {}).get(hou)
        if not kn or hou not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[hou], xs, ys))
        return {hou: round(p, 4), alt: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `hs` 段同算法（`hou_shape.fingerprint`）。"""
        from . import hou_shape
        return hou_shape.fingerprint(str(self.path))


def _pair_fingerprint(path: Path, pair) -> str:
    """{path, pair} 写法的指纹：模型文件（＋同名校准表）的指纹与这一对（按码位排，次序不论）合起来的 sha256 短哈希。"""
    h = hashlib.sha256()
    h.update(_dir_fingerprint(path).encode())
    h.update(("|pair:" + "".join(sorted(str(c) for c in pair))).encode())
    return h.hexdigest()[:16]


class PartShape:
    """剌刺／疎踈 等部件刻形判法（`groups.part_shape`，一份模型挂多对）包成 3b 方法，取其中一对，见模块头「part_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path, pair=None):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from . import part_shape
        model = part_shape.load(str(self.path))
        if pair is None:
            if len(model["pairs"]) != 1:
                raise ValueError(f"part_shape：{self.path} 挂了 {len(model['pairs'])} 对，书配置要写 "
                                 f"{{path, pair: [字, 字]}} 指明哪一对")
            self.pair = model["pairs"][0]
            self.want = None
        else:
            want = [str(c) for c in pair]
            hit = [pr for pr in model["pairs"] if sorted(pr["chars"]) == sorted(want)]
            if len(want) != 2 or not hit:
                raise ValueError(f"part_shape：{self.path} 里没有 {''.join(want)} 这一对"
                                 f"（有 {[''.join(pr['chars']) for pr in model['pairs']]}）")
            self.pair = hit[0]
            self.want = want
        self.chars = tuple(self.pair["chars"])
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`part_shape.judge` 的结果 → `{chars[1]: p, chars[0]: 1−p}`（p 用 judge 已取整的那个值）；没有 p → `{}`。"""
        q = v.get("p")
        if q is None:
            return {}
        a, b = self.chars
        return {b: float(q), a: round(1.0 - float(q), 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import part_shape
        out = []
        for g in patches:
            v = part_shape.judge(g, self.pair)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "part_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        a, b = self.chars
        kn = (self.calib or {}).get("knots", {}).get(b)
        if not kn or b not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[b], xs, ys))
        return {b: round(p, 4), a: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src) if self.want is None else _pair_fingerprint(self.src, self.want)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `pt` 段同算法（`part_shape.fingerprint`）。"""
        from . import part_shape
        return part_shape.fingerprint(str(self.path))


class PairShape:
    """两字刻形二选一（`groups.pair_shape`，schema /1 HOG、/2 墨量图）包成 3b 方法，见模块头「pair_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path, pair=None):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from . import pair_shape
        self.model = pair_shape.load(str(self.path))
        self.chars = tuple(self.model["chars"])
        self.want = None if pair is None else [str(c) for c in pair]
        if self.want is not None and sorted(self.want) != sorted(self.chars):
            raise ValueError(f"pair_shape：{self.path} 是 {''.join(self.chars)} 的模型，书配置写的 pair 是 {''.join(self.want)}")
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`pair_shape.judge` 的结果 → `{chars[1]: σ(s), chars[0]: 1−σ(s)}`（s 用 judge 已取整的 score）；没有 s → `{}`。"""
        s = v.get("score")
        if s is None:
            return {}
        a, b = self.chars
        q = round(1.0 / (1.0 + math.exp(-min(50.0, max(-50.0, float(s))))), 4)    # 截到 ±50：多类的对数概率差可能很大
        return {b: q, a: round(1.0 - q, 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import pair_shape
        out = []
        for g in patches:
            v = pair_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "pair_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        a, b = self.chars
        kn = (self.calib or {}).get("knots", {}).get(b)
        if not kn or b not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[b], xs, ys))
        return {b: round(p, 4), a: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src) if self.want is None else _pair_fingerprint(self.src, self.want)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里 `ps`／`pp` 段同算法（`pair_shape.fingerprint`）。"""
        from . import pair_shape
        return pair_shape.fingerprint(str(self.path))


def lib_fingerprint(src) -> str:
    """书级刻例库（book_knn／near_knn 的模型文件：本书已放行格当刻例的 PCA 库）钉好的那一版的指纹：文件内容 sha256 前 16 位。

    `src` 是库文件路径（`str`／`Path`；相对路径照 `resolve_dir` 先找数据目录再找仓根；给目录时取目录里的 `model.json`）。
    与第四步参数指纹 `bk`／`nk` 段（`book_knn.fingerprint`／`near_knn.fingerprint`）**同算法同值**；3b 把它写进 `methods_sha`
    （`<组>:book_knn=<指纹>`），4d 拿它现用的那份库（`group_flow_book_knn[组]`，已解析成绝对路径）调同一个函数比对，
    不一致时本地现算。文件不在 → `""`（同 `book_knn.fingerprint`）。"""
    p = resolve_dir(str(src))
    if p.is_dir():
        p = p / "model.json"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else ""


BOOK_KNN_KEYS = ("char", "why", "tier", "pick", "votes", "ratio", "nn")
"""第四步 `evidence.book_knn` 的键（`seed_admit_shapes._book_knn_pass` 的 trail），`book_knn_settle` 按这个次序出。"""


def book_knn_measure(f, model: dict) -> dict:
    """book_knn 前段「出原始量」：HOG 特征 → 不看整理本时 `book_knn.judge_feat` 的结果（票数、距离比、nn、pick、A 档结论或弃权），
    再加 `b_ok`（只在 `abstain:low_margin` 时有）：整理本对位字若恰是 pick，B 档（`ref_votes_min`／`ref_ratio_max`）过不过。

    `judge_feat` 只在 B 档那一句用到 `ref`，且只看 `ref == pick`，所以 `b_ok` 直接拿 `ref=pick` 再调一次 `judge_feat` 算
    （比的是未取整的距离比，与现役同一个判断），不另写一份门槛。"""
    from . import book_knn
    v = book_knn.judge_feat(f, model, None)
    if v["why"] == "abstain:low_margin":
        v["b_ok"] = book_knn.judge_feat(f, model, v["pick"])["why"] == "agree_ref"
    return v


def book_knn_settle(ev: dict, ref: str | None) -> dict:
    """book_knn 后段「定档」：前段的量（`book_knn_measure` 的结果，或 3b 证据 `NearMethodOut.evidence`，多的 `method` 键不管）
    ＋整理本对位字 → 与现役 `book_knn.judge(图, 模型, ref)` 逐键相同的 dict（键次序同 `BOOK_KNN_KEYS`，即第四步 `evidence.book_knn`）。
    只有前段弃权在 `low_margin`、`b_ok` 为真、整理本字＝pick 时升 B 档（`agree_ref`），其余原样。不读模型。"""
    v = {k: ev[k] for k in BOOK_KNN_KEYS if k in ev}
    if ev.get("why") == "abstain:low_margin" and ev.get("b_ok") and ref is not None and ref == ev.get("pick"):
        v.update(char=ev["pick"], why="agree_ref", tier="B")
    return v


class BookKnn:
    """字组书级刻形近邻（`groups.book_knn`）包成 3b 方法，只出前段（A 档）；B 档由 4d 用 `book_knn_settle` 定，见模块头「book_knn」。"""

    patch = "char_patch"
    lib = True                       # 方法指纹＝刻例库文件指纹（`lib_fingerprint`），不是模型目录指纹

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from . import book_knn
        self.model = book_knn.load(str(self.path))

    def sims_of(self, v: dict) -> dict[str, float]:
        """前段结果 → `{pick: 票数/k}`（4 位）：只给近邻多数字的票份额；没有 pick、pick 是背景刻例 `~` → `{}`。"""
        from . import book_knn
        pick = v.get("pick")
        if pick is None or pick == book_knn.BACKGROUND:
            return {}
        return {str(pick): round(int(v["votes"]) / int(self.model["k"]), 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from .rr_shape import features
        out = []
        for g in patches:
            v = book_knn_measure(features(g)[0], self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "book_knn", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        return None                  # 没有校准表：票份额只当证据

    def fingerprint(self) -> str:
        return lib_fingerprint(self.path)

    @property
    def model_sha(self) -> str:
        """库文件的版本，与第四步参数指纹 `bk` 段同算法（`book_knn.fingerprint`）。"""
        return self.fingerprint()


METHODS = {"cnn_small": CnnSmall, "rr_shape": RrShape, "wu_shape": WuShape, "hou_shape": HouShape,
           "part_shape": PartShape, "pair_shape": PairShape, "book_knn": BookKnn}
SPEC_KEYS = ("path", "pair")

_CACHE: dict[tuple, object] = {}


def parse_spec(spec) -> tuple[str, dict]:
    """书配置里一个方法的写法 → (模型路径, 其余参数)。字符串＝模型目录或文件；dict＝`{path, pair}`。"""
    if isinstance(spec, (str, Path)):
        return str(spec), {}
    if isinstance(spec, dict):
        bad = set(spec) - set(SPEC_KEYS)
        if bad or "path" not in spec:
            raise ValueError(f"glyph_near 方法写法 {spec!r} 不认识：要 {{path, pair}}（多了 {sorted(bad)}）")
        kw = {k: (list(v) if k == "pair" else v) for k, v in spec.items() if k != "path"}
        return str(spec["path"]), kw
    raise ValueError(f"glyph_near 方法写法 {spec!r} 不认识：写模型路径字符串或 {{path, pair}}")


def load_method(name: str, spec):
    """方法名＋模型目录（或单个模型文件，或 `{path, pair}`）→ 方法对象（按解析后的路径＋参数缓存）。"""
    cls = METHODS.get(name)
    if cls is None:
        raise ValueError(f"glyph_near：不认识的方法 {name!r}（已登记：{sorted(METHODS)}）")
    path, kw = parse_spec(spec)
    d = resolve_dir(path)
    key = (name, str(d), json.dumps(kw, ensure_ascii=False, sort_keys=True))
    m = _CACHE.get(key)
    if m is None:
        if not d.exists():
            raise FileNotFoundError(f"glyph_near 方法 {name} 的模型目录不存在：{d}")
        m = cls(d, **kw)
        _CACHE[key] = m
    return m


def method_fingerprint(name: str, spec) -> str:
    """`<方法>=<指纹>`，进 3b `methods_sha`；4d 比对模型版本也调它。spec 是字符串时＝模型目录（或文件）的指纹（与 11-28 之前逐位相同）；
    `{path, pair}` 时＝文件指纹并上这一对（按码位排，次序不论）；书级刻例库方法（`lib = True`，book_knn）＝`lib_fingerprint`。"""
    path, kw = parse_spec(spec)
    d = resolve_dir(path)
    if getattr(METHODS.get(name), "lib", False):
        return f"{name}={lib_fingerprint(d)}"
    if kw.get("pair") is not None:
        return f"{name}={_pair_fingerprint(d, kw['pair'])}"
    return f"{name}={_dir_fingerprint(d)}"
