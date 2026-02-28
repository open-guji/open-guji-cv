import fitz
import urllib.request
import os
import sys

# the ID and URL
item_id = "06054854.cn"
url = f"https://archive.org/download/{item_id}/{item_id}.pdf"
pdf_path = f"{item_id}.pdf"

print(f"Checking for {pdf_path}...")
if not os.path.exists(pdf_path):
    print(f"Downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, pdf_path)
        print("Download complete.")
    except Exception as e:
        print(f"Failed to download: {e}")
        sys.exit(1)
else:
    print(f"{pdf_path} already exists.")

print(f"Opening {pdf_path}...")
try:
    doc = fitz.open(pdf_path)
    print(f"Loaded document with {len(doc)} pages.")
except Exception as e:
    print(f"Failed to open PDF: {e}")
    sys.exit(1)

out_dir = "data/book7"
os.makedirs(out_dir, exist_ok=True)

# User requested pages 110-119, URL n109, which means index 109 to 118 (10 pages)
for i in range(109, 119):
    if i >= len(doc):
        print(f"Warning: page index {i} is out of bounds (max {len(doc)-1}). Stopping.")
        break
    print(f"Extracting page {i+1} (index {i})...")
    page = doc.load_page(i)
    # Extract to high res
    pix = page.get_pixmap(dpi=300)
    out_path = os.path.join(out_dir, f"{item_id}_page_{i+1:03d}.png")
    pix.save(out_path)
    print(f"Saved {out_path}")

print("Extraction complete.")
