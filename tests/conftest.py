# -*- coding: utf-8 -*-
"""测试的共享地基：**测试只依赖本仓库，且只依赖 `tests/` 下冻结的数据。**

## 为什么有这份文件（2026-09-20 用户定的口径）

这之前的测试大面积依赖三种仓外/仓内的**活数据**：

1. 隔壁的测试集仓 `../open-guji-dataset`（金标分片、rare-char 集）；
2. 某本书的工作区 `GUJI_WORKSPACE`（原图 `data_full/`、产物 `products/`、
   派生缓存 `cache/`、字形库 `output/glyph.db`）；
3. 引擎仓里会跟着跑批变的生产目录（`output/`、`corpus/`、`data/`）。

后果有两种，都很坏：
- **数据一变测试就红**——它们断言的是「当下这批产物长什么样」，不是代码行为；
- **数据不在就整条 skip**——云端一跑 94 条静默跳过，看着全绿，其实什么都没测。

所以现在的规矩是：

- **单元测试自己造数据**。产物都是 pydantic 模型，直接 `构造()` 就行，
  不要去扫 `products/` 看碰巧有什么。
- **要真图像的集成测试用 `tests/fixtures/` 里冻结的样本**（从 `data/` 复制过来的
  三张真页），**长期不动**；改 fixture 等于改所有用它的测试的输入。
- **任何测试都不读工作区、不读测试集仓、不读仓内生产目录**。
  `tests/test_suite_hygiene.py` 是这条的守卫，会扫源码拦回去。

## 这份 conftest 提供什么

`_isolated_env`（autouse）把每条测试的起点钉死：清掉所有 `GUJI_*` 环境变量，
并把 `core.workspace` 的「仓内默认根」改指到本条测试的 tmp 目录——于是**忘了用
fixture 的测试会落到空目录，而不是悄悄读到本机跑批的真产物**。这正是老测试
在开发机上绿、在云端红（或反过来）的根源。

`ws` 给一个隔离的工作区（fixture 册配置 + 冻结原图 + 小语料，可写），
`keben_book` / `fixture_page` / `gold_root` 是它上面的常用便利层。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

#: 让子目录里的测试也能 `from helpers import ...`。pytest 只会把**测试文件自己
#: 所在的目录**塞进 sys.path（tests/clustering 那批拿不到 tests/），根 conftest
#: 最先被导入，在这儿补上。
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: `tests/fixtures/` —— 冻结的测试数据。**只读**：测试要写就先 copy 到 tmp。
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_WS = FIXTURES / "workspace"

#: 会改变路径解析的全部环境变量。autouse fixture 逐条清掉，保证「本机设了什么」
#: 不影响测试结果——2026-09-17 那次「本地绿、云端红」就是 `GUJI_WORKSPACE`
#: 只写在本机 `~/.bashrc` 里造成的。
GUJI_ENV_VARS = (
    "GUJI_WORKSPACE", "GUJI_GLYPH_DB", "GUJI_GLYPH_STORE", "GUJI_PRODUCTS_DIR",
    "GUJI_CACHE_DIR", "GUJI_BATCHES_DIR", "GUJI_EXCLUSIONS", "GUJI_FEEDBACK_DIR",
    "GUJI_VERDICTS_DIR", "GUJI_REPORTS_DIR", "GUJI_RAW_ROOT", "GUJI_REPO_ROOT",
    "GUJI_ALLOW_SAMPLE_DB", "GUJI_FONT_DIR", "GUJI_DATASET",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """每条测试都从「没有工作区、仓内默认根是空的」开始。

    第二件事比第一件要紧：`core.workspace` 在没有工作区时会退回 `REPO_ROOT/...`
    （`output/glyph.db`、`products/`、`cache/`…）。那些目录在开发机上装着真跑批
    的结果，测试读到就等于依赖了活数据，还会**往仓库里写**。这里把 `REPO_ROOT`
    指到本条测试专属的空目录，读得到的只有自己放进去的东西。
    """
    from open_guji_cv.core import workspace as W

    for k in GUJI_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    fake_repo = tmp_path / "_repo_default"
    fake_repo.mkdir(exist_ok=True)
    monkeypatch.setattr(W, "REPO_ROOT", fake_repo)
    # 工作区覆盖是 contextvar，跨测试不会自动还原（上一条测试抛在中途就留下了）。
    monkeypatch.setattr(W, "_WORKSPACE_OVERRIDE", type(W._WORKSPACE_OVERRIDE)(
        "guji_workspace", default=None))
    return fake_repo


def _copy_fixture_workspace(dst: Path) -> Path:
    """把 `tests/fixtures/workspace` 摆成一个可写的工作区。

    册配置与语料是小文本，直接复制；原图几百 KB 且只读，优先做符号链接，
    链接不了（Windows 无权限）再复制——两种情况下布局完全一样。
    """
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("books", "corpus"):
        shutil.copytree(FIXTURE_WS / name, dst / name)
    raw_src, raw_dst = FIXTURE_WS / "raw", dst / "raw"
    try:
        raw_dst.symlink_to(raw_src, target_is_directory=True)
    except (OSError, NotImplementedError):
        shutil.copytree(raw_src, raw_dst)
    return dst


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Path:
    """一个隔离的工作区：fixture 册配置 + 冻结原图 + 小语料，产物/缓存从空开始。

    `GUJI_WORKSPACE` 指向它，所以 `load_book` / `products_root` / `cache_root`
    这些全都落在 tmp 里，跑完即弃。
    """
    root = _copy_fixture_workspace(tmp_path / "ws")
    monkeypatch.setenv("GUJI_WORKSPACE", str(root))
    return root


@pytest.fixture
def keben_book(ws):
    """fixture 册「keben」：八列二十一字的刻本半页，配着三张真页。"""
    from open_guji_cv.core.book import load_book

    return load_book("keben")


@pytest.fixture
def fixture_page_path() -> Path:
    """冻结样页 1 的路径（**只读**，别往这儿写）。"""
    return FIXTURE_WS / "raw" / "keben" / "1.png"


@pytest.fixture
def fixture_page(fixture_page_path) -> "object":
    """冻结样页 1 的灰度图（真扫描件，带双层版框与界行）。"""
    import cv2

    img = cv2.imread(str(fixture_page_path), cv2.IMREAD_GRAYSCALE)
    assert img is not None, f"读不到冻结样页：{fixture_page_path}"
    return img


@pytest.fixture
def gold_root(tmp_path) -> Path:
    """空的金标根——要哪个分片就在测试里自己写进去（`gold_shard` 便利函数）。"""
    root = tmp_path / "gold"
    root.mkdir()
    return root


def write_gold_shard(root: Path, shard: str, items: list[dict]) -> Path:
    """往金标根里写一个分片，返回分片目录。测试自备金标一律走这里。"""
    import json

    d = root / shard
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "items.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    return d


@pytest.fixture
def repo_root() -> Path:
    """引擎仓真根——只给「扫自己的源码」这类测试用（守卫测试、打包检查），
    **不要**拿它去读 `output/` / `products/` / `data/` 这些会变的目录。"""
    return Path(__file__).resolve().parent.parent


#: 仓内那些**跑批会动**的目录。测试往里写东西 = 污染工作副本，读它 = 依赖活数据。
#: `corpus/` 之所以在列，是因为 `context_decide` 会在 `corpus/external/` 下落一份
#: 22 MB 的 LM 缓存——2026-09-20 实测，一条全链用例因此从 5 秒变成跑不完，
#: 而且 `git status` 看不见（那个缓存在 .gitignore 里）。
VOLATILE_REPO_DIRS = ("output", "products", "cache", "corpus", "runs", "reports",
                      "review", "precleaned", "glyph_store")

_REPO = Path(__file__).resolve().parent.parent


def _volatile_snapshot() -> dict[str, tuple[int, float]]:
    """仓内易变目录的 {路径: (大小, mtime)}。只扫这几个目录，几毫秒。"""
    snap: dict[str, tuple[int, float]] = {}
    for name in VOLATILE_REPO_DIRS:
        d = _REPO / name
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file():
                try:
                    st = p.stat()
                except OSError:
                    continue
                snap[str(p)] = (st.st_size, st.st_mtime)
    return snap


@pytest.fixture(scope="session", autouse=True)
def _no_writes_into_the_repo():
    """跑完之后仓内那几个易变目录必须**逐字节没动过**。

    `_isolated_env` 已经把 `core.workspace` 的默认根挪到 tmp，但那拦不住**绕过
    workspace 的路径**——`ContextDecideParams.general_corpus_dir` 缺省是
    `"corpus/external"`，按 cwd 解析，于是一条全链用例在仓里写下 22 MB 缓存，
    `.gitignore` 还把它藏了起来。静态扫源码看不出这种（路径来自生产默认值，
    不在测试代码里），所以这里在运行期兜一道。

    ⚠️ 只报**新增/改动**，不报删除：有的用例会清自己造的临时文件。
    """
    before = _volatile_snapshot()
    yield
    after = _volatile_snapshot()
    added = sorted(set(after) - set(before))
    changed = sorted(k for k in set(after) & set(before) if after[k] != before[k])
    bad = [f"新增 {p}" for p in added[:10]] + [f"改动 {p}" for p in changed[:10]]
    assert not bad, (
        "测试往仓内易变目录写了东西——那既污染工作副本，也说明它在依赖活数据：\n"
        + "\n".join(bad)
        + f"\n（共新增 {len(added)} / 改动 {len(changed)}）")
