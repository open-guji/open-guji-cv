"""C1 进库准入（`seed_admit`）的书级放行通道钩子：缺省什么都不做，各书产物不变。

2026-11-24 CV4（Sheldon 定「搬进全唐文书仓」）：只有某本书在用的放行通道不再做成 cv 里「缺省关、按书开」的参数，
放进书仓 `code/`。书仓写一个同名模块，`code/code.yaml` 的 `overrides` 写 `keben.admit_lanes: <本书模块>`，
册配置 `params.seed_admit.book_lanes` 写这些通道的取值，出新 `k` 即生效。写了 `book_lanes` 而书仓没覆盖本钩子 → 拒跑。

- `noref_lanes(*, out, mmap, amap, rare, coord, params, facts) -> int`

  无参照补放（升）：在 `solo_5b` 之后、`ref_lib_5b_veto` 之前调一次（全唐文 001–003 原来的 solo_adapt／num_run／
  solo_cal／lead_5b 四条通道就在这个位置）。原地改格、返回升级格数。

  - `out`：本页 `ColumnAdmit` 列表；格（`AdmitRec`）可改 `admit`／`char`／`channel`／`provenance`／`doubts`／`evidence`；
  - `mmap`：格 id → 库匹配记录（`candidates` [(字, cov)]、`guard`）；`amap`：格 id → 现役整理本对位；
  - `rare`：本页 5-b 产物（`rare_candidates`，没有为 None）；`coord`：格 id → 坐标对位的整理本字；
  - `params`：册配置 `params.seed_admit.book_lanes`（dict，原样进参数指纹）；
  - `facts`：cv 给的只读工具（书级代码不许 import cv 内部模块），见 `seed_admit._AdmitFacts`：
    `gap_chars`、`group_chars`、`near_form_chars`、`is_gap(ch)`、`is_hanzi(ch)`、`are_variants(a, b)`、
    `look_alike(a, b)`、`canonical_char`（本书码位归一，没有码位表为 None）、`data_path(rel)`（按数据目录→工作区解析）。

`book_lanes` 里的 `data`（相对数据目录的路径表）是本书通道要读的数据文件：cv 把内容哈希填进参数
`book_lanes_fingerprint`，文件改了产物过期；钩子里用 `facts.data_path(rel)` 取绝对路径。
"""

noref_lanes = None
