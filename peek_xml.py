"""
peek_xml.py
-----------------
Lihat isi mentah beberapa KB pertama dari sheet XML di dalam .xlsx,
tanpa decompress seluruh file.

Cara pakai:
    python peek_xml.py "path/ke/file.xlsx" [sheet_name] [n_bytes]
"""
import sys
import zipfile

filepath = sys.argv[1]
sheet = sys.argv[2] if len(sys.argv) > 2 else "xl/worksheets/sheet1.xml"
n_bytes = int(sys.argv[3]) if len(sys.argv) > 3 else 3000

with zipfile.ZipFile(filepath) as z:
    with z.open(sheet) as f:
        chunk = f.read(n_bytes)
        print(chunk.decode('utf-8', errors='replace'))
