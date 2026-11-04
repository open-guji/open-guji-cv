"""本书用字账（`variant_ledger`）按书选（2026-11-03，配置分层清理第 5 条）。

用字账是「这本书常刻哪个异体」的先验，只能是**本书**的。账本文件在 cv 仓 `config/variants/books/<键>.json`，
现在只有殿本一份（`wuyingdian_zongmu`）。`SeedAdmitParams.edition` 的缺省值也是它——此前不管哪本书都读殿本的账，
史記、全唐文等书的自动放行与形的取舍也拿殿本的惯刻形、殿本的人裁转换对当先验。

现在：`edition` 还是缺省值时，`core/step.py::_with_book_ledger` 按这册的书换键——

- 书 ID 取生效册配置的 `book_id`，没写就取中心库工作区名（`.central.json` 的 `ws`）；
- 殿本（书 ID `96mid1ogzk`，工作区 `siku-zongmu`）照旧 `wuyingdian_zongmu`；
- 别的书键＝书 ID，账本目录里没有 `<书 ID>.json` 就是空账（所有查询答「不知道」）；以后给这本书建账，起名 `<书 ID>.json` 就自动接上；
- 两样都取不到（没迁中心库、也没写 book_id，如测试夹具）照旧用缺省值，行为不变。

册配置 `params.seed_admit.edition` 显式写了别的键的照写的来。本模块不在任何 Step 的 `code_deps` 里。
"""
from __future__ import annotations

#: 用这份殿本账的书（书 ID 与中心库工作区名都认）
ZONGMU_KEYS = frozenset({"96mid1ogzk", "siku-zongmu"})
ZONGMU_EDITION = "wuyingdian_zongmu"


def book_key(vol: str) -> str | None:
    """册 → 书 ID（生效册配置的 `book_id`，没有则中心库工作区名）；都取不到 → None。"""
    try:
        from .volume_id import volume_of
        bid = volume_of(vol).book_id
    except Exception:            # noqa: BLE001 —— 没工作区、yaml 坏了：当取不到
        bid = None
    if bid:
        return str(bid)
    try:
        from .workspace import central_marker
        m = central_marker() or {}
    except Exception:            # noqa: BLE001
        m = {}
    return str(m["ws"]) if m.get("ws") else None


def edition_for(vol: str, default: str = ZONGMU_EDITION) -> str:
    """这册该读的用字账键。殿本、认不出书的 → `default`；别的书 → 书 ID。"""
    key = book_key(vol)
    if key is None or key in ZONGMU_KEYS:
        return default
    return key
