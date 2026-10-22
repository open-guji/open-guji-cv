"""GUJI_DATA_TOKEN 缺省退回 GUJI_DATA_TOKEN_READ（open_guji_cv/__init__.py）。"""
import os
import subprocess
import sys


def _token_after_import(env: dict) -> str:
    base = {k: v for k, v in os.environ.items() if not k.startswith("GUJI_DATA_TOKEN")}
    base.update(env)
    out = subprocess.run([sys.executable, "-c", "import os, open_guji_cv; print(os.environ.get('GUJI_DATA_TOKEN', ''))"],
                         env=base, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_falls_back_to_read_token():
    assert _token_after_import({"GUJI_DATA_TOKEN_READ": "r"}) == "r"


def test_explicit_token_wins():
    assert _token_after_import({"GUJI_DATA_TOKEN_READ": "r", "GUJI_DATA_TOKEN": "p"}) == "p"


def test_nothing_set_stays_unset():
    assert _token_after_import({}) == ""
