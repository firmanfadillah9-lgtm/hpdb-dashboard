r"""
track_status.py - Tracking perubahan status HPID di HPDB (change-log / SCD)

MENDUKUNG DUA FORMAT SUMBER:
  Lama : homepass_report_daily_*.xlsx + homepass_linknet_report_daily_*.xlsx
  Baru : HPDB_G2A_<tgl>.xlsb + HPDB_B2S_<tgl>.xlsb   (sejak Sep 2026)

File .xlsb dibaca lewat API pyxlsb baris-per-baris, bukan pandas.read_excel,
karena metadata dimensi sheet di file ini tidak benar (pandas gagal IndexError).
Cara ini juga lebih hemat memori untuk file ratusan MB.

Cara pakai:
    python track_status.py
    python track_status.py --all
    python track_status.py --folder "C:\path\ke\folder"

Butuh: pip install python-calamine   (cadangan: pyxlsb)
"""

import os
import re
import sys
import glob
import argparse
import duckdb
import pandas as pd
from datetime import datetime

ONEDRIVE_BASE = r"C:\Users\RYZEN\OneDrive - XLSMART\XL HOME - Service Delivery - HPDB"
DB_PATH       = r"C:\hpdb\addhp.duckdb"

TRACK_COLUMNS = ["HOMEPASS_ID", "HOMEPASS_STATUS", "VENDOR_NAME", "CITY", "CLUSTER_NAME"]

REMAP = {"LONGITUDE": "FAT_LONGITUDE", "LATITUDE": "FAT_LATITUDE"}


def folder_date(folder):
    m = re.search(r"(\d{8})$", os.path.basename(folder.rstrip("\\/")))
    if m:
        d = m.group(1)
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    for f in glob.glob(os.path.join(folder, "*.xls*")):
        m2 = re.search(r"(\d{2})-(\d{2})-(\d{4})", os.path.basename(f))
        if m2:
            return f"{m2.group(3)}-{m2.group(1)}-{m2.group(2)}"
    raise ValueError(f"Tidak bisa menentukan tanggal dari folder: {folder}")


def list_folders(base):
    folders = glob.glob(os.path.join(base, "homepass_report_daily_*"))
    return sorted([f for f in folders if os.path.isdir(f)])


def cari_file_hpdb(folder):
    hasil = []
    for pola in ("*.xlsb", "*.xlsx"):
        for f in glob.glob(os.path.join(folder, pola)):
            if os.path.basename(f).startswith("~$"):
                continue
            hasil.append(f)
    return sorted(set(hasil))


def _ambil_kolom(baris_list, nama_sheet):
    """Dari list-of-list (baris pertama = header), ambil kolom yang dibutuhkan."""
    if not baris_list:
        return None
    header = [REMAP.get(str(v).strip().upper(), str(v).strip().upper())
              for v in baris_list[0]]
    idx = {k: header.index(k) for k in TRACK_COLUMNS if k in header}
    if "HOMEPASS_ID" not in idx or "HOMEPASS_STATUS" not in idx:
        print(f"      [WARN] Sheet '{nama_sheet}' tanpa kolom HPID/status, dilewati")
        return None

    hasil = []
    for nilai in baris_list[1:]:
        if not any(str(v).strip() for v in nilai):
            continue
        hasil.append([
            (str(nilai[idx[k]]).strip() if k in idx and idx[k] < len(nilai) else "")
            for k in TRACK_COLUMNS
        ])
    if hasil:
        print(f"      Sheet '{nama_sheet}': {len(hasil):,} baris")
    return hasil


def baca_xlsb_calamine(path):
    """Baca .xlsb dengan python-calamine (cepat & andal). Return DataFrame atau None."""
    try:
        from python_calamine import CalamineWorkbook
    except ImportError:
        return None

    wb = CalamineWorkbook.from_path(path)
    kumpulan = []
    for nama_sheet in wb.sheet_names:
        try:
            baris = wb.get_sheet_by_name(nama_sheet).to_python()
            hasil = _ambil_kolom(baris, nama_sheet)
            if hasil:
                kumpulan.extend(hasil)
        except Exception as e:
            print(f"      [WARN] Sheet '{nama_sheet}': {type(e).__name__}: {str(e)[:70]}")
    if not kumpulan:
        return pd.DataFrame(columns=TRACK_COLUMNS)
    return pd.DataFrame(kumpulan, columns=TRACK_COLUMNS)


def baca_xlsb_pyxlsb(path):
    """Cadangan: baca .xlsb lewat pyxlsb baris-per-baris."""
    from pyxlsb import open_workbook

    kumpulan = []
    with open_workbook(path) as wb:
        for nama_sheet in wb.sheets:
            with wb.get_sheet(nama_sheet) as sheet:
                baris = []
                for row in sheet.rows():
                    baris.append([(c.v if c.v is not None else "") for c in row])
                baris = [b for b in baris if any(str(v).strip() for v in b)]
                hasil = _ambil_kolom(baris, nama_sheet)
                if hasil:
                    kumpulan.extend(hasil)
    if not kumpulan:
        return pd.DataFrame(columns=TRACK_COLUMNS)
    return pd.DataFrame(kumpulan, columns=TRACK_COLUMNS)


def baca_xlsb(path):
    """Coba calamine dulu (lebih andal), kalau gagal baru pyxlsb."""
    df = None
    try:
        df = baca_xlsb_calamine(path)
        if df is None:
            print("      [INFO] python-calamine belum terinstall, pakai pyxlsb...")
        elif not df.empty:
            return df
    except Exception as e:
        print(f"      [WARN] calamine gagal: {type(e).__name__}: {str(e)[:80]}")

    print("      [INFO] Mencoba pyxlsb...")
    return baca_xlsb_pyxlsb(path)


def baca_xlsx(path):
    dfs = []
    xls = pd.ExcelFile(path)
    for sheet in xls.sheet_names:
        d = pd.read_excel(xls, sheet_name=sheet, dtype=str)
        d.columns = [REMAP.get(str(c).strip().upper(), str(c).strip().upper()) for c in d.columns]
        if "HOMEPASS_ID" not in d.columns or "HOMEPASS_STATUS" not in d.columns:
            print(f"      [WARN] Sheet '{sheet}' tanpa kolom HPID/status, dilewati")
            continue
        for c in TRACK_COLUMNS:
            if c not in d.columns:
                d[c] = ""
        print(f"      Sheet '{sheet}': {len(d):,} baris")
        dfs.append(d[TRACK_COLUMNS])
    if not dfs:
        return pd.DataFrame(columns=TRACK_COLUMNS)
    return pd.concat(dfs, ignore_index=True)


def load_status_from_folder(folder):
    files = cari_file_hpdb(folder)
    if not files:
        raise FileNotFoundError(f"Tidak ada file HPDB (.xlsb/.xlsx) di folder: {folder}")

    dfs = []
    for path in files:
        nama = os.path.basename(path)
        ukuran = os.path.getsize(path) / 1024 / 1024
        print(f"   Membaca {nama} ({ukuran:.0f} MB)...")
        ext = os.path.splitext(path)[1].lower()
        try:
            d = baca_xlsb(path) if ext == ".xlsb" else baca_xlsx(path)
            if not d.empty:
                dfs.append(d)
        except Exception as e:
            print(f"      [ERROR] Gagal baca {nama}: {type(e).__name__}: {str(e)[:120]}")

    if not dfs:
        raise ValueError("Tidak ada data yang berhasil dibaca dari folder ini.")

    df = pd.concat(dfs, ignore_index=True)
    df["HOMEPASS_ID"] = df["HOMEPASS_ID"].astype(str).str.strip()
    df["HOMEPASS_STATUS"] = df["HOMEPASS_STATUS"].astype(str).str.strip().str.upper()
    df = df[(df["HOMEPASS_ID"] != "") & (~df["HOMEPASS_ID"].str.lower().isin(["nan", "none"]))]
    df = df.drop_duplicates(subset=["HOMEPASS_ID"], keep="first").reset_index(drop=True)
    print(f"   Total HPID unik: {len(df):,}")
    return df


def ensure_tables(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS status_current (
            HOMEPASS_ID VARCHAR PRIMARY KEY, HOMEPASS_STATUS VARCHAR,
            VENDOR_NAME VARCHAR, CITY VARCHAR, CLUSTER_NAME VARCHAR, last_seen_date DATE)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS status_history (
            HOMEPASS_ID VARCHAR, status_from VARCHAR, status_to VARCHAR,
            change_date DATE, VENDOR_NAME VARCHAR, CITY VARCHAR, CLUSTER_NAME VARCHAR)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS status_processed (
            snapshot_date DATE PRIMARY KEY, processed_at TIMESTAMP,
            n_changes INTEGER, n_new INTEGER)
    """)


def process_folder(con, folder):
    snap_date = folder_date(folder)
    if con.execute("SELECT 1 FROM status_processed WHERE snapshot_date = ?", [snap_date]).fetchone():
        print(f"[SKIP] {snap_date} sudah pernah diproses.")
        return False

    print(f"\n[INFO] Memproses snapshot {snap_date} ({os.path.basename(folder)})")
    df = load_status_from_folder(folder)
    con.register("df_snap", df)

    first_run = con.execute("SELECT COUNT(*) FROM status_current").fetchone()[0] == 0

    if first_run:
        print("   [INFO] Baseline pertama - mengisi status_current (tanpa history)")
        con.execute(f"""INSERT INTO status_current
            SELECT HOMEPASS_ID, HOMEPASS_STATUS, VENDOR_NAME, CITY, CLUSTER_NAME,
                   DATE '{snap_date}' FROM df_snap""")
        n_changes, n_new = 0, 0
    else:
        n_changes = con.execute(f"""INSERT INTO status_history
            SELECT s.HOMEPASS_ID, c.HOMEPASS_STATUS, s.HOMEPASS_STATUS,
                   DATE '{snap_date}', s.VENDOR_NAME, s.CITY, s.CLUSTER_NAME
            FROM df_snap s JOIN status_current c USING (HOMEPASS_ID)
            WHERE s.HOMEPASS_STATUS <> c.HOMEPASS_STATUS""").fetchone()[0]

        n_new = con.execute(f"""INSERT INTO status_history
            SELECT s.HOMEPASS_ID, NULL, s.HOMEPASS_STATUS,
                   DATE '{snap_date}', s.VENDOR_NAME, s.CITY, s.CLUSTER_NAME
            FROM df_snap s LEFT JOIN status_current c USING (HOMEPASS_ID)
            WHERE c.HOMEPASS_ID IS NULL""").fetchone()[0]

        con.execute(f"""UPDATE status_current c SET
                HOMEPASS_STATUS = s.HOMEPASS_STATUS, VENDOR_NAME = s.VENDOR_NAME,
                CITY = s.CITY, CLUSTER_NAME = s.CLUSTER_NAME, last_seen_date = DATE '{snap_date}'
            FROM df_snap s WHERE c.HOMEPASS_ID = s.HOMEPASS_ID""")
        con.execute(f"""INSERT INTO status_current
            SELECT s.HOMEPASS_ID, s.HOMEPASS_STATUS, s.VENDOR_NAME, s.CITY, s.CLUSTER_NAME,
                   DATE '{snap_date}'
            FROM df_snap s LEFT JOIN status_current c USING (HOMEPASS_ID)
            WHERE c.HOMEPASS_ID IS NULL""")
        print(f"   [OK] Perubahan status: {n_changes:,} | HPID baru: {n_new:,}")

    con.unregister("df_snap")
    con.execute("INSERT INTO status_processed VALUES (?, ?, ?, ?)",
                [snap_date, datetime.now(), n_changes, n_new])
    return True


def print_summary(con):
    print("\n" + "=" * 62)
    print("  RINGKASAN TRANSISI (status_history)")
    print("=" * 62)
    rows = con.execute("""
        SELECT strftime(change_date, '%Y-%m') AS bulan,
               COALESCE(status_from, '(BARU)') AS dari, status_to AS ke, COUNT(*) AS jml
        FROM status_history GROUP BY 1,2,3 ORDER BY 1, 4 DESC""").fetchall()
    if not rows:
        print("  (belum ada transisi - baru baseline)")
    for bulan, dari, ke, jml in rows:
        print(f"  {bulan} | {dari:>14} -> {ke:<14} : {jml:,}")


def main():
    ap = argparse.ArgumentParser(description="Track perubahan status HPID HPDB")
    ap.add_argument("--folder", help="Path folder daily report spesifik")
    ap.add_argument("--all", action="store_true", help="Proses semua folder yang belum diproses")
    args = ap.parse_args()

    start = datetime.now()
    print("=" * 62)
    print("  TRACK STATUS HPDB (change-log)")
    print(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)

    con = duckdb.connect(DB_PATH)
    ensure_tables(con)

    try:
        if args.folder:
            folders = [args.folder]
        elif args.all:
            folders = list_folders(ONEDRIVE_BASE)
        else:
            folders = list_folders(ONEDRIVE_BASE)[-1:]

        if not folders:
            raise FileNotFoundError(f"Tidak ada folder daily report di: {ONEDRIVE_BASE}")

        processed = 0
        for folder in folders:
            try:
                if process_folder(con, folder):
                    processed += 1
            except Exception as e:
                print(f"[ERROR] {os.path.basename(folder)}: {type(e).__name__}: {str(e)[:150]}")

        print_summary(con)
        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n[DONE] {processed} snapshot diproses dalam {elapsed/60:.1f} menit")
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    finally:
        con.close()


if __name__ == "__main__":
    main()
