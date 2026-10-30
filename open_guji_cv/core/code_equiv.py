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
)


#: 搬过家的模块：新模块名 → (搬家前的模块名, 搬家前的代码哈希)。指纹里模块名也进哈希，所以搬家要换回旧名字。
#: 只在「现在的代码（经 ENTRIES 换算后）仍等于搬家前那一版」时生效（见 engine._fingerprint_name）；之后真改了就按新名字，
#: 照常判过期。搬家时只有 import 路径变的模块，在 ENTRIES 里另登 new→old 哈希。登记纪律同 ENTRIES：只增不删。
#: 切分模块化（2026-10-30，Sheldon 定）：代码搬进 books/<套书>/。
MOVED: dict[str, tuple[str, str]] = {
    "open_guji_cv.books.zengguang_youxue.free_blocks": ("open_guji_cv.utils.free_blocks", "eef4c4c127d5f5acb5f5b143a276d613f76fc2d78239be2cb298b5a5050e8d5f"),
    "open_guji_cv.books.zengguang_youxue.free_columns": ("open_guji_cv.utils.free_columns", "277550471a0881db4e62e7192e6c6fb25f785fe545f9eb9912f447ab35a06a6f"),
    "open_guji_cv.books.zengguang_youxue.free_cells": ("open_guji_cv.utils.free_cells", "761eaa8e09be2cb1c1736bf1aaf528a2c62e6e63aee8ffb001f32e0ca47559c6"),
    "open_guji_cv.books.zengguang_youxue.free_rectify": ("open_guji_cv.utils.free_rectify", "9f39c373de06349d1d040ff488b152f36820f11c2b20e9b2a43a8563c7093ab0"),
    "open_guji_cv.books.zengguang_youxue.free_ocr": ("open_guji_cv.utils.free_ocr", "d913668cfa50b267394c24ae0193d1d9ae859d5510179f74e40499dd477ebf41"),
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
