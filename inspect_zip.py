"""
inspect_zip.py
-----------------
File .xlsx sebenarnya adalah ZIP archive. Script ini membedah isi internal
untuk tahu di mana ukuran besar file sebenarnya berada
(misal: xl/media/* untuk gambar embedded, xl/worksheets/*.xml untuk data sheet,
xl/sharedStrings.xml untuk string table).

Cara pakai:
    python inspect_zip.py "path/ke/file.xlsx"
"""
import sys
import os
import zipfile

if len(sys.argv) != 2:
    print("Cara pakai: python inspect_zip.py \"path/ke/file.xlsx\"")
    sys.exit(1)

filepath = sys.argv[1]
print(f"File: {filepath}")
print(f"Ukuran total: {os.path.getsize(filepath) / (1024*1024):.1f} MB")
print("=" * 70)

with zipfile.ZipFile(filepath, 'r') as z:
    infos = z.infolist()
    # Sort by uncompressed size, descending
    infos_sorted = sorted(infos, key=lambda x: x.file_size, reverse=True)

    print(f"\nTotal entries dalam ZIP: {len(infos)}")
    print("\nTop 20 file terbesar (uncompressed):")
    print(f"{'Size (MB)':>12} | {'Compressed (MB)':>16} | Name")
    print("-" * 70)
    for info in infos_sorted[:20]:
        size_mb = info.file_size / (1024*1024)
        comp_mb = info.compress_size / (1024*1024)
        print(f"{size_mb:>12.2f} | {comp_mb:>16.2f} | {info.filename}")

    # Grup berdasarkan folder/prefix
    print("\n" + "=" * 70)
    print("Total ukuran per folder/prefix:")
    folder_sizes = {}
    for info in infos:
        # ambil prefix sampai 2 level folder
        parts = info.filename.split('/')
        prefix = '/'.join(parts[:2]) if len(parts) > 1 else parts[0]
        folder_sizes[prefix] = folder_sizes.get(prefix, 0) + info.file_size

    for prefix, size in sorted(folder_sizes.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {size/(1024*1024):>10.2f} MB  |  {prefix}")
