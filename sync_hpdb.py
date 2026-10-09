r"""
sync_hpdb.py
------------
Load data HPDB dari file daily report (OneDrive) ke addhp.duckdb.

MENDUKUNG DUA FORMAT SUMBER:
  Lama : homepass_report_daily_*.xlsx + homepass_linknet_report_daily_*.xlsx
  Baru : HPDB_G2A_<tgl>.xlsb + HPDB_B2S_<tgl>.xlsb   (sejak Sep 2026)

Strategi: FULL REPLACE - tabel hpdb di-drop dan dibuat ulang setiap sync.
Data ditulis PER SHEET langsung ke DuckDB (streaming), tidak ditumpuk di
memori dulu - penting karena file baru berisi 8+ juta baris.

Cara pakai:
    python sync_hpdb.py
    python sync_hpdb.py --folder "C:\path\ke\folder"

Butuh: pip install python-calamine   (untuk baca .xlsb)
"""

import os
import sys
import glob
import argparse
import duckdb
import pandas as pd
from datetime import datetime

# CONFIG
ONEDRIVE_BASE = r"C:\Users\RYZEN\OneDrive - XLSMART\XL HOME - Service Delivery - HPDB"
DB_PATH       = r"C:\hpdb\addhp.duckdb"
TABLE_NAME    = "hpdb"

HPDB_COLUMNS = [
    "HOMEPASS_ID", "HOMEPASS_STATUS",
    "ACQUISITION_CLASS", "ACQUISITION_TIER", "COMPETITION", "BUILDING_TYPE",
    "OWNERSHIP", "VENDOR_NAME", "REGION", "CITY", "CITY_CODE",
    "PROJECT_NAME", "PROJECT_ID", "RESIDENCE_NAME",
    "CLUSTER_NAME", "CLUSTER_CODE",
    "PREFIX_ADDRESS", "STREET_NAME", "HOUSE_NUMBER", "BLOCK", "FLOOR",
    "RT", "RW", "DISTRICT", "SUB_DISTRICT", "ZIP_CODE",
    "OLT_LOCATION", "OLT_LOCATION_CODE", "OLT_DEVICE_CODE", "OLT_NAME",
    "FDT_CODE", "FAT_CODE",
    "FDT_LONGITUDE", "FDT_LATITUDE",
    "FAT_LONGITUDE", "FAT_LATITUDE",
    "BUILDING_LATITUDE", "BUILDING_LONGITUDE",
    "NETWORK_ID", "FRAME", "SLOT", "PORT",
    "IP_DEVICE", "VLAN_SERVICE",
    "RFS_DATE", "REMARKS",
    "MOBILE_REGION", "MOBILE_CLUSTER", "PARTNER_RFS_DATE",
    "CITY_GROUP", "BUILDING_NAME", "COUNTER",
    "FULL_ADDRESS", "SOURCE_FILE",
]

# Kolom yang namanya berbeda antar format
COL_REMAP = {
    "LONGITUDE": "FAT_LONGITUDE",
    "LATITUDE":  "FAT_LATITUDE",
}


def find_latest_folder(base):
    folders = sorted(glob.glob(os.path.join(base, "homepass_report_daily_*")), reverse=True)
    folders = [f for f in folders if os.path.isdir(f)]
    if not folders:
        raise FileNotFoundError(f"Tidak ada folder daily report di:\n  {base}")
    print(f"[INFO] Folder ditemukan: {os.path.basename(folders[0])}")
    return folders[0]


def cari_file(folder):
    """Kumpulkan file HPDB, apa pun format & penamaannya."""
    hasil = []
    for pola in ("*.xlsb", "*.xlsx"):
        for f in glob.glob(os.path.join(folder, pola)):
            if os.path.basename(f).startswith("~$"):
                continue
            hasil.append(f)
    return sorted(set(hasil))


def label_sumber(path):
    """Tandai asal data: G2A / B2S / MAIN / LINKNET."""
    n = os.path.basename(path).upper()
    if "G2A" in n:
        return "G2A"
    if "B2S" in n:
        return "B2S"
    if "LINKNET" in n:
        return "LINKNET"
    return "MAIN"


def siapkan_df(baris_list, sumber):
    """Dari list-of-list (baris[0] = header) -> DataFrame sesuai HPDB_COLUMNS."""
    if not baris_list or len(baris_list) < 2:
        return None

    header = [COL_REMAP.get(str(v).strip().upper(), str(v).strip().upper())
              for v in baris_list[0]]
    if "HOMEPASS_ID" not in header:
        return None

    df = pd.DataFrame(baris_list[1:], columns=header)
    df = df.loc[:, ~df.columns.duplicated()]

    for c in HPDB_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["SOURCE_FILE"] = sumber

    df = df[HPDB_COLUMNS].astype(str)
    df = df.replace({"None": None, "nan": None, "NaT": None})

    for c in ("FAT_CODE", "FDT_CODE", "HOMEPASS_ID"):
        if c in df.columns:
            df[c] = df[c].str.strip()

    df = df[df["HOMEPASS_ID"].notna() & (df["HOMEPASS_ID"] != "")]
    return df


def iter_sheets(path):
    """Yield (nama_sheet, list_of_rows) untuk tiap sheet, hemat memori."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".xlsb":
        try:
            from python_calamine import CalamineWorkbook
        except ImportError:
            raise RuntimeError(
                "python-calamine belum terinstall. Jalankan:\n"
                "   python -m pip install python-calamine"
            )
        wb = CalamineWorkbook.from_path(path)
        for nama in wb.sheet_names:
            yield nama, wb.get_sheet_by_name(nama).to_python()
    else:
        xls = pd.ExcelFile(path)
        for nama in xls.sheet_names:
            d = pd.read_excel(xls, sheet_name=nama, dtype=str)
            yield nama, [list(d.columns)] + d.values.tolist()


def main():
    ap = argparse.ArgumentParser(description="Sync HPDB (xlsb/xlsx) -> addhp.duckdb")
    ap.add_argument("--folder", help="Path folder daily report (default: terbaru)")
    args = ap.parse_args()

    start = datetime.now()
    print("=" * 62)
    print("  SYNC HPDB -> addhp.duckdb")
    print(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)

    try:
        folder = args.folder if args.folder else find_latest_folder(ONEDRIVE_BASE)
        files = cari_file(folder)
        if not files:
            raise FileNotFoundError(f"Tidak ada file HPDB (.xlsb/.xlsx) di folder:\n  {folder}")

        print(f"[INFO] File ditemukan: {len(files)}")
        for f in files:
            print(f"        - {os.path.basename(f)} ({os.path.getsize(f)/1024/1024:.0f} MB)")

        con = duckdb.connect(DB_PATH)
        con.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")

        tabel_dibuat = False
        total_baris = 0

        for path in files:
            sumber = label_sumber(path)
            print(f"\n[INFO] Membaca {os.path.basename(path)}  (sumber: {sumber})")
            for nama_sheet, baris in iter_sheets(path):
                df = siapkan_df(baris, sumber)
                del baris
                if df is None or df.empty:
                    print(f"       Sheet '{nama_sheet}': dilewati (tanpa HOMEPASS_ID)")
                    continue

                con.register("df_batch", df)
                if not tabel_dibuat:
                    con.execute(f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM df_batch")
                    tabel_dibuat = True
                else:
                    con.execute(f"INSERT INTO {TABLE_NAME} SELECT * FROM df_batch")
                con.unregister("df_batch")

                total_baris += len(df)
                print(f"       Sheet '{nama_sheet}': {len(df):,} baris  "
                      f"(total: {total_baris:,})")
                del df

        if not tabel_dibuat:
            raise ValueError("Tidak ada data yang berhasil dibaca.")

        # Index untuk mempercepat lookup
        print("\n[INFO] Membuat index...")
        for nama_idx, kolom in (("idx_fat", "FAT_CODE"),
                                ("idx_hpid", "HOMEPASS_ID"),
                                ("idx_fdt", "FDT_CODE")):
            try:
                con.execute(f"CREATE INDEX IF NOT EXISTS {nama_idx} ON {TABLE_NAME} ({kolom})")
            except Exception as e:
                print(f"       [WARN] index {nama_idx}: {str(e)[:60]}")

        count = con.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
        fat_count = con.execute(f"SELECT COUNT(DISTINCT FAT_CODE) FROM {TABLE_NAME}").fetchone()[0]
        print(f"\n[OK] Tabel '{TABLE_NAME}' berhasil dibuat")
        print(f"     Total rows : {count:,}")
        print(f"     Unique FAT : {fat_count:,}")

        print("\n     Per sumber:")
        for src, cnt in con.execute(f"""
                SELECT SOURCE_FILE, COUNT(*) FROM {TABLE_NAME}
                GROUP BY 1 ORDER BY 2 DESC""").fetchall():
            print(f"       {src or 'NULL'}: {cnt:,}")

        print("\n     Per vendor (top 10):")
        for vendor, cnt in con.execute(f"""
                SELECT VENDOR_NAME, COUNT(*) FROM {TABLE_NAME}
                GROUP BY 1 ORDER BY 2 DESC LIMIT 10""").fetchall():
            print(f"       {vendor or 'NULL'}: {cnt:,}")

        print("\n     Per status:")
        for st, cnt in con.execute(f"""
                SELECT HOMEPASS_STATUS, COUNT(*) FROM {TABLE_NAME}
                GROUP BY 1 ORDER BY 2 DESC LIMIT 10""").fetchall():
            print(f"       {st or 'NULL'}: {cnt:,}")

        con.close()

        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n[DONE] Selesai dalam {elapsed/60:.1f} menit")
        print(f"       DB siap dipakai: {DB_PATH}")

    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
