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


#: 拆过的模块：旧模块名 → (拆分前的代码哈希, [(拆出来的新模块, 拆分时的代码哈希), …])。
#: 一个模块拆成几块，Step 的模块表从一项变几项，指纹公式就变了；这里登记了，算指纹时几块都在、代码都还是
#: 拆分时那一版，就合回一项（旧名＋旧哈希，见 engine._collapse_splits），产物不过期。之后任何一块真改了就不合并，
#: 照常过期。用到旧模块的 Step 要在 code_deps 里列齐全部几块。纪律同 ENTRIES：只增不删；拆出来的块又拆或又搬时，
#: 把那一项的块表换成最新的几块（旧哈希不动，块表里的旧块已不存在，留着也合不上）。
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
