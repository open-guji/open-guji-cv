#!/usr/bin/env python3
"""删除指定页的 JSON 并重新运行 OCR。

用法：
    python .claude/scripts/delete_and_rerun.py 1 31,32,35
    python .claude/scripts/delete_and_rerun.py 1 all   # 删除全部并重跑
"""
import os, sys, argparse, subprocess
from pathlib import Path

BOOK = "欽定四庫全書簡明目錄·文淵閣本"
BASE = Path(f"//wsl.localhost/Ubuntu/home/lishaodong/workspace/guji-resource/{BOOK}/03_信息提取/ocr")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ce", type=int)
    parser.add_argument("pages", help="页码列表 '31,32,35' 或 'all'")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    ce_dir = BASE / f"ce{args.ce:02d}"
    if not ce_dir.exists():
        print(f"目录不存在: {ce_dir}"); return
    
    if args.pages == "all":
        files = sorted(ce_dir.glob("page*.json"))
    else:
        page_nums = [int(p) for p in args.pages.split(",")]
        files = [ce_dir / f"page{p:03d}.json" for p in page_nums]
    
    deleted = []
    for f in files:
        if f.exists():
            if not args.dry_run:
                f.unlink()
            deleted.append(f.name)
            print(f"{'[dry]' if args.dry_run else 'Deleted'} {f.name}")
        else:
            print(f"Not found: {f.name}")
    
    if not deleted:
        print("没有文件被删除"); return
    
    if args.dry_run:
        print(f"\nDry run: 将删除 {len(deleted)} 个文件"); return
    
    pages_arg = args.pages if args.pages != "all" else None
    cmd = ["python", "run_phase5.py", "--ce", str(args.ce)]
    if pages_arg:
        cmd += ["--pages", pages_arg]
    
    print(f"\n运行: {' '.join(cmd)}")
    env = os.environ.copy()
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.run(cmd, env=env)

if __name__ == "__main__":
    main()
