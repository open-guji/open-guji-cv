#!/usr/bin/env python3
"""快照导入（容忍行尾）：包里 `_manifest.jsonl` 的 sha256 若是按 Windows CRLF 算的，
git 里存的是 LF，`guji snap import` 会判校验不过。本脚本对 `_manifest.jsonl` 同时认 LF 与 CRLF 两种形态，
其余文件仍严格校验。用法同 `guji snap import`（参数原样透传）。

这是临时垫片：cv 的 pack/import 统一行尾后就不需要了（见 overview#425）。
"""
import hashlib
import sys
from pathlib import Path

import open_guji_cv.snap.importer as imp

_orig = imp.sha256_file


def _both(p):
    data = Path(p).read_bytes()
    lf = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(lf).hexdigest(), hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest()


class _Hex(str):
    """与 LF 或 CRLF 任一形态的哈希相等。"""
    def __new__(cls, lf, crlf):
        o = str.__new__(cls, lf)
        o.alt = crlf
        return o

    def __eq__(self, other):
        return str.__eq__(self, other) or other == self.alt

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = str.__hash__


def _patched(p):
    if Path(p).name == "_manifest.jsonl":
        return _Hex(*_both(p))
    return _orig(p)


imp.sha256_file = _patched

from open_guji_cv.cli_v2 import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["snap", "import", *sys.argv[1:]]))
