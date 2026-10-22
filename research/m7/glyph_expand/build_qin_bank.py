"""禽會俞命舍：产物池 → `config/groups/qin/ids_bank.json`。

用法：python build_qin_bank.py <pool/qin.json（`pool.py` 产出，旁有 .d 字块目录）> [仓根]
标签：seed_admit 放行字（无疑问；禽不要求无疑问，含 不进库）＋看图预填（`eval_qin.OVERRIDE`）。每类最多 `CAP` 个。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_qin import labels  # noqa: E402

from open_guji_cv.groups import ids_online as O, ids_whole  # noqa: E402

if __name__ == "__main__":
    pool = json.load(open(sys.argv[1]))
    repo = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[3]
    cells = labels(pool, Path(sys.argv[1]).with_suffix(".d"))
    sp = O.SPECS["qin"]
    d = ids_whole.build("qin", cells, sp.size, {"labels": "殿本 vol04–10 seed_admit 放行字（禽：witness3 放行＋看图预填，待确认），每类 ≤60"})
    O.write_bank(d, repo / "config" / "groups" / "qin" / "ids_bank.json")
    print({k: len(v) for k, v in d["templates"].items()}, (repo / "config/groups/qin/ids_bank.json").stat().st_size)
