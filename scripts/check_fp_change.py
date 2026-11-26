"""发版／合并前查「哪几步的代码指纹变了」，变了却没写明就挡（GM2 2026-11-24，v0.7.83、v0.7.99 两次 patch 线漏登 code_equiv 之后加）。

    # 两个版本之间哪几步的规范指纹（`core/engine.code_hash`，已按 code_equiv 登记换算）变了
    python scripts/check_fp_change.py --base v0.7.97 --head v0.7.99

    # CI 用：变了的步要在说明里有书面放行，否则退出码 1
    python scripts/check_fp_change.py --base <rev> --head <rev> --note-file <tag 说明或 PR 正文>

指纹变了＝用这个版本的册从那一步起产物判过期、不能与旧版本产物混批。两种正当情形：
1. 真改了算法，就该重算 → 在 tag 说明／PR 正文里写一行放行（见 `ALLOW`），如「指纹变更：seed_admit 起过期，随统一重跑」；
2. 产物逐字节不变（提速、加缺省关的开关）→ 用 `scripts/code_equiv.py check` 证明后登记进 `core/code_equiv.py`，指纹就不变，本检查自然过。
本检查只挡第三种：既没登记、也没写明——不知不觉让各书过期或误混批。

做法：两个 rev 各 `git worktree add` 一份，子进程（`PYTHONPATH` 指向那份检出）导入全部 Step、算 `code_hash`，逐步比。
套书覆盖（`seg_set.replace_deps`）与书仓 `guji_book.*` 不在这里算（与册有关），只比 cv 本体。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 书面放行：说明里出现这些就认（写在哪一行都行）。ZM 11-24：「随统一重跑」之类的说明即可放行。
ALLOW = re.compile(r"指纹变更|指纹变了|起过期|统一重跑|不登记\s*code_equiv|fp-change-ok", re.I)

_DUMP = r"""
import json, sys
import open_guji_cv.steps  # noqa: F401  注册全部 Step
from open_guji_cv.core.step import STEPS
from open_guji_cv.core.engine import code_hash
out = {}
for sid, st in STEPS.items():
    try:
        out[sid] = code_hash(st)
    except Exception as e:  # noqa: BLE001
        out[sid] = f"error:{type(e).__name__}:{e}"
sys.stdout.write("\n@@FP@@" + json.dumps(out, ensure_ascii=False))
"""


def step_hashes(rev: str) -> dict[str, str]:
    """`rev` 这份代码里各步的规范指纹。"""
    with tempfile.TemporaryDirectory(prefix="fpchk-") as tmp:
        wt = Path(tmp) / "wt"
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", "-q", str(wt), rev], check=True)
        try:
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(wt), *filter(None, [os.environ.get("PYTHONPATH")])]),
                       PYTHONIOENCODING="utf-8")
            r = subprocess.run([sys.executable, "-c", _DUMP], cwd=str(wt), env=env, capture_output=True, text=True)
            if "@@FP@@" not in r.stdout:
                raise SystemExit(f"✗ 算 {rev} 的指纹失败：\n{r.stderr[-3000:]}")
            return json.loads(r.stdout.rsplit("@@FP@@", 1)[1])
        finally:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(wt)], check=False)


def diff(base: dict[str, str], head: dict[str, str]) -> list[tuple[str, str | None, str | None]]:
    """(步, 旧指纹, 新指纹)：变了的、新加的、删掉的；按 head 的步序。"""
    order = list(head) + [s for s in base if s not in head]
    return [(s, base.get(s), head.get(s)) for s in order if base.get(s) != head.get(s)]


def tag_base(tag: str) -> str | None:
    """patch 线 tag 的比较基线：tag 说明里第一个别的 vX.Y.Z（惯例写「v0.7.97＋…」）；没写就取最近的祖先 tag。
    各书 patch 线合 main 用 -s ours，最近祖先 tag 常是别的线的，所以先认说明。"""
    msg = tag_message(tag)
    for v in re.findall(r"v\d+\.\d+\.\d+(?:-rc\.\d+)?", msg):
        if v != tag and _rev_ok(v):
            return v
    r = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--abbrev=0", "--match", "v*", f"{tag}^"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def tag_message(tag: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "tag", "-l", "--format=%(contents)", tag], capture_output=True, text=True)
    return r.stdout


def _rev_ok(rev: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", f"{rev}^{{commit}}"],
                          capture_output=True).returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="比较基线 rev；给了 --tag 可省（取 tag 说明里的基线版本）")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--tag", help="查这个 tag：head＝tag，说明＝tag 说明")
    ap.add_argument("--note-file", help="书面放行说明（PR 正文等）；与 --tag 的说明合并看")
    a = ap.parse_args(argv)
    note = ""
    if a.tag:
        a.head = a.tag
        note += tag_message(a.tag)
        a.base = a.base or tag_base(a.tag)
    if a.note_file:
        note += "\n" + Path(a.note_file).read_text(encoding="utf-8")
    if not a.base:
        print("✗ 找不到比较基线（--base）", file=sys.stderr)
        return 2
    changed = diff(step_hashes(a.base), step_hashes(a.head))
    print(f"指纹比较 {a.base} → {a.head}：{len(changed)} 步变了")
    for s, o, n in changed:
        print(f"  {s:<24}{o or '（无）'} → {n or '（无）'}")
    if not changed:
        return 0
    if ALLOW.search(note):
        print("✓ 说明里有书面放行（指纹变更已知悉），不挡")
        return 0
    print("\n✗ 上面这些步的指纹变了（用这一版的册从那一步起过期、不能与基线产物混批），但没登记 code_equiv、说明里也没写明。\n"
          "  二选一：产物逐字节不变 → scripts/code_equiv.py check 证明后登记进 open_guji_cv/core/code_equiv.py；\n"
          "  真改了算法 → 在 tag 说明／PR 正文写一行「指纹变更：<步> 起过期（随统一重跑／原因）」。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
