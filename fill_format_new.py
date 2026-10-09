"""
fill_format_new.py
------------------
Mengisi kolom HPDB pada file FORMAT NEW.xlsx menggunakan data dari addhp.duckdb.

Struktur file FORMAT NEW:
  Baris 1 : Header HPDB (kolom yang diisi dari HPDB)
  Baris 2 : Kosong (separator)
  Baris 3 : Header original (dipertahankan sebagai penanda)
  Baris 4+ : Data

Strategi:
  1. Lookup via fat_code → ambil referensi dari HPDB
  2. Fallback via near_HOMEPASS_ID jika fat_code tidak ditemukan
  3. Kolom HPDB kosong setelah lookup → diisi "-"
  4. HOMEPASS_ID → selalu kosong (diisi sales)

Cara pakai:
    python fill_format_new.py --input "C:\\path\\FORMAT NEW.xlsx"
    python fill_format_new.py --input "C:\\path\\FORMAT NEW.xlsx" --output "C:\\path\\out.xlsx"
"""

import os
import sys
import argparse
import duckdb
import pandas as pd
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

# ── CONFIG ──────────────────────────────────────────────────────────────────
DB_PATH = r"C:\hpdb\addhp.duckdb"
TABLE   = "hpdb"

# Kolom HPDB yang diisi dari lookup
HPDB_FILL_COLS = [
    "ACQUISITION_CLASS", "ACQUISITION_TIER", "COMPETITION", "BUILDING_TYPE",
    "OWNERSHIP", "VENDOR_NAME", "REGION", "CITY",
    "CITY_CODE", "PROJECT_NAME", "PROJECT_ID", "RESIDENCE_NAME",
    "CLUSTER_NAME", "CLUSTER_CODE", "PREFIX_ADDRESS", "STREET_NAME",
    "BLOCK", "FLOOR", "RT", "RW", "DISTRICT", "SUB_DISTRICT", "ZIP_CODE",
    "OLT_LOCATION", "OLT_LOCATION_CODE", "OLT_DEVICE_CODE", "OLT_NAME",
    "FDT_CODE", "FAT_CODE",
    "FDT_LONGITUDE", "FDT_LATITUDE", "FAT_LONGITUDE", "FAT_LATITUDE",
    "BUILDING_LATITUDE", "BUILDING_LONGITUDE",
    "NETWORK_ID", "FRAME", "SLOT", "PORT",
    "HOMEPASS_STATUS", "IP_DEVICE", "VLAN_SERVICE",
    "RFS_DATE", "REMARKS",
    "MOBILE_REGION", "MOBILE_CLUSTER", "PARTNER_RFS_DATE",
    "CITY_GROUP", "BUILDING_NAME", "COUNTER",
]

# Kolom kunci lookup di data original
FAT_COL       = "fat_code"
NEAR_HPID_COL = "near_HOMEPASS_ID"
ID_FAT_COL    = "id fat"

# Field yang tidak di-overwrite dari HPDB (sudah ada di original atau by design kosong)
DO_NOT_OVERWRITE = {"HOMEPASS_ID"}
# ────────────────────────────────────────────────────────────────────────────


def check_db(db_path: str) -> None:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB tidak ditemukan: {db_path}\nJalankan dulu: python sync_hpdb.py")
    con = duckdb.connect(db_path, read_only=True)
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    if TABLE not in tables:
        con.close()
        raise ValueError(f"Tabel '{TABLE}' belum ada. Jalankan: python sync_hpdb.py")
    count = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    con.close()
    if count == 0:
        raise ValueError(f"Tabel '{TABLE}' kosong. Jalankan: python sync_hpdb.py")
    print(f"[INFO] DB OK — {count:,} rows di tabel '{TABLE}'")


def build_ref_table(con, key_col: str, keys: list, fill_cols: list) -> dict:
    """Buat dict referensi {key: {col: val}} dari HPDB."""
    if not keys:
        return {}

    cols_select = ", ".join(fill_cols)
    keys_df = pd.DataFrame({key_col: keys})
    con.register("_keys", keys_df)

    h_cols_select = ", ".join([f"h.{c}" for c in fill_cols])
    ref = con.execute(f"""
        SELECT k."{key_col}", {h_cols_select}
        FROM _keys k
        JOIN (
            SELECT {key_col}, {cols_select},
                   ROW_NUMBER() OVER (PARTITION BY {key_col} ORDER BY HOMEPASS_ID) AS rn
            FROM {TABLE}
            WHERE HOMEPASS_ID IS NOT NULL
              AND HOMEPASS_ID != ''
              AND {key_col} IS NOT NULL
              AND {key_col} != ''
        ) h ON k."{key_col}" = h.{key_col} AND h.rn = 1
    """).df()

    con.unregister("_keys")
    if ref.empty:
        return {}
    return ref.set_index(key_col).to_dict("index")


def is_empty(val) -> bool:
    """Cek apakah nilai kosong/null/dash."""
    if val is None:
        return True
    s = str(val).strip()
    return s in ("", "None", "nan", "NaT", "-", "--")


def process(input_path: str, output_path: str) -> None:
    print(f"[INFO] Membaca: {os.path.basename(input_path)}")

    # Baca raw tanpa header
    df_raw = pd.read_excel(input_path, engine="openpyxl", header=None)
    total_cols = len(df_raw.columns)
    print(f"[INFO] Total baris: {len(df_raw)} | Total kolom: {total_cols}")

    # ── Parse header ─────────────────────────────────────────────────────────
    hpdb_header = [str(v).strip() if pd.notna(v) else "" for v in df_raw.iloc[0]]
    orig_header = [str(v).strip() if pd.notna(v) else "" for v in df_raw.iloc[2]]

    # Data mulai baris 4 (index 3)
    df_data = df_raw.iloc[3:].reset_index(drop=True)
    df_data.columns = range(total_cols)

    print(f"[INFO] Data rows: {len(df_data):,}")
    print(f"[INFO] Kolom HPDB: {sum(1 for h in hpdb_header if h)}")
    print(f"[INFO] Kolom original: {sum(1 for h in orig_header if h)}")

    # Buat mapping nama kolom original → index kolom
    orig_col_idx = {name: i for i, name in enumerate(orig_header) if name}
    hpdb_col_idx = {name: i for i, name in enumerate(hpdb_header) if name}

    # Ambil kolom kunci dari data original
    def get_orig_col(col_name):
        idx = orig_col_idx.get(col_name)
        if idx is None:
            return pd.Series([None] * len(df_data))
        return df_data[idx].astype(str).str.strip().replace({"nan": None, "None": None, "-": None, "": None})

    fat_series      = get_orig_col(FAT_COL)
    near_hpid_series = get_orig_col(NEAR_HPID_COL)
    id_fat_series   = get_orig_col(ID_FAT_COL)

    # ── Lookup HPDB ──────────────────────────────────────────────────────────
    # Filter FILL_COLS yang ada di HPDB tabel
    con = duckdb.connect(DB_PATH, read_only=True)
    db_cols = [r[0] for r in con.execute(f"DESCRIBE {TABLE}").fetchall()]
    fill_cols = [c for c in HPDB_FILL_COLS if c in db_cols]

    filled_mask = [False] * len(df_data)
    hpdb_vals = [{} for _ in range(len(df_data))]

    # Pass 1: via fat_code
    print("[INFO] Pass 1: Lookup via fat_code...")
    fat_keys = fat_series.dropna().unique().tolist()
    fat_keys = [k for k in fat_keys if k]

    if fat_keys:
        ref_fat = build_ref_table(con, "FAT_CODE", fat_keys, fill_cols)
        for i in range(len(df_data)):
            fat = fat_series.iloc[i]
            if fat and fat in ref_fat:
                hpdb_vals[i] = ref_fat[fat]
                filled_mask[i] = True
        print(f"       {sum(filled_mask):,} rows matched")

    # Pass 2: via near_HOMEPASS_ID
    not_filled = [i for i, f in enumerate(filled_mask) if not f]
    if not_filled and near_hpid_series.notna().any():
        print(f"[INFO] Pass 2: Lookup via near_HOMEPASS_ID ({len(not_filled):,} rows)...")
        hpid_keys = near_hpid_series.iloc[not_filled].dropna().unique().tolist()
        hpid_keys = [k for k in hpid_keys if k]

        if hpid_keys:
            ref_hpid = build_ref_table(con, "HOMEPASS_ID", hpid_keys, fill_cols)
            newly = 0
            for i in not_filled:
                hpid = near_hpid_series.iloc[i]
                if hpid and hpid in ref_hpid:
                    hpdb_vals[i] = ref_hpid[hpid]
                    filled_mask[i] = True
                    newly += 1
            print(f"       {newly:,} rows matched")

    con.close()
    not_found = sum(1 for f in filled_mask if not f)
    print(f"[INFO] {not_found:,} rows tidak ditemukan → diisi '-'")

    # ── HOUSE_NUMBER per id fat ─────────────────────────────────────────────
    hn_counters = {}
    house_numbers = []
    for i in range(len(df_data)):
        id_fat = id_fat_series.iloc[i]
        if id_fat:
            hn_counters[id_fat] = hn_counters.get(id_fat, 0) + 1
            house_numbers.append(f"?-{hn_counters[id_fat]:03d}")
        else:
            house_numbers.append("-")
    print(f"[INFO] HOUSE_NUMBER assigned untuk {len(hn_counters)} id fat unik")

    # ── Tulis output dengan openpyxl (pertahankan struktur) ─────────────────
    print(f"\n[INFO] Menyimpan output ke: {os.path.basename(output_path)}")

    # Load workbook original untuk pertahankan format/styling
    wb = load_workbook(input_path)
    ws = wb.active

    # Isi data mulai baris 4 (1-indexed = row 4)
    for row_i in range(len(df_data)):
        excel_row = row_i + 4  # baris 4 = data pertama

        for col_name, col_excel_idx in hpdb_col_idx.items():
            excel_col = col_excel_idx + 1  # 1-indexed

            # Skip HOMEPASS_ID — selalu kosong
            if col_name in DO_NOT_OVERWRITE:
                continue

            # HOUSE_NUMBER khusus
            if col_name == "HOUSE_NUMBER":
                ws.cell(row=excel_row, column=excel_col, value=house_numbers[row_i])
                continue

            # Cek apakah sel sudah ada nilai dari original
            existing = ws.cell(row=excel_row, column=excel_col).value
            if not is_empty(existing):
                continue  # tidak overwrite yang sudah ada

            # Ambil dari HPDB lookup
            val = hpdb_vals[row_i].get(col_name)

            # Kosong → "-"
            if is_empty(val):
                val = "-"

            ws.cell(row=excel_row, column=excel_col, value=val)

    wb.save(output_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  SUMMARY")
    print("=" * 55)
    print(f"  Total rows diproses  : {len(df_data):,}")
    print(f"  Filled via fat_code  : {sum(filled_mask):,}")
    print(f"  Tidak ditemukan      : {not_found:,} → diisi '-'")
    print(f"\n  Output: {output_path}")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(description="Fill FORMAT NEW.xlsx dari HPDB")
    parser.add_argument("--input", required=True, help="Path file FORMAT NEW.xlsx")
    parser.add_argument("--output", help="Path output (default: input_filled.xlsx)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERROR] File tidak ditemukan: {args.input}")
        sys.exit(1)

    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(args.input)
        output_path = f"{base}_filled{ext}"

    start = datetime.now()
    print("=" * 55)
    print("  FILL FORMAT NEW — from HPDB")
    print(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    try:
        check_db(DB_PATH)
        process(args.input, output_path)
        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n[DONE] Selesai dalam {elapsed:.1f} detik")

    except (FileNotFoundError, ValueError) as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected: {e}")
        raise


if __name__ == "__main__":
    main()
