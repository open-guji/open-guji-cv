t=$1
cd /tmp/claude-0/wt_$t
export GUJI_PRODUCTS_DIR=/tmp/claude-0/sbx/c47/$t/products GUJI_GLYPH_DB=/tmp/claude-0/sbx/c47/$t/glyph.db GUJI_GLYPH_STORE=/tmp/claude-0/sbx/c47/store_$t GUJI_FEEDBACK_DIR=/tmp/claude-0/sbx/c47/$t/fb PYTHONIOENCODING=utf-8
/home/user/open-guji-cv/.venv/bin/python /tmp/claude-0/-home-user/cd1568e4-4e27-5a23-9c18-3dc898ab3296/scratchpad/run_cli.py /tmp/claude-0/wt_$t pipeline keben_body_v2 vol04 --pages 1-5 --to seed_admit -w "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本" > /tmp/claude-0/sbx/c47/run_$t.log 2>&1
echo EXIT $? >> /tmp/claude-0/sbx/c47/run_$t.log
