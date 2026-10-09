"""
sync_hpdb.py
------------
Load data HPDB dari KEDUA file Excel daily report (OneDrive) ke addhp.duckdb.
  1. homepass_report_daily_*.xlsx          (punya FAT_LONGITUDE/LATITUDE)
  2. homepass_linknet_report_daily_*.xlsx  (coverage vendor LINKNET)

Strategi: FULL REPLACE — tabel hpdb di-drop dan dibuat ulang setiap sync.
Data kedua file di-UNION ALL, duplikat HOMEPASS_ID dipertahankan (beda vendor).

Cara pakai:
    python sync_hpdb.py
    python sync_hpdb.py --folder "C:\\path\\ke\\folder\\custom"

Jadwal: Manual, cukup dijalankan sekali atau saat ada update FAT baru.
"""

import os
import sys
import glob
import argparse
import duckdb
import pandas as pd
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────────
ONEDRIVE_BASE   = r"C:\Users\RYZEN\OneDrive - XLSMART\XL HOME - Service Delivery - HPDB"
DB_PATH         = r"C:\hpdb\addhp.duckdb"
TABLE_NAME      = "hpdb"

# Kolom yang diload dari HPDB
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
]

# Mapping kolom linknet → standard (kolom berbeda nama dari file main)
LINKNET_COL_REMAP = {
    "LONGITUDE":          "FAT_LONGITUDE",
    "LATITUDE":           "FAT_LATITUDE",
    "BUILDING_LONGITUDE": "BUILDING_LONGITUDE",
    "BUILDING_LATITUDE":  "BUILDING_LATITUDE",
}
# ────────────────────────────────────────────────────────────────────────────


def find_latest_folder(base: str) -> str:
    """Auto-detect folder daily report terbaru berdasarkan tanggal di nama folder."""
    pattern = os.path.join(base, "homepass_report_daily_*")
    folders = sorted(glob.glob(pattern), reverse=True)
    if not folders:
        raise FileNotFoundError(f"Tidak ada folder daily report di:\n  {base}")
    latest = folders[0]
    print(f"[INFO] Folder ditemukan: {os.path.basename(latest)}")
    return latest


def load_excel(path: str, label: str) -> pd.DataFrame:
    """Baca SEMUA sheet dari file Excel HPDB, gabungkan jadi satu DataFrame."""
    print(f"[INFO] Membaca {label}...")
    print(f"       File: {os.path.basename(path)}")
    xls = pd.ExcelFile(path)
    sheet_names = xls.sheet_names
    print(f"       Sheet ditemukan: {sheet_names}")
    sheet_dfs = []
    for sheet in sheet_names:
        df_sheet = pd.read_excel(xls, sheet_name=sheet, dtype=str)
        print(f"       Sheet '{sheet}': {len(df_sheet):,} baris")
        sheet_dfs.append(df_sheet)
    df = pd.concat(sheet_dfs, ignore_index=True)
    print(f"       Total setelah semua sheet digabung: {len(df):,} baris | Kolom: {len(df.columns)}")

    # Rename kolom yang berbeda nama (khusus linknet)
    df = df.rename(columns=LINKNET_COL_REMAP)

    # Normalize key columns
    for col in ["FAT_CODE", "FDT_CODE", "HOMEPASS_ID"]:
        if col in df.columns:
            df[col] = df[col].str.strip()

    # Ambil kolom yang tersedia saja
    available = [c for c in HPDB_COLUMNS if c in df.columns]
    missing   = [c for c in HPDB_COLUMNS if c not in df.columns]
    if missing:
        print(f"       [WARN] Kolom tidak ada di file ini: {missing}")

    df = df[available].copy()

    # Tambahkan kolom yang tidak ada sebagai kosong
    for col in HPDB_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Reorder sesuai HPDB_COLUMNS
    df = df[HPDB_COLUMNS]
    print(f"       Kolom diload: {len(available)}/{len(HPDB_COLUMNS)}")
    return df


def sync_to_duckdb(df: pd.DataFrame, db_path: str) -> None:
    """Full replace tabel hpdb di DuckDB."""
    print(f"\n[INFO] Menyimpan ke DuckDB: {db_path}")
    con = duckdb.connect(db_path)

    con.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
    con.execute(f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM df")

    # Index untuk mempercepat lookup
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_fat  ON {TABLE_NAME} (FAT_CODE)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_hpid ON {TABLE_NAME} (HOMEPASS_ID)")
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_fdt  ON {TABLE_NAME} (FDT_CODE)")

    count     = con.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    fat_count = con.execute(f"SELECT COUNT(DISTINCT FAT_CODE) FROM {TABLE_NAME}").fetchone()[0]
    vendor_counts = con.execute(f"""
        SELECT VENDOR_NAME, COUNT(*) as cnt
        FROM {TABLE_NAME}
        GROUP BY VENDOR_NAME
        ORDER BY cnt DESC
        LIMIT 10
    """).fetchall()

    print(f"[OK] Tabel '{TABLE_NAME}' berhasil dibuat")
    print(f"     Total rows  : {count:,}")
    print(f"     Unique FAT  : {fat_count:,}")
    print(f"     Per vendor  :")
    for vendor, cnt in vendor_counts:
        print(f"       {vendor or 'NULL'}: {cnt:,}")

    con.close()


def main():
    parser = argparse.ArgumentParser(description="Sync HPDB Excel (kedua file) → addhp.duckdb")
    parser.add_argument("--folder", help="Path folder daily report (opsional, default: auto-detect terbaru)")
    args = parser.parse_args()

    start = datetime.now()
    print("=" * 60)
    print("  SYNC HPDB → addhp.duckdb (ALL SOURCES)")
    print(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        folder = args.folder if args.folder else find_latest_folder(ONEDRIVE_BASE)

        # Cari kedua file
        files_main    = glob.glob(os.path.join(folder, "homepass_report_daily_*.xlsx"))
        files_linknet = glob.glob(os.path.join(folder, "homepass_linknet_report_daily_*.xlsx"))

        # Filter: pastikan linknet tidak masuk ke files_main
        files_main = [f for f in files_main if "linknet" not in os.path.basename(f).lower()]

        if not files_main and not files_linknet:
            raise FileNotFoundError(f"Tidak ada file HPDB di folder:\n  {folder}")

        dfs = []

        # Load file utama (punya FAT_LONGITUDE/LATITUDE)
        if files_main:
            df_main = load_excel(files_main[0], "HPDB MAIN")
            dfs.append(df_main)
        else:
            print("[WARN] File homepass_report_daily_*.xlsx tidak ditemukan")

        # Load file linknet
        if files_linknet:
            df_linknet = load_excel(files_linknet[0], "HPDB LINKNET")
            dfs.append(df_linknet)
        else:
            print("[WARN] File homepass_linknet_report_daily_*.xlsx tidak ditemukan")

        # Gabungkan kedua dataframe
        print(f"\n[INFO] Menggabungkan {len(dfs)} file...")
        # Pastikan tidak ada duplikat kolom sebelum concat
        dfs_clean = []
        for df in dfs:
            df = df.loc[:, ~df.columns.duplicated()]
            df = df.reindex(columns=HPDB_COLUMNS)
            dfs_clean.append(df)
        df_combined = pd.concat(dfs_clean, ignore_index=True)
        print(f"       Total setelah digabung: {len(df_combined):,} rows")

        # Sync ke DuckDB
        sync_to_duckdb(df_combined, DB_PATH)

        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n[DONE] Selesai dalam {elapsed:.1f} detik")
        print(f"       DB siap dipakai: {DB_PATH}")

    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected: {e}")
        raise


if __name__ == "__main__":
    main()
