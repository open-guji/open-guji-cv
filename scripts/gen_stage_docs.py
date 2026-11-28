"""从代码生成四大步的「步骤、产物、参数」速查（doc/<N>-<大步>/步骤与产物.md）。

这几页只写事实（schema），全部从注册表取：步骤的输入输出、闸、代码依赖、参数缺省值，产物的存法与字段。
改了 Step 或产物定义后重跑一次；`--check` 只比对不写，测试 `tests/test_stage_docs.py` 用它守着文档不过时。

    python scripts/gen_stage_docs.py          # 重写四页
    python scripts/gen_stage_docs.py --check  # 有出入就退出码 1
"""
from __future__ import annotations

import argparse
import ast
import inspect
import re
import sys
import textwrap
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import open_guji_cv.steps  # noqa: E402,F401  —— 触发 Step 注册
from open_guji_cv.core.pipeline import list_pipelines, load_pipeline  # noqa: E402
from open_guji_cv.core.step import KINDS, STEPS  # noqa: E402
from pydantic import BaseModel  # noqa: E402

STAGES = [  # (大步 id, 目录名, 中文名)
    ("layout", "1-版面", "版面"),
    ("cut", "2-切字", "切字"),
    ("read", "3-识字", "识字"),
    ("decide", "4-定字", "定字"),
]


def _t(ann) -> str:
    s = getattr(ann, "__name__", None) if not typing.get_args(ann) else None
    s = s or str(ann).replace("typing.", "")
    return s.replace("|", "｜")


def _default(f) -> str:
    if f.default_factory is not None:
        try:
            v = f.default_factory()
        except TypeError:
            return "（工厂）"
    else:
        v = f.default
    if isinstance(v, str) and v.startswith(str(ROOT)):   # 仓内路径缺省值：去掉本机前缀，各机生成一致
        v = "<cv仓>/" + Path(v).relative_to(ROOT).as_posix()
    r = repr(v)
    return (r[:60] + "…") if len(r) > 60 else r


def _first_sentence(s: str, limit: int = 80) -> str:
    s = " ".join(s.split())
    m = re.search(r"[。；;]", s)
    if m:
        s = s[:m.start() + 1]
    return (s[:limit] + "…") if len(s) > limit else s


def _field_docs(cls) -> dict[str, str]:
    """字段说明：`Field(description=)`，否则字段后紧跟的字符串（属性 docstring），否则同一行的 `#` 注释；取第一句。
    取不到源码（动态类）就空着。"""
    out: dict[str, str] = {}
    for c in reversed([k for k in getattr(cls, "__mro__", (cls,)) if k.__module__ != "pydantic.main" and k is not object]):
        try:
            src = textwrap.dedent(inspect.getsource(c))
        except (OSError, TypeError):
            continue
        lines = src.splitlines()
        try:
            body = ast.parse(src).body[0].body
        except (SyntaxError, IndexError, AttributeError):
            continue
        for i, node in enumerate(body):
            if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
                continue
            nxt = body[i + 1] if i + 1 < len(body) else None
            doc = ""
            if isinstance(nxt, ast.Expr) and isinstance(getattr(nxt, "value", None), ast.Constant) \
                    and isinstance(nxt.value.value, str):
                doc = nxt.value.value
            else:
                m = re.search(r"#:?\s*(.+)$", lines[node.end_lineno - 1])
                if m and "noqa" not in m.group(1):
                    doc = m.group(1)
            if doc:
                out[node.target.id] = _first_sentence(doc)
    for name, f in getattr(cls, "model_fields", {}).items():
        if f.description:
            out[name] = _first_sentence(f.description)
    return out


def _submodels(ann) -> list:
    out, stack = [], [ann]
    while stack:
        a = stack.pop()
        if isinstance(a, type) and issubclass(a, BaseModel):
            out.append(a)
        stack.extend(typing.get_args(a))
    return out


def _cell(s: str) -> str:
    return s.replace("|", "｜").replace("\n", " ")


def _chains_by_step() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for pid in list_pipelines():
        for sid in load_pipeline(pid).steps:
            out.setdefault(sid, []).append(pid.split("@")[-1])     # 2026-11-28 三链合一：列版式 grid／free／print
    return out


def _stage_steps() -> dict[str, list[str]]:
    """各大步的步骤（默认链三个版式合起来，按第一次出现的顺序去重）。"""
    out: dict[str, list[str]] = {st: [] for st, *_ in STAGES}
    for pid in list_pipelines():
        for st, sids in load_pipeline(pid).stages.items():
            for sid in sids:
                if sid not in out[st]:
                    out[st].append(sid)
    return out


def render(stage: str, title: str, n: int, steps: list[str], chains: dict[str, list[str]]) -> str:
    L = [f"# {n} {title}：步骤、产物与参数",
         "",
         "> 由 `scripts/gen_stage_docs.py` 从代码生成，**不要手改**；改了 Step 或产物定义后重跑。"
         f"命令里写大步名 `{stage}`：`guji-cv pipeline <管线> <册> --from {stage} --to {stage}`。",
         "",
         "| 步骤 id | 名称 | 单位 | 版本 | 用在哪些版式 | 出口闸 |",
         "|---|---|---|---|---|---|"]
    for sid in steps:
        sp = STEPS[sid].spec
        L.append(f"| `{sid}` | {_cell(sp.title)} | {sp.unit} | {sp.version} | "
                 f"{'、'.join(chains.get(sid, []))} | {f'`{sp.gate.id}`' if sp.gate else '—'} |")
    kinds: list[str] = []
    for sid in steps:
        sp = STEPS[sid].spec
        L += ["", f"## `{sid}` {_cell(sp.title)}", ""]
        L.append(f"- 输入：{'、'.join(f'`{k}`' for k in sp.consumes) or '—'}"
                 + (f"；可选 {'、'.join(f'`{k}`' for k in sp.optional_consumes)}" if sp.optional_consumes else ""))
        L.append(f"- 产出：{'、'.join(f'`{k}`' for k in sp.produces) or '—'}")
        if sp.gate:
            L.append(f"- 出口闸 `{sp.gate.id}`（{sp.gate.unit}，不过时 {sp.gate.on_fail}）：")
            for lv in sp.gate.levels:
                L.append(f"  - {lv.id} `{lv.name}`：{_cell(lv.desc)}")
        if sp.book_deps:
            L.append(f"- 进指纹的册配置：{'、'.join(f'`{d}`' for d in sp.book_deps)}")
        if sp.code_deps:
            L.append(f"- 进指纹的代码：{'、'.join(f'`{d}`' for d in sp.code_deps)}")
        fields = sp.params.model_fields
        if fields:
            docs = _field_docs(sp.params)
            L += ["", "| 参数 | 类型 | 缺省 | 说明（代码注释第一句） |", "|---|---|---|---|"]
            for name, f in fields.items():
                L.append(f"| `{name}` | {_cell(_t(f.annotation))} | `{_cell(_default(f))}` | {_cell(docs.get(name, ''))} |")
        kinds += [k for k in sp.produces if k not in kinds]
        if sp.gate:
            kinds += [k for k in getattr(sp.gate, "produces", ()) if k not in kinds]
    L += ["", "## 产物", "", "| 产物 | 名称 | 存法 | 单位 | 坐标 | 字段（顶层） |", "|---|---|---|---|---|---|"]
    for k in kinds:
        ks = KINDS.get(k)
        if ks is None:
            continue
        cols = "、".join(f"`{f}`" for f in (ks.schema.model_fields if ks.schema else {})) or f"图像 .{ks.ext}"
        L.append(f"| `{k}` | {_cell(ks.title)} | {ks.storage} | {ks.unit} | {ks.coord_space or '—'} | {cols} |")
    for k in kinds:
        ks = KINDS.get(k)
        if ks is None or not ks.schema or not ks.schema.model_fields:
            continue
        todo, seen = [(f"`{k}`", ks.schema)], set()
        while todo:          # 顶层与嵌套的子模型（列、格…）都列出来：验收标准 S3 要求写到格级
            label, cls = todo.pop(0)
            if cls in seen:
                continue
            seen.add(cls)
            docs = _field_docs(cls)
            L += ["", f"### {label} 字段", "", "| 字段 | 类型 | 说明（代码注释第一句；空＝待补，见验收标准 S3） |",
                  "|---|---|---|"]
            for name, f in cls.model_fields.items():
                L.append(f"| `{name}` | {_cell(_t(f.annotation).replace(cls.__module__ + '.', ''))} | {_cell(docs.get(name, ''))} |")
                for sub in _submodels(f.annotation):
                    if sub not in seen:
                        todo.append((f"{label} › `{sub.__name__}`", sub))
    rows = [l for l in L if l.startswith("| `")]
    par = [l for l in rows if l.count("|") == 5]          # 参数行四列
    fld = [l for l in rows if l.count("|") == 4]          # 产物字段行三列
    blank = lambda xs: sum(1 for l in xs if l.rstrip().endswith("|  |"))
    L.insert(4, f"> 说明覆盖：参数 {len(par) - blank(par)}／{len(par)}，产物字段 {len(fld) - blank(fld)}／{len(fld)}"
                "（说明取代码里字段后的 docstring 或行尾注释第一句；补注释后重跑本脚本，验收标准 S3）。")
    L.insert(5, "")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    chains, stage_steps = _chains_by_step(), _stage_steps()
    bad = []
    for n, (stage, d, title) in enumerate(STAGES, 1):
        path = ROOT / "doc" / d / "步骤与产物.md"
        text = render(stage, title, n, stage_steps[stage], chains)
        if a.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                bad.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"→ {path.relative_to(ROOT)}")
    if bad:
        print("这几页和代码对不上，跑 python scripts/gen_stage_docs.py 重写：\n  " + "\n  ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
