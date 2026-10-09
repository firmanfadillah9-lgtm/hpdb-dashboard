"""
count_rows.py - hitung jumlah baris per sheet, override dimension bug
"""
import sys, time
from openpyxl import load_workbook

filepath = sys.argv[1]
MAX_ROW = 2_000_000

wb = load_workbook(filepath, read_only=True, data_only=True)
for sheet_name in wb.sheetnames:
    ws = wb[sheet_name]
    count = 0
    start = time.time()
    for row in ws.iter_rows(min_row=1, max_row=MAX_ROW, min_col=1, max_col=1, values_only=True):
        count += 1
        if row[0] is None and count > 1:
            # Kemungkinan sudah lewat data asli, cek apakah benar-benar habis
            pass
        if time.time() - start > 90:
            print(f"  {sheet_name}: >{count:,} baris (timeout 90s)")
            break
    else:
        elapsed = time.time() - start
        print(f"  {sheet_name}: {count:,} baris (termasuk header) [{elapsed:.1f}s]")
wb.close()
