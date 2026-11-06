"""代码等价登记（2026-10-20，sheldon 定）：「产物逐字节不变」的提速改动不让各册产物过期。

## 为什么

Step 模块与它的 `code_deps` 进产物指纹（`core/engine.py::code_hash`），改一个字符各册这一步
以下全线判过期、整册重算。这是对的——改算法就该重算。但纯提速的改动（加索引、按需算、
缓存）产物逐字节不变，重算一遍白花几个小时，久而久之没人敢动热点代码。

## 怎么用

改完代码，用 `scripts/code_equiv.py check` 拿旧版本（`--base`）与工作区现版本在同一批页上
各跑一遍受影响的步，**产物逐页 sha256 全部相同**才打印登记行；把登记行抄进下面的 `ENTRIES`，
同一个 PR 里提交。登记的意思是「这个模块新代码的指纹 ≡ 旧代码的指纹」：`_module_source_hash`
算出新哈希后查这张表，换回旧哈希，于是指纹、`self_hash`、`guji status` 都看不出代码变过。

## 纪律

- **只登记逐字节相同的改动。** 结果哪怕只差浮点末位，也不许登记——那是算法改动，该重算。
- 证据写进 `evidence`：哪个基线 commit、哪册哪些页、多少页逐字节相同。页要够杂（正文、
  夹注、难页），一册几十页起步；能多册更好。
- 本模块不在任何 Step 的 `code_deps` 里（`tests/test_code_equiv.py` 守着），改它不动指纹。
- 登记行**只增不删**：删一行，曾经靠它保持新鲜的产物就会全部判过期。
- 链式：A→B、B→C 都登记了，A 也映到 C（多次提速叠加）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Equiv:
    module: str
    new: str
    """改后的「只认代码」哈希（`engine.code_only_text` 的 sha256 全长）。"""
    old: str
    """改前的哈希；指纹里继续用它。"""
    evidence: str


_GM_1020 = ("glyph_match 提速（wmax 按需算、同格查找分桶、HOG 向量化）：vol04 46 页（每 5 页取 1，加 p17/p100/p186，含夹注与最慢页）、vol06 15 页（每 10 页取 1）与改前 529f071 产物逐字节相同，4 进程；scripts/code_equiv.py check，2026-10-20")

_GM_1020_PM = ("glyph_match 加 batch_knn 开关（缺省关）、匹配器可收现成相似度、整库矩阵抽成 library_matrix（GUJI-647）："
               "开关关着时 vol06 30 页（每 5 页取 1）与 origin/dev fbfd1f9 产物逐字节相同，库含字体域（17.4 万条），"
               "匹配器走新的特征缓存；scripts/code_equiv.py check，2026-10-20")

_SYM_1022 = ("特殊符号进候选集 S3（seed_admit 加 symbol_review 开关，缺省关；ctx_l1 目标位换私用区码位）："
             "开关关着时 vol06 30 页（每 5 页取 1，group_flow 的 ctx_l1 规则有命中）与 origin/dev 5826853 产物逐字节相同；"
             "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn（dev 上 ids_bank 与钉子不符，新旧两边同样），2026-10-22")

_HR_1026 = ("抬头框探测加 head_raise_scale（GUJI-748，缺省 1.0 取原常数）：border_detect 在殿本 vol05 旧图 188 页"
            "（全册）与 vol07 新图 134 页（全册，缺省尺度下 7 列抬头）上与 origin/dev abeac44 产物逐字节相同；"
            "scripts/code_equiv.py check，2026-10-26")

_GL_1027 = ("网格模式加 grid_lattice_fallback（GUJI-748 vol12 p139，缺省关不传参）：border_detect 在殿本 vol12 新图 152 页"
            "（全册，yaml 已点名网格页 p79）与 vol07 新图 134 页（全册）、column_warp 在 vol12 152 页上与 origin/dev "
            "（border_detect 1.11，1fa91e8；column_warp 比的是 126e021）产物逐字节相同；scripts/code_equiv.py check，2026-10-27")

_BC_1027 = ("push_bottom_to_bar 右界截到图内（GUJI-748，换源新图 vol23 p10、vol37 p74 越界报错）：只在原先越界报错的页上生效；"
            "border_detect 在殿本 vol20 新图 94 页（每 3 页取 1）上与 origin/dev f3b96b9 产物逐字节相同；scripts/code_equiv.py check，2026-10-27")

_HRV_1027 = ("人裁逐列抬头（head-raise-columns 裁决补／去 Step1 抬头框、row_segment 级数听裁决；没有裁决的页不动）："
             "border_detect 在殿本 vol23 新图 172 页（全册，21 列抬头）、row_segment 在 vol23 46 页（每 4 页取 1，加 p116–119 抬头页）"
             "上与 origin/dev 78f00ac 产物逐字节相同；scripts/code_equiv.py check，2026-10-27")

_SEED_1027 = ('seed_admit 的 clustering.seeding 去掉联网取派生缓存（拆分 M3b：改用 core.derived 注册的取法，行为不变）：seed_admit 在殿本 vol04 新图 40 页（每 6 页取 1，加 p17/p100/p186）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn（dev 上语料底库与钉子不符，新旧两边同样），2026-10-27')

_MV_FREE = ("切分模块化第 2a 步：free_* 五个模块从 utils/ 原样搬进 books/zengguang_youxue/，只有 import 路径变"
            "（free_cells 的 `..core` → `...core`；四个自由版式步骤只改 import 与 code_deps 里的模块名），算法未动；"
            "搬前搬后 24 个 Step 的 code_hash 逐位相同（对 origin/dev d199da5 逐步比对），2026-10-30")

_MV_BEIXING = ("切分模块化第 2b 步：line_layout、run_segment 从 utils/ 原样搬进 books/beixing/，只有 import 路径变"
               "（line_layout 的 `.border_geometry` → `...utils.border_geometry`；两个现代印刷步骤只改 import 与 code_deps 里的模块名），"
               "算法未动；搬前搬后 24 个 Step 的 code_hash 逐位相同（对 origin/dev 逐步比对），2026-10-30")

_MV_SIKU = ("切分模块化第 2c 步：殿本 Step3 的 row_boundaries、row_grid、jiazhu_split、roster_segment、roster_glyph、yolo_tool_infer 与 calibrate "
            "从 utils/ 原样搬进 books/siku_zongmu/，只有 import 路径变（相对层数加一、指向 utils 里留下的模块改成 `...utils.x`），"
            "算法未动；搬前搬后全部 Step 与闸的 code_hash 逐位相同（对 origin/dev 3d064ce 逐步比对），2026-10-30")

_MV_SJ = ("切分模块化第 2d 步：row_segment._run_roster 里职名页的 load_scorer／segment_roster_page 改成按册的套书取模块"
          "（core/seg_set.resolve；史記册取 books/shiji_wyg 的复制，其余册取到的仍是原模块），非史記册逻辑与产物不变；"
          "非史記册 23 个 Step 与闸的 code_hash 前后逐位相同，史記册的 row_segment 指纹另按自己的模块算，2026-10-30")

_MV_SEG1 = ("切分模块化第 3 步（一）：seam、cut_select 从 utils/ 原样搬进共用原语库 seg/（两套以上的书在用的走缝、切点裁判），"
            "只有 import 路径变，算法未动；搬前搬后全部 Step 与闸的 code_hash 逐位相同（对 origin/dev 869694b 逐步比对），2026-10-30")

_MV_SIKU2 = ("切分模块化第 3 步（二）：殿本 Step1 专用的 pitch_rescue、column_pair_merge、column_types 从 utils/ 原样搬进 "
             "books/siku_zongmu/，只有 import 路径变，算法未动；搬前搬后全部 Step 与闸的 code_hash 逐位相同"
             "（对 origin/dev d974185 逐步比对），2026-10-30")

_SP_FT = ("切分模块化第 3 步（三）：border_geometry 里的边框结果数据类型（HLine／VLine／HeadRaiseBorder／BorderDetectionResult）"
          "原样拆进 seg/frame_types.py，border_geometry 从那里 import 并转出口；用到 border_geometry 的三步把 frame_types 列进 code_deps，"
          "products 与北行日錄 line_layout 改从 seg 引；算法未动；拆前拆后全部 Step 与闸的 code_hash 逐位相同（对 origin/dev 7111864），2026-10-30")

_SP_PLS = ("切分模块化第 3 步（四）：peak_line_search 拆成两块——投影找峰、位置＋角度联合搜索、整页找竖线／上下框线（含粗外条吸内框、"
           "胖假峰换线、下框救援，这几样在通用函数里一直开着）原样拆进 seg/lines.py；网格模式（GRID_*、grid_thresholds、"
           "select_frame_pair、verify_slots、lattice_frame_pair、find_vertical_lines_grid 等）留在 utils/peak_line_search，"
           "从 seg.lines import；border_geometry 与 locate_gutter 改 import，border_detect 把 seg.lines 列进 code_deps；"
           "算法未动；拆前拆后全部 Step 与闸的 code_hash 逐位相同（对 origin/dev 289ef4b），2026-10-30")

_SP_BG = ("切分模块化第 3 步（五）：utils/border_geometry 拆完——界行折线拟合（BEND_*／KNOT_*、_rule_rows、gutter_projection、"
          "_fit_knots、fit_vlines_polyline 等，只依赖自己的常量）原样拆进 seg/polyline.py，其余（抬头框、双边外框与下框条、"
          "按横带证据回直、整册标定、detect_borders）原样搬成 books/siku_zongmu/border.py；utils/peak_line_search 剩下的网格模式"
          "原样搬成 seg/grid.py（北行日錄与殿本都用）。各处 import 按名字改到定义模块，三步 code_deps 换成新模块；"
          "算法未动；拆前拆后全部 Step 与闸的 code_hash 逐位相同（对 origin/dev 88a8a9e），2026-10-30")

_SP_CP = ("切分模块化第 3 步（六）：utils/column_projection 拆成三块——单列射影矫正与列窗口（column_warp_matrix、warp_column、"
          "page_column_windows 等）原样拆进 seg/warp.py，列投影／去噪／文字带（denoise_column、column_profile、column_row_profile、"
          "column_text_band、stamp_noise_density）原样拆进 seg/profile.py，界行与版框残墨剥法、clean_column、refine_top_by_frame、"
          "warp_page_columns 原样搬成 books/siku_zongmu/column.py；column_triage 搬 books/siku_zongmu、locate_gutter 搬 seg（只改 import）。"
          "四步 code_deps 换成三块；算法未动；拆前拆后全部 Step 与闸的 code_hash 逐位相同（对 origin/dev eef311e），2026-10-30")

_SJ_PINS = "row_segment 在史記 04 册 7 页（--pages 1,20,40,80,100,130,141，离线 layout_prior 配置）上与改前产物逐字节相同"
_SJ_780 = ("史記文淵閣本前三册切分（#780）在 Step 壳加缺省关的开关：row_segment 的 roster_ref_corpus／roster_ref_pins（职名页、"
           "卷端标题列按整理本字数重切，只史記套书实现钩子）、cell_shrink／extractor 的 frame_line_max_off、jiazhu_end_halves；"
           "开关关着时 row_segment、cell_shrink 在殿本 vol01 43 页（每 6 页取 1，加职名页 87–130 每 3 页）与 vol06 37 页"
           "（每 4 页取 1）上与 origin/dev e2cb245 产物逐字节相同；scripts/code_equiv.py check，2026-10-31")

_SJ_788 = ("史記文淵閣本册 01–03 坐标对位（#788）在 align_ref 壳加缺省关的开关 coord_relaxed（圈号「○」格不占字位、按 Step3 格号配、"
           "职名列按次序配，逻辑在 align_ref_coord._coord_relaxed）；开关关着时 align_ref 在殿本 vol06 48 页（每 4 页取 1，加坐标退回页）"
           "与 vol30 46 页（同法）上与 be17cce 产物逐字节相同；2026-11-02 合 dev 后重证：史記 04 册 10 页（coord_relaxed 关着）与 origin/dev 逐字节相同；scripts/code_equiv.py check")

_SJ_VLINE = ("border_detect 加缺省关的页级人核界行 vline_overrides（史記 04 p120/p122、06 p63 右/左外框被扫描裁掉，界行整串错一位）："
             "不配时 border_detect 在史記 04 册 10 页（--pages 2,10,34,47,80,100,120,122,138,141）上与 origin/dev eb68e864 产物逐字节相同；"
             "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-02")

_SJ_TOPK = ("seed_admit 加缺省关的书级开关 ref_topk_follow（库前 5 名候选里有整理本字且 cov 接近首位时按整理本放，要 reference_trust very_high）："
            "不配时 seed_admit 在史記 04 册 8 页（--pages 2,10,34,47,120,122,135,138）上与 origin/dev e1c28387 产物逐字节相同；"
            "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-03")
_ALT_CUT = ("备选切法 alt_cut（row_segment 书级开关，缺省关；Step4/5a 另存 alt_columns、align_ref 按列挑、seed_admit 读挑中那份）："
            "开关关着时 row_segment、cell_shrink、glyph_match、align_ref、seed_admit 在殿本 vol12 新图 31 页（每 5 页取 1）上"
            "与 6154bc1f 产物逐字节相同，cell_shrink 字块 5089 张同（A22）；史記 04 册 12 页（p2,10,34,41,43,47,105,119,120,122,124,138）"
            "五步亦逐字节相同；scripts/code_equiv.py check，2026-11-03")
_SJ_INKCUT = ("row_segment 书级开关 seal_inkcut（缺省关，史記文淵閣本第 5 轮，大印下抹印泥再切）："
              "开关关着时 row_segment 在史記 04 册 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 0883ff37 产物逐字节相同；"
              "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-03")

_SJ_DP = ("align_ref 在史記文淵閣本 04 册 10 页（--pages 2,10,34,41,43,47,120,122,124,138）上与 origin/dev（含 #788）产物逐字节相同；"
          "coord_dp 关着（册 yaml coord_dp: false，缺省）；scripts/code_equiv.py check，2026-11-02")

_SJ_GAP = ("row_segment 加缺省关的书级开关 layout_gap_cols_empty（本页两列表行之间缺的列当整列空，史記卷末叶大印压着的空列）："
           "不配时 row_segment 在史記 04 册 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 531f241f 产物逐字节相同；"
           "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-03")

_SJ_PITCH = ("row_segment 加书级参数 row_pitch（uniform 缺省／free：写本不让等距格网优先，史記文淵閣本）："
             "缺省 uniform 时 row_segment 在史記 04 册 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 571313c0 产物逐字节相同；"
             "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-03")

_SJ_R5 = ("row_segment 书级开关 seal_gap_slots_empty、align_ref 书级开关 coord_dp_flat（都缺省关，史記文淵閣本第 5 轮）："
          "开关关着时 row_segment、align_ref 在史記 04 册 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 0c773642 产物逐字节相同；"
          "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-03")

_JZ_ROWS = ("雙行小注两行各切 jiazhu_rows（row_segment 书级开关，缺省关；seg.seam 加 fit_row_cuts；cell_shrink／extractor 半格自己的 y）："
             "开关关着时 row_segment、cell_shrink 在殿本 vol12 新图 31 页（每 5 页取 1）上与 origin/dev d961e8c1 产物逐字节相同；"
             "scripts/code_equiv.py check，2026-11-03")

_JZ_STRIP = ("夹注格列端剥框线、长竖线 jiazhu_strip_rules（cell_shrink 书级开关，缺省关；extractor strip_long_rule 加 through）："
             "开关关着时 cell_shrink 在殿本 vol12 新图 31 页（每 5 页取 1）上与 origin/dev 0c773642 产物逐字节相同；"
             "scripts/code_equiv.py check，2026-11-03")

_FRAME_GROW = ("列端剥框线认粗框线与毛边 frame_line_grow（cell_shrink 书级开关，缺省关；extractor strip_frame_line、strip_long_rule 加 grow）："
               "开关关着时 cell_shrink 在全唐文 vol06 40 页（每 5 页取 1）上与 origin/dev 6c11060 产物逐字节相同；"
               "scripts/code_equiv.py check，2026-11-03")

_TAIL_EMPTY = ("表外末列不当整列空 layout_tail_empty（row_segment 书级开关，缺省开取原行为；_layout_row 加 tail_empty）："
               "开关缺省时 row_segment 在全唐文 vol09 有表外末列的 28 页（全部）上与 origin/dev 产物逐字节相同；"
               "scripts/code_equiv.py check，2026-11-03")

_ROW_FREE_PITCH = ("格位表单列 pitch: free（row_segment：表里写了这个键的列不优先等距格网；全唐文卷首帝名列）："
                   "表里没这个键时 row_segment 在全唐文 vol06 p20–29（产物包 r9b）上与 origin/dev 产物逐字节相同；"
                   "scripts/code_equiv.py check，2026-11-04")

_JZ_SINGLE_HEAD = ("一行就完的雙行小注段头 jiazhu_single_head（row_segment 书级开关，缺省关；jiazhu_split.single_row_heads、"
                   "row_boundaries.segment_column 加参数）：开关关着时 row_segment 在全唐文 vol06 p20–29（产物包 r9b）上"
                   "与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-04")

_COORD_PAIR = ("align_ref 加缺省关的书级开关 coord_shift_needs_pair（坐标对位「邻格错位」要邻格现役也错开才算整列错一位；全唐文 r10 "
                "006 p81 列 3 紛／綸）：开关关着时 align_ref 在全唐文 vol06 p75–89（产物包 r10）上与 origin/dev 产物逐字节相同；"
                "scripts/code_equiv.py check，2026-11-04")

_COORD_PAIR_SUB = ("align_ref 加缺省关的书级开关 coord_pair_no_sub（coord_shift_needs_pair 不管夹注半格；全唐文 r11 007 p47 列 3）："
                    "开关关着时 align_ref 在全唐文 vol06 p75–89（产物包 r11）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-05")

_QTW_FORK = ("全唐文套书 books/quantangwen 分叉（2026-11-04，A22）：row_boundaries、jiazhu_split 从殿本原样复制（含 #1025 "
             "jiazhu_single_head），殿本两份退回 #1025 之前；row_segment 壳按册套书取 row_boundaries（core/seg_set.resolve）。"
             "复制与殿本 #1025 之后那一版逐字相同，#1025 已证开关关着时等价（_JZ_SINGLE_HEAD）；全唐文册的指纹按 FORKED 记原模块名，不过期。"
             "殿本 vol12 31 页 row_segment 与 origin/dev bc219f2 逐字节相同（scripts/code_equiv.py check）")

_SJ_PAIR_SHAPE = ("seed_admit 加缺省关的书级开关 group_flow_pair_shape（史记之矣刻形二选一，groups.pair_shape；缺省空时参数 dump 不含该键）："
                  "开关缺省时 seed_admit 在史記 03 册 25 页（--pages 100-124，产物包 job65 cv 0a5ba0b）上与 origin/dev 产物逐字节相同；"
                  "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-03")

_TIGHT_BAND = ("写本界行判带收紧 tight_rule_band（column_warp 书级开关，缺省关；seg.profile column_text_band 加 first_valley、"
               "siku_zongmu.column clean_column 透传）：开关关着时 column_warp 在殿本 vol12 新图 31 页（每 5 页取 1）上与 origin/dev "
               "af1fa3c4 产物逐字节相同，279 张清理后列图逐字节相同；scripts/code_equiv.py check，2026-11-03")

_JZ_FREE = ("雙行小注两行字数可不等 jiazhu_free_split（row_segment 书级开关，缺省关；siku_zongmu.row_boundaries 加 _free_split）："
             "开关关着时 row_segment 在殿本 vol12 新图 31 页（每 5 页取 1）上与 origin/dev 0a5ba0b7 产物逐字节相同；"
             "关着时只多一个空的 half_side 判断，全唐文等走同一 row_segment 的书同理；scripts/code_equiv.py check，2026-11-03")

_JZ_HALF = ("夹注格半格框线、贴外沿竖框 jiazhu_strip_rules r6（cell_shrink 书级开关，缺省关；extractor 加 strip_jiazhu_half_line、"
             "strip_long_rule through 认碰字的线、page_frame_line_offsets 加 span_frac）：开关关着时 cell_shrink 在殿本 vol12 新图 31 页"
             "（每 5 页取 1）上与 origin/dev f48e3466 产物逐字节相同；scripts/code_equiv.py check，2026-11-03")

_JZ_GUARD = ("夹注两行差 2 字兜底、写本内框细线一页 2 列即认（row_segment jiazhu_free_split、cell_shrink jiazhu_strip_rules 书级开关，缺省关）："
             "开关关着时 cell_shrink 在殿本 vol12 新图 31 页（每 5 页取 1）、row_segment 在 9 页上与 origin/dev c651c8d2 产物逐字节相同；"
             "scripts/code_equiv.py check，2026-11-03")

_JZ_BAND = ("写本内框细线断成几截（cell_shrink jiazhu_strip_rules 书级开关，缺省关；extractor 加 inner_frame_band_mask／"
             "strip_inner_frame_band，列端格按全页半格线位认线带）：开关关着时 cell_shrink 在殿本 vol12 新图 31 页（每 5 页取 1）"
             "上与 origin/dev 61332c2 产物逐字节相同，另 5 页 907 张字块 PNG 同；scripts/code_equiv.py check，2026-11-04（A22）")

_IF_PROFILE = ("内框细线整宽行墨补拟 inner_frame_profile（cell_shrink 书级开关，缺省关；seg.frame_line 小段投票抽成 _chunk_inner、"
               "加 _profile_inner）：开关关着时 cell_shrink 在殿本 vol30 新图 28 页（每 5 页取 1）上与 origin/dev 4a47fbe 产物逐字节相同；"
               "另 inner_frame_cut 开、inner_frame_profile 关时 vol05（186 页）、vol30（140 页）全册 char_index 与 55417 张字块 PNG 与 dev 逐字节相同；"
               "scripts/code_equiv.py check，2026-11-05（A22）")

_IF_ONLY = ("内框细线已抹的一端不再逐格剥框线、框渣只剥贴线的 inner_frame_only（cell_shrink 书级开关，缺省关；extractor "
            "strip_frame_debris 加 line_bot/line_top）：开关关着时 cell_shrink 在殿本 vol30 新图 28 页（每 5 页取 1）上与 origin/dev "
            "76b7431 产物逐字节相同；inner_frame_cut＋inner_frame_profile 开、本开关关时 vol05、vol30 全册 char_index 与字块 PNG 与 dev 逐字节相同；"
            "scripts/code_equiv.py check，2026-11-05（A22）")

_JZ_HALF_A = ("只有右半的夹注格整字发右半 jiazhu_half_a（row_segment 书级开关，全唐文套书，缺省关；quantangwen.row_boundaries 加 "
              "_half_a_left）：开关关着时 row_segment 在全唐文 013 p146–151（6 页，含格位表 half 39 格；基底产物包 r12）上与 origin/dev "
              "9ce806a 产物逐字节相同；scripts/code_equiv.py check，2026-11-05（切分线）")

_TAIL_ONE_ABS = ("列端孤「一」绝对量逃生口 tail_one_abs（cell_shrink 书级开关，缺省关；extractor is_end_cell_junk 加 one_abs、"
                 "列端渣格闸按往里一格是字才放）：开关关着时 cell_shrink 在全唐文 012 p20/31/33/80/89/146（基底产物包 r13）上与 origin/dev "
                 "产物逐字节相同；scripts/code_equiv.py check，2026-11-05（切分线）")

_LAYOUT_CUTS = ("格位表人定格线 cuts（row_segment，表行写了 cuts／col_h 才照线切，没写的列不变）：row_segment 在全唐文 012 p20/31/33/80/89/146、"
                 "013 p140/147（本机 dev 从 border_detect 起出上游）上与 origin/dev b148b2c 产物逐字节相同；scripts/code_equiv.py check，2026-11-05（切分线）")

_COLTEXT = ("自动配页加参照类型 page_map_ref（缺省 column_slots，原路径；column_text 的算法在 steps/row_segment_coltext.py、"
            "不在 code_deps、指纹走 page_map_fingerprint）；page_align 抽出 align_scores（align 改为调用它，加 reorder/swap 开关缺省开）："
            "row_segment 在殿本 vol60 22 页（page_map: strict，--pages 1,6,…,126 每 6 页取 1）与全唐文 006 7 页"
            "（离线 layout_prior，--pages 20,40,61,100,120,150,182）上与 origin/dev cbb1917 产物逐字节相同；scripts/code_equiv.py check，2026-11-06")

_SEAL_TOP = ("卷端标题列去印点后抹列顶印边残块＋起格跳过整格在首字之上的印泥格（row_segment._clear_seal_top_residue，"
             "只在 roster_seal_despeckle 开着、header_cols 认得的大印列生效，殿本不走）：row_segment 在殿本 vol12 152 页（--pages all）"
             "上与 origin/dev 6a2aca8 产物逐字节相同；史記 02/04/07/10 册全册重跑只 02 p2 c4–c6、04 p2 c4、10 p2 c6 变（有意改动），"
             "scripts/code_equiv.py check，2026-11-06")

ENTRIES: tuple[Equiv, ...] = (
    Equiv(module="open_guji_cv.clustering.match",
          new="b92800929fb79593ec59194fbd81c4dda912763ba39b9e31c10cadb32761935e",
          old="7fa5464da6ca4c45382394b0ecc847e8b8495c806609e2505da4ef9b0c762ab5",
          evidence=_GM_1020),
    Equiv(module="open_guji_cv.clustering.verify",
          new="78f15462e72b050a027f3e201d3bb45cee56ac0376c73e35e437e98713021e2e",
          old="a52029152e1c89a2c5b0c269bea99d0cd9f477e85b3deb6e6e041684db739c29",
          evidence=_GM_1020),
    Equiv(module="open_guji_cv.clustering.features",
          new="1e6c03d679834e9e74effdb44df0da2fef9608c1905f38f5b0214718a31732be",
          old="28cd1749594a804c94f92e7dd3e9b298af30cc834357cd3c0a323d7d2af5fc4c",
          evidence=_GM_1020),
    Equiv(module="open_guji_cv.steps.align_ref_coord",
          new="2eab06857f480e3bea599a57c7207291e0b080d2eb4e0af6c76c3dda40b7b8b2",
          old="b7f1dca521754254e92f782c0fa42767ab838e8a1b4cf09c629bc4d14b39c235",
          evidence=("align_ref 起跑提速（parse_lines 复用 Unit、is_text_char 记忆）：vol04 46 页（每 5 页取 1，"
                    "加 p17/p100/p186）与改前 ea23fa2 产物逐字节相同；scripts/code_equiv.py check，2026-10-20")),
    Equiv(module="open_guji_cv.steps.occlusion",
          new="117331bc9546623d4f868373e180a11b87fd358a523e56f2a604727c9889a2f5",
          old="f7c7523a877b2beaa697ceadb9b345c4df1b327c96d34bd4c7a7d5579be6ed7c",
          evidence=("印章遮挡 cell_densities 不建整页积分图、直接数框内墨点（0.21 s → 0.02 s/页）：cell_densities "
                    "vol04 46 页逐项相同；cell_shrink、seed_admit 各 46 页与改前 e3aed02 产物逐字节相同；2026-10-20")),
    Equiv(module="open_guji_cv.clustering.seeding",
          new="d929e31c4168f89190c1d4204c0307449b67e248ce85bf37e51600b4ad81f260",
          old="605f584a6dbc53965c57e457ab520dc3f3aa1a7ec1d3d3c9cb5a30192eb7407d",
          evidence=("匹配器特征按内容缓存、整库矩阵只存一份（GUJI-647）：seed_admit 在 vol06 30 页（每 5 页取 1）上"
                    "与 origin/dev fbfd1f9 产物逐字节相同，库含字体域（17.4 万条）；scripts/code_equiv.py check，2026-10-20")),
    Equiv(module="open_guji_cv.steps.glyph_match",
          new="393c49ce70ff3ba5672beb3493f650dd5dcb933e002d296871f87b8cd9469484",
          old="f67439e5c78f68150e1509bf7e8aa7db437d66ef5e7a145340c505fd00bf4b5d",
          evidence=_GM_1020_PM),
    Equiv(module="open_guji_cv.clustering.match",
          new="fce6b16b7513e40ba0edda3f66df99a6f1089d5acce9869272229c3ed3363389",
          old="7fa5464da6ca4c45382394b0ecc847e8b8495c806609e2505da4ef9b0c762ab5",
          evidence=_GM_1020_PM),
    Equiv(module="open_guji_cv.steps.glyph_match",
          new="7f2f4fb431f137add3bea3cfa979e637ba7eb0dff52844f381c2b201240c69a4",
          old="f67439e5c78f68150e1509bf7e8aa7db437d66ef5e7a145340c505fd00bf4b5d",
          evidence=("glyph_match 加 font_tier 开关（缺省关，GUJI-726）：开关关着时 vol06 30 页（每 5 页取 1）与 origin/dev "
                    "（glyph_match 与 code_deps 同 fb6ff83）产物逐字节相同，库含字体域（17.4 万条）；scripts/code_equiv.py check，2026-10-21")),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="2a4219983670c95907006ebdd3aeac23130c19d0aac7df7011b637749248bc83",
          old="3d8e409fbeeb20d41cba5d4e8eef694dd5e9285490e4f8ba6c21e234b442a867",
          evidence=_SYM_1022),
    Equiv(module="open_guji_cv.groups.ctx_l1",
          new="720a9e15855681456378e88ec5504d5643372c07f8b456e11e1ba61b01a1c573",
          old="1d5e011d22e7cd25514cdcb6dea8d8b877126f2d227326add1a789525a6f6449",
          evidence=_SYM_1022),
    Equiv(module="open_guji_cv.clustering.rare_panel",
          new="36638fb605c036d8ac3744855dfd39e0b02ff8fa09e6413532603356c35ca555",
          old="bec943126936e2e9d49db88c56d8d7faff8ca851af96ae805baa63b57bed8f21",
          evidence=("特殊符号进候选集 S3（5-b 符号门槛：字表里有符号的册才过滤／前移符号）：字表无符号的 vol07 30 页（每 5 页取 1，"
                    "3 页新旧同样失败）、vol04 30 页与 origin/dev 5826853 产物逐字节相同；新旧同一 emb 索引，"
                    "删掉本步旧产物免得格级复用，手工跑 guji step 比 sha，2026-10-22")),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="af34b525f1e3610d8925074747371bccfe1598f7411f7a615ef348eeb7d31d42",
          old="64386e40f5600be7211a560ce8eaea099ef1a8fd66a97b62f5c398181b56258e",
          evidence=_HR_1026),
    Equiv(module="open_guji_cv.utils.border_geometry",
          new="25e4481b46153b33d17cb4e83eadf5313e67529b13a43a796a9074073508f1e3",
          old="c6f0f1e26ed8748178597801cffcf6c0d22fe52d46da324355f721108a33c871",
          evidence=_HR_1026),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="b8299e630e3a794c90aafa1d8e0c48ffd9a5aaa638021ca8bd39727a9ef80be4",
          old="ec4539bc0cc6d76e8bf4630a6b3cdd4f4c0d75071cd559792ca2f614159bc8c7",
          evidence=_GL_1027),
    Equiv(module="open_guji_cv.utils.border_geometry",
          new="ce8758574f364ea998b8b07e6d58465bb3e7d4ec895286561dfc8f3c0bf4d7eb",
          old="c6f0f1e26ed8748178597801cffcf6c0d22fe52d46da324355f721108a33c871",
          evidence=_GL_1027),
    Equiv(module="open_guji_cv.utils.peak_line_search",
          new="5108626482b37582b6f59d772216a9f0cb8bed6cdd5c3fc9aaad3e068a443b6c",
          old="90afd63cf2eec6ace053c4d470d1568c3c39582a532c99d2a929cec5bf016890",
          evidence=_GL_1027),
    Equiv(module="open_guji_cv.utils.border_geometry",
          new="dd501ed2fae87e402186cfc5b4a7f19e58e92669d68e3b978b8b68c13994f04f",
          old="c6f0f1e26ed8748178597801cffcf6c0d22fe52d46da324355f721108a33c871",
          evidence=_BC_1027),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="e70d82079e5d610cc3d833fac53ac82d439cf6ab7eb7601e4ce4efa48ee5e00d",
          old="ec4539bc0cc6d76e8bf4630a6b3cdd4f4c0d75071cd559792ca2f614159bc8c7",
          evidence=_HRV_1027),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="5c8dd9193249b81b1d0e1e0f4ed13103d92771b1feb11feaa40ff87d6447f323",
          old="58c07dca48941d33c6f9166a49da3c506f49df64efc91620992bb44f70eb125f",
          evidence=_HRV_1027),
    Equiv(module="open_guji_cv.clustering.seeding",
          new="597e2781a32ab64db886efc716eb215434fbe7a8a4e028d892f35a5a0387a055",
          old="6d99b28bc637ede04cffaa056f5502eb31f77c6c6ef6d905cccea0f302a34d01",
          evidence=_SEED_1027),
    Equiv(module="open_guji_cv.books.zengguang_youxue.free_cells",
          new="27f2942643b95ad4da9d0d1630821a0deda75dc69e4480988b5c639097f2f916",
          old="761eaa8e09be2cb1c1736bf1aaf528a2c62e6e63aee8ffb001f32e0ca47559c6",
          evidence=_MV_FREE),
    Equiv(module="open_guji_cv.steps.block_detect",
          new="b9a010a31810b2b66c97c4fedef2c644e6ea670e4e9f0a0d54fc686391163624",
          old="c4e3f4c3ced328953f14599c97fbd171fb17bf8e755da4bf942168fc8f7802c2",
          evidence=_MV_FREE),
    Equiv(module="open_guji_cv.steps.column_trace",
          new="dbe4e9a055e0662f8373d74a55346c68970b1d3c47a8bea5f02741a0df01a469",
          old="e18bbbe1054d2f13dd4b6547018046c544a68dd6a745bb9648942337384bc901",
          evidence=_MV_FREE),
    Equiv(module="open_guji_cv.steps.cell_cut",
          new="9327219c48a4983be825455085605abec84fc5b0e45f770d9979a51e4a27ee0b",
          old="ee41ec3a4b2ec3f7fb57fe0d5803cbc629524b68c428ad491450534cfa8e695a",
          evidence=_MV_FREE),
    Equiv(module="open_guji_cv.steps.line_ocr",
          new="5fd4d98a143ff15bd63ee77413c81ea2bc42d3415b07d87758a6ac1811e756b7",
          old="3c460388cd9a000f4195e41137f347ec9d553cd0a0857ffec73a7f5ac75afd85",
          evidence=_MV_FREE),
    Equiv(module="open_guji_cv.books.beixing.line_layout",
          new="b8c1a2ca0a78502a546d169a26909ae8d07219a8e31e4a0b722ef47e5aa70058",
          old="33f17f6be1f6f2f54345bc970f61c2772b41dc670bb602d006e478c1b6259d24",
          evidence=_MV_BEIXING),
    Equiv(module="open_guji_cv.steps.line_detect",
          new="bef809bd600afea1d8f038fc480e8a92a244bb63cd67ec5adf0b4e9495446ddd",
          old="a90fc471a3e806a2b3655b663295bc66957e68d651e2a1372dbdbad195de2d1c",
          evidence=_MV_BEIXING),
    Equiv(module="open_guji_cv.steps.row_segment_runs",
          new="af18d5d39d00d353c2e04de755ec616457d379c07a5ce9ad1be0382cbda16bb0",
          old="4762e1c3f71c857f8afe44091a488ac4c2a4c3337eed32e3d467cf7baba1679d",
          evidence=_MV_BEIXING),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="69c95d3cb5fff6ceeabda2314251b443e08929e0304d4c81009830f290da5507",
          old="7ca231b5277f35b458362ba6ede3e992585607d06c4e9cd01d78cea71e4633be",
          evidence=_MV_SIKU),
    Equiv(module="open_guji_cv.gates.column_gate",
          new="a072761f50f0c01481e94db76abf3be9856bda7705230e0fc1027ddda2ba9090",
          old="bc4749f1f07753e004d84b5006ec4cfbdf1af23383c457f085475acc05063b22",
          evidence=_MV_SIKU),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="deaf1c8e1b0de1b6b791e47f7d0a90edf72811161b14493cfa1a9e9d0e5799ad",
          old="9183257430cb19c877746f9ca8d5f78c54c8290baa7a18513778d3711d7a27af",
          evidence=_MV_SIKU),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="1affc6f9cd9dcf98505b48ec3d7d248535395b94363b062f2baa4457bd6f1826",
          old="deaf1c8e1b0de1b6b791e47f7d0a90edf72811161b14493cfa1a9e9d0e5799ad",
          evidence=_MV_SJ),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="9bf54284729da3494d71a9a13547f660b679f96232fa2539d55bfaeca2018910",
          old="69c95d3cb5fff6ceeabda2314251b443e08929e0304d4c81009830f290da5507",
          evidence=_MV_SEG1),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="86a46b8055a48170102e1182d49c741ce2c32d0a9d015035a946b61e633261b1",
          old="1010e8943e3f1519b71f4659d25603f5f1f00a364dfec29018e2168d29c0b822",
          evidence=_MV_SEG1),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="93d48d4cd24d4304b223c94e3abff8c14e81de2763f46d325e9a2a0783eecc8e",
          old="1affc6f9cd9dcf98505b48ec3d7d248535395b94363b062f2baa4457bd6f1826",
          evidence=_MV_SEG1),
    Equiv(module="open_guji_cv.gates.border_detect_gate",
          new="43f4e1d70c019a9a2fd3e451a7099718384848bc6eb202143f645fdc5477cc75",
          old="0d0ce595139eeeb9bfa94839061b768e5d2b497803daf8067c4f3508fc3b2766",
          evidence=_MV_SIKU2),
    Equiv(module="open_guji_cv.gates.column_gate",
          new="e7b6a6f69e80258beefc3f0fee5fa9d867a6dc9b19bcff3283dd0f94f7cdbb15",
          old="a072761f50f0c01481e94db76abf3be9856bda7705230e0fc1027ddda2ba9090",
          evidence=_MV_SIKU2),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="5a0785bdbf2d9a63edc13a43838e1c8b4ad2df2bea4d41f92789e3ac9cabb5b3",
          old="51a8a57c3b0f7364a624690fbbdd90d90a8dba587aabbde009d8cda0b6743093",
          evidence=_MV_SIKU2),
    Equiv(module="open_guji_cv.books.beixing.line_layout",
          new="3b932525eb96c42c3ac8323d3a316cb526f2f42e28ad01dd6fcbaa72870ee627",
          old="b8c1a2ca0a78502a546d169a26909ae8d07219a8e31e4a0b722ef47e5aa70058",
          evidence=_SP_FT),
    Equiv(module="open_guji_cv.gates.border_detect_gate",
          new="ee7454ae45bfc1bd9ea91c85b853ae929b7443b6ac9cfbbfbdc25fb282a1cdf6",
          old="43f4e1d70c019a9a2fd3e451a7099718384848bc6eb202143f645fdc5477cc75",
          evidence=_SP_FT),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="3a3c072df391d6e2dd7d26ce77428e4dd3370e183bebcb038cb16a793fc82dda",
          old="5a0785bdbf2d9a63edc13a43838e1c8b4ad2df2bea4d41f92789e3ac9cabb5b3",
          evidence=_SP_FT),
    Equiv(module="open_guji_cv.steps.column_warp",
          new="d33d045963883e8b4f53e9d37e2b50b11e7ba4288da96850628dca8da80d4d6d",
          old="7b269c9f7a5faf1f61180e4e58c7cd56cac8691745a571adda899c5423ab368c",
          evidence=_SP_FT),
    Equiv(module="open_guji_cv.utils.border_geometry",
          new="eae44439b1333ab5c3ce686232c20b6292ac46d9f597875b43b7ed54a3d80019",
          old="ddfdb066f247b0a93790fd9a1c7e8c4e497f8471b0334b417a9e939c0707782e",
          evidence=_SP_PLS),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="3f8bc2f3e63edddab45356c10f458c9cd281602962223d366d3ff23c5cba5b08",
          old="3a3c072df391d6e2dd7d26ce77428e4dd3370e183bebcb038cb16a793fc82dda",
          evidence=_SP_PLS),
    Equiv(module="open_guji_cv.gates.border_detect_gate",
          new="4dbead785e9980af73a144ad628529c53a0cf33dd0327e0b3ca7c94630a2e79f",
          old="ee7454ae45bfc1bd9ea91c85b853ae929b7443b6ac9cfbbfbdc25fb282a1cdf6",
          evidence=_SP_BG),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="80ecf12a3dee7e3c8d4f5116f202707ff3f61bc3af3bbace3110bf8741229663",
          old="3f8bc2f3e63edddab45356c10f458c9cd281602962223d366d3ff23c5cba5b08",
          evidence=_SP_BG),
    Equiv(module="open_guji_cv.steps.column_warp",
          new="eca98f041edf9ebe762c92a2979b49f427175a5b20cdd45df5ebf437d0e1c404",
          old="d33d045963883e8b4f53e9d37e2b50b11e7ba4288da96850628dca8da80d4d6d",
          evidence=_SP_BG),
    Equiv(module="open_guji_cv.utils.column_projection",
          new="b513802033538bd3475050c0e0575ed3787b1bd7f69c581b9521f3c87d26fc7a",
          old="614cc9b0f4ffcb6f151c15c8bd56824df81d5e01edb4fb3bd8df3176e3c645ef",
          evidence=_SP_BG),
    Equiv(module="open_guji_cv.gates.column_gate",
          new="08beb5ff74c9f5358d1036c4877e972dd9cbc8b3971733cec91bc6db136544f7",
          old="e7b6a6f69e80258beefc3f0fee5fa9d867a6dc9b19bcff3283dd0f94f7cdbb15",
          evidence=_SP_CP),
    Equiv(module="open_guji_cv.steps.column_crop",
          new="0a290a058d9ce72b754e0326d4c4fa505491baab393fe5d6517ccc64e903a57f",
          old="3dcc21da5a93afe0af339c2356c874ec591090fbc1930a1ee1e0af0f22c664e8",
          evidence=_SP_CP),
    Equiv(module="open_guji_cv.steps.column_warp",
          new="06755e382dd648af0c0f766f44f37e5414995a83f3fe0745d7616f96008a6e8a",
          old="eca98f041edf9ebe762c92a2979b49f427175a5b20cdd45df5ebf437d0e1c404",
          evidence=_SP_CP),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="9a2fa559f6e056ad2b1a58f726fe4d4b1c3849c0efcc3bbd1fb7ecb2d6c6238a",
          old="93d48d4cd24d4304b223c94e3abff8c14e81de2763f46d325e9a2a0783eecc8e",
          evidence=_SP_CP),
    Equiv(module="open_guji_cv.books.siku_zongmu.column_triage",
          new="73ff9002ed6ab67e0b617a0a459d68dbb69e18cea5c8d1d43cc9be3508f6a23d",
          old="9b98ee76d1a45032e014e3d385297dac192f3a07e2b0e0de7b96f226e716580b",
          evidence=_SP_CP),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="9aaf71e13388c447b41ed3f9723ea805b1e193dac238b5cf7cc26788b9c1c7ce",
          old="9183257430cb19c877746f9ca8d5f78c54c8290baa7a18513778d3711d7a27af",
          evidence=_SJ_780),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="388770763eaa474c4989c4c7068edd4c742e7ad271208e7ef0289435d3131488",
          old="1010e8943e3f1519b71f4659d25603f5f1f00a364dfec29018e2168d29c0b822",
          evidence=_SJ_780),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="1cb1977e26c99263aee9fe5e4bbd211c8d644a2d3eaf5610ef5ea9ac47dafcdc",
          old="4fbb1535a764d403f566aa1ce7c00bdbf82a082a1c05dcaec03a379fa0facff7",
          evidence=_SJ_780),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="7c77e9ac98ac2476324a252c0151a0f61b52fb43c01c838ed2ba4f18b7c7b4b6",
          old="50e9558e7654335537f0dca09d5d7cedc56d7ad75ff7e17e6fee6c10c23f519b",
          evidence=_SJ_788),
    Equiv(module="open_guji_cv.steps.align_ref_coord",
          new="7edd6f3d13885a5efd87a18c651533ac122168f8a3d89126e72ec394fc0e8758",
          old="5d729e5b5398d287b315e0cf21386302fbf7b08ece15bd13774beafd2c07b96e",
          evidence=_SJ_788),
    # 2026-10-31：Step3 自动配页加 pins 档（史記按逐页钉位出格位表）；缺省 off 与离线表路径不动。
    Equiv(module="open_guji_cv.steps.row_segment",
          new="18208a62542902ab2ca1d76f5deafcaf844c8eb74dbbd2de0a5a3f11e7be7f73",
          old="9183257430cb19c877746f9ca8d5f78c54c8290baa7a18513778d3711d7a27af",
          evidence=_SJ_PINS),
    Equiv(module="open_guji_cv.steps.row_segment_pagemap",
          new="a869dd025d2602bd99dc369b38f30152c8ba0a091260ef0fd16b2833a9ad06a4",
          old="3ef375f764f67717152ebd4e11b234ca338bbb02091dc6d07a3de50bfc52c9f0",
          evidence=_SJ_PINS),
    # 书级陪衬字 group_flow_tolerate_extra（缺省空）＋人裁顺移豁免 human_unbound_shift_ok（缺省关）：2026-11-01 史記 02
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="38b9d11ce4338c8bfa8b2c1ec4fb4ab8945e6b6d4cb2f3c91ed32e5fb8baffb0",
          old="df2d8a69fe3bbf80b5ecfc97540aff3634a536d20cdd442c8998472bfdf5019b",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 产物逐字节相同"),
    Equiv(module="open_guji_cv.groups.flow",
          new="a866f82c00097b54f43a2062fe4e7dcb9cb37a1acb4310a6fc7aa27924228d47",
          old="1d2277f983f07f18c18c79bab84350a867cc5b141e8d6bdb34f32d4dac239e60",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 产物逐字节相同"),
    # 书级字形＝整理本补放 group_flow_lift_shape_ref（缺省空）：2026-11-01 史記 02
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="a7a0418923dbf6b61010d17d83e072f7a0987bce54b9a2c5464dbddd34a9e5cf",
          old="df2d8a69fe3bbf80b5ecfc97540aff3634a536d20cdd442c8998472bfdf5019b",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 产物逐字节相同"),
    Equiv(module="open_guji_cv.groups.flow",
          new="046fe1adaff78f4900fe665134a4b945883934c73988cf79716e74ed569407d2",
          old="1d2277f983f07f18c18c79bab84350a867cc5b141e8d6bdb34f32d4dac239e60",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 产物逐字节相同"),
    # 书级按参校本取异体 follow_ref_variants（缺省关）：2026-11-01 史記 02
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="e3d42c945641454ad426932469235703d009750163b6115cc8d7136abedcbc77",
          old="df2d8a69fe3bbf80b5ecfc97540aff3634a536d20cdd442c8998472bfdf5019b",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含异体与小注格）上与 origin/dev 产物逐字节相同"),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="dcb61485d6ae38bbfe9ae9646f763710290f55b84750d729447970c3009a1f49",
          old="4451f904c4d519067d67e50d569fa7c9e25a77f73bccc219e7111b22c5f77886",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199）上与 origin/dev 产物逐字节相同（书级开关 group_flow_abstain_ref_ok 缺省空）"),
    Equiv(module="open_guji_cv.groups.flow",
          new="abeefb2ca96f877eca465bc6f83fda42c09998d39a82fdbcaf05b55f508fc286",
          old="697812c2bf65871d068c7d674c213ae6af9043b50baca08d1f937a96f0c2c105",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199）上与 origin/dev 产物逐字节相同（书级开关 group_flow_abstain_ref_ok 缺省空）"),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="616d05dc5f7b1d64c5095495439d68cec2d2722e3ecd0e8027f55b32ddd544eb",
          old="dcb61485d6ae38bbfe9ae9646f763710290f55b84750d729447970c3009a1f49",
          evidence="seed_admit 在史記 01／05／08 册共 363 页（任务库 #1835–1837，cv 083e788＝claude/shiji-run ba2b739＋本改动）上与 ba2b739 产物逐字节相同（书级开关 ref_lib_coord、group_flow_shape_ref_ok 缺省关）"),
    Equiv(module="open_guji_cv.groups.flow",
          new="5ad584eacd0e6461eeb7e5e39a226973f0c52ef32b92d24054e3a163b593b8ef",
          old="abeefb2ca96f877eca465bc6f83fda42c09998d39a82fdbcaf05b55f508fc286",
          evidence="seed_admit 在史記 01／05／08 册共 363 页（任务库 #1835–1837，cv 083e788＝claude/shiji-run ba2b739＋本改动）上与 ba2b739 产物逐字节相同（书级开关 ref_lib_coord、group_flow_shape_ref_ok 缺省关）"),
    # 参校本可信度 reference_trust（缺省 none）收拢 ref_lib_coord／group_flow_shape_ref_ok 两个键：2026-11-02 史記 07／08
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="910bc3d0d07762625e136648a8853ea1337f9a5b5e4013bbc2e37f29e507e175",
          old="05cee0edaa795b1cfffa39841012cce5f734c9f9ff02daa8fb5564d6451df7e6",
          evidence="seed_admit 在史記 07／08 册共 224 页（任务库 #1929–1930 新码 reference_trust=none 对 #1933–1934 旧码 083e788 关掉旧键，同一批显式开关）上产物逐字节相同；reference_trust=very_high 单参数复现旧键全开的 230 格新放行"),
    # 圈号 ○ 遇整理本空格位 symbol_ref_blank（缺省关）：2026-11-02 史記 02
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="7ddbe7509a3c2de9a7ab94bb7a0c23c115c0abaffc766f211e08b0c1581e4a98",
          old="4451f904c4d519067d67e50d569fa7c9e25a77f73bccc219e7111b22c5f77886",
          evidence="seed_admit 在史記 02 8 页（2,90,167,168,208,209,210,211，含 ○ 圈号页与卷端页）上与 origin/dev 产物逐字节相同"),
    Equiv(module="open_guji_cv.steps.seal_detect",
          new="288648cf2643aedd2fab0e87a9567bf6c16e8a67f568c0a7fdeaebb9c004e100",
          old="d2c3e0db3d45d75fa5fe5743492b84083f2e3e640baf44f2c5187766cd2cb8cc",
          evidence="书级 stain_pages 开关（缺省 None 不进 dump）：seal_detect 在 vol44 15 页、vol30 3 页、vol82 2 页"
                   "（首叶大印、卷末小印、普通页）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，A32 2026-11-02"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="23864ee71ac5a22aca46866c77114e56d5606627d62b359668ec1346f74d42ee",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence="书级开关 roster_seal_despeckle（缺省 0，不进参数 dump）；02 8 页（4,9,19,24,41,86,141,199）产物逐字节相同"),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="9ac2c3a275b463ef05a87ab8838690d99f1c583f13b7cc2a15caac21790b9fa3",
          old="7c77e9ac98ac2476324a252c0151a0f61b52fb43c01c838ed2ba4f18b7c7b4b6",
          evidence=_SJ_DP),
    Equiv(module="open_guji_cv.steps.align_ref_coord",
          new="49a9e0c6a90d8f43ea6d054c1f20531123534ae6f26e2798fcf2fee51e24ec74",
          old="7edd6f3d13885a5efd87a18c651533ac122168f8a3d89126e72ec394fc0e8758",
          evidence=_SJ_DP),
    Equiv(module="open_guji_cv.steps.border_detect",
          new="a97bd62bf8710c31e9bec09ee1e51a960bc9ea6eca007ce7d5749dd781e0bd52",
          old="357436b41d433d33c194d84e2b114c2148266f9350fc9fd33a4771428c894550",
          evidence=_SJ_VLINE),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="646f9ed7015e564cfe119b3f705583296a70ddf75301da63864003519e5608dd",
          old="23864ee71ac5a22aca46866c77114e56d5606627d62b359668ec1346f74d42ee",
          evidence="书级开关 layout_slots_grow（缺省关，不进参数 dump）：row_segment 在史記文淵閣本 04 册 12 页（2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-02"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="5950f746efd6131f84d8886748d100b2cdf243bc339309d6dea9cf211328c096",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence="书级开关 roster_top_dash（缺省关，不进参数 dump）：row_segment 在史記文淵閣本 01 册目錄页 87,111,119,132,134 上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-02"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="85fa1a892f9e80cb72ebb620b43fc56e88b25744046abe3f814023f9c6588a04",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence="书级开关 header_ref_flag（缺省关，不进参数 dump）：row_segment 在史記文淵閣本 01 册目錄页 87,111,119,132,134 上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-02"),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="7620888bd88f475e72b070135f5c46ac591a781f5048d81030fb947836efacab",
          old="82930b01adb3c224cac7547d22dcc0a557a64ed7c0b6d8f7d072450e62081805",
          evidence="书级开关 lane_header_formula（缺省关，不进参数 dump）：seed_admit 在史記文淵閣本 01 册目錄页 87,111,119,132,134 上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-02"),
    # 题列信坐标对位 coord_title_trust／遮挡格整理本空行判空 occluded_ref_empty_blank（缺省关）：2026-11-03 史記 03
    Equiv(module="open_guji_cv.steps.align_ref",
          new="2521b7de8e2d86fbca291d6107068b924c17684756b016db13d4b5a8899c3cb7",
          old="50e9558e7654335537f0dca09d5d7cedc56d7ad75ff7e17e6fee6c10c23f519b",
          evidence="align_ref 在史記 03 第 2 页（卷端大印页）上与 origin/dev 产物逐字节相同"),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="68444a805f3eab2dc7544f02dce2174719f3ed8aebb6837e7829c2804564b713",
          old="82930b01adb3c224cac7547d22dcc0a557a64ed7c0b6d8f7d072450e62081805",
          evidence="seed_admit 在史記 03 第 2 页（卷端大印页）上与 origin/dev 产物逐字节相同"),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="771b230474a7a43506bbb566b8d7692b82edda475908c1d1b17bbc0c05836de2",
          old="4b459486cbea651f8723c1438ba0b45f392edbadf3693848cc3c892d4dcada7d",
          evidence=_SJ_TOPK),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="adb1eaabeef2dad69975a887e258937b1f5e8dd9cee55095456f335992cc7ff6",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence="书级开关 roster_seal_trim_extra（缺省 0，不进参数 dump）：史記 02 8 页（2,4,9,19,24,41,86,141）产物逐字节相同"),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="4c7c9f6b62047e38a5a8d6da2df846b7d5c929063a95401026cae33842108b53",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence="_is_blank_i／_dropped_rows_i 改前缀计数（2026-11-03）：row_segment 在全唐文 06 8 页（27,60,100,140,180,15,45,120）上与 origin/dev 8bf0cdf 产物逐字节相同"),
    Equiv(module="open_guji_cv.seg.cut_select",
          new="1cd807a6a9f306ddea55eb63802ea6c7ec0132011b18f0dd230a2a740d88fdae",
          old="fad2da0e7322c7d0da354c2d1b246346060609fc616f53a33d4f46dfe5c4b13b",
          evidence="#901 UNetJudge 窗口记忆 8→192 LRU（2026-11-03）：row_segment 在全唐文 06 8 页（27,60,100,140,180,15,45,120）上 882bd7a 与 e0c9acd 产物逐字节相同"),
    Equiv(module="open_guji_cv.seg.cut_select",
          new="6b20cef67dbadffa8576246fc195be70ca75dee5e9c5d713ca0256b7353c062b",
          old="1cd807a6a9f306ddea55eb63802ea6c7ec0132011b18f0dd230a2a740d88fdae",
          evidence="guided_seam_from_owner 改用 seam.seam_dp（2026-11-03）：row_segment 在全唐文 06 8 页（27,60,100,140,180,15,45,120）上与 origin/dev 13d33ea 产物逐字节相同；随机 3000 例逐位相同"),
    Equiv(module="open_guji_cv.seg.seam",
          new="8444b11b39dead8f114d6e09313b78d241a1de1a580202a7b7749efe6d9dbca7",
          old="2d3f4c680d5a1aabb68c5773ce6a2b67afe20ccbd9fe561b64c29131e1e0b671",
          evidence="走廊 DP 抽成 seam_dp、预分配 pad/cand（2026-11-03）：row_segment 在全唐文 06 8 页（27,60,100,140,180,15,45,120）上与 origin/dev 13d33ea 产物逐字节相同；随机 3000 例 find_seam 逐位相同、快 1.8 倍"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="54c5e31759f53c8d91c5a0d8bc3ebd513243b65f7b7644a2655962e50d724c69",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence="挑格网试切不跑折线与 U-Net 判官、挑定后只按原参数重切中选那遍（2026-11-03，全唐文 CPU 提速）：row_segment 在全唐文 06 43 页"
                   "（每 5 页取 1，加 27/100/101）与 05 36 页（每 7 页取 1，加 1/2/100/222）上与 origin/dev 4cf8260 产物逐字节相同，4 进程；"
                   "scripts/code_equiv.py check；同 24 页 row_segment 合计 747→259 s"),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="a338535870f9aa1b74d03180c48335dc81ec12fefd2557c3181de718e0c2961b",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence="弹性 DP 内部转移代价（含逐格先验罚分）与 find_valleys 按曲线内容跨调用记忆（2026-11-03，全唐文 CPU 提速）：row_segment 在全唐文 06 43 页"
                   "（每 5 页取 1，加 27/100/101）与 05 36 页（每 7 页取 1，加 1/2/100/222）上与 origin/dev e074e9b 产物逐字节相同，4 进程；"
                   "scripts/code_equiv.py check；p27 row_segment 21→11 s"),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="e0da5a74a69970049db6b4af06fb82557d34d6d3009c0b5fb8c17c174dec59f1",
          old="8e5c7812f44651bc850a6f34f15e8e773bf9af3e6559b21e476edae08ef9357b",
          evidence="render 再生字块时整列抽字与全页框线按页记忆（2026-11-03，全唐文 CPU 提速）：cell_shrink 在全唐文 06 42 页（每 5 页取 1，加 27/100）"
                   "与 05 34 页（每 7 页取 1，加 1/222）上与 origin/dev 59a8dbe 产物逐字节相同；再生路径：glyph_match 06 6 页（2,27,60,100,140,181）"
                   "空缓存起跑，产物与 853 个缓存文件逐字节相同，每页 60–85 s→12–20 s；scripts/code_equiv.py check，4 进程"),
    Equiv(module="open_guji_cv.clustering.page_type",
          new="1e597b8c3f1ab98f92eca79e50529c6940189d49de6b901e920c384638e2aa70",
          old="44eae13696f440a061b44550dad45df52bd72f27e9253c5717e2d50973a81161",
          evidence="page_features 竖线开运算只算一次（2026-11-03，全唐文 CPU 提速）：row_segment_gate 的 code_dep；全唐文 05/06 原图 106 页（每 4 页取 1）"
                   "上新旧 page_features 返回值逐项相同；改动是同一数组复用，不改任何运算"),
    Equiv(module="open_guji_cv.clustering.page_type",
          new="24c9957349c35ffdb742af95b2dc9f82b66d70549ccbeac976ccff3bdfee3dbe",
          old="1e597b8c3f1ab98f92eca79e50529c6940189d49de6b901e920c384638e2aa70",
          evidence="page_features 的长线形核开运算换成 boxFilter 计数 line_open（2026-11-03，耗时统计查出 border_detect_gate 单线程每页 3.5–6 s 大半在此）："
                   "border_detect_gate／row_segment_gate 的 code_dep；随机 0/1 图 14,400 例（奇偶 k、k 超过边长）与 cv2 原式逐位相同；"
                   "真图全唐文 05（12 页，每 15 页取 1）、殿本 05、史記 01、北行日錄 01（各 8 页）上新旧 page_features 返回值逐项相同；"
                   "border_detect_gate 在全唐文 05 那 12 页上与 origin/dev 产物逐字节相同"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="7daa5c74ec9dca3460bc74936d44c3ca01b104b33bf217390ce3a90e7fe8694e",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_SJ_GAP),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="a68db00813c3919bdd36f5cc929e016141fa37897dee44efb9339d4e495eaf4c",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_JZ_ROWS),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="195bd90aef2b566b2482c5d45bff24c3f8493340cb59d9803128de33b1504b7f",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence=_JZ_ROWS),
    Equiv(module="open_guji_cv.seg.seam",
          new="41fefe234ed8c27c17084a58f70d92813ae2b5c4826de5cfc418308af4511d86",
          old="2d3f4c680d5a1aabb68c5773ce6a2b67afe20ccbd9fe561b64c29131e1e0b671",
          evidence=_JZ_ROWS),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="e0e0df18af41d28953d29972cb167f2364c1d179e862821032dc310ae65dbfd5",
          old="641b7ace4349757a18a2d8eb1f7a3ec81381f815da766227d20ffd5e00e553a2",
          evidence=_JZ_ROWS),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="7fd29111e69a2b7572df5603ba7aca0e38cc5bb744195b1e4bf600a8edcd6036",
          old="a9f232fc7111165f419c0257a6ba08a4ad5dc1fcb9dd9f3b358652cc5a9c029b",
          evidence=_JZ_ROWS),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="d412534edd496d6aea42320098e67c982a67859eb2f1df17657f255790a63b60",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_SJ_PITCH),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="278aa0c1fbb3db659dc7b5d0357c19e71dc32fe6d8f23ea186628f361c291b14",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_SJ_R5),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="c7921a8fefbab598b2a6e4ccdea360bf089dad67fbb1b33ec99aa93a43d8042e",
          old="50e9558e7654335537f0dca09d5d7cedc56d7ad75ff7e17e6fee6c10c23f519b",
          evidence=_SJ_R5),
    Equiv(module="open_guji_cv.steps.align_ref_coord",
          new="3cd4fcf820c9b22301c8fdbc8990c0f822c44d879e55e5d55a0363ad801859a1",
          old="5d729e5b5398d287b315e0cf21386302fbf7b08ece15bd13774beafd2c07b96e",
          evidence=_SJ_R5),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="3cf74689b1995b8d8baeeb50d8fc33862af5eb9f32b93e5e55e922d9cfcd2db2",
          old="641b7ace4349757a18a2d8eb1f7a3ec81381f815da766227d20ffd5e00e553a2",
          evidence=_JZ_STRIP),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="8c698218deb28060a4af17d3bde17d0788c225b417b1cdf435bd3c59ee67b801",
          old="a9f232fc7111165f419c0257a6ba08a4ad5dc1fcb9dd9f3b358652cc5a9c029b",
          evidence=_JZ_STRIP),
    Equiv(module="open_guji_cv.steps.column_warp",
          new="29c891323d3531ead6fe5fbd9075f85a46fe8152d73a614bb80597380f6417d8",
          old="7b269c9f7a5faf1f61180e4e58c7cd56cac8691745a571adda899c5423ab368c",
          evidence=_TIGHT_BAND),
    Equiv(module="open_guji_cv.seg.profile",
          new="5a1a33e72c8068029302576bd72b153bceedcd32aa4d3a6a3c51da2957ec9947",
          old="508270c9484b07c734e3c671f123093ecdd2405c0851340e5d0deb3437cd6609",
          evidence=_TIGHT_BAND),
    Equiv(module="open_guji_cv.books.siku_zongmu.column",
          new="003fe27cfbe7c06de891e6d23ae081db1f5d4d4bf66359b1467b2f2a17ae6789",
          old="4465ac6dfe85c0eaba56e06d75c260285f7fd5a02cef69cc5787ba8e0caae3dd",
          evidence=_TIGHT_BAND),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="bd5d50e99caa7b100e9067347416e36209b92672f1c95f4ab0b8db2a88c8ba3e",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_SJ_INKCUT),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="950a2c54d289dfd6172567859dc9df0074bdb3949e968ac2f9ece84699121230",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_JZ_FREE),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="fb520ff1c2b13c680fe4ace5c9ed1e5426e32a9a935a27343f2dcf62300d21b8",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence=_JZ_FREE),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="db9134b389edee9b8ff051d2bb4328b14ee7bd6fbbb515239ff7136f20223467",
          old="641b7ace4349757a18a2d8eb1f7a3ec81381f815da766227d20ffd5e00e553a2",
          evidence=_FRAME_GROW),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="e6a77a310d20bfdd0ed22db0cca681490ff78885f65b4277e9030ccd979cbbf8",
          old="a9f232fc7111165f419c0257a6ba08a4ad5dc1fcb9dd9f3b358652cc5a9c029b",
          evidence=_FRAME_GROW),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="39c00c4a48fb1e079cb786228b8f2a0d44fd7708dabf24542f1d07e599d3487e",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_TAIL_EMPTY),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="9b6efd259dedb6c517def3be1ed6204c6ed645647b987bf5227b6191438d9ab6",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_ROW_FREE_PITCH),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="e6baa41f1a77c69b4ccb62bc239670f0f72dbb57c9a728ba5218255e34aaecd7",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_JZ_SINGLE_HEAD),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="b5c2b5fb08fc415f3f8e21dffcbfe8f6c57ef7f68d3a3b931b8c0a1e6622a9b7",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence=_JZ_SINGLE_HEAD),
    Equiv(module="open_guji_cv.books.siku_zongmu.jiazhu_split",
          new="7ca934262db39eecbcca59f61ebf44b90224c8b20849c75692382c586d26cced",
          old="e7c605b8247e14f4aae7c90c1e05be0a8b01cb32dbdbf2a9e6cb5e7086fcc82b",
          evidence=_JZ_SINGLE_HEAD),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="35599c861269dd09c094e824b219ef8cd6c83b33fbac91f9a99d584d8836dad9",
          old="427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28",
          evidence=_QTW_FORK),
    Equiv(module="open_guji_cv.books.quantangwen.row_boundaries",
          new="b5c2b5fb08fc415f3f8e21dffcbfe8f6c57ef7f68d3a3b931b8c0a1e6622a9b7",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence=_QTW_FORK),
    Equiv(module="open_guji_cv.books.quantangwen.jiazhu_split",
          new="7ca934262db39eecbcca59f61ebf44b90224c8b20849c75692382c586d26cced",
          old="e7c605b8247e14f4aae7c90c1e05be0a8b01cb32dbdbf2a9e6cb5e7086fcc82b",
          evidence=_QTW_FORK),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="546e305a92ebe7ec03cb64f9dfd3397209780ea421941d82382e0f5970f984c7",
          old="097c1ec750580fdb59dac552c7969b9604a5749b286bc53865912cd37405e455",
          evidence=_SJ_PAIR_SHAPE),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="b14148bb32ee5dd5d205383ba03b39678c0c580ca69e901fbfcd559a2bb5889f",
          old="641b7ace4349757a18a2d8eb1f7a3ec81381f815da766227d20ffd5e00e553a2",
          evidence=_JZ_HALF),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="4afb9c48f669b5d7de1c7f25bab044ef050b2c8307937b8cc9faf0ce8ab6cb99",
          old="a9f232fc7111165f419c0257a6ba08a4ad5dc1fcb9dd9f3b358652cc5a9c029b",
          evidence=_JZ_HALF),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="020d3d4972ef4855ad97822255eab36c8ccd913a81277b0db4f39b7b967189a8",
          old="641b7ace4349757a18a2d8eb1f7a3ec81381f815da766227d20ffd5e00e553a2",
          evidence=_JZ_GUARD),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="df88163370f34458e8c71bf19e2464ac2cd566ccf67304125f27e6f5ec404df6",
          old="a9f232fc7111165f419c0257a6ba08a4ad5dc1fcb9dd9f3b358652cc5a9c029b",
          evidence=_JZ_GUARD),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="2061620748ae6bef98a3325256b1ec6495887c14e083b748f41665d7134321c6",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence=_JZ_GUARD),
    # row_segment alt_cut（PR #965）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='8c808c47a30147c6139522bc59f9a927838416860393f7e51da37ab98b422f4c',
          old='427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28',
          evidence=_ALT_CUT),
    # row_segment 雙行小注逐步切 jiazhu_step_split（缺省关；史記专用实现在 books/shiji_wyg，空实现进 SPLITS）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='0dc068e912694af013b3e036d1f802649a09adfd5526595385ff71f2874c77c0',
          old='8c808c47a30147c6139522bc59f9a927838416860393f7e51da37ab98b422f4c',
          evidence='row_segment 在 04 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 3bb2e40 产物逐字节相同（开关关）'),
    Equiv(module='open_guji_cv.steps.row_segment',
          new='68c22796571ede8c6ff3f0bd203c0d9aefc436f50a5cefe94f5bbbcfb7cabb5b',
          old='e6baa41f1a77c69b4ccb62bc239670f0f72dbb57c9a728ba5218255e34aaecd7',
          evidence='合入 dev（#1022、#1025）后 row_segment 在 04 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 343bc4a 产物逐字节相同（开关关）；殿本 vol12 31 页同（A22 11-04）'),
    # seed_admit 分法不均闸收窄：三者一致的放行格不降（第 10 轮 10b）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='295c187599628bea97df0906be3c3d81938c8862b8aab4f90de64576e11ceef7',
          old='2286171c1222101634a2811fa10c338432398725271666be031880645ea3d9b7',
          evidence='seed_admit 在 04 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 产物逐字节相同'),
    # seed_admit 雙行小注分法不均闸 _jiazhu_uneven_pass（只认 row_segment 的 jiazhu_uneven 列旗，没有列旗不动）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='b4b8fa809954527737aed7433a7be73ca8a5914242b2e4dc59cd556e9ef3a879',
          old='e1fe837a2910c67f9a89b6ffd35a28b7f893d7d38db00cb3ef92bfa41b1cc449',
          evidence='seed_admit 在 04 12 页（--pages 2,10,34,41,43,47,105,119,120,122,124,138）上与 origin/dev 3bb2e40 产物逐字节相同'),
    Equiv(module='open_guji_cv.steps.cell_shrink',
          new='ef4c41f5ae699fe71d8d82c872fdaa8c83625662e5b29fae46b335b3d5ddae13',
          old='641b7ace4349757a18a2d8eb1f7a3ec81381f815da766227d20ffd5e00e553a2',
          evidence=_ALT_CUT),
    Equiv(module='open_guji_cv.steps.glyph_match',
          new='f4009831c773fe19c5a5251e0f9e7b31b003f1f4a264c29bf8a3dc762b2a04a7',
          old='3f8dbeeed4cd82d298bcc6f6f0cb0b40aeee46cdd71283c3bf58fff3ec5cfcbd',
          evidence=_ALT_CUT),
    Equiv(module='open_guji_cv.steps.align_ref',
          new='e89727bbca19f814ed15946600f0ad8134032b80456101bcb5d2c6dafed263f6',
          old='50e9558e7654335537f0dca09d5d7cedc56d7ad75ff7e17e6fee6c10c23f519b',
          evidence=_ALT_CUT),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='8c874ab19a2ef0dfb4ce745a9f4e2a05bc45b99aa6a10a0f678bb3caad69fa69',
          old='097c1ec750580fdb59dac552c7969b9604a5749b286bc53865912cd37405e455',
          evidence=_ALT_CUT),
    Equiv(module='open_guji_cv.steps.cell_shrink',
          new='dd7163ec5679d9c67819d8d4235370127a41811f710db595d806490414f71777',
          old='641b7ace4349757a18a2d8eb1f7a3ec81381f815da766227d20ffd5e00e553a2',
          evidence='alt_cut 合进 #966 之后的 cell_shrink：开关关着时史記 04 册 12 页（p2,10,34,41,43,47,105,119,120,122,124,138）'
                   '与 ba4dd1c 产物逐字节相同；scripts/code_equiv.py check，2026-11-03'),
    Equiv(module='open_guji_cv.steps.align_ref',
          new='4022416876a4ea6becb980b4b315dbe503736f04c74a2b38294dcf6f7b347517',
          old='50e9558e7654335537f0dca09d5d7cedc56d7ad75ff7e17e6fee6c10c23f519b',
          evidence='alt_cut 挑列收紧（只改备选分支）：开关关着时史記 04 册 12 页（p2,10,34,41,43,47,105,119,120,122,124,138）'
                   '与 dev 6c3705d9 产物逐字节相同；scripts/code_equiv.py check，2026-11-03'),
    Equiv(module='open_guji_cv.steps.align_ref',
          new='0a56f1ecc1a7c72fb119209e8f4bd0f810aec17b5797b43af32e2b304c162c2c',
          old='30515d5d225a5c157dd5dff9d476d2c4f3ede0ec5d5e99f19e5e4bec42b77642',
          evidence='alt_cut 错格闸（只改备选分支）：开关关着时史記 04 册 12 页（p2,10,34,41,43,47,105,119,120,122,124,138）'
                   '与 dev 62b64e2f 产物逐字节相同；殿本 vol12 31 页同（A22 11-04）；scripts/code_equiv.py check，2026-11-04。'
                   '史记开着 alt_cut，换列结果会变，第 8 轮须从 align_ref 起强制重跑'),
    Equiv(module='open_guji_cv.clustering.extractor',
          new='6db213006a8b7471cd4cd9c8191e06fd14ad0a3dcf2270a36b1453a4aa296207',
          old='a9f232fc7111165f419c0257a6ba08a4ad5dc1fcb9dd9f3b358652cc5a9c029b',
          evidence=_JZ_BAND),
    Equiv(module='open_guji_cv.steps.align_ref',
          new='2ae95f04104d150000d9c4f70112be0c017e0daf867f43d8fba234f812e03836',
          old='30515d5d225a5c157dd5dff9d476d2c4f3ede0ec5d5e99f19e5e4bec42b77642',
          evidence='alt_cut 挑列挪到准入之后（align_ref.alt_select=admit，缺省 align）：开关关着时史記 04 册 12 页（p2,10,34,41,43,47,105,119,120,122,124,138）与 dev f6055e10 产物逐字节相同；殿本 vol12 31 页同（A22 11-04）；scripts/code_equiv.py check，2026-11-04'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='56240fd3e22c0046c506b1870f0fb72fa268003edc2f01543ce115ab0e2f778a',
          old='e1fe837a2910c67f9a89b6ffd35a28b7f893d7d38db00cb3ef92bfa41b1cc449',
          evidence='alt_cut 挑列挪到准入之后（align_ref.alt_select=admit，缺省 align；换列要求字形背书，用户 11-04 定 B；首格切坏守卫）：'
                   '开关关着时史記 04 册 12 页（p2,10,34,41,43,47,105,119,120,122,124,138）与 dev 86ca2fc5 产物逐字节相同；'
                   '殿本 vol12 31 页同（A22 11-04，对 f6055e10 上的同一改动）；scripts/code_equiv.py check，2026-11-04'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='2c6bc69b38ae3e28678ed99d7a89b1aa78b40fd26de35ba111b5312048c5836e',
          old='e1fe837a2910c67f9a89b6ffd35a28b7f893d7d38db00cb3ef92bfa41b1cc449',
          evidence='witness3 本书刻例近邻否决 witness3_knn_veto（缺省关，全唐文形近字线 11-04）：开关关着时全唐文 012 册 13 页'
                   '（p5,20,35,…,185 每 15 页取 1，含 near_knn 与 witness3 放行页）与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-04'),
    Equiv(module='open_guji_cv.gates.border_detect_gate',
          new='4211e11070e897a519af60631dd5dc9dedcbd7fe9d911e54dc4221229692892b',
          old='803fcffb9dfc915e1ba80512694639857ebd6fb9c7ef6610f5143e4c30d800a8',
          evidence='页型 cover 点名 cover_pages（A20 11-04，SJ 建议；缺省空，空时参数 dump 不含该键，新分支只在点名页才走）：不点名封面时'
                   '测试册 keben 三页（tests/fixtures/workspace）border_detect＋border_detect_gate 产物与 origin/dev 逐字节相同'
                   '（新旧代码各跑一遍，gate 不能单独跑 step，所以按 border_detect 一起比）；2026-11-04'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='453c40fd35939660856a7e183ea219db58f23e24241417399e68e79de6aa1939',
          old='f6dfb7618ec03ac0ff0c92c39bc6c70c6b13964888c826fc530f0d813bf05cae',
          evidence='group_flow_lift_ref_veto 书级开关（缺省关，#980）：开关关着时史記 03 册 25 页（--pages 100-124）与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-04'),
    Equiv(module='open_guji_cv.groups.flow',
          new='080e42ba4cb39f84cfa5fe4c31b5de6f5779acd2c14a6dc83487c8365c0759e8',
          old='d81b0f7d3c661095d34fe1baa4886501672c2f85bf44224d29cc4c6eb5335f4e',
          evidence='group_flow_lift_ref_veto 书级开关（缺省关，#980）：开关关着时史記 03 册 25 页（--pages 100-124）与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-04'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='361801066a8830d81e48f32212e1b3c4aec287d6b7b483947fa5bf4c92f94be1',
          old='3041eb1d51519f9af60f81a1be0ce44ee1e4850b7897ee6e32c76136798e202c',
          evidence='near_knn 入口放宽 near_knn_gap（缺省关，全唐文形近字线 11-05，A24 审过）：开关关着时全唐文 012 册 13 页'
                   '（p5,20,35,…,185 每 15 页取 1）与 origin/dev 391d83b 产物逐字节相同；scripts/code_equiv.py check，2026-11-05'),
    Equiv(module='open_guji_cv.clustering.verify',
          new='4f9c2196e83e86414a9f0799ac7c25cc611fce807b931d59f066cfdc3c91ef62',
          old='78f15462e72b050a027f3e201d3bb45cee56ac0376c73e35e437e98713021e2e',
          evidence='弹性对齐提速（query 侧取数表按条记忆、块内位移最优改滑窗最大值，A20 11-05）：取数与滑窗最大值逐元素相同'
                   '（tests/clustering/test_verify_elastic.py），合成字形 57,600 次 verify_pair_elastic（64/96/48 边长、6 套参数）结果逐位相同；'
                   '任务库 #459（dev 081d48a）对 #460（本改动 f5a5052）史記 01 册全册 143 页 glyph_match＋seed_admit：glyph_match 143 页逐字节相同，'
                   'seed_admit 135 页相同，另 8 页只差 evidence.iron_ex_missing（执行机上刻例原图读不到，两边各有缺，与本改动无关），放行与待审逐格相同；2026-11-05'),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="762b1b7c217f5546e2e865f473054ff483839e73bc895acb1c6ad72f0bd5539a",
          old="35599c861269dd09c094e824b219ef8cd6c83b33fbac91f9a99d584d8836dad9",
          evidence="书级开关 layout_raise_box（缺省关，不进参数 dump；A22 11-05 殿本抬头框重编）：row_segment 关着时在殿本 34 册 76 页"
                   "（有抬头框而切分没抬的 164 列所在页，含 vol01/07/09 旧图源页与 vol28/45/56/73/82/88 整页框认错页）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='c7c1f46d042d5c1b6237ca00f755c5b83c8827f45ff7b9b541fb6be667675fdb',
          old='de749a131133f682da5f64a4c1f18ea5e19af7dc75e7e108a0a685abde0b54dd',
          evidence='iron_ex_from_store（缺省关，A20 11-05）：开关关着时任务库 #472（dev aad5ae8）对 #473（3929d51）史記 01 册全册 143 页 seed_admit '
                   '137 页逐字节相同，另 6 页只差 iron_ex_missing（#473 的执行机缓存缺别册刻例图，#472 不缺；正是本开关要消掉的机器差异），放行与待审逐格相同；2026-11-05'),
    Equiv(module='open_guji_cv.steps.cell_shrink',
          new='1b7b7a91ec05c6fe447c6dbbea470af9817cf3e9bfaac2e50fd2547aedc2f74d',
          old='14de10e4ff7c3c0e663a71052e68e416213f6f107838b293160416e47bc34e43',
          evidence='再生字块按页记忆 cells 产物与列图（A20 11-05，只动 render，run_page 不变）：tests/test_cell_shrink_render_memo.py 清缓存再生 100+ 格与 Step4 写入的逐像素相同（记忆开／关）；'
                   '任务库 #477（bb9eb76）冷缓存执行机从 glyph_match 起跑史記 01 册全册 143 页，glyph_match 与 #460 逐字节相同；2026-11-05'),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="1b101b4d25356f55302577544712fe1c19ae1959754f0ee87ca124bacafce16e",
          old="b8519c1fb383d8e7fbf8fad5f5705a5a8d9a8456d66154663a68574d68d4fb2e",
          evidence=_COORD_PAIR),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='9205734c66442a43ee349ac45fbe6465d7c071a47388f71444a90193a50f5bcb',
          old='de749a131133f682da5f64a4c1f18ea5e19af7dc75e7e108a0a685abde0b54dd',
          evidence='near_knn_gap 挪到各补放通道之后（缺省关，全唐文形近字线 11-05）：开关关着时全唐文 012 册 13 页'
                   '（p5,20,35,…,185）与 origin/dev 73f189b 产物逐字节相同；scripts/code_equiv.py check，2026-11-05'),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="b8ed17ca3942912b94848ae4d0eb8d19243b2b475d67ba946a10b5d412489480",
          old="b8519c1fb383d8e7fbf8fad5f5705a5a8d9a8456d66154663a68574d68d4fb2e",
          evidence=_COORD_PAIR_SUB),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='fc1c19db605f42f8d442f68b8b8cc66a4df4ce454c85a1ab2e6154c6221d772e',
          old='de749a131133f682da5f64a4c1f18ea5e19af7dc75e7e108a0a685abde0b54dd',
          evidence='seed_admit 在 012 13 页（--pages 5,20,35,50,65,80,95,110,125,140,155,170,185）上与 origin/dev 产物逐字节相同（group_flow_provisional_to／ref_lib_coord_dissent／replace_form_edge_exclude 缺省关）'),
    Equiv(module='open_guji_cv.groups.flow',
          new='e59ec85463defe2b1e0b731685b98d73c71bfae3c0818544291f571682d4cb21',
          old='623f6703f114d2fea9fc297804ded071f066aacc552895ca114f3d8a20145fdb',
          evidence='seed_admit 在 012 13 页（--pages 5,20,35,50,65,80,95,110,125,140,155,170,185）上与 origin/dev 产物逐字节相同（group_flow_provisional_to／ref_lib_coord_dissent／replace_form_edge_exclude 缺省关）'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='6bd2f3049ff8241fdab909dc94f413ccd8eb3fd3ece19cd2c7558dfdaaa08753',
          old='bb7d6556b2ea242df04b3467a3b179e3baca4646364fd895aaab2a225b5e785e',
          evidence='seed_admit 在 012 13 页（--pages 5,20,35,50,65,80,95,110,125,140,155,170,185）上与 origin/dev 产物逐字节相同（fold_coord_ref 缺省关）'),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="484efb123a713cd8ce1e1da85c97e486e5aab4f3e619f6ede43c18bd1bafda9f",
          old="c8565a7229ff9256438535b5a452ad86be56f1d0a25f5b246101e9d08f243102",
          evidence="inner_frame_only 列端补救（缺省关；列首条带开到内框线、挨线的首末格地盘外伸、贴线碎块只剥薄片（没拟出内线的一端框渣也只剥薄片）、Step2 削掉的列端行在线字侧从 column_raw 补回，A22 11-05）："
                   "三个内框开关都关时殿本 vol30 新图 28 页（每 5 页取 1）、inner_frame_cut＋inner_frame_profile 开而 inner_frame_only 关时 vol05 全册 186 页，"
                   "cell_shrink 产物与字块 PNG 与 origin/dev aad5ae8 逐字节相同（只差 _manifest）；2026-11-05"),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="bdd65c9c87a39526fda83499bcbb7c4c1b62716ed936273aaf1f522fe612ad39",
          old="1b7b7a91ec05c6fe447c6dbbea470af9817cf3e9bfaac2e50fd2547aedc2f74d",
          evidence="inner_frame_only 列端补救（缺省关；同上一条，A22 11-05）：三个内框开关都关时殿本 vol30 新图 28 页（每 5 页取 1）、inner_frame_cut＋inner_frame_profile 开而 inner_frame_only 关时 vol05 全册 186 页，cell_shrink 产物与字块 PNG 与 origin/dev aad5ae8 逐字节相同（只差 _manifest）；合入 dev（含 A20 再生字块记忆）后 vol30 28 页两种配置再核一遍同样逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.utils.daizhige",
          new="2a3573600390796020b55915e3c58ce7d06af1215ec9af79ecc940c5baba41be",
          old="504321227060b83062dbe45680a9df9c29b214a629b1a310124a36cf78c7e0fd",
          evidence="待收字：僻字码原码位（daizhige:U+XXXX）旁路带到 run 的 pua／pua_r／pua_l（新增函数 pua_codes，文本仍写〓，A24 11-05）："
                   "row_segment 在殿本 vol04 7 页（--pages 5,12,30,60,90,120,150）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="00a6f2b28da6d1e20bea27bf4bdd2af2cc3df98def3258e14be15238c2389cf2",
          old="589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f",
          evidence=_JZ_HALF_A),
    Equiv(module="open_guji_cv.books.quantangwen.row_boundaries",
          new="230be14bfebcd19130c40e9479e2b73d0fcb46378007b91c9340e2cc257aff84",
          old="b5c2b5fb08fc415f3f8e21dffcbfe8f6c57ef7f68d3a3b931b8c0a1e6622a9b7",
          evidence=_JZ_HALF_A),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="fab2ca38c755cf3a0389d0dbcf95af9468acc527f6b9e890700c80d8a41af3e5",
          old="bdd65c9c87a39526fda83499bcbb7c4c1b62716ed936273aaf1f522fe612ad39",
          evidence="书级开关 inner_frame_keep_cross（缺省关，A22 11-05，史記列尾字脚压线）：开关关着时殿本 vol30 新图 28 页（每 5 页取 1；"
                   "三个内框开关开、全关两种配置）与史記 05 册全册 95 页（册配置原样），cell_shrink 产物与字块 PNG 与 origin/dev 逐字节相同（只差 _manifest）；2026-11-05"),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="cd57bb1b1bd865fe7f5f217ba1e84abbaef44f44f20da070d4e897b121cff605",
          old="18517e310d5a4af1946c39c28c2fcb32427ae5fc28c5eb84037c9cf3ec2c53e3",
          evidence="inner_frame_keep_cross 收窄（新参数 inner_frame_cross_max_w 只在 keep_cross 开时进 dump，A22 11-06，SJ 第 13 轮列尾框下伸）："
                   "keep_cross 关时殿本 vol30 新图 28 页（每 5 页取 1，三个内框开关开）与史記 05 册全册 95 页，cell_shrink 产物与字块 PNG 与 origin/dev c73b6f8 逐字节相同（只差 _manifest）；"
                   "开 keep_cross 的书（史記）params_hash 变、照常过期；2026-11-06"),
    Equiv(module="open_guji_cv.steps.column_warp",
          new="12a0d170a3843f32b76c18eedad8d313f83e0596e9d19d0f4a2cc1e4e85c6463",
          old="991a42b0a7af0825750f929e9892e1a397b56a224e709b858dbbec2716724c65",
          evidence="S9 跨 CPU 确定开关 column_warp.det_warp、row_segment cut_judge=unet_f64（缺省关）：column_warp 与 row_segment 在全唐文 010 4 页（--pages 20,23,27,34）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="1abd6033efc1138cd6e4a63f0795f5a78b298f0c2362bb3d2932329e6608f2e8",
          old="589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f",
          evidence="S9 跨 CPU 确定开关 column_warp.det_warp、row_segment cut_judge=unet_f64（缺省关）：column_warp 与 row_segment 在全唐文 010 4 页（--pages 20,23,27,34）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.seg.warp",
          new="114369950bbde51b6e4dca56d9471f08046385d30f942d905abeb19a8cbb568f",
          old="5e750f4a8781a7ca6ea8a6916d330d7a27719a91fafb4814aa2e62a8bc5af353",
          evidence="S9 跨 CPU 确定开关 column_warp.det_warp、row_segment cut_judge=unet_f64（缺省关）：column_warp 与 row_segment 在全唐文 010 4 页（--pages 20,23,27,34）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.books.siku_zongmu.column",
          new="9684c4f568ecbbdb3fe54de8572d9def5fd0a01ee64797c089cce416b7bba2c6",
          old="57eac44b46c0ce8126d45774bcf309f6a628aec75259f3692568ff7456a8e54b",
          evidence="S9 跨 CPU 确定开关 column_warp.det_warp、row_segment cut_judge=unet_f64（缺省关）：column_warp 与 row_segment 在全唐文 010 4 页（--pages 20,23,27,34）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.seg.cut_select",
          new="dd00ea8f3e0ef148d1a0422c8ebdf63ae7995491737509826ef86905f57cfde1",
          old="fad2da0e7322c7d0da354c2d1b246346060609fc616f53a33d4f46dfe5c4b13b",
          evidence="S9 跨 CPU 确定开关 column_warp.det_warp、row_segment cut_judge=unet_f64（缺省关）：column_warp 与 row_segment 在全唐文 010 4 页（--pages 20,23,27,34）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="2ce1199fb028fcdab7b83f31e7d78421a03047f5635c2e8d5680d02d21abdb7f",
          old="14de10e4ff7c3c0e663a71052e68e416213f6f107838b293160416e47bc34e43",
          evidence="S4 内框细线逐段贴线 cell_shrink.inner_frame_local（缺省关）：cell_shrink 在全唐文 010 4 页（--pages 41,50,64,72，书级 inner_frame_cut 开）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.seg.frame_line",
          new="58657ca853fe63e8fea1ba6a7e37d463338a69da12fc311454f782000bbad3fe",
          old="0060b94fa6c5421484b9df42fcb7869728239c7fa98125d5c4ea4a691b2d7b5b",
          evidence="S4 内框细线逐段贴线 cell_shrink.inner_frame_local（缺省关）：cell_shrink 在全唐文 010 4 页（--pages 41,50,64,72，书级 inner_frame_cut 开）上与 origin/dev 产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="403b83c2b6accbbd21f1f6f80272fe569b310f9881325341c0f1a77df42b170c",
          old="14de10e4ff7c3c0e663a71052e68e416213f6f107838b293160416e47bc34e43",
          evidence=_TAIL_ONE_ABS),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="7fc8b038633f8c23a0421251004cbc13ccbf6a875a44bb370258e7c91abb11d0",
          old="c8565a7229ff9256438535b5a452ad86be56f1d0a25f5b246101e9d08f243102",
          evidence=_TAIL_ONE_ABS),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="54dc154cfba6db8cfd8010a1747b6e6f647d16959ff49818f1500b40e0670514",
          old="589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f",
          evidence=_LAYOUT_CUTS),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="18517e310d5a4af1946c39c28c2fcb32427ae5fc28c5eb84037c9cf3ec2c53e3",
          old="14de10e4ff7c3c0e663a71052e68e416213f6f107838b293160416e47bc34e43",
          evidence="S5 内框贴线放宽到半格、种子线兜底、列端剥框线只认贴着整页内线的线行（只在 cell_shrink.inner_frame_local 开时生效）：cell_shrink 在全唐文 010 4 页（--pages 41,50,64,74，书级 inner_frame_cut 开、inner_frame_local 关）上与 origin/dev（b148b2c）产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="c658979461e3be53fda935c0705d1bd4a8dfc48073eaf4c7b7f680a6b98da988",
          old="c8565a7229ff9256438535b5a452ad86be56f1d0a25f5b246101e9d08f243102",
          evidence="S5 内框贴线放宽到半格、种子线兜底、列端剥框线只认贴着整页内线的线行（只在 cell_shrink.inner_frame_local 开时生效）：cell_shrink 在全唐文 010 4 页（--pages 41,50,64,74，书级 inner_frame_cut 开、inner_frame_local 关）上与 origin/dev（b148b2c）产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.seg.frame_line",
          new="d7447bb3945fbdb008e46048d9571b7022b7910bf9509b54691f3d25fca9b238",
          old="0060b94fa6c5421484b9df42fcb7869728239c7fa98125d5c4ea4a691b2d7b5b",
          evidence="S5 内框贴线放宽到半格、种子线兜底、列端剥框线只认贴着整页内线的线行（只在 cell_shrink.inner_frame_local 开时生效）：cell_shrink 在全唐文 010 4 页（--pages 41,50,64,74，书级 inner_frame_cut 开、inner_frame_local 关）上与 origin/dev（b148b2c）产物逐字节相同；2026-11-05"),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="04d065eef7987103b93c7cd1fd1c7b54558e44372a939fb5a2e6a305e231b6d4",
          old="94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e",
          evidence="S6 墨团闸 cell_shrink.ink_blob_empty（缺省关）：cell_shrink 在全唐文 010 4 页（--pages 41,50,64,74）上与 origin/dev（835325b）产物逐字节相同；2026-11-06"),
    Equiv(module="open_guji_cv.clustering.extractor",
          new="4bab89e01a18b859e43c608800010e7e951dc0843b36588f11b91a1ed7b90eaf",
          old="c8565a7229ff9256438535b5a452ad86be56f1d0a25f5b246101e9d08f243102",
          evidence="S6 墨团闸 cell_shrink.ink_blob_empty（缺省关）：cell_shrink 在全唐文 010 4 页（--pages 41,50,64,74）上与 origin/dev（835325b）产物逐字节相同；2026-11-06"),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="d8775d706a25f56c2bd538252dc33057a8da6478d5752891426d4839beb8298c",
          old="589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f",
          evidence=_COLTEXT),
    Equiv(module="open_guji_cv.steps.row_segment_pagemap",
          new="80c25b7688c53da3e0fbfc17f3fd92abfd808ce05adc5d38f1d9a7ef208e360a",
          old="3ef375f764f67717152ebd4e11b234ca338bbb02091dc6d07a3de50bfc52c9f0",
          evidence=_COLTEXT),
    Equiv(module="open_guji_cv.utils.page_align",
          new="596abeebaefa4d07c048e8a3bd31e0f1dea46b48f5ad80a6be91248d396cba19",
          old="9be05ea88089263da8421b3e71dcce436f26bf8be989a68c6cf6a4c2356774f2",
          evidence=_COLTEXT),
    Equiv(module="open_guji_cv.steps.row_segment",
          new="7f810225612f4ea526dab7d258174282bc4270a4454c72a94c011371381b71f6",
          old="589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f",
          evidence=_SEAL_TOP),
)


#: 搬过家的模块：新模块名 → (搬家前的模块名, 搬家前的代码哈希)。指纹里模块名也进哈希，所以搬家要换回旧名字。
#: 只在「现在的代码（经 ENTRIES 换算后）仍等于搬家前那一版」时生效（见 engine._fingerprint_name）；之后真改了就按新名字，
#: 照常判过期。搬家时只有 import 路径变的模块，在 ENTRIES 里另登 new→old 哈希。登记纪律同 ENTRIES：只增不删。
#: 切分模块化（2026-10-30，Sheldon 定）：代码搬进 books/<套书>/。
MOVED: dict[str, tuple[str, str]] = {
    "open_guji_cv.books.siku_zongmu.column_triage": ("open_guji_cv.utils.column_triage", "9b98ee76d1a45032e014e3d385297dac192f3a07e2b0e0de7b96f226e716580b"),
    "open_guji_cv.books.siku_zongmu.column_pair_merge": ("open_guji_cv.utils.column_pair_merge", "1b943e53a2d01db37949866b3b8f43c25f64e787096c6b0ce14a456441a7ecfd"),
    "open_guji_cv.books.siku_zongmu.column_types": ("open_guji_cv.utils.column_types", "85b6a36a684c2236c43f60a3826357e4785f17abbe2dcb4ad97dc4f7bfa6a41a"),
    "open_guji_cv.books.siku_zongmu.pitch_rescue": ("open_guji_cv.utils.pitch_rescue", "e28dc2b23ab157ae34104369194741aad2d87e8a8966267f8fcb558247818b72"),
    "open_guji_cv.seg.cut_select": ("open_guji_cv.utils.cut_select", "fad2da0e7322c7d0da354c2d1b246346060609fc616f53a33d4f46dfe5c4b13b"),
    "open_guji_cv.seg.seam": ("open_guji_cv.utils.seam", "2d3f4c680d5a1aabb68c5773ce6a2b67afe20ccbd9fe561b64c29131e1e0b671"),
    "open_guji_cv.books.siku_zongmu.jiazhu_split": ("open_guji_cv.utils.jiazhu_split", "e7c605b8247e14f4aae7c90c1e05be0a8b01cb32dbdbf2a9e6cb5e7086fcc82b"),
    "open_guji_cv.books.siku_zongmu.roster_glyph": ("open_guji_cv.utils.roster_glyph", "84f0636a76c93b4c74dbe25919b99100ae8dce8db18e7e41561db839d5f3ab68"),
    "open_guji_cv.books.siku_zongmu.roster_segment": ("open_guji_cv.utils.roster_segment", "894c946b329304625f8db915124b62a2308affe244fbb9b301506d43d008496f"),
    "open_guji_cv.books.siku_zongmu.row_boundaries": ("open_guji_cv.utils.row_boundaries", "7ca231b5277f35b458362ba6ede3e992585607d06c4e9cd01d78cea71e4633be"),
    "open_guji_cv.books.siku_zongmu.row_grid": ("open_guji_cv.utils.row_grid", "283f1e2564615d55bf27c6f5638ee10d949c05d3953c74eb5398d6c2a38d2a0e"),
    "open_guji_cv.books.siku_zongmu.yolo_tool_infer": ("open_guji_cv.utils.yolo_tool_infer", "33de2955e1c3eb8871f723c7929a8f62bd8baf37074777f20362918fdc33ba95"),
    "open_guji_cv.books.beixing.line_layout": ("open_guji_cv.utils.line_layout", "33f17f6be1f6f2f54345bc970f61c2772b41dc670bb602d006e478c1b6259d24"),
    "open_guji_cv.books.beixing.run_segment": ("open_guji_cv.utils.run_segment", "e770b30c24de8dfa927e615547d66e109b8f6a97ae6e6a0726bbdf66473a6a17"),
    "open_guji_cv.books.zengguang_youxue.free_blocks": ("open_guji_cv.utils.free_blocks", "eef4c4c127d5f5acb5f5b143a276d613f76fc2d78239be2cb298b5a5050e8d5f"),
    "open_guji_cv.books.zengguang_youxue.free_columns": ("open_guji_cv.utils.free_columns", "277550471a0881db4e62e7192e6c6fb25f785fe545f9eb9912f447ab35a06a6f"),
    "open_guji_cv.books.zengguang_youxue.free_cells": ("open_guji_cv.utils.free_cells", "761eaa8e09be2cb1c1736bf1aaf528a2c62e6e63aee8ffb001f32e0ca47559c6"),
    "open_guji_cv.books.zengguang_youxue.free_rectify": ("open_guji_cv.utils.free_rectify", "9f39c373de06349d1d040ff488b152f36820f11c2b20e9b2a43a8563c7093ab0"),
    "open_guji_cv.books.zengguang_youxue.free_ocr": ("open_guji_cv.utils.free_ocr", "d913668cfa50b267394c24ae0193d1d9ae859d5510179f74e40499dd477ebf41"),
}


#: 套书分叉的复制：复制出来的模块 → (原模块名, 分叉时的代码哈希，经 ENTRIES 换算后)。与 MOVED 的区别是原模块还在
#: （别的套书照用）。复制还是分叉时那一版，这套书的指纹就记原模块名，产物不过期；之后这套书改了自己那份，照常过期。
#: 纪律同 ENTRIES：只增不删（2026-11-04，全唐文分叉 Step3 行切分）。
FORKED: dict[str, tuple[str, str]] = {
    "open_guji_cv.books.quantangwen.row_boundaries": ("open_guji_cv.books.siku_zongmu.row_boundaries", "4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c"),
    "open_guji_cv.books.quantangwen.jiazhu_split": ("open_guji_cv.books.siku_zongmu.jiazhu_split", "e7c605b8247e14f4aae7c90c1e05be0a8b01cb32dbdbf2a9e6cb5e7086fcc82b"),
}

#: 拆过的模块：旧模块名 → (拆分前的代码哈希, [(拆出来的新模块, 拆分时的代码哈希), …])。
#: 一个模块拆成几块，Step 的模块表从一项变几项，指纹公式就变了；这里登记了，算指纹时几块都在、代码都还是
#: 拆分时那一版，就合回一项（旧名＋旧哈希，见 engine._collapse_splits），产物不过期。之后任何一块真改了就不合并，
#: 照常过期。用到旧模块的 Step 要在 code_deps 里列齐全部几块。纪律同 ENTRIES：只增不删；拆出来的块又拆或又搬时，
#: 把那一项的块表换成最新的几块（旧哈希不动，块表里的旧块已不存在，留着也合不上）。
#: 也用来登 Step 新加的 code_dep（不是拆分）：旧模块名就是 Step 模块自己，块表＝它自己＋新加的那个模块；
#: 两块都还是登记时那一版就合回原来一项，指纹不变（row_segment＋jiazhu_step 空实现，cv#1011）。这种项不是错登，别删。
SPLITS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "open_guji_cv.utils.border_geometry": ("20c5f6fde41a30ad2e22200be0a97a793ceef3492e283b0fff92cb657bb896fb", (
        ("open_guji_cv.books.siku_zongmu.border", "f4989571d81cbb4d988c77cf5e4622dd57634df0ad8dbe31ee9ec432c563d0c1"),
        ("open_guji_cv.seg.polyline", "bf94b777e8bd227b12a64916ee3a2bf7bc457163047bdc9126a3f164e52825d4"),
        ("open_guji_cv.seg.frame_types", "910317f58be2061fbe06468ba3abf2de685e6250440b1008b8308fd37561fa4b"))),
    "open_guji_cv.utils.peak_line_search": ("90afd63cf2eec6ace053c4d470d1568c3c39582a532c99d2a929cec5bf016890", (
        ("open_guji_cv.seg.grid", "93f436b06ca22e975e211d5e194b5bc657cc6cdba0b6b3438bb6ba9c4e49780a"),
        ("open_guji_cv.seg.lines", "322ed871071601159e4123bfdb1b4b8ffb10c07cb0616c7783c003f0e88d8e61"))),
    "open_guji_cv.utils.column_projection": ("614cc9b0f4ffcb6f151c15c8bd56824df81d5e01edb4fb3bd8df3176e3c645ef", (
        ("open_guji_cv.seg.warp", "5e750f4a8781a7ca6ea8a6916d330d7a27719a91fafb4814aa2e62a8bc5af353"),
        ("open_guji_cv.seg.profile", "508270c9484b07c734e3c671f123093ecdd2405c0851340e5d0deb3437cd6609"),
        ("open_guji_cv.books.siku_zongmu.column", "4465ac6dfe85c0eaba56e06d75c260285f7fd5a02cef69cc5787ba8e0caae3dd"))),
    # 不是拆分、是 row_segment 新加了一个 code_dep（jiazhu_step 空实现）：两块都还是这一版时合回 row_segment 一项
    "open_guji_cv.steps.row_segment": ("427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28", (
        ("open_guji_cv.steps.row_segment", "427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28"),
        ("open_guji_cv.books.siku_zongmu.jiazhu_step", "095bb58deee8dcb0f81c030c1f8037b39dd193000f95baa14205588939810c67"))),
}


def _table() -> dict[str, dict[str, str]]:
    t: dict[str, dict[str, str]] = {}
    for e in ENTRIES:
        t.setdefault(e.module, {})[e.new] = e.old
    return t


_TABLE = _table()


def canonical(module: str, h: str) -> str:
    """模块 `module` 的代码哈希 `h` 在等价登记下的规范值（沿链走到头）。"""
    m = _TABLE.get(module)
    if not m:
        return h
    seen = set()
    while h in m and h not in seen:
        seen.add(h)
        h = m[h]
    return h
