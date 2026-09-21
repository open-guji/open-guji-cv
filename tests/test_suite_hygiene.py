# -*- coding: utf-8 -*-
"""测试套件自身的护栏：**测试只依赖本仓库，且只依赖 `tests/` 下冻结的数据。**

口径与来由见 `tests/conftest.py` 的模块头。这一条守的是「别再长回去」——
2026-09-20 那轮清理之前，37 个测试文件、94 条用例挂在三种活数据上
（隔壁测试集仓 / 某本书的工作区 / 引擎仓里跟着跑批变的目录），
数据一变就红，数据不在就静默 skip。清完不设闸的话，下一个人照着旧文件
抄一遍，半年又回到原样。

这里查三件事，都只看**代码**，不看注释和 docstring——解释「为什么当初删掉了
某个依赖」的散文里当然会出现 `open-guji-dataset` 这种词，那不是依赖。

1. 代码里不许出现仓外路径与某台机器特有的绝对路径；
2. 不许从仓根拼进会跟着跑批变的目录（`output/` `products/` `cache/`
   `corpus/` `data/`）；
3. `tests/` 下名字像测试的文件必须真的有用例——「0 tests collected」
   比失败更危险，它看着像有测试守着。
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
#: 本文件自己在讲这些词，扫的时候跳过。
SELF = Path(__file__).name

#: 仓外 / 机器特有的路径片段。出现在代码里就是把测试绑死在某台机器上。
FORBIDDEN_PATHS = {
    "open-guji-dataset": "测试集仓在仓外。要金标就在测试里自己造，或用 tests/fixtures/",
    "siku-zongmu": "某本书的工作区在仓外",
    "data_full": "原图在工作区，不在这个仓",
    "D:/workspace": "某台 Windows 机器的绝对路径",
    "D:\\workspace": "某台 Windows 机器的绝对路径",
    "/usr/share/fonts": "系统字体因机器而异；仓里自带 fonts/，用 _font_files()",
    "/home/": "某台机器的 home 目录",
}

#: 仓根下会跟着跑批变的目录。测试从这些地方读东西，就等于依赖了活数据。
VOLATILE_DIRS = ("output", "products", "cache", "corpus", "data", "runs",
                 "reports", "review", "precleaned")

#: 「仓根 / 会变的目录」这种拼法。
_ROOT_NAMES = {"REPO", "REPO_ROOT", "ROOT", "_project_root", "PROJECT_ROOT"}

#: 明文放行的例外。**只放行 `-m manual` 才会跑的人工验收工具**，并写清理由；
#: 自动化用例一条都不许进这张表——要放行就说明它不该是自动化测试。
ALLOWED_VOLATILE = {
    "test_console_routes.py": (
        "控制台路由快照是 `manual` 的人工验收工具（默认不跑）。它调的是真路由，"
        "其中两条会往仓内 `output/` 写东西（`review_rate_history.jsonl` 台账、"
        "`glyph.db` 空库），所以它**跑完要把这两处还原**——那两行正是还原代码，"
        "不是在读生产数据。根治要让那两条路由的落点也认环境变量，属另一件事。"),
}


def _label(path: Path) -> str:
    """报错里用相对 `tests/` 的路径；扫临时文件（守卫自检）时退回文件名。"""
    try:
        return str(path.relative_to(TESTS))
    except ValueError:
        return path.name


def _test_files() -> list[Path]:
    return sorted(p for p in TESTS.rglob("*.py")
                  if p.name != SELF and "__pycache__" not in p.parts)


def _code_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """代码里的字符串字面量，**不含 docstring、不含 assert 里的**。

    `assert "open-guji-dataset" not in str(store.root)` 这种是在**断言某个路径
    不是它**——正是我们要的护栏，不能反过来被自己拦掉。
    """
    docstrings = set()
    in_assert = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    in_assert.add(id(sub))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings and id(node) not in in_assert):
            out.append((node.lineno, node.value))
    return out


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """去掉注释与整行 docstring 之后的代码行。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                d = body[0].value
                doc_lines.update(range(d.lineno, (d.end_lineno or d.lineno) + 1))

    comment_lines: dict[int, int] = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            comment_lines.setdefault(tok.start[0], tok.start[1])

    out = []
    for i, line in enumerate(src.splitlines(), start=1):
        if i in doc_lines:
            continue
        if i in comment_lines:
            line = line[:comment_lines[i]]
        if line.strip():
            out.append((i, line))
    return out


def scan_outside_paths(path: Path) -> list[str]:
    """这个文件里，代码（不含注释 / docstring / assert）引用了哪些仓外路径。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for lineno, value in _code_strings(tree):
        for frag, why in FORBIDDEN_PATHS.items():
            if frag in value:
                bad.append(f"{_label(path)}:{lineno} 出现 {frag!r}——{why}")
    return bad


def test_no_paths_outside_this_repo():
    """代码里不许出现仓外路径与机器特有的绝对路径。

    只看代码：注释与 docstring 里提这些词是在讲来龙去脉；`assert "…" not in p`
    这种是**在断言某个路径不是它**，正是我们要的护栏，不能被自己拦掉。
    """
    bad = [m for f in _test_files() for m in scan_outside_paths(f)]
    assert not bad, "\n".join(bad)


def scan_volatile_reads(path: Path) -> list[str]:
    """这个文件里，代码从仓根拼进了哪些会跟着跑批变的目录。"""
    if path.name in ALLOWED_VOLATILE:
        return []
    pat = re.compile(
        r"(?:%s)\s*/\s*[\"'](%s)\b" % ("|".join(_ROOT_NAMES), "|".join(VOLATILE_DIRS)))
    bad = []
    rel = _label(path)
    for lineno, line in _code_lines(path):
        if line.lstrip().startswith("assert ") or " == " in line:
            continue            # 断言某个默认路径**应该**解析成什么，不是去读它
        m = pat.search(line)
        if m:
            bad.append(f"{rel}:{lineno} 从仓根拼进 {m.group(1)}/：{line.strip()}")
        # `Path(__file__)….parent.parent.parent` = 爬出仓外，一律不许
        if ".parent.parent.parent" in line:
            bad.append(f"{rel}:{lineno} 路径爬出了仓外：{line.strip()}")
    return bad


def test_no_reads_from_volatile_repo_dirs():
    """不许从仓根拼进会跟着跑批变的目录。

    `output/` `products/` `cache/` `corpus/` `data/` 里装的是跑批结果与生产
    样本，跑一次批就变。测试要数据就自己造，或用 `tests/fixtures/` 里冻结的。
    """
    bad = [m for f in _test_files() for m in scan_volatile_reads(f)]
    assert not bad, "\n".join(bad)


def test_every_test_file_actually_has_tests():
    """`tests/` 下名字像测试的文件必须真的有用例。

    「0 tests collected」比失败危险：它在报告里看不见，却让人以为有测试守着。
    2026-09-20 实例：`tests/recognize-profile/test_recognize_profile.py` 是个带
    `argparse` 的脚本，一条 pytest 用例都没有，在 `tests/` 下待了很久。
    """
    empty = []
    for path in _test_files():
        if not path.name.startswith("test_"):
            continue            # conftest / helpers 这类辅助模块不算
        tree = ast.parse(path.read_text(encoding="utf-8"))
        has = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name.startswith("test_")
                  for n in ast.walk(tree))
        if not has:
            empty.append(str(path.relative_to(TESTS)))
    assert not empty, (
        f"这些文件叫 test_*.py 却没有用例：{empty}。"
        "它要是个脚本，就放到 scripts/ 去；要是个辅助模块，改个不以 test_ 开头的名字。")


def test_fixtures_are_committed_and_small():
    """冻结数据要小到能一直待在仓里。

    真页三张 ≈400 KB。哪天有人往这儿塞几十 MB，说明那份数据该待在工作区
    或测试集仓，不该进测试目录。
    """
    fixtures = TESTS / "fixtures"
    assert fixtures.is_dir(), "tests/fixtures/ 不见了"
    total = sum(p.stat().st_size for p in fixtures.rglob("*") if p.is_file())
    assert total < 8 * 1024 * 1024, (
        f"tests/fixtures/ 已经 {total / 1024 / 1024:.1f} MB。"
        "冻结数据该是「够用的最小样本」，大了就说明放错地方了。")
    assert (fixtures / "README.md").exists(), "fixtures 要有 README 说明它是什么、能不能改"


# ── 守卫自检 ─────────────────────────────────────────────────────────
#
# 一条永远绿的护栏等于没有护栏。下面两条把「坏文件」摆在临时目录里喂给扫描
# 函数，确认它确实报得出来——顺带也钉住「散文里提到不算违规」这半边。


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "test_sample.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_guard_catches_an_outside_path(tmp_path):
    bad = _write(tmp_path, 'DATASET = "../open-guji-dataset/rare-char/items.jsonl"\n')
    assert scan_outside_paths(bad), "仓外路径没被拦住，这条护栏是假的"


def test_guard_ignores_prose_and_negative_assertions(tmp_path):
    ok = _write(tmp_path, (
        '"""当年这里读 ../open-guji-dataset，见 2026-09-20 那轮清理。"""\n'
        '# 注释里提 data_full 也不算\n'
        'def test_x(store):\n'
        '    assert "open-guji-dataset" not in str(store.root)\n'))
    assert not scan_outside_paths(ok), "散文与反向断言被误判成依赖了"


def test_guard_catches_a_volatile_repo_read(tmp_path):
    bad = _write(tmp_path, (
        'from pathlib import Path\n'
        'REPO = Path(__file__).resolve().parent.parent\n'
        'def test_x():\n'
        '    db = REPO / "output" / "glyph.db"\n'
        '    assert db\n'))
    assert scan_volatile_reads(bad), "读仓内生产目录没被拦住，这条护栏是假的"
