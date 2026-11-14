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


_WU_1114 = ("seed_admit 嗚鳴 书级刻形判法 group_flow_wu_shape（缺省空、找不到 config/groups/wu_shape.json 就不跑；模型指纹只在有模型时进指纹）：全唐文 020 f5 包（cv0.7.8-c52-g-9f3d37-k4-qtw020-f5）20 页 seed_admit 与 origin/dev a2b61a9 产物逐字节相同；scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-14（全唐文·形近字线）")
_WU_OOD_1114 = ("seed_admit _wu_shape_pass 补放护栏（总览 11-14 审 #1539）：待审格须本格字是嗚鳴或库前 3 名候选有嗚鳴，只有整理本／字组说嗚鳴的不补放；"
                "只在 group_flow_wu_shape 开时走：全唐文 020 f5 包（cv0.7.8-c52-g-9f3d37-k4-qtw020-f5）20 页 seed_admit 与 origin/dev 0371709 产物逐字节相同；"
                "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-14（全唐文·形近字线）")
_RF_1113 = ("seed_admit group_flow_ruling_first（书级，缺省空不进参数 dump；Chain._ruling_first 名单外直接返回 (None, None)、ask_rf 只在名单内记）：全唐文 020 f5 包（cv0.7.8-c52-g-9f3d37-k4-qtw020-f5）40 页 seed_admit 与 origin/dev 69711fa 产物逐字节相同；scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-13（全唐文·形近字线）")
_FR_HOOK_1113 = ("seed_admit follow_ref 加书级钩子 impl/keben/follow_ref_hooks.rival_skip（缺省 None，不调；follow_ref_decide 加 rival_skip "
                 "参数缺省空集，max 的过滤条件多一个恒真项）、新函数 _RivalFacts／_pair_facts／_follow_ref_rival_hook（只在钩子非 None 时用）："
                 "殿本 vol28 16 页（1,2,3,5,8,12,20,30,45,60,80,100,102,130,160,190，main 包 cv0.6.23-c33-g19-r8 当上游）seed_admit 与 origin/dev e466f52 "
                 "产物逐字节相同；Step code_hash 改前改后同（babb397c0ee19af7，follow_ref_hooks 经 SPLITS 合回 pua_v2_codes）；"
                 "scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-13（A22）")

_DROP_L0_1114 = ("删缺省关、没书开、关时不进参数 dump 的开关（A22 开关收敛 L0 批，A20 11-14 定）：border_detect.merge_narrow_pair、"
                 "border_detect_gate.pagetype_model 三件、column_gate.period_edge_fallback、row_segment.colgold_prior／colgold_fingerprint、"
                 "yolo_merge 等七件及其只在开着时走的代码；关时控制流与改前相同。殿本 vol01 13 页（1,2,3,30,48,60,87,100,130,160,182,203,204，"
                 "含卷端大印、职名页、门目页、卷末印，main 包 cv0.7.16-c16-g21-m2-p48-col9-grid-1113-a2 当上游）border_detect、border_detect_gate、"
                 "column_gate、row_segment 与 origin/dev 84f5bc28 产物逐字节相同；scripts/code_equiv.py check，2026-11-14（A22）")
_QTW_HOOKS_1113 = ("row_hooks 加书级钩子 jiazhu_pair_ok（缺省 None，不调）、jiazhu_heads 多传 ruler（只在钩子非 None 时调）："
                   "殿本 fixture 册 keben 冻结三页（tests/fixtures/workspace/raw/keben 1–3）row_segment 与 origin/dev 84f5bc28 产物逐字节相同；"
                   "全唐文 k8（书仓 fork 改钩子，cv 本分支）对 k6 fork（cv v0.7.31）：054 全册 180 页（包 cv0.7.31-c68-g-02bb02-k6-qtw054-n1）、115 全册 208 页（判、小注密，包 cv0.7.31-c69-g-02bb02-k6-qtw115-p1）row_segment→cell_shrink 产物逐字节相同；"
                   "2026-11-13（全唐文切分线）")

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

_BX_1110 = ("外框采样列 xs 去掉 ≥ 图宽的列（cv #1362，史記09 年表页 border_detect IndexError）：border_detect 在测试样本 keben 3 页上"
            "与 fd4976e0~1 产物逐字节相同；另按代码论证——xs 用来取 binm[·, xs]，原先没崩的页里 ≥ 图宽的列从没被取过墨"
            "（取了就 IndexError），去掉后各偏移的取墨集合不变、均值不变；scripts/code_equiv.py check，2026-11-10（A31）")

_MF_1110 = ("cell_shrink 人工定框列加书级开关 manual_ink_fit（缺省关不进 dump；SJ 11-10 报定框满宽网格框带进邻字）："
            "开关关着时殿本 vol28 30 页（p1–30，main 包）、全唐文 001 20 页（p1–20，main 包）与 origin/dev 345e5877 产物逐字节相同；"
            "scripts/code_equiv.py check --always，2026-11-10（A22）")

_MF_1111 = ("manual_ink_fit 跨框笔画整块留下（SJ cv #1410）＋开了的书 dump 加 manual_ink_fit_rev（只让开了的书过期）："
            "开关关着时殿本 vol28 30 页、全唐文 001 20 页 cell_shrink 与 origin/dev 58108ae 产物逐字节相同；"
            "scripts/code_equiv.py check --always，2026-11-11（A22）")

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

_COORD_PAIR_ONLY = ('align_ref 加缺省关的书级开关 coord_conflict_pair_only（与现役对位冲突只退冲突格；A32 D02 深挖）：开关关着时 align_ref 在殿本 vol82 45 页（每 6 页取 1 加 p2/p3/p147，★main 包 cv0.6.4-c30-g19-r5-a2）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn（语料清单 yh/rules.yaml 与钉不符，新旧两边同样），2026-11-06')

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

_BEND_1108 = ("border_detect 加书级弯页门槛 bend_w80_med（缺省 None 取 seg/polyline.BEND_W80_MED，不进参数 dump；殿本第7轮"
              "Commons 图源列端切半，写 0＝整页三段折线）：border_detect 在殿本 vol28 192 页（全册）与 vol89 190 页（全册）"
              "上与 origin/dev af80b48e（已含 #1256 下版框护栏）产物逐字节相同；border_detect、siku border 两项接在 #1256 登记之后；column_warp 只在 code_deps 里列 siku_zongmu.border，不调改动的函数；"
              "scripts/code_equiv.py check，2026-11-08")


_FIT2_1108 = ('cell_shrink.inner_frame_fit2／inner_frame_snap 列尾内框线补拟与补抹（都缺省关、不进参数 dump；A22，殿本第 7 轮带框重字块，Sheldon 11-08 定修）：cell_shrink 在殿本 vol95 新图 10 页（19,45,46,50,83,108,129,170,186,202，含原先拟不出内线的页）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08')

_LOCK_1108 = 'border_detect.bottom_lock_reslope 下框贴边重找倾角（缺省关、不进参数 dump）＋下框越出图底不崩（_rule_offset 夹图内；A22，vol01–19 换新图 vol09 p112 等 9 页 IndexError、vol12 p27 下框落字身）：border_detect、column_warp 在殿本 vol22 新图 12 页（1,5,20,41,60,77,100,120,147,160,180,188）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08'

_TOPEDGE_1108 = 'border_detect.top_edge_reslope 上框贴图顶时连倾角重找（缺省关、不进参数 dump；A22，vol01–19 换新图 vol14 p45 上框落在图顶伪影）：border_detect、column_warp 在殿本 vol22 新图 12 页（1,5,20,41,60,77,100,120,147,160,180,188）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08'

_ROSTER_LR_1108 = ('row_segment 职名页大字雙行整段分栏 roster_lr_run、臣字上限 roster_side_max（都缺省关、不进参数 dump；A22，殿本 vol01 新图 001-r6 职名页切坏格）：'
                   'row_segment 在殿本 vol01 新图 17 页（22,24,31,45,58,87,88,99,100,101,123,130,135,139,149,160,203：正文页、职名页含 87/88/99 切坏页、卷首門目大印页）'
                   '上与 dev b519fba 产物逐字节相同；scripts/code_equiv.py check，2026-11-08')

_HINT_1109 = ('border_detect.hline_hints 页级人给上／下版框 y（缺省空、不进参数 dump；A22，GUJI-758 殿本上版框认错 10 页）：'
              'border_detect、column_warp 在殿本 vol20 新图 12 页（1,5,20,41,60,77,100,120,147,156,180,254，含上框认错页 156、'
              'vline_overrides 页 254）上与 origin/dev 5ed735d 产物逐字节相同；scripts/code_equiv.py check，2026-11-09')

_SNAP_CUT = ("按墨块切割量补挪格线 snap_cut（row_segment 书级参数，缺省 0＝关，史記 r54 劈字，GUJI-771；seg.seam 只加 cut_cost_profile／"
             "cut_cost_sides 两个新函数，原有函数不动，cell_shrink 用的走缝函数不变）：row_segment 在史記 42 册 10 页"
             "（--pages 27,43,64,92,137,14,36,31,33,59，SJ 强档劈字最多的页，等距＋DP 格网、夹注、alt_cut）上与 origin/dev 0422e3c 产物逐字节相同；殿本 vol58（page_map strict，--pages 1,20,40,60,80,100,120,140 中 7 页）同样逐字节相同；"
             "scripts/code_equiv.py check，2026-11-13")
_GLYPH_GUARD = ("snap_cut 整字护栏（seg.cut_select 只加 move_keeps_glyphs 新函数；row_boundaries 在 snap_cut>0 且有 U-Net 裁判时"
                 "缺省接它当 snap_gap_ok，snap_cut 关时不走）：row_segment 在殿本 vol30 10 页（--pages 2,15,30,45,60,75,90,105,120,135）"
                 "与史記 42 册 3 页（--pages 3,36,59）上与 origin/dev 4b337f0 产物逐字节相同；scripts/code_equiv.py check，A22 2026-11-13")
_GUARD_TOL = ("snap_cut 整字护栏门槛 seg.cut_select.MOVE_TOL 0→0.05（只在 snap_cut>0 且有 U-Net 裁判时用；snap_cut 关不走）："
              "row_segment 在殿本 vol30 6 页（--pages 2,30,60,90,120,135）与史記 42 册 3 页（--pages 3,36,59）上与 origin/dev "
              "1244b8d 产物逐字节相同；scripts/code_equiv.py check，A22 2026-11-13")
_GRID_END_FIT = ("等距格网末线外推到末字墨外沿 grid_end_fit（row_segment 书级开关，殿本套书，缺省关；siku_zongmu.row_boundaries 加 "
                 "fit_grid_end）：开关关着时 row_segment 在殿本 vol28 新图 12 页（2,11,27,44,62,92,100,116,130,150,166,186；基底产物包 r8）"
                 "上与 origin/dev 5ed735d 产物逐字节相同，另 vol28/49/89 整册 cell_shrink 与 r8 包 char_index 逐字节相同；"
                 "scripts/code_equiv.py check，2026-11-09（A22）")


_MV_IMPL = ("书级代码第 2 步（2026-11-09，cv v0.7.0）：三条版式的缺省实现由 books/ 改名——books/siku_zongmu → impl/keben、"
            "books/beixing → impl/modern、books/zengguang_youxue → impl/free，文件原样 git mv；引用它们的 Step 壳、闸、feedback.lookup "
            "只改 import 路径与 code_deps 里的模块名（逐文件核过：改动行全是改名）。改名前后 5 套书 × 23 步 code_hash 逐位相同"
            "（对 origin/dev dc16d35 逐步比对）")


_HOOKS_1110 = ("书级代码第 4 步（cv #1375，2026-11-10）：row_segment 的史記开关 seal_inkcut／seal_gap_slots_empty／jiazhu_free_split／"
               "jiazhu_step_split 改成书级钩子（impl/keben/seal_ink 新、jiazhu_step.free_split），实现原样搬进史記书仓 code/（k2）；"
               "缺省钩子什么都不做，殿本等书走的分支代码未动。证据：SJ 11-10 用 cv dev 1bb3d44b＋书仓 PR #1 code/ 本地重跑 row_segment，"
               "与 r28 main 包（v0.6.38＋k1）比 02 册 p2/13/58/100/150/200、05 册 p2/26/50/80 共 10 页产物逐字节相同"
               "（史記走的正是改动的钩子分支，也覆盖 row_segment／row_boundaries 的公共部分）；殿本等缺省钩子分支是删开关后的原路径")

_PCLEAN_1110 = ("cell_shrink 加书级钩子「发前清格」（impl/keben/patch_clean，缺省 clean_column=None 不清，2026-11-10 SJ）："
                "缺省时 `_extract_column` 原样返回；史記文淵閣本 02 册 12 页（p2 卷端＋正文每 20 页取 1）与 origin/dev df08209 "
                "产物逐字节相同，scripts/code_equiv.py check，书仓 k2（无覆盖）")

_PINS_SRC_1112 = ("row_segment 的 pins 档格位表指纹（page_map_fingerprint）与夹注参照指纹（roster_ref_fingerprint）改为只算本册钉位点名的 daizhige 源文件"
                  "（原先算 corpus/daizhige/ 下全部 4 位数 jsonl），好让 0244.jsonl 入库不让 0243 册过期。等价性按真数据证明而不是跑产物："
                  "用中心库 988g3f0wsu 的 page_pins.jsonl（rev 346019，sha a433e753…）与 0243.jsonl（sha 13fca24f…），01 册 pins 指纹 8b867fc8b4dcc0d2、17 册 8ff8527b6f73d615、"
                  "夹注参照指纹 f2d6945a67503581，与改前代码在只有 0243 时算出的值逐位相同，加入 0244.jsonl 后仍相同（改前会变）；"
                  "指纹值不变、其余代码路径未动，故产物不变；2026-11-12（A31，史記 0244 入库）")

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
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 3fd1180d 产物逐字节相同"),
    Equiv(module="open_guji_cv.groups.flow",
          new="a866f82c00097b54f43a2062fe4e7dcb9cb37a1acb4310a6fc7aa27924228d47",
          old="1d2277f983f07f18c18c79bab84350a867cc5b141e8d6bdb34f32d4dac239e60",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 3fd1180d 产物逐字节相同"),
    # 书级字形＝整理本补放 group_flow_lift_shape_ref（缺省空）：2026-11-01 史記 02
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="a7a0418923dbf6b61010d17d83e072f7a0987bce54b9a2c5464dbddd34a9e5cf",
          old="df2d8a69fe3bbf80b5ecfc97540aff3634a536d20cdd442c8998472bfdf5019b",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 3fd1180d 产物逐字节相同"),
    Equiv(module="open_guji_cv.groups.flow",
          new="046fe1adaff78f4900fe665134a4b945883934c73988cf79716e74ed569407d2",
          old="1d2277f983f07f18c18c79bab84350a867cc5b141e8d6bdb34f32d4dac239e60",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含日曰组与小注格）上与 origin/dev 3fd1180d 产物逐字节相同"),
    # 书级按参校本取异体 follow_ref_variants（缺省关）：2026-11-01 史記 02
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="e3d42c945641454ad426932469235703d009750163b6115cc8d7136abedcbc77",
          old="df2d8a69fe3bbf80b5ecfc97540aff3634a536d20cdd442c8998472bfdf5019b",
          evidence="seed_admit 在史記 02 8 页（4,9,19,24,41,86,141,199，含异体与小注格）上与 origin/dev 3fd1180d 产物逐字节相同"),
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
          evidence="seed_admit 在史記 02 8 页（2,90,167,168,208,209,210,211，含 ○ 圈号页与卷端页）上与 origin/dev 3fd1180d 产物逐字节相同"),
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
          evidence="align_ref 在史記 03 第 2 页（卷端大印页）上与 origin/dev 3fd1180d 产物逐字节相同"),
    Equiv(module="open_guji_cv.steps.seed_admit",
          new="68444a805f3eab2dc7544f02dce2174719f3ed8aebb6837e7829c2804564b713",
          old="82930b01adb3c224cac7547d22dcc0a557a64ed7c0b6d8f7d072450e62081805",
          evidence="seed_admit 在史記 03 第 2 页（卷端大印页）上与 origin/dev 3fd1180d 产物逐字节相同"),
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
                   "border_detect_gate 在全唐文 05 那 12 页上与 origin/dev 3fd1180d 产物逐字节相同"),
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
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='047553c6e7db56f5cbbf99e648230d36bf946c6bd1bfdc4a9bd52253b55ca49f',
          old='41b4e1ab7a05a6970a5e05c9d5db29f83339220aef2eba32cdf81e79b1d9c449',
          evidence='seed_admit 在 001 3 页（--pages 61,120,150）上与 origin/dev 50295b8 产物逐字节相同（solo_5b_cov 缺省关，版本号不升；全唐文·形近字 11-08）'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='08f2f62fa6e2dd5569aae7051f29f55ee9f8a2545d2e615330fd1858192327bc',
          old='0f64460b8df1ba15fb1c871fb83a98569a9963276cf796e9723e7e03dd93de86',
          evidence='seed_admit 在 vol62 11 页（--pages 5,20,35,50,65,80,95,110,125,140,148）上与 origin/dev 25ecc52 产物逐字节相同（solo_5b 刻例门槛读可信刻例数、放行格带 no_glyph_lib、solo_5b_borrow_db 借库；solo_5b_cov 缺省关，版本号不升；A24 参校本属性 C1/C4 11-08，GUJI_CORPUS_DRIFT=warn）'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='57bc6ab9f7b0944b6e2219826056664139834edd99568e3a6b5c5e29e218fbb7',
          old='41b4e1ab7a05a6970a5e05c9d5db29f83339220aef2eba32cdf81e79b1d9c449',
          evidence='seed_admit 在 vol62 11 页（--pages 5,20,35,50,65,80,95,110,125,140,148）上与 origin/dev 产物逐字节相同（solo_5b_char_ok／solo_5b_human_min 字级白名单，缺省 None 关、不进 dump，版本号不升；A24 11-08，GUJI_CORPUS_DRIFT=warn）'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='2d5860a65f1354cb12ced87dc2000f53da060c1c56a720a3b7514104a484c485',
          old='41b4e1ab7a05a6970a5e05c9d5db29f83339220aef2eba32cdf81e79b1d9c449',
          evidence='seed_admit 在 02 18 页（--pages 4,9,19,24,33,41,44,53,86,95,102,106,114,141,173,180,185,199）上与 1cefd43a 产物逐字节相同；史記 vol02 r18 产物，18 页含夹注半格；#1277 group_flow_llm_half_groups 缺省空，版本号撤回 1.81'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='42446299bb0628237c0062e112b56096d291a57e7408afc580cd7be46aab2ec5',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；全唐文 001 front1 包，含姓氏韻編卷数小注数字格（num_run_cov 缺省 None 关、不进 dump，版本号不升；形近字线 11-08）'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='4fb5ffaa8021414aecd890ddefc14fd23838a7d439018608671ca096e0d2480c',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；全唐文 001 front1 包；num_run_juan_cov、solo_5b_same_cov 缺省 None 关、不进 dump，版本号不升；形近字线 11-08'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='ede5c2f60438abf0fb086713e279271fa87bed2db1a420d63e2d423076cb2ff0',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；全唐文 001 front1 包；solo_adapt_pct 缺省 None 关、不进 dump，版本号不升；形近字线 11-08'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='bc154ec583e9b0463c65dfc4282658d3bf39659118c0d7dc8a11bc32ca777faf',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；solo_5b_same_cov 认 consensus_fallback 退档前的 verdict，缺省 None 关；形近字线 11-08'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='50177a07c1953f11636c23ce6a7aa23df6907b82eaa78b0b189d98519cfd31d1',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；front7 三档 num_run_cov_5b、solo_adapt_risk_gap、solo_adapt_abstain_ok 缺省关、不进 dump；形近字线 11-08'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='f65c32a4eb6ed07119c4c8fa9f53f863a22f74ad7a4ac531bd8e010f45d5515c',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；自适应门槛二期 solo_adapt_near_slack、solo_adapt_nf_ok 缺省关、不进 dump；形近字线 11-08'),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='48d7102c8a2b77c397addc83298702cfc0c70e9f4e770396bcd08623b9fd5da3',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；solo_cal、solo_cal_5b_cov 缺省关、不进 dump；形近字线 11-08'),
    Equiv(module='open_guji_cv.groups.flow',
          new='5fb3a333880faf84ee9e104fe726992197b5ac0cb64b835eb4a291b56f47c2ac',
          old='e5df695c08db5b368007b7cf69b7e3ee1dcf769fcd04028ad8253974d5a7b373',
          evidence='seed_admit 在 02 18 页（--pages 4,9,19,24,33,41,44,53,86,95,102,106,114,141,173,180,185,199）上与 1cefd43a 产物逐字节相同；史記 vol02 r18 产物，18 页含夹注半格；#1277 group_flow_llm_half_groups 缺省空，版本号撤回 1.81'),
    Equiv(module='open_guji_cv.groups.methods',
          new='aace7cf4d0de8a02bdd8e66e2b8c39d67a881cc320241935ec33e76a00eebb96',
          old='45258af23d0898bfefb4957736316a953c3bdd334c3278a43aaa73fe97a5f861',
          evidence='seed_admit 在 02 18 页（--pages 4,9,19,24,33,41,44,53,86,95,102,106,114,141,173,180,185,199）上与 1cefd43a 产物逐字节相同；史記 vol02 r18 产物，18 页含夹注半格；#1277 group_flow_llm_half_groups 缺省空，版本号撤回 1.81'),
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
    Equiv(module="open_guji_cv.seg.cut_select",
          new="d49c22c5d713e5da83827c42dc0cf2c74fe482761b47c96816a133bc42e151f7",
          old="dd00ea8f3e0ef148d1a0422c8ebdf63ae7995491737509826ef86905f57cfde1",
          evidence="切点判官结果落盘复用（UNetJudge.owner 按窗口内容＋阈值＋判官指纹存 cache/_judge，GUJI_JUDGE_CACHE=0 关）：史記 01 8 页（--pages 18,20,24,28,29,69,73,138，cut_judge=unet_f64）row_segment 旧代码、新代码冷缓存、新代码热缓存三次产物逐字节相同，热缓存 108→7 秒；2026-11-06"),
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
    Equiv(module="open_guji_cv.steps.align_ref",
          new="0f26855c8f378bf028927ac328f602061769bb46f48a736f0d56b2e439aef9e3",
          old="b8519c1fb383d8e7fbf8fad5f5705a5a8d9a8456d66154663a68574d68d4fb2e",
          evidence=_COORD_PAIR_ONLY),
    # glyph_match 判决层抽成 glyph_rules（5a 规则框架，2026-11-06）
    Equiv(module='open_guji_cv.steps.glyph_match',
          new='87cae8c868d07adc21efad96f764289ca54be50968e6b9b3f5ae69dbebbd4681',
          old='fe823292dd35a88d6d8394f814c215819c784bb1d6fa87f905d12d88171edb32',
          evidence='glyph_match 判决规则抽成规则表 steps.glyph_rules（Rule 枚举＋RULES＋decide，含 #1174 缺省关的三组参数）：测试样页 keben 3 页（--pages 1,2,3，库用殿本 glyph.db）与 origin/dev 产物逐字节相同；另把殿本 1500 格、史記 800 格（含真借库）真匹配结果喂给改前内联逻辑与 decide()，18 组参数×2 种借库×近形开关共 24.8 万次判决 0 差（共识、借库、近形三通道都有命中）；scripts/code_equiv.py check，2026-11-06'),
    # kNN 每字限额（Sheldon 11-06，缺省关）
    Equiv(module='open_guji_cv.steps.glyph_match',
          new='977387eac7b8c04527f60688ec4a30f75bf41a0f030935bd6a250df161987ce7',
          old='fe823292dd35a88d6d8394f814c215819c784bb1d6fa87f905d12d88171edb32',
          evidence='kNN 每字限额 knn_per_char／knn_per_char_top（缺省 0 关，GlyphMatcher.per_char）：glyph_match 在测试样页 keben 3 页（--pages 1,2,3，库用殿本 glyph.db）与 origin/dev 产物逐字节相同；关着时匹配器只多一次属性判断，选 top 的代码路径与改前一字不差（seed_admit 等用 clustering.match 的步同理）；scripts/code_equiv.py check，2026-11-06'),
    Equiv(module='open_guji_cv.clustering.match',
          new='f686765a1e1905deba28398fefe7de4ca6083bd5e3a9525c09ffb82f25753afd',
          old='7fa5464da6ca4c45382394b0ecc847e8b8495c806609e2505da4ef9b0c762ab5',
          evidence='kNN 每字限额 knn_per_char／knn_per_char_top（缺省 0 关，GlyphMatcher.per_char）：glyph_match 在测试样页 keben 3 页（--pages 1,2,3，库用殿本 glyph.db）与 origin/dev 产物逐字节相同；关着时匹配器只多一次属性判断，选 top 的代码路径与改前一字不差（seed_admit 等用 clustering.match 的步同理）；scripts/code_equiv.py check，2026-11-06'),
    Equiv(module='open_guji_cv.steps.glyph_rules',
          new='8f1789da3ea7c9b45d005d34b2f3f4230f6cfc4b912e33de120dff6da7e7cc84',
          old='968766dcb15536599efeb17b95608c3864f82bce0bd6f89014ec01d2407d3ae9',
          evidence='kNN 每字限额 knn_per_char／knn_per_char_top（缺省 0 关，GlyphMatcher.per_char）：glyph_match 在测试样页 keben 3 页（--pages 1,2,3，库用殿本 glyph.db）与 origin/dev 产物逐字节相同；关着时匹配器只多一次属性判断，选 top 的代码路径与改前一字不差（seed_admit 等用 clustering.match 的步同理）；scripts/code_equiv.py check，2026-11-06'),
    # 共识升档退回原档（A23，全唐文 r15 回退，2026-11-07；第 7 轮）
    Equiv(module='open_guji_cv.steps.align_ref',
          new='61e396b487119919fc0c14e7455248f7e838c47ce314e4853efd17a952074f77',
          old='8bb8855702a074c168ac19776b22333f123521638792130b3e3df6c47a142715',
          evidence='坐标对位冲突闸 coord_consensus_not_same（缺省关、不进参数 dump；A23，史記 r18 09:183 空格位「○」共识 same 整列退回）：align_ref 在测试样页 keben 3 页（--pages 1,2,3）与 origin/dev 产物逐字节相同；关时 same 表与改前同值；scripts/code_equiv.py check，2026-11-07'),
    Equiv(module='open_guji_cv.steps.context_decide',
          new='05eac4afb853e7c3530c9103430ba0267286ff5d3b45fe3cf3b1d48f8114fe40',
          old='442732ff599c28b52a7dca9064ce776441c2f9b4dadf867d9863d380e6a43a1a',
          evidence='Step6 consensus_as_unsure（缺省关、不进参数 dump；A23，全唐文 r15 共识 same 被准入拦 46 格）：context_decide 在测试样页 keben 3 页（--pages 1,2,3）与 origin/dev 产物逐字节相同；关时 same 档判断与改前同值；scripts/code_equiv.py check，2026-11-07'),
    # column_warp 书级开关 ruled_warp（缺省关；A22，殿本 Commons 新图列首列尾切半根治，2026-11-08）
    Equiv(module='open_guji_cv.steps.column_warp',
          new='6452437a374cae7f29412d7b9926076bfb7cb1e814dfc7b461816fe3d19801b0',
          old='991a42b0a7af0825750f929e9892e1a397b56a224e709b858dbbec2716724c65',
          evidence='column_warp 在 vol49 3 页（--pages 13,93,187）上与 origin/dev 产物逐字节相同；殿本 vol49 新图（Commons r004），ruled_warp 关'),
    Equiv(module='open_guji_cv.seg.warp',
          new='91929f871aab2f5dd0410e136706f7d2590b8d636f4f0c70f280ea029a701df7',
          old='5e750f4a8781a7ca6ea8a6916d330d7a27719a91fafb4814aa2e62a8bc5af353',
          evidence='column_warp 在 vol49 3 页（--pages 13,93,187）上与 origin/dev 产物逐字节相同；殿本 vol49 新图（Commons r004），ruled_warp 关'),
    Equiv(module='open_guji_cv.books.siku_zongmu.column',
          new='deb342fb1677da3da4b7cb49d1f2075dc2dcd3963d55c5b3f208788a9bcba35f',
          old='57eac44b46c0ce8126d45774bcf309f6a628aec75259f3692568ff7456a8e54b',
          evidence='column_warp 在 vol49 3 页（--pages 13,93,187）上与 origin/dev 产物逐字节相同；殿本 vol49 新图（Commons r004），ruled_warp 关'),
    Equiv(module='open_guji_cv.steps.row_segment',
          new='5644f7941c144488e4ed901d2d0b8d86681234eed9776004fa0484facf3ceb4e',
          old='589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f',
          evidence='row_segment 在 vol49 3 页（--pages 13,93,187）上与 origin/dev 产物逐字节相同；殿本 vol49 新图（Commons r004），ruled_warp 关'),
    Equiv(module='open_guji_cv.steps.cell_shrink',
          new='418f2a32f1a4caa50c4894145d7082db211c8a4385674664105c27ca9ac6e3fc',
          old='94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e',
          evidence='cell_shrink 在 vol49 3 页（--pages 13,93,187）上与 origin/dev 产物逐字节相同；殿本 vol49 新图（Commons r004），ruled_warp 关'),
    # 下版框弱线护栏（A22，2026-11-08）
    Equiv(module='open_guji_cv.steps.border_detect',
          new='97c0f1758798397dd2dfd9de1b4862f4c34c579cf6845052072302843de35c90',
          old='301df64d7926568d93c17181bff46e358275c74967b8621a619a044ec6614916',
          evidence='border_detect.bottom_weak_ratio 下版框弱线护栏（缺省 0 关、不进参数 dump；A22，殿本第 7 轮 vol22 p147 下框落在末行字身）：border_detect 在殿本 vol22 新图 12 页（1,5,20,41,60,77,100,120,147,160,180,188）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08'),
    Equiv(module='open_guji_cv.books.siku_zongmu.border',
          new='68a672f759817954e81f4c58b1569bf273d9849b1ae4f8184f88829f5899b00b',
          old='fe76aa1fb0a0a0b7e0f5df19aa17fd3cf324fba29014a8be68d0fe8d559db51e',
          evidence='border_detect.bottom_weak_ratio 下版框弱线护栏（缺省 0 关、不进参数 dump；A22，殿本第 7 轮 vol22 p147 下框落在末行字身）：border_detect 在殿本 vol22 新图 12 页（1,5,20,41,60,77,100,120,147,160,180,188）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08'),
    Equiv(module='open_guji_cv.seg.lines',
          new='7df2015660f06eb33b49b0976d4c4cffe8ef7a7a5d21eb3554b250556747ee8e',
          old='61d0f2a36137eb909ae8b132e33936e25fcbee184d1eb284b30e258b04ce72d2',
          evidence='border_detect.bottom_weak_ratio 下版框弱线护栏（缺省 0 关、不进参数 dump；A22，殿本第 7 轮 vol22 p147 下框落在末行字身）：border_detect 在殿本 vol22 新图 12 页（1,5,20,41,60,77,100,120,147,160,180,188）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08'),
    # 书级弯页门槛 bend_w80_med（A20，殿本第7轮列端切半，2026-11-08）
    Equiv(module='open_guji_cv.steps.border_detect',
          new='cbf40755dde3946c384d85189fb76f9fd2c94b9e39e75cf2209c0b78669986dc',
          old='97c0f1758798397dd2dfd9de1b4862f4c34c579cf6845052072302843de35c90',
          evidence=_BEND_1108),
    Equiv(module='open_guji_cv.books.siku_zongmu.border',
          new='eeb02e8ae3ba45b5bb3ba4ed0e6baa0111c0bdf22834f84625724d20a5f356c0',
          old='68a672f759817954e81f4c58b1569bf273d9849b1ae4f8184f88829f5899b00b',
          evidence=_BEND_1108),
    Equiv(module='open_guji_cv.seg.polyline',
          new='8dba35b0510ff7bf1b5c35116184e86a7c38ba5cc06db31e9bd60e3d90039449',
          old='691460064488f81cc25e2a918c77227511a57806690eac36d82514771e1d8bcb',
          evidence=_BEND_1108),
    # 书名列候选 layout_title_fit（A22，殿本第 7 轮书名列，2026-11-08）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='bb5a2cd0b674d358c21a5b2bcf206f4bdfd46efb935fca69445da25d0b48dda4',
          old='589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f',
          evidence='row_segment.layout_title_fit 书名列候选（缺省关、不进参数 dump；A22，殿本第 7 轮 vol88 p129 c9）：row_segment 在殿本 vol88 新图 10 页（1,10,30,50,75,100,118,129,150,171,200）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08'),
    # 列尾内框线补拟 inner_frame_fit2、补抹 inner_frame_snap（A22，2026-11-08）
    Equiv(module='open_guji_cv.steps.cell_shrink',
          new='b1e47db6a8e6c7f19d5b4ec4e784979381803281317f99393ef2d9abf5842c0b',
          old='94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e',
          evidence=_FIT2_1108),
    Equiv(module='open_guji_cv.seg.frame_line',
          new='1873e0ae30c7a8ae4f34c27c038d2bdd0f1d341d56cfd40514834c7a1a37827c',
          old='0060b94fa6c5421484b9df42fcb7869728239c7fa98125d5c4ea4a691b2d7b5b',
          evidence=_FIT2_1108),
    # 下框越界护栏＋贴边重找倾角 bottom_lock_reslope（A22，vol01–19 换新图，2026-11-08）
    Equiv(module='open_guji_cv.steps.border_detect',
          new='92dcc6bde02debda8306a317cd9ec775d908e5c10c649f99e6b4c597738b72b3',
          old='301df64d7926568d93c17181bff46e358275c74967b8621a619a044ec6614916',
          evidence=_LOCK_1108),
    Equiv(module='open_guji_cv.books.siku_zongmu.border',
          new='99dc738ba0e5e56002d0721ae06aa1c6aca64a22792c89bb1afe366b1eb3c551',
          old='fe76aa1fb0a0a0b7e0f5df19aa17fd3cf324fba29014a8be68d0fe8d559db51e',
          evidence=_LOCK_1108),
    Equiv(module='open_guji_cv.seg.lines',
          new='0269f5426a22fbb8157931579019349b93476c5bc2d6e140ee9ca52f42d1de68',
          old='61d0f2a36137eb909ae8b132e33936e25fcbee184d1eb284b30e258b04ce72d2',
          evidence=_LOCK_1108),
    Equiv(module='open_guji_cv.books.siku_zongmu.row_boundaries',
          new='289dfdc83f992b9a2e1ff777b96a1862d7a886870492038363e17838db8b32d2',
          old='4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c',
          evidence='row_boundaries.trim_content_span 下框越出列图底时夹图内（原先 IndexError；A22，vol09 p204 column_gate 崩）：row_segment 在殿本 vol22 新图 12 页（1,5,20,41,60,77,100,120,147,160,180,188）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-08'),
    # 参校本属性 B 块（A22，2026-11-08）
    Equiv(module='open_guji_cv.steps.align_ref',
          new='ff1df0dc64abf24fe7f7c4e07bb9b30f4b8db2c4fcc9e6444dd07eaaf95d81b3',
          old='8bb8855702a074c168ac19776b22333f123521638792130b3e3df6c47a142715',
          evidence='参校本属性 B 块（reference_profile；none 页不对位、text 页不做坐标对位，未声明的册不变）：align_ref 在殿本 vol60 新图 12 页（1,2,3,10,20,30,45,60,75,90,105,120）、全唐文 006 12 页（每 20 页取 1）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-08（A22）'),
    Equiv(module='open_guji_cv.steps.row_segment',
          new='d63807f867b018129e984c563f5b7e2fcf297f1b445781938544bea102c99e5b',
          old='589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f',
          evidence='参校本属性 B 块（reference_profile，未声明的册不变；写了的册 layout_prior 缺表不拦、自动配页不配 none／text 页）：row_segment 在殿本 vol60 新图 12 页（1,2,3,10,20,30,45,60,75,90,105,120，自动配页 strict）、全唐文 006 12 页（每 20 页取 1）、001 8 页（35–64 text、65 起 none，带离线格位表）、002 4 页（整册 none）、003 7 页（1–102 none）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-08（A22）'),
    Equiv(module='open_guji_cv.steps.row_segment_pagemap',
          new='65ed80d08f58bd97393f955bc71e43a5f380eb735cb3f1a3df3a97232fddc6ef',
          old='3ef375f764f67717152ebd4e11b234ca338bbb02091dc6d07a3de50bfc52c9f0',
          evidence='参校本属性 B 块（reference_profile，未声明的册不变；写了的册 layout_prior 缺表不拦、自动配页不配 none／text 页）：row_segment 在殿本 vol60 新图 12 页（1,2,3,10,20,30,45,60,75,90,105,120，自动配页 strict）、全唐文 006 12 页（每 20 页取 1）、001 8 页（35–64 text、65 起 none，带离线格位表）、002 4 页（整册 none）、003 7 页（1–102 none）上与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-08（A22）'),
    Equiv(module='open_guji_cv.steps.border_detect',
          new='bc37fa6957f8756a106cc157857dc3a027c4a73f4d1f48e969629a4e6a358244',
          old='301df64d7926568d93c17181bff46e358275c74967b8621a619a044ec6614916',
          evidence=_TOPEDGE_1108),
    Equiv(module='open_guji_cv.books.siku_zongmu.border',
          new='3d424f82ee6c4fd460525e22d421399de9b38149755e3dae39c8ec2ec84a2bcb',
          old='fe76aa1fb0a0a0b7e0f5df19aa17fd3cf324fba29014a8be68d0fe8d559db51e',
          evidence=_TOPEDGE_1108),
    Equiv(module='open_guji_cv.seg.lines',
          new='51f174fa9b9f26d2df85848ec2a8042b69bf77b6c08ba470c05598efdfa86cf5',
          old='61d0f2a36137eb909ae8b132e33936e25fcbee184d1eb284b30e258b04ce72d2',
          evidence=_TOPEDGE_1108),
    Equiv(module='open_guji_cv.steps.border_detect',
          new='8d76b8f867f164aaa261d522f1d3f231c168d2d29186522f8556a5d411235f8e',
          old='301df64d7926568d93c17181bff46e358275c74967b8621a619a044ec6614916',
          evidence=_HINT_1109),
    Equiv(module='open_guji_cv.books.siku_zongmu.border',
          new='8b09db3368f2cddfa499f3e55e38aade131ed4dc2509148182d6ba6ceb80e606',
          old='fe76aa1fb0a0a0b7e0f5df19aa17fd3cf324fba29014a8be68d0fe8d559db51e',
          evidence=_HINT_1109),
    Equiv(module='open_guji_cv.seg.lines',
          new='97407131a39ae521fcb4777bbe2fbefd56a8e978e73a4acdd579e13992bf703d',
          old='61d0f2a36137eb909ae8b132e33936e25fcbee184d1eb284b30e258b04ce72d2',
          evidence=_HINT_1109),
    Equiv(module='open_guji_cv.steps.row_segment',
          new='788188c720a84f81fec062403eef27a1ad638701b3dc04812be935b55712b535',
          old='589c6cbc3f1d86b491a1bf47b972d139eaaeecc597ee1b327c14c236d23e9f3f',
          evidence=_ROSTER_LR_1108),
    Equiv(module='open_guji_cv.books.siku_zongmu.roster_segment',
          new='97a08fd32f28a643df087154a2fb506b3f286479217c7206f145782b4c15027d',
          old='894c946b329304625f8db915124b62a2308affe244fbb9b301506d43d008496f',
          evidence=_ROSTER_LR_1108),
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='fcdd74d43a28b827782dc9994e5d98b2f2bb8d4f3342d1414776cf33bd14f260',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 vol62 11 页（--pages 5,20,35,50,65,80,95,110,125,140,148）上与 origin/dev 产物逐字节相同（edge_pair_to 缺省 freq＝旧行为、不进 dump，版本号不升；A24 V01 定案 11-09，GUJI_CORPUS_DRIFT=warn）'),
    # solo_cal_allow／lead_5b 书级开关（缺省关，2026-11-09，形近字线 全唐文 001–003 front9）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='a79811a45e4cb8c7a9068d7f5df0e1b8af8b8d8711d196fead426184bd9eec4c',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在 001 3 页（--pages 76,100,150）上与 origin/dev 产物逐字节相同；solo_cal_allow／lead_5b 缺省关'),
    # textlayer_ref_gap 书级开关（缺省关，2026-11-09，R02 参校本没字第二见证，#1332）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='7fb78be931a21f6f71c24a7b69b3092cf110f52f2a395119ddfa74ab064be13c',
          old='4ebd6999371f4c921c34212cb4235e32e97bcc2b96d9ce24f06e72e952465ba6',
          evidence='seed_admit 在殿本 vol04 新图 38 页（--pages 每 6 页取 1，加 p17/p100/p186）上与 3576628（#1332 之前的 dev）产物逐字节相同；textlayer_ref_gap 缺省空＝关、参数不进 dump；用殿本新图包 cv0.6.29-c20-g21-r9c-v0629，scripts/code_equiv.py check，GUJI_CORPUS_DRIFT=warn，2026-11-09'),
    # snap_cut 书级参数（缺省关，2026-11-13，史記 r54 格线劈字，GUJI-771）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='5d36006bb348afaed6773ef61043835f719afc06b0b19e5a9121b90fb3dc79cd',
          old='c585153c706c21e3ddf6b131b0205098f50cb3a08be53f698d5b9e54f97e7a20',
          evidence=_SNAP_CUT),
    Equiv(module='open_guji_cv.impl.keben.row_boundaries',
          new='31b1191d837245092b635fde53c40a1b5d1ebda607fb6cc9901b566148660039',
          old='4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c',
          evidence=_SNAP_CUT),
    Equiv(module='open_guji_cv.seg.seam',
          new='f2ac3d9708392558a9d7db889cf02a4abd90d0b02f881d41b405bd05848ee654',
          old='2d3f4c680d5a1aabb68c5773ce6a2b67afe20ccbd9fe561b64c29131e1e0b671',
          evidence=_SNAP_CUT),
    # snap_cut 整字护栏（2026-11-13，防横点字劈开，snap_cut 关时不走）
    Equiv(module='open_guji_cv.impl.keben.row_boundaries',
          new='09b51e79e3fbfbcf1c77407a87a224c421c7c53eb0bab4855135be6b66423589',
          old='4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c',
          evidence=_GLYPH_GUARD),
    Equiv(module='open_guji_cv.seg.cut_select',
          new='a32630fc154efa51ff9e8f734b257fbe09a5c51729501b5de9679032be2be6f2',
          old='fad2da0e7322c7d0da354c2d1b246346060609fc616f53a33d4f46dfe5c4b13b',
          evidence=_GLYPH_GUARD),
    Equiv(module='open_guji_cv.seg.cut_select',
          new='1a505f0d68bdb696936b4f89af83ad7f99d82fbd92712bfe26a401a171b56713',
          old='fad2da0e7322c7d0da354c2d1b246346060609fc616f53a33d4f46dfe5c4b13b',
          evidence=_GUARD_TOL),
    # grid_end_fit 书级开关（缺省关，2026-11-09，殿本 vol28 列尾下溢）
    Equiv(module="open_guji_cv.steps.row_segment",
          new="6a3617931b93c706e43d43ccd2e1b9f5d63e1307343c424637cb0ecb77b32258",
          old="b8a5d95090c07068019d77e5a37b727c15c0be13f46fcb001fd14d60464c41b9",
          evidence=_GRID_END_FIT),
    Equiv(module="open_guji_cv.books.siku_zongmu.row_boundaries",
          new="8c31a0d7e3c8a4d224daccf2f32063af6c98a9dd0e47583d26a25fa01503061c",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence=_GRID_END_FIT),
    Equiv("open_guji_cv.gates.border_detect_gate",
          new="b6e8458642a906ee9b05b78b0e6d150b683cc7adead6137e06a0acf208999b68",
          old="803fcffb9dfc915e1ba80512694639857ebd6fb9c7ef6610f5143e4c30d800a8",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.gates.column_gate",
          new="222cf212e17eac8a7601aa7d1c51c880cb71356169c9b38df9f41d682eb2d3b0",
          old="bc4749f1f07753e004d84b5006ec4cfbdf1af23383c457f085475acc05063b22",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.impl.free.free_cells",
          new="27f2942643b95ad4da9d0d1630821a0deda75dc69e4480988b5c639097f2f916",
          old="761eaa8e09be2cb1c1736bf1aaf528a2c62e6e63aee8ffb001f32e0ca47559c6",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.impl.keben.border",
          new="8b09db3368f2cddfa499f3e55e38aade131ed4dc2509148182d6ba6ceb80e606",
          old="fe76aa1fb0a0a0b7e0f5df19aa17fd3cf324fba29014a8be68d0fe8d559db51e",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.impl.keben.column",
          new="deb342fb1677da3da4b7cb49d1f2075dc2dcd3963d55c5b3f208788a9bcba35f",
          old="57eac44b46c0ce8126d45774bcf309f6a628aec75259f3692568ff7456a8e54b",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.impl.keben.column_triage",
          new="73ff9002ed6ab67e0b617a0a459d68dbb69e18cea5c8d1d43cc9be3508f6a23d",
          old="9b98ee76d1a45032e014e3d385297dac192f3a07e2b0e0de7b96f226e716580b",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.impl.keben.row_boundaries",
          new="8c31a0d7e3c8a4d224daccf2f32063af6c98a9dd0e47583d26a25fa01503061c",
          old="4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.impl.modern.line_layout",
          new="3b932525eb96c42c3ac8323d3a316cb526f2f42e28ad01dd6fcbaa72870ee627",
          old="33f17f6be1f6f2f54345bc970f61c2772b41dc670bb602d006e478c1b6259d24",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.block_detect",
          new="a86611ff6377f6731adf8fa4c62536476ba6c24e327ac0dfea903790a7a644a8",
          old="c4e3f4c3ced328953f14599c97fbd171fb17bf8e755da4bf942168fc8f7802c2",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.border_detect",
          new="3b0deb2fc5e4c337fc75bab8dabbd314804b23002d763d8f337e1407f7e92318",
          old="301df64d7926568d93c17181bff46e358275c74967b8621a619a044ec6614916",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.cell_cut",
          new="a77e55914c45a35f40800976accf9329ab049aeea6a951d6c3cafd181331687d",
          old="ee41ec3a4b2ec3f7fb57fe0d5803cbc629524b68c428ad491450534cfa8e695a",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.column_crop",
          new="09e6c46b9b530b3a329476dc44d8580c0080569892bcf30e3c7b803d16fdf758",
          old="3dcc21da5a93afe0af339c2356c874ec591090fbc1930a1ee1e0af0f22c664e8",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.column_trace",
          new="086eeda1a547f2b57354bb23cc3d97efa09441688cf70781d25c5ed7d2a5564d",
          old="e18bbbe1054d2f13dd4b6547018046c544a68dd6a745bb9648942337384bc901",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.column_warp",
          new="d5c46a816760e0737924eb6fb0f11722b5a71b4d079dbf6e81e70ce4f89e772f",
          old="991a42b0a7af0825750f929e9892e1a397b56a224e709b858dbbec2716724c65",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.line_detect",
          new="ba2e5afb7d76a274f9b9b737fe2f5e3ed03c2fb5bba25a5ae22c3963812727ee",
          old="a90fc471a3e806a2b3655b663295bc66957e68d651e2a1372dbdbad195de2d1c",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.line_ocr",
          new="d2e4e5d2b8200bd5a1eedbeb99f997999923933b8423cd651c43c79bb900e16f",
          old="3c460388cd9a000f4195e41137f347ec9d553cd0a0857ffec73a7f5ac75afd85",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.row_segment",
          new="160eba594e84d23cf4ef1af93a906e6e011fdaeef95ca4634c1631cca3be171f",
          old="b8a5d95090c07068019d77e5a37b727c15c0be13f46fcb001fd14d60464c41b9",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.steps.row_segment_runs",
          new="47cde846ac5378eef452e9734fb179698ab7c960af78ac738dc1bbcbbca7cabd",
          old="2d6aa09866629ba270df420a4ad7ca0a15aae9b23730f3ca354fc74b54925da1",
          evidence=_MV_IMPL),
    Equiv("open_guji_cv.impl.keben.border",
          new="632040e47845843bc5f8afcab1d9fb6564d95b4bf7ffb68bbd2d37f191347a23",
          old="fe76aa1fb0a0a0b7e0f5df19aa17fd3cf324fba29014a8be68d0fe8d559db51e",
          evidence=_BX_1110),
    Equiv("open_guji_cv.steps.cell_shrink",
          new="cb1f88b8123e924d82cba4cc17a75c4560f43fad9eb3d8540c7418f87711adaa",
          old="94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e",
          evidence=_MF_1110),
    Equiv("open_guji_cv.steps.cell_shrink",
          new="54311ec727a64754a83015d384ae554080a65bbf46af05ee3653cbf3530e08fd",
          old="94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e",
          evidence=_MF_1111),
    # group_flow_pair_shape_nm_5b／solo_cal_5b_canon 书级开关（缺省关，2026-11-10，形近字线 全唐文 001–003 c38 第三层 王、愼吕）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='dedab8d15ba911f5663eefdd6832051b82d9c55ee41abb51bfa825462f023638',
          old='b8e8e0446898454c53e803ecb392fd4cd2fa9d6b5199a3b58894e98f03bd9873',
          evidence='seed_admit 在 001 2 页（--pages 76,100）上与 origin/dev 产物逐字节相同；group_flow_pair_shape_nm_5b／solo_cal_5b_canon 缺省关、不进 dump'),
    # consensus_lib_cov 书级开关（缺省关，2026-11-11，字形线 全唐文 f4 共识升档 same 库字放行）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='141fc62a87fd6382410b8292375de282add7000fedc256c03eab39e6fc8ad465',
          old='b8e8e0446898454c53e803ecb392fd4cd2fa9d6b5199a3b58894e98f03bd9873',
          evidence='seed_admit 在 016 3 页（--pages 141,103,80）上与 origin/dev 产物逐字节相同；全唐文 f4 包 016 共识升档待审页；consensus_lib_cov 缺省关、不进 dump'),
    Equiv("open_guji_cv.steps.row_segment",
          new="1c2b138a859640333b390aad62c037e99a2d4eaf968754e402d12b65aeddd8b2",
          old="5af1ee266342914c68f3ee53d59d6b778874cbf2d95c4190d6a6d3f67ed90733", evidence=_HOOKS_1110),
    Equiv("open_guji_cv.impl.keben.row_boundaries",
          new="8ff128e3e27f9a0b017c49a1ffdf38a750020858e4964b21d5c4653bbeb4dc8f",
          old="8c31a0d7e3c8a4d224daccf2f32063af6c98a9dd0e47583d26a25fa01503061c", evidence=_HOOKS_1110),
    Equiv("open_guji_cv.impl.keben.jiazhu_step",
          new="f49b7576cdb30ee9b456eeb1e2f80d5aae0a2bda2779aee1dffaf8668b4f9921",
          old="095bb58deee8dcb0f81c030c1f8037b39dd193000f95baa14205588939810c67", evidence=_HOOKS_1110),
    # glyph_match 加 sim_model 开关（CNN 逐对相似度，缺省关；A23，2026-11-10）
    Equiv("open_guji_cv.steps.glyph_match",
          new="15d5d1779c227b6b21a0640c43b8cd099e63b930410b2f5ea309133446c88309",
          old="fe823292dd35a88d6d8394f814c215819c784bb1d6fa87f905d12d88171edb32",
          evidence="glyph_match 加 sim_model 开关（缺省 None＝关，sim_model／sim_model_sha 不进参数 dump，匹配器不换精验）："
                   "测试样页 keben 3 页（--pages 1,2,3，库用全唐文 glyph.db）与 origin/dev 9c8d894 产物逐字节相同；"
                   "新模块 clustering.sim_cnn 不进 code_deps（开着时其代码哈希经 sim_model_sha 进参数指纹）；"
                   "scripts/code_equiv.py check，2026-11-10"),
    Equiv(module="open_guji_cv.steps.cell_shrink",
          new="0d920c95deb46011204479d86cd85122a98a463341fc45f8b989dae5afdbb5b6",
          old="94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e", evidence=_PCLEAN_1110),
    # align_ref 加 coord_circle_ext（缺省关；GUJI-767，史記圈号 ○ 对位，2026-11-12）
    Equiv(module='open_guji_cv.steps.align_ref',
          new='92f9e07ef18267c074789a9a74b012c45181301e3210b91096e9d9666f9eccaa',
          old='8bb8855702a074c168ac19776b22333f123521638792130b3e3df6c47a142715',
          evidence='align_ref 在史記 03/09/02 各 7 页（○列、夹注、职名杂页）上，两开关（coord_circle_ext、coord_relaxed 之外的新分支）关着，与 3d94f3a9 产物逐字节相同；SJ 11-12，scripts/code_equiv.py check'),
    Equiv(module='open_guji_cv.steps.align_ref_coord',
          new='d349110272246e70d060055b7589da62484a9ddd4a19f3bb4675fee6de44e42d',
          old='862f2f24da84debb2ce702f244115285de7de8d22adea085ec69b9fbdcba7e9f',
          evidence='同上'),
    # align_ref 加 coord_ref_hint（缺省关；GUJI-767 第二步，2026-11-12）
    Equiv(module='open_guji_cv.steps.align_ref',
          new='6afd38325a5f4060b74ddf7f8bfe1a316505479e420899a059fd648182cf4ad6',
          old='8bb8855702a074c168ac19776b22333f123521638792130b3e3df6c47a142715',
          evidence='align_ref 在 03/09/02 各 7 页（03: 99,103,117,122,208,2,40；09: 167,170,172,176,187,193,194；02: 88,90,165,166,168,171,204）上，coord_relaxed 开、coord_circle_ext／coord_ref_hint 关，与 origin/dev c16d142 产物逐字节相同；SJ 史記文淵閣 r42，scripts/code_equiv.py check，11-12'),
    Equiv(module='open_guji_cv.steps.border_detect',
          new='f5124151f3aa1576d4a166cd73e3a0752358f1a5f29219e866ffb209a4850e67',
          old='301df64d7926568d93c17181bff46e358275c74967b8621a619a044ec6614916',
          evidence='按页列数 expected_cols_pages（缺省空、不进参数 dump；殿本 vol01 p100 图上 10 列、版框探出 9 列，参校本质检）：border_detect 在殿本 vol01 9 页（--pages 1,22,45,48,88,100,105,130,150，含职名页 p100、p48/88/105）上与 origin/dev 62cc5009 产物逐字节相同；scripts/code_equiv.py check，2026-11-12（ZM-切分）'),
    Equiv(module='open_guji_cv.gates.border_detect_gate',
          new='2b85d40c19387689e50dbf66e94cd21adde6c854af262576fc2fb5599bcd931e',
          old='803fcffb9dfc915e1ba80512694639857ebd6fb9c7ef6610f5143e4c30d800a8',
          evidence='按页列数 expected_cols_pages（缺省空、不进参数 dump；殿本 vol01 p100 图上 10 列、版框探出 9 列，参校本质检）：border_detect 与 border_detect_gate 在殿本 vol01 9 页（--pages 1,22,45,48,88,100,105,130,150，含职名页 p100、p48/88/105）上与 origin/dev 62cc5009 产物逐字节相同；scripts/code_equiv.py check，2026-11-12（ZM-切分）'),
    Equiv(module='open_guji_cv.gates.column_gate',
          new='d572284813e4fded87ab399e69fd3c79edd7152c5d6ee95c29bcd1ef4c98ad82',
          old='bc4749f1f07753e004d84b5006ec4cfbdf1af23383c457f085475acc05063b22',
          evidence='按页列数 expected_cols_pages（缺省空、不进参数 dump；殿本 vol01 p100 图上 10 列、版框探出 9 列，参校本质检）：column_warp 与 column_gate 在殿本 vol01 9 页（--pages 1,22,45,48,88,100,105,130,150，含职名页 p100、p48/88/105）上与 origin/dev 62cc5009 产物逐字节相同；scripts/code_equiv.py check，2026-11-12（ZM-切分）'),
    # row_segment alt_cut：有字格全同（只差空格框、格号）不出备选，开了的书 dump 加 alt_cut_rev（SJ r43 09:194:5，2026-11-12）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='82e424e3e8231dc6b779254abfcb7a084d9ae876f4962f2583a777f05f1da392',
          old='5af1ee266342914c68f3ee53d59d6b778874cbf2d95c4190d6a6d3f67ed90733',
          evidence='alt_cut 关着时：row_segment 在殿本 vol28 新图 15 页（1,2,3,5,8,12,20,30,45,60,80,100,130,160,190，main 包）、'
                   '全唐文 001 13 页（1,3,10,20,35,40,50,64,65,80,100,140,190）上与 origin/dev ba636a6 产物逐字节相同；'
                   '开着的书（史記）参数 dump 多 alt_cut_rev，照常过期；scripts/code_equiv.py check，GUJI_CODE_DRIFT=warn（全唐文），2026-11-12（A22）'),
    # 2026-11-12 A22《切分三方向》第 4、5 步：人定切分统一读取入口 feedback/seg_overrides.SegOverrides（不进 code_deps）、
    # row_segment 书级钩子 row_hooks（缺省 None）。殿本 vol01 11 页（含 manual-cells 88/89/129/48/105）、
    # vol28 10 页（含 head-raise 14/19/28）产物与 origin/dev 逐字节相同
    Equiv("open_guji_cv.steps.row_segment",
          "009d4ce86488c14e378e8e56ccb0f90609ccf92b0bcd068aaaa7da894290cf1f",
          "5af1ee266342914c68f3ee53d59d6b778874cbf2d95c4190d6a6d3f67ed90733",
          "row_segment 在 vol01 11 页（2,20,48,60,88,89,100,105,129,150,180）、vol28 10 页（2,14,19,28,40,60,80,100,102,120）上与 origin/dev 3fd1180d 产物逐字节相同"),
    Equiv("open_guji_cv.impl.keben.row_boundaries",
          "588e6994117894060ff913b1c2fd76a0ff4bcce8806715de4eca0da14b27b0a1",
          "4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c",
          "同上（segment_column 加三个缺省 None 的钩子参数）"),
    # groups.registry 加 OPT_IN_GROUPS（zw 丈文，需点名才开；GUJI-767／#1413，2026-11-12）
    Equiv(module='open_guji_cv.groups.registry',
          new='c07ffe446c652c68fbb2cdc7590fa15a60ea54c839f089662db48ef0a4c0344b',
          old='a865a98d5e9c2d961ae6090971dc7790a8d3108ee67ae292e6406638ca3e3d27',
          evidence='seed_admit 在 03/09/02 各 7 页（03: 99,103,117,122,208,2,40；09: 167,170,172,176,187,193,194；02: 88,90,165,166,168,171,204）上，zw 未点名，与 v0.7.10 产物逐字节相同；SJ 史記文淵閣 r43，scripts/code_equiv.py check，11-12'),
    # groups.registry 加 OPT_IN_GROUPS 项 wu 嗚鳴（需点名才开；全唐文 QTW 经 Ops 转，2026-11-13，A31）
    Equiv(module='open_guji_cv.groups.registry',
          new='e7e536d72abc423a5cb9cae05d549f0dead8f2fb8f87a5a332094f562a96c340',
          old='c07ffe446c652c68fbb2cdc7590fa15a60ea54c839f089662db48ef0a4c0344b',
          evidence='按代码论证（同 zw／#1413）：新项只进 OPT_IN_GROUPS 与 FLOW_GROUPS，不进 GROUPS 与 generic_flow_names，没在册配置 group_flow 点名 wu 的书走的分支与旧版逐字相同，dump 不变；tests/test_group_flow.py::test_wu_is_opt_in 守；11-13'),
    # follow_ref 表项不再接管 follow_ref_variants 路径（cv#1438，史記 r45 嵗=歳；2026-11-12，A24）：
    # 开着 follow_ref＋按参校本取异体的书 dump 加 follow_ref_variants_rev，**这类书 seed_admit 一律过期**（不只表里那几对：表里的整理本形
    # 此后都会走 variants，带出此前不改的同义异体改字，史記 r47 实测 04/08/09 册 吳→呉 6 格，整书 11-12）；别的书走的分支与 v0.7.11 逐字相同，不过期
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='fb82c05c52f83d8ecec06a697a5fad987eee0c2e6df3991f25b508f2f12259c8',
          old='141fc62a87fd6382410b8292375de282add7000fedc256c03eab39e6fc8ad465',
          evidence='seed_admit 在殿本 vol01 12 页（5,22,48,61,75,87,100,119,135,150,170,190，含正文、职名、门目）上与 v0.7.11 产物逐字节相同（ZM，scripts/code_equiv.py check --base v0.7.11 --step seed_admit --always，11-12）；另按代码论证：新分支要求 vmap 非空（只在 _follow_variants() 时才传）且整理本形在 follow_ref 表里；'
                   '没开 follow_ref_variants、或表空的书走的分支与 v0.7.11 逐字相同，dump 不变（tests/test_seed_admit_follow_ref.py 守 dump）'),
    # v0.7.14（含 #1452 未登记）补登：vis_ruling_half 缺省关（A22 在史記 01 册 23 页验，11-12）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='019b9281f94f024b5325a4871f8c70c506a9ca308d5d4c1cd59ce36ad53f336c',
          old='b8e8e0446898454c53e803ecb392fd4cd2fa9d6b5199a3b58894e98f03bd9873',
          evidence='v0.7.14 seed_admit 在史記 01 册 23 页上与 v0.7.12 产物逐字节相同（A22，scripts/code_equiv.py check --base v0.7.12 --step seed_admit，11-12）；vis_ruling_half 缺省关、不进参数 dump'),
    # vis_ruling_half／solo_coord_dissent 书级开关（缺省关，cv#1452／#1456，2026-11-12，SJ 史記）：关时不进 dump、行为不变
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='60563a317cd208ccda0c8804d69f03d2e2b31b8c4936c9eb258ca0598f0e35f8',
          old='fb82c05c52f83d8ecec06a697a5fad987eee0c2e6df3991f25b508f2f12259c8',
          evidence='seed_admit 在史記 r49 包 03/04/05 共 9 页（03:46,84,96；04:26,35,39；05:21,27,75，含半格与 match_solo 放行多的页）上与 v0.7.13 产物逐字节相同（SJ，scripts/code_equiv.py check --base v0.7.13 --step seed_admit，rc/v0.7.15，11-12）；两开关缺省关、不进参数 dump'),
    # row_segment／pagemap：pins 档与夹注参照的语料指纹只看本册钉位点名的源文件（2026-11-12，史記 18–20 册要入 0244.jsonl）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='6dde638e3511de593834b9ca0a69e4142491c04bb405fe4e5a3a1ea6eb5ef57b',
          old='009d4ce86488c14e378e8e56ccb0f90609ccf92b0bcd068aaaa7da894290cf1f',
          evidence=_PINS_SRC_1112),
    Equiv(module='open_guji_cv.steps.row_segment_pagemap',
          new='a71017d111945b477cb9f65b464ea8e277b998a552688559ed7c96a182ef228a',
          old='65ed80d08f58bd97393f955bc71e43a5f380eb735cb3f1a3df3a97232fddc6ef',
          evidence=_PINS_SRC_1112),
    # align_ref coord_dp 加跳过扣分 coord_dp_skip_cost（缺省关；史記 r53，2026-11-13，A22）
    Equiv(module='open_guji_cv.steps.align_ref',
          new='f235b50d80d8f1037bf8b7cc27e02ec84cf1d76ee4db72fe0e423388a16de866',
          old='8bb8855702a074c168ac19776b22333f123521638792130b3e3df6c47a142715',
          evidence='align_ref 加 coord_dp_skip_cost（缺省 0 不进参数 dump；史記 r53 coord_dp 两次跳过换一处吻合致整理本字错一格）：开关关着时史記 37 册 25 页（--pages 1-20,110,127,153,170,194，coord_dp 开、含 dp 配列页）与 3f0d116 产物逐字节相同；另 33/35/37/41 四册全册 coord 逐格与 r53 包相同；scripts/code_equiv.py check，2026-11-13（A22）'),
    Equiv(module='open_guji_cv.steps.align_ref_coord',
          new='9de0c6ed3a822acee36610bb674b84f1f70d30a7cf2cdea97fc79a7921f682cd',
          old='862f2f24da84debb2ce702f244115285de7de8d22adea085ec69b9fbdcba7e9f',
          evidence='同上'),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="1f4878abc68b1f32e7d782706830e83af80fea3588e85b95bf0385fd8f828545",
          old="f235b50d80d8f1037bf8b7cc27e02ec84cf1d76ee4db72fe0e423388a16de866",
          evidence="align_ref 加缺省关的书级开关 coord_conflict_drop_bad（与现役对位冲突只丢冲突格，ZM 殿本 vol05 p1 列 4／p101／p177）：新增分支只在该开关开且列将因「与现役对位冲突」退回时可达，关时控制流与改前逐句相同（代码核对＋tests/test_align_ref_coord.py）；★未在有产物的机器上跑 scripts/code_equiv.py check，请持产物者（ZM）钉前补跑，不同则撤这条，2026-11-13"),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="06fe196f9b2a44cf4ab61d09dc8ace5ef4f13b80ed9ff69a0d6def2a5d983443",
          old="1f4878abc68b1f32e7d782706830e83af80fea3588e85b95bf0385fd8f828545",
          evidence="align_ref coord_conflict_drop_bad 加稀疏列例外（vol05 p1 列 4）：改动全在该开关开且列将因「与现役对位冲突」退回时才可达的 _drop_bad_recs 内，关时控制流与改前相同（代码核对＋tests/test_align_ref_coord.py）；★未在有产物的机器跑 scripts/code_equiv.py check（同上一条），2026-11-13"),
    # row_segment／pagemap：pins 档与夹注参照的语料指纹只看本册钉位点名的源文件（2026-11-12，史記 18–20 册要入 0244.jsonl）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='fb60a8eb7ebe1c84d7468f301d18e2b0f42b3da5fa2f78b9e22f6f5e6579cb93',
          old='1c2b138a859640333b390aad62c037e99a2d4eaf968754e402d12b65aeddd8b2',
          evidence=_PINS_SRC_1112),
    # stroke_veto 笔画反向护栏（缺省关，cv#1487，2026-11-13，全唐文形近字线）：空串时整段不执行、不进 dump
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='527fb5aa243ccb985f570622bbd8ee7a0f4b0b94f6872dc1fd103efb0db332f6',
          old='60563a317cd208ccda0c8804d69f03d2e2b31b8c4936c9eb258ca0598f0e35f8',
          evidence='按代码论证、未做逐页产物比对（本环境无书数据）：新增的唯一执行路径是 `if p.stroke_veto:` 调 _stroke_veto_pass，缺省空串不进；'
                   '模型字段在 stroke_veto 为空时 _drop_off_rare 把两个新键从 dump 去掉（tests/test_seed_admit_stroke_veto.py::test_params_not_in_dump_when_off 守 dump、'
                   'test_default_off 守关着时放行结果不变），path_params 只多一个空串项；其余改动是新函数定义。关着的书 seed_admit 参数指纹与行为同 v0.7.23。开着的书（全唐文）按参数指纹自然过期'),
    # v0.7.25（史記 patch 线）补记：snap_cut 在 patch 线上的哈希（dev 上不出现这两个哈希，只追加不改动 dev 已有的登记；
    # seg.seam 的 patch 线 new 与 dev 的 new 同值但 old 不同，不追加，免得覆盖 dev 的登记）
    Equiv(module='open_guji_cv.steps.row_segment',
          new='7fdda3460f73f1839cc1bcc84780ed73c04bad60b8b24d219154d723fc6c5ab3',
          old='7be4d500c747cca9e214e2272caf7b248231fc70f2c336f96ae048dd6b6e9a6c',
          evidence=_SNAP_CUT),
    Equiv(module='open_guji_cv.impl.keben.row_boundaries',
          new='a7f43f47126728c8e206bd016cbffdc8e692ea52e32cc74e42312fd602d8c04a',
          old='8ff128e3e27f9a0b017c49a1ffdf38a750020858e4964b21d5c4653bbeb4dc8f',
          evidence=_SNAP_CUT),
    # v0.7.26（史記 patch 线）补记：snap_cut 整字护栏在 patch 线上 row_boundaries 的哈希（dev 上不出现，只追加；
    # seg.cut_select 的 patch 线 new 与 dev 同值而 old 不同，不追加，免得覆盖 dev 的登记）
    Equiv(module='open_guji_cv.impl.keben.row_boundaries',
          new='5983f2059782aa6f4de8ea1c0197e2c892fd550eb324f994994c1aa1936613f9',
          old='a7f43f47126728c8e206bd016cbffdc8e692ea52e32cc74e42312fd602d8c04a',
          evidence=_GLYPH_GUARD),
    Equiv(module="open_guji_cv.steps.align_ref",
          new="cace3586ccc86342ae513b2a1365813db22dfe8fc6d8a2e8c285bc1e726d3397",
          old="06fe196f9b2a44cf4ab61d09dc8ace5ef4f13b80ed9ff69a0d6def2a5d983443",
          evidence="align_ref coord_conflict_drop_bad 丢掉的冲突格现役字改成坐标字（vol05 1:4:1）：新增 _use_coord_char 只在该开关开且 _drop_bad_recs 成功时调用，关时控制流与改前相同（代码核对＋tests/test_align_ref_coord.py）；★未在有产物的机器跑 scripts/code_equiv.py check，2026-11-13"),
    # seed_admit follow_ref 书级钩子 follow_ref_hooks.rival_skip（缺省 None 不调；史記同族第三形不当领先差对手，SJ／A24 11-13）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='052a744b74f64b6b45c62bd6f74b5ae38220fd8d39e5a70609609983999ee25b',
          old='527fb5aa243ccb985f570622bbd8ee7a0f4b0b94f6872dc1fd103efb0db332f6',
          evidence=_FR_HOOK_1113),
    # v0.7.32（史記 patch 线）补记：#1517 在 patch 线上 seed_admit 的哈希（dev 上不出现，只追加；本线没有 stroke_veto）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='a9b84a4bb6ec9eee6d095e4919b41ea83e3e8deb86e6ee7973b386783c8d0dad',
          old='60563a317cd208ccda0c8804d69f03d2e2b31b8c4936c9eb258ca0598f0e35f8',
          evidence=_FR_HOOK_1113),
    # seed_admit group_flow_ruling_first：本组文意先查裁定库（全唐文 11-13 己已巳按文意＋AI）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='2339553fdf1f82d708af22e6518d4043714f1ce97203d2402ad55993c22ecf17',
          old='b8e8e0446898454c53e803ecb392fd4cd2fa9d6b5199a3b58894e98f03bd9873',
          evidence=_RF_1113),
    Equiv(module='open_guji_cv.groups.flow',
          new='c41868e27e5b8fe996570de17d707fc473e3b8ae9af847546753849308c7510e',
          old='e5df695c08db5b368007b7cf69b7e3ee1dcf769fcd04028ad8253974d5a7b373',
          evidence=_RF_1113),
    Equiv(module='open_guji_cv.groups.methods',
          new='a8cdae9b8875b071d1fbdd04bb514f4be0d49ac7e3f44975ce1e6290e2755f88',
          old='45258af23d0898bfefb4957736316a953c3bdd334c3278a43aaa73fe97a5f861',
          evidence=_RF_1113),
    # #1526 补：_ruling_first 在线模式（GUJI_LLM_ONLINE=1）不生效（总览审 ①），同 020 f5 包 40 页逐字节相同
    Equiv(module='open_guji_cv.groups.methods',
          new='4e6551fe7cff11bdd0a1f831eaa35db99d48019b701f0c65b84ebadc736fb722',
          old='45258af23d0898bfefb4957736316a953c3bdd334c3278a43aaa73fe97a5f861',
          evidence=_RF_1113),
    # seed_admit group_flow_wu_shape：嗚鳴 书级刻形判法（全唐文 11-14）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='0708e0c321976a3fc3cef4a1eddf3b3ade36335ab0d6122dcae261effd9444c3',
          old='b8e8e0446898454c53e803ecb392fd4cd2fa9d6b5199a3b58894e98f03bd9873',
          evidence=_WU_1114),
    # seed_admit wu_shape 补放护栏：只认库字／库前 3 名是嗚鳴（全唐文 11-14）
    Equiv(module='open_guji_cv.steps.seed_admit',
          new='84e728f32f5c8ed37a5141f76b1e4cff34ba2878308c826b79573d8e515dca2b',
          old='b8e8e0446898454c53e803ecb392fd4cd2fa9d6b5199a3b58894e98f03bd9873',
          evidence=_WU_OOD_1114),
    # align_ref coord_legacy_line_guard 现役跨行借字不算冲突（缺省关；史記 r60 37:2:6–7 参校本缺「正義」，2026-11-13，A22）
    Equiv(module='open_guji_cv.steps.align_ref',
          new='9e787a1f39ed3f7827de1e79be7b5bb543ff844415f5566c562c3665f7cdbd58',
          old='8bb8855702a074c168ac19776b22333f123521638792130b3e3df6c47a142715',
          evidence='align_ref 加 coord_legacy_line_guard（缺省关不进参数 dump）：殿本 vol60 全册 126 页、史記 37 全册 231 页（coord_dp 等开着、开关关）'
                   '与 origin/dev 产物逐字节相同；scripts/code_equiv.py check，2026-11-13（A22）'),
    # v0.7.33（史記 patch 线）补记：align_ref 在 patch 线上的哈希（dev 上不出现，只追加；本线无 #1497）
    Equiv(module='open_guji_cv.steps.align_ref',
          new='a2bc661cbb0a0cf2fb4dd998b73a935facd04c2f9419fbfb089c363cc3616a5a',
          old='f235b50d80d8f1037bf8b7cc27e02ec84cf1d76ee4db72fe0e423388a16de866',
          evidence='align_ref 加 coord_legacy_line_guard（缺省关不进参数 dump），见上一条 #1523 的证据；哈希按 v0.7.32 线重算，本线未另跑产物比对'),
    # 开关收敛 L0 批：删没书开、关时不进 dump 的开关（A22 2026-11-14）
    Equiv(module='open_guji_cv.steps.border_detect',
          new='bf37cedacdcefcadc09c34a4689db33918acd3893272fe114e4fdea15148e2b6',
          old='301df64d7926568d93c17181bff46e358275c74967b8621a619a044ec6614916',
          evidence=_DROP_L0_1114),
    Equiv(module='open_guji_cv.gates.border_detect_gate',
          new='b36b70ceaad1c9bf19b1216e57d0c3ae3ffe8d67245200c12f4f206b6dca61b4',
          old='803fcffb9dfc915e1ba80512694639857ebd6fb9c7ef6610f5143e4c30d800a8',
          evidence=_DROP_L0_1114),
    Equiv(module='open_guji_cv.gates.column_gate',
          new='bd2821bed4e4e2b07cc5e08daec0fa219ca29ee84bc653dc5e40809c851b3c0d',
          old='bc4749f1f07753e004d84b5006ec4cfbdf1af23383c457f085475acc05063b22',
          evidence=_DROP_L0_1114),
    Equiv(module='open_guji_cv.steps.row_segment',
          new='419e5b9ed8d29be42ade1931a69531b367b49c161e9cf0ea658e72dc7c442d76',
          old='c585153c706c21e3ddf6b131b0205098f50cb3a08be53f698d5b9e54f97e7a20',
          evidence=_DROP_L0_1114),
    # row_hooks 加 jiazhu_pair_ok、jiazhu_heads 传 ruler（全唐文 k8 撤掉 row_boundaries／jiazhu_split 整文件 fork，2026-11-13）
    Equiv("open_guji_cv.steps.row_segment",
          "b6622dfd40c6989354bb5e5338b68bb929ff4c725e8899cc3efae826870244de",
          "419e5b9ed8d29be42ade1931a69531b367b49c161e9cf0ea658e72dc7c442d76", _QTW_HOOKS_1113),
    Equiv("open_guji_cv.impl.keben.row_boundaries",
          "5b0a8cc07abdcb7e35e49f691ea9433590aa8b6991e6d52bc2103f2551ba5006",
          "09b51e79e3fbfbcf1c77407a87a224c421c7c53eb0bab4855135be6b66423589", _QTW_HOOKS_1113),
    Equiv("open_guji_cv.impl.keben.row_hooks",
          "929638d4bf1a4b6a3c63ad18549fbcb7af06634c4de507fdcda427e5eebba743",
          "52ffeffbf71bc6b94a9789068b94fa5d25d5076700c2bfba730a9e1d2c6cf459", _QTW_HOOKS_1113),
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
    # 书级代码第 2 步：缺省实现改名（_MV_IMPL）
    "open_guji_cv.impl.free.free_blocks": ("open_guji_cv.books.zengguang_youxue.free_blocks", "eef4c4c127d5f5acb5f5b143a276d613f76fc2d78239be2cb298b5a5050e8d5f"),
    "open_guji_cv.impl.free.free_cells": ("open_guji_cv.books.zengguang_youxue.free_cells", "761eaa8e09be2cb1c1736bf1aaf528a2c62e6e63aee8ffb001f32e0ca47559c6"),
    "open_guji_cv.impl.free.free_columns": ("open_guji_cv.books.zengguang_youxue.free_columns", "277550471a0881db4e62e7192e6c6fb25f785fe545f9eb9912f447ab35a06a6f"),
    "open_guji_cv.impl.free.free_ocr": ("open_guji_cv.books.zengguang_youxue.free_ocr", "d913668cfa50b267394c24ae0193d1d9ae859d5510179f74e40499dd477ebf41"),
    "open_guji_cv.impl.free.free_rectify": ("open_guji_cv.books.zengguang_youxue.free_rectify", "9f39c373de06349d1d040ff488b152f36820f11c2b20e9b2a43a8563c7093ab0"),
    "open_guji_cv.impl.keben.border": ("open_guji_cv.books.siku_zongmu.border", "fe76aa1fb0a0a0b7e0f5df19aa17fd3cf324fba29014a8be68d0fe8d559db51e"),
    "open_guji_cv.impl.keben.column": ("open_guji_cv.books.siku_zongmu.column", "57eac44b46c0ce8126d45774bcf309f6a628aec75259f3692568ff7456a8e54b"),
    "open_guji_cv.impl.keben.column_pair_merge": ("open_guji_cv.books.siku_zongmu.column_pair_merge", "1b943e53a2d01db37949866b3b8f43c25f64e787096c6b0ce14a456441a7ecfd"),
    "open_guji_cv.impl.keben.column_triage": ("open_guji_cv.books.siku_zongmu.column_triage", "9b98ee76d1a45032e014e3d385297dac192f3a07e2b0e0de7b96f226e716580b"),
    "open_guji_cv.impl.keben.column_types": ("open_guji_cv.books.siku_zongmu.column_types", "85b6a36a684c2236c43f60a3826357e4785f17abbe2dcb4ad97dc4f7bfa6a41a"),
    "open_guji_cv.impl.keben.jiazhu_split": ("open_guji_cv.books.siku_zongmu.jiazhu_split", "e7c605b8247e14f4aae7c90c1e05be0a8b01cb32dbdbf2a9e6cb5e7086fcc82b"),
    "open_guji_cv.impl.keben.jiazhu_step": ("open_guji_cv.books.siku_zongmu.jiazhu_step", "095bb58deee8dcb0f81c030c1f8037b39dd193000f95baa14205588939810c67"),
    "open_guji_cv.impl.keben.pitch_rescue": ("open_guji_cv.books.siku_zongmu.pitch_rescue", "c007e49e89d7adc65bac5b96e4305f23e0c759b7d640b66122a92a1d84040fdc"),
    "open_guji_cv.impl.keben.roster_glyph": ("open_guji_cv.books.siku_zongmu.roster_glyph", "84f0636a76c93b4c74dbe25919b99100ae8dce8db18e7e41561db839d5f3ab68"),
    "open_guji_cv.impl.keben.roster_segment": ("open_guji_cv.books.siku_zongmu.roster_segment", "30963e0ad1fea0ae9ce4714a7d1aa397979da6d665b3e5fe383e0bd55fee95dc"),
    "open_guji_cv.impl.keben.row_boundaries": ("open_guji_cv.books.siku_zongmu.row_boundaries", "4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c"),
    "open_guji_cv.impl.keben.row_grid": ("open_guji_cv.books.siku_zongmu.row_grid", "283f1e2564615d55bf27c6f5638ee10d949c05d3953c74eb5398d6c2a38d2a0e"),
    "open_guji_cv.impl.keben.yolo_tool_infer": ("open_guji_cv.books.siku_zongmu.yolo_tool_infer", "33de2955e1c3eb8871f723c7929a8f62bd8baf37074777f20362918fdc33ba95"),
    "open_guji_cv.impl.modern.line_layout": ("open_guji_cv.books.beixing.line_layout", "33f17f6be1f6f2f54345bc970f61c2772b41dc670bb602d006e478c1b6259d24"),
    "open_guji_cv.impl.modern.run_segment": ("open_guji_cv.books.beixing.run_segment", "e770b30c24de8dfa927e615547d66e109b8f6a97ae6e6a0726bbdf66473a6a17"),
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
    # 不是拆分、是 seed_admit 新加了一个 code_dep（书级钩子 follow_ref_hooks，缺省 rival_skip=None；2026-11-13 A22）：
    # pua_v2_codes 与 follow_ref_hooks 都还是这一版时合回 pua_v2_codes 一项，指纹不变。书仓覆盖了钩子的书（史記）照常过期
    "open_guji_cv.utils.pua_v2_codes": ("909be2f3c3054883a2666af3e775e9baaa5a6e0f9ba73f3f04f99137dffde528", (
        ("open_guji_cv.utils.pua_v2_codes", "909be2f3c3054883a2666af3e775e9baaa5a6e0f9ba73f3f04f99137dffde528"),
        ("open_guji_cv.impl.keben.follow_ref_hooks", "67ffed25de9e2f114bfd57a4f490d1fa5a7e162d02b1a0174d92bc45543b4895"))),
    "open_guji_cv.utils.border_geometry": ("20c5f6fde41a30ad2e22200be0a97a793ceef3492e283b0fff92cb657bb896fb", (
        ("open_guji_cv.impl.keben.border", "f4989571d81cbb4d988c77cf5e4622dd57634df0ad8dbe31ee9ec432c563d0c1"),
        ("open_guji_cv.seg.polyline", "bf94b777e8bd227b12a64916ee3a2bf7bc457163047bdc9126a3f164e52825d4"),
        ("open_guji_cv.seg.frame_types", "910317f58be2061fbe06468ba3abf2de685e6250440b1008b8308fd37561fa4b"))),
    "open_guji_cv.utils.peak_line_search": ("90afd63cf2eec6ace053c4d470d1568c3c39582a532c99d2a929cec5bf016890", (
        ("open_guji_cv.seg.grid", "93f436b06ca22e975e211d5e194b5bc657cc6cdba0b6b3438bb6ba9c4e49780a"),
        ("open_guji_cv.seg.lines", "322ed871071601159e4123bfdb1b4b8ffb10c07cb0616c7783c003f0e88d8e61"))),
    "open_guji_cv.utils.column_projection": ("614cc9b0f4ffcb6f151c15c8bd56824df81d5e01edb4fb3bd8df3176e3c645ef", (
        ("open_guji_cv.seg.warp", "5e750f4a8781a7ca6ea8a6916d330d7a27719a91fafb4814aa2e62a8bc5af353"),
        ("open_guji_cv.seg.profile", "508270c9484b07c734e3c671f123093ecdd2405c0851340e5d0deb3437cd6609"),
        ("open_guji_cv.impl.keben.column", "4465ac6dfe85c0eaba56e06d75c260285f7fd5a02cef69cc5787ba8e0caae3dd"))),
    # 不是拆分、是 row_segment 新加了一个 code_dep（jiazhu_step 空实现）：两块都还是这一版时合回 row_segment 一项
    "open_guji_cv.steps.row_segment": ("427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28", (
        ("open_guji_cv.steps.row_segment", "427c437a8ce5a034b069c6b95f3cebffa496bbf42babffad1098d7a981301d28"),
        ("open_guji_cv.impl.keben.jiazhu_step", "095bb58deee8dcb0f81c030c1f8037b39dd193000f95baa14205588939810c67"))),
    # 不是拆分、是 glyph_match 新加了一个 code_dep（判决规则表 glyph_rules）：两块都还是这一版时合回 glyph_match 一项
    "open_guji_cv.steps.glyph_match": ("fe823292dd35a88d6d8394f814c215819c784bb1d6fa87f905d12d88171edb32", (
        ("open_guji_cv.steps.glyph_match", "fe823292dd35a88d6d8394f814c215819c784bb1d6fa87f905d12d88171edb32"),
        ("open_guji_cv.steps.glyph_rules", "968766dcb15536599efeb17b95608c3864f82bce0bd6f89014ec01d2407d3ae9"))),
    # 不是拆分、是补登记漏列的 code_dep（2026-11-06，manager test_code_deps_coverage 红）：align_ref 2.8 起 import
    # utils.han_ranges、seed_admit 1.37 起 import utils.pua_v2_codes，当时没列进 code_deps。代码早已在跑，现有产物
    # 就是这版算的，补登记不改行为：Step 模块与新加的块都还是这一版时合回原来一项，指纹不变；之后哪块真改了照常过期。
    "open_guji_cv.steps.align_ref": ("0daed94e68cea57b475ea01e5239cfdc2095bc5fab8a3acc3dbab09f2368995b", (
        ("open_guji_cv.steps.align_ref", "358cef6c7b2ab6251654ec64ed6d8a465c2ecc9060c8427a8957535b3025395d"),
        ("open_guji_cv.utils.han_ranges", "2feaa83bebcaffcb71ccdba148cc77183f402f45fbf1b116da4cddaff77aef8e"))),
    "open_guji_cv.steps.seed_admit": ("af762775452247be49c6f539663ecbf516a16ba29fb11f09d0fc7e11a5296fc1", (
        ("open_guji_cv.steps.seed_admit", "9fab395141161db5735b2e423fd924813f4a318a5bddd364992606fbd533bdeb"),
        ("open_guji_cv.utils.pua_v2_codes", "b19257019711a01c30b17a41303c24aac9e45b6f25718bae738e179545cd8d3f"))),
    # 不是拆分、是 row_segment 新加了两个 code_dep（书级钩子 row_hooks，缺省三个钩子都是 None；人定切分读取入口
    # seg_overrides，「哪些人定屏蔽格位表」的规则在它里头；2026-11-12 A22《切分三方向》第 4、5 步）：
    # 三块都还是这一版时合回 seal_ink 一项，再由下一项合回 jiazhu_step。
    # 必须排在下一项之前（_collapse_splits 按登记顺序合）
    "open_guji_cv.impl.keben.seal_ink": ("eb14ac23baa75eb2a4b7304f152687cdb0b3ecef596da6cacfaca988645fa418", (
        ("open_guji_cv.impl.keben.seal_ink", "eb14ac23baa75eb2a4b7304f152687cdb0b3ecef596da6cacfaca988645fa418"),
        ("open_guji_cv.impl.keben.row_hooks", "52ffeffbf71bc6b94a9789068b94fa5d25d5076700c2bfba730a9e1d2c6cf459"),
        ("open_guji_cv.feedback.seg_overrides", "81f5eb066e4d8fca8df69f95ef375ffb3196ccd30e850a35c099ee9648733fd0"))),
    # 同上，史記书仓覆盖了 seal_ink：书仓 seal_ink 与缺省 row_hooks 都还是这一版时合回书仓 seal_ink 一项
    "guji_book.shiji_wyg.seal_ink": ("ddfdec934a1f07f81a14ab0a0083a6aefc272d8055aff9942b30c23d9f826a25", (
        ("guji_book.shiji_wyg.seal_ink", "ddfdec934a1f07f81a14ab0a0083a6aefc272d8055aff9942b30c23d9f826a25"),
        ("open_guji_cv.impl.keben.row_hooks", "52ffeffbf71bc6b94a9789068b94fa5d25d5076700c2bfba730a9e1d2c6cf459"),
        ("open_guji_cv.feedback.seg_overrides", "81f5eb066e4d8fca8df69f95ef375ffb3196ccd30e850a35c099ee9648733fd0"))),
    # 不是拆分、是 row_segment 新加了一个 code_dep（书级钩子 seal_ink，缺省什么都不做；cv #1375 书级代码第 4 步）：
    # jiazhu_step 与 seal_ink 都还是这一版时合回 jiazhu_step 一项（键＝v0.6.39 时 jiazhu_step 进指纹的名字，搬家前的旧名）
    "open_guji_cv.books.siku_zongmu.jiazhu_step": ("095bb58deee8dcb0f81c030c1f8037b39dd193000f95baa14205588939810c67", (
        ("open_guji_cv.impl.keben.jiazhu_step", "095bb58deee8dcb0f81c030c1f8037b39dd193000f95baa14205588939810c67"),
        ("open_guji_cv.impl.keben.seal_ink", "eb14ac23baa75eb2a4b7304f152687cdb0b3ecef596da6cacfaca988645fa418"))),
    # 同上，史記书仓 k2（书级模块；书仓 code/equiv.yaml 只支持 moved／forked／entries，合项登在这里）：
    # 书仓 jiazhu_step（经书仓 entries 换回 k1 的 941e…）与新钩子 seal_ink 都还是 k2 这一版时，合回 k1 时进指纹的那一项
    "open_guji_cv.books.shiji_wyg.jiazhu_step": ("941e17d3b4de9157f37c8515f28ba8f3ae681c076bc97fb121d9c690bf5af0a0", (
        ("guji_book.shiji_wyg.jiazhu_step", "941e17d3b4de9157f37c8515f28ba8f3ae681c076bc97fb121d9c690bf5af0a0"),
        ("guji_book.shiji_wyg.seal_ink", "ddfdec934a1f07f81a14ab0a0083a6aefc272d8055aff9942b30c23d9f826a25"))),
    # 不是拆分、是 cell_shrink 新加了一个 code_dep（书级钩子 patch_clean「发前清格」，缺省不清；2026-11-10 SJ）：
    # 两块都还是这一版时合回 cell_shrink 一项。史記书仓覆盖了 patch_clean（k3 起）就照常过期，那是要的
    "open_guji_cv.steps.cell_shrink": ("94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e", (
        ("open_guji_cv.steps.cell_shrink", "94585c12504e404e802475389c541753e034d5f1d1e0538847ed8644de669d0e"),
        ("open_guji_cv.impl.keben.patch_clean", "44241a22b9f46de4a70feb68662ece757511aa86727cfe2b0034a1d8a56db16e"))),
    # 全唐文 k8（2026-11-13 切分线）：书仓 row_boundaries、jiazhu_split 两份整文件 fork（k6 那一版）撤掉，差异挂成书级钩子
    # guji_book.quantangwen.row_hooks。几块都还是登记时那一版时：cv row_boundaries＋书仓 row_hooks 合回 k6 书仓 row_boundaries
    # 一项，cv jiazhu_split＋seg_overrides 合回 k6 书仓 jiazhu_split 一项，全唐文各册 row_segment 指纹不变（054、115 全册逐字节相同）。
    # 书仓 row_hooks 只有全唐文有，第一项只在全唐文合；别的书 seg_overrides 已被上面 seal_ink 两项收走，第二项合不上。
    # 两项必须排在 seal_ink 两项之后。column_gate 的模块表只有 row_boundaries、没有书级模块，认不出是全唐文，
    # 全唐文 column_gate 指纹会变一次（产物不变，下游按上游产物 sha 不过期；115 全册 208 页 column_gate 逐字节相同）。
    "guji_book.quantangwen.row_boundaries": ("99682ac7af551c7f03ffc321bcfb5c8e94be249909d10f358d14527f067f43c3", (
        ("open_guji_cv.impl.keben.row_boundaries", "4098bb248ce17566b10e5530e65ca48410669d72bac56d6770b945c17420ee2c"),
        ("guji_book.quantangwen.row_hooks", "d903be4d92599f4e37c60203c4d30253b72c291f004fc094e30afc2aadcfe139"))),
    "guji_book.quantangwen.jiazhu_split": ("a0bdb376848116f288d3f912c64b98d6c834ded95b28d297e5fae5ca588f26a0", (
        ("open_guji_cv.impl.keben.jiazhu_split", "e7c605b8247e14f4aae7c90c1e05be0a8b01cb32dbdbf2a9e6cb5e7086fcc82b"),
        ("open_guji_cv.feedback.seg_overrides", "81f5eb066e4d8fca8df69f95ef375ffb3196ccd30e850a35c099ee9648733fd0"))),
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


def book_tables() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """(MOVED, FORKED) 并上当前工作区书仓 `code/equiv.yaml` 的登记（`core/book_code.py`，2026-11-09）。
    书仓里登记的只许是本书模块（`guji_book.<name>.…`）的键，不能改写 cv 模块的等价。"""
    from .book_code import load
    bc = load()
    if bc is None or not (bc.moved or bc.forked):
        return MOVED, FORKED
    pre = bc.pkg + "."
    mv = {**MOVED, **{k: v for k, v in bc.moved.items() if k.startswith(pre)}}
    fk = {**FORKED, **{k: v for k, v in bc.forked.items() if k.startswith(pre)}}
    return mv, fk

