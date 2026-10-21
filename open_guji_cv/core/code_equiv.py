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
)


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
