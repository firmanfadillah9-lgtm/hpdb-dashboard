r"""
cek_file_hpdb.py — Periksa struktur file HPDB .xlsb (baca langsung via pyxlsb)

pandas.read_excel gagal ("IndexError") karena metadata dimensi sheet di file
ini tidak benar - masalah yang sama seperti file .xlsx lama dulu.
Script ini membaca baris satu per satu lewat API pyxlsb, jadi tidak bergantung
pada metadata tersebut.

Jalankan:
    python cek_file_hpdb.py
    python cek_file_hpdb.py "C:\path\ke\folder"
"""
import os
import sys
import glob

try:
    from pyxlsb import open_workbook
except ImportError:
    print("[ERROR] pyxlsb belum terinstall. Jalankan:")
    print("   python -m pip install pyxlsb")
    sys.exit(1)

BASE = r"C:\Users\RYZEN\OneDrive - XLSMART\XL HOME - Service Delivery - HPDB"
MAKS_BARIS_CEK = 5      # berapa baris contoh yang ditampilkan
KUNCI = ["HOMEPASS_ID", "HOMEPASS_STATUS", "VENDOR_NAME", "CITY",
         "CLUSTER_NAME", "FAT_CODE", "BUILDING_LATITUDE", "BUILDING_LONGITUDE"]

folder = sys.argv[1] if len(sys.argv) > 1 else None
if not folder:
    kand = sorted(glob.glob(os.path.join(BASE, "homepass_report_daily_*")))
    if not kand:
        print(f"[ERROR] Tidak ada folder di {BASE}")
        sys.exit(1)
    folder = kand[-1]

print("=" * 70)
print("  CEK STRUKTUR FILE HPDB (.xlsb)")
print("=" * 70)
print(f"Folder: {folder}\n")

files = sorted(glob.glob(os.path.join(folder, "*.xlsb")))
if not files:
    files = sorted(glob.glob(os.path.join(folder, "*.xls*")))
if not files:
    print("[ERROR] Tidak ada file Excel di folder ini.")
    sys.exit(1)

for path in files:
    nama = os.path.basename(path)
    size = os.path.getsize(path) / 1024 / 1024
    print("-" * 70)
    print(f"FILE  : {nama}")
    print(f"Ukuran: {size:.1f} MB")

    try:
        with open_workbook(path) as wb:
            print(f"Sheet : {wb.sheets}")
            for nama_sheet in wb.sheets:
                print(f"\n  === [{nama_sheet}] ===")
                try:
                    with wb.get_sheet(nama_sheet) as sheet:
                        header = None
                        contoh = []
                        n = 0
                        for row in sheet.rows():
                            nilai = [(cel.v if cel.v is not None else "") for cel in row]
                            # lewati baris yang benar-benar kosong
                            if not any(str(v).strip() for v in nilai):
                                continue
                            if header is None:
                                header = [str(v).strip() for v in nilai]
                            else:
                                contoh.append(nilai)
                                n += 1
                                if n >= MAKS_BARIS_CEK:
                                    break

                        if header is None:
                            print("     (sheet kosong)")
                            continue

                        print(f"     Jumlah kolom: {len(header)}")
                        for i, h in enumerate(header, 1):
                            c1 = ""
                            if contoh and i <= len(contoh[0]):
                                c1 = str(contoh[0][i - 1])[:30]
                            print(f"     {i:3d}. {h:30s} | {c1}")

                        hu = [h.upper() for h in header]
                        print("\n     Cek kolom kunci:")
                        for k in KUNCI:
                            print(f"        {k:20s}: {'ADA' if k in hu else '-- TIDAK ADA --'}")
                except Exception as e:
                    print(f"     gagal: {type(e).__name__}: {str(e)[:100]}")
    except Exception as e:
        print(f"  GAGAL buka file: {type(e).__name__}: {str(e)[:150]}")
    print()

print("=" * 70)
print("Kirim output ini supaya track_status.py bisa disesuaikan.")
