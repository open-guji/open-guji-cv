# -*- coding: utf-8 -*-
"""验一件事：页面重发自己这件事是**定点**。

    python check_fixedpoint.py review.html

自存靠的是页面读自己的 `#css`/`#js` 重建一份完整文档再发上去。如果重建出来的
文档跟原文档不等价，那每存一次页面就漂一点——第一次可能只是少个换行，第三次
就可能把 `</script>` 提前截断，人裁到一半页面自己散了。所以：真在浏览器里跑一遍，
点一个裁决，让它重建（v2），把 v2 装回浏览器再重建一次（v3），**要求 v3 与 v2
逐字节相同**，并且 v2 里确实嵌上了刚才那个裁决。

这个检查抓到过真 bug。改了 `renderIndex()`、改了 `render()` 的拼装顺序、往
`#data` 里加字段之后，都跑一遍再发布。
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def _chromium() -> dict:
    """pip 装的 playwright 版本常和机器上预装的浏览器版本对不上；对不上就
    直接指路，别去下浏览器（很多环境根本不让下）。"""
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                "/opt/pw-browsers/chromium_headless_shell-*/"
                "chrome-headless-shell-linux64/chrome-headless-shell"):
        hit = sorted(glob.glob(pat))
        if hit:
            return {"executable_path": hit[-1]}
    return {}

WRAP_HEAD = '<!doctype html>\n<html lang="zh-Hans">\n<head>\n<meta charset="utf-8">\n'


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "review.html")
    frag = src.read_text(encoding="utf-8")
    tmp = src.parent / (src.stem + ".fixedpoint.tmp.html")
    # 发布时宿主会把片段裹进 doctype/head/body；本地照做一遍，让第一次加载
    # 尽量贴近线上。
    tmp.write_text(WRAP_HEAD + frag + "</body>\n</html>\n", encoding="utf-8")

    errs: list[str] = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(**_chromium(), args=["--no-sandbox"])
        try:
            pg = br.new_context().new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(tmp.resolve().as_uri())
            pg.wait_for_selector(".card")
            # 页里可能已经带着上一轮的裁决（重发前 read 回来带过来的），
            # 所以比的是"多了一条"，不是"只有一条"。
            n1 = pg.evaluate("Object.keys(state).length")
            btn = pg.locator(".verdicts button").first
            vv = btn.get_attribute("data-v")
            btn.click()
            v2 = pg.evaluate("renderIndex()")
            n2 = pg.evaluate("Object.keys(state).length")
            if errs:
                print("页面报错：" + "; ".join(errs))
                return 1
            if n2 != n1 + 1:
                print(f"点了一下裁决，state 从 {n1} 变成 {n2} 条（应为 {n1 + 1}）——状态没接上")
                return 1

            tmp.write_text(v2, encoding="utf-8")
            # 换一个干净上下文：localStorage 是空的，state 只能从 #data 里来，
            # 这样才真的验到「裁决嵌进页里了」。
            pg2 = br.new_context().new_page()
            pg2.on("pageerror", lambda e: errs.append(str(e)))
            pg2.goto(tmp.resolve().as_uri())
            pg2.wait_for_selector(".card")
            v3 = pg2.evaluate("renderIndex()")
            got = pg2.evaluate("JSON.stringify(state)")
        finally:
            br.close()
            tmp.unlink(missing_ok=True)

    if errs:
        print("页面报错：" + "; ".join(errs))
        return 1
    if f'"{vv}"' not in got:
        print(f"重装后 state={got}，没读到刚才那个裁决——裁决没嵌进 #data")
        return 1
    if v2 != v3:
        i = next((k for k in range(min(len(v2), len(v3))) if v2[k] != v3[k]),
                 min(len(v2), len(v3)))
        print(f"不是定点：v2 {len(v2)} 字节 / v3 {len(v3)} 字节，第 {i} 字节起分岔")
        print("  v2 …" + v2[max(0, i - 60):i + 60].replace("\n", "\\n"))
        print("  v3 …" + v3[max(0, i - 60):i + 60].replace("\n", "\\n"))
        return 1
    print(f"定点 OK：v3 == v2（{len(v2)/1024:.0f} KB），裁决 {got} 已嵌进页里")
    return 0


if __name__ == "__main__":
    sys.exit(main())
