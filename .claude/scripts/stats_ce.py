#!/usr/bin/env python3
"""ce 统计分析脚本：夹注覆盖率、text=None、空页面等。

用法：
    python .claude/scripts/stats_ce.py 1
    python .claude/scripts/stats_ce.py 1 --verbose
"""
import json, os, sys, argparse

BOOK = "欽定四庫全書簡明目錄·文淵閣本"
BASE = f"//wsl.localhost/Ubuntu/home/lishaodong/workspace/guji-resource/{BOOK}/03_信息提取/ocr"

def analyze(ce_num, verbose=False):
    ce_dir = os.path.join(BASE, f"ce{ce_num:02d}")
    if not os.path.exists(ce_dir):
        print(f"目录不存在: {ce_dir}"); return
    
    files = sorted(f for f in os.listdir(ce_dir) if f.startswith("page") and f.endswith(".json"))
    print(f"ce{ce_num:02d}: {len(files)} 个 JSON 文件")
    
    total_cols = jiazhu_cols = text_none_cells = 0
    empty_pages = []
    content_cols = content_jiazhu = content_pages = pages_with_jiazhu = 0
    
    for fname in files:
        page_num = int(fname[4:7])
        with open(os.path.join(ce_dir, fname), encoding="utf-8") as f:
            data = json.load(f)
        cols = data.get("columns", [])
        
        page_jiazhu = page_cells = page_none = 0
        all_empty = True
        for col in cols:
            cells = col.get("cells", [])
            if cells: all_empty = False
            col_has_j = any(c.get("type") == "jiazhu" for c in cells)
            if col_has_j: jiazhu_cols += 1; page_jiazhu += 1
            total_cols += 1
            page_cells += len(cells)
            page_none += sum(1 for c in cells if c.get("type") == "char" and c.get("text") is None)
        text_none_cells += page_none
        if cols and all_empty:
            empty_pages.append(page_num)
        
        if page_num >= 25:
            content_pages += 1
            content_cols += len(cols)
            content_jiazhu += page_jiazhu
            if page_jiazhu > 0: pages_with_jiazhu += 1
        
        if verbose:
            j_rate = f"{page_jiazhu}/{len(cols)}" if cols else "0/0"
            flag = " EMPTY" if page_num in empty_pages else ""
            print(f"  page {page_num:3d}: {len(cols)} cols, jiazhu={j_rate}, none={page_none}{flag}")
    
    print(f"\n总列数: {total_cols}, 夹注列: {jiazhu_cols} ({jiazhu_cols/total_cols*100:.1f}%)" if total_cols else "")
    print(f"text=None cells: {text_none_cells}")
    print(f"空页面: {empty_pages} (共 {len(empty_pages)} 页)")
    if content_pages:
        print(f"\n内容页 (page≥25): {content_pages} 页")
        print(f"  含夹注页面: {pages_with_jiazhu}/{content_pages} ({pages_with_jiazhu/content_pages*100:.1f}%)")
        print(f"  夹注列: {content_jiazhu}/{content_cols} ({content_jiazhu/content_cols*100:.1f}%)" if content_cols else "")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ce", type=int)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    analyze(args.ce, args.verbose)
