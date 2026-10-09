"""
convert_to_analyzed.py
----------------------
Konversi file original (format GIS/export) ke format Analyzed
yang siap diproses oleh fill_analyzed.py.

Transformasi yang dilakukan:
  1. Rename kolom lowercase → UPPERCASE sesuai format Analyzed
  2. Generate kolom ID NW dari kombinasi PROJECT_NAME + OLT_NAME + FDT_CODE + FAT_CODE
  3. Tambahkan semua kolom yang belum ada (kosong) sesuai urutan Analyzed
  4. Bersihkan nilai '-' (dash) → kosong

Cara pakai:
    python convert_to_analyzed.py --input "C:\\path\\Original.xlsx"
    python convert_to_analyzed.py --input "C:\\path\\Original.xlsx" --output "C:\\path\\Analyzed.xlsx"

Setelah convert, jalankan:
    python fill_analyzed.py --input "C:\\path\\Analyzed.xlsx"
"""

import os
import sys
import argparse
import pandas as pd
from datetime import datetime

# ── Urutan kolom format Analyzed (harus persis) ─────────────────────────────
ANALYZED_COLS = [
    'fid', 'Building_ID', 'Dist to FAT_road_dist_m', 'Cat Dist to FAT', 'ID NW',
    'ACQUISITION_CLASS', 'ACQUISITION_TIER', 'COMPETITION', 'BUILDING_TYPE',
    'OWNERSHIP', 'VENDOR_NAME', 'REGION', 'CITY', 'CITY_CODE', 'PROJECT_NAME',
    'PROJECT_ID', 'RESIDENCE_NAME', 'CLUSTER_NAME', 'CLUSTER_CODE', 'PREFIX_ADDRESS',
    'STREET_NAME', 'HOUSE_NUMBER', 'BLOCK', 'FLOOR', 'RT', 'RW', 'DISTRICT',
    'SUB_DISTRICT', 'ZIP_CODE', 'OLT_LOCATION', 'OLT_LOCATION_CODE', 'OLT_DEVICE_CODE',
    'OLT_NAME', 'FDT_CODE', 'FAT_CODE', 'FDT_LONGITUDE', 'FDT_LATITUDE',
    'FAT_LONGITUDE', 'FAT_LATITUDE', 'BUILDING_LATITUDE', 'BUILDING_LONGITUDE',
    'NETWORK_ID', 'FRAME', 'SLOT', 'PORT', 'HOMEPASS_ID', 'HOMEPASS_STATUS',
    'IP_DEVICE', 'VLAN_SERVICE', 'RFS_DATE', 'REMARKS', 'MOBILE_REGION',
    'MOBILE_CLUSTER', 'PARTNER_RFS_DATE', 'CITY_GROUP', 'BUILDING_NAME', 'COUNTER',
    'dist Dummy_to_road', 'near_HOMEPASS_ID', 'distance_naear_hp', 'Tech Isu',
    'G2A Bound Name', 'OB NAME', 'vendor_name_2', 'G2A_HOMEPASS_ID', 'In Out Bound',
    'Overlap HP Exis', 'Potensi HP Dummy', 'id fat',
]

# ── Mapping kolom original → Analyzed ───────────────────────────────────────
# Key = nama kolom di file original, Value = nama kolom di format Analyzed
COL_MAPPING = {
    # Rename lowercase → UPPERCASE
    'ownership':    'OWNERSHIP',
    'vendor_name':  'VENDOR_NAME',
    'city':         'CITY',
    'project_name': 'PROJECT_NAME',
    'cluster_name': 'CLUSTER_NAME',
    'olt_name':     'OLT_NAME',
    'fdt_code':     'FDT_CODE',
    'fat_code':     'FAT_CODE',
    # Koordinat
    'Dummy_lat':    'BUILDING_LATITUDE',
    'Dummy_long':   'BUILDING_LONGITUDE',
}

# Kolom yang langsung dipakai as-is (nama sudah sama)
PASSTHROUGH_COLS = [
    'fid', 'Building_ID', 'Dist to FAT_road_dist_m',
    'dist Dummy_to_road', 'near_HOMEPASS_ID', 'distance_naear_hp',
    'Tech Isu', 'G2A Bound Name', 'OB NAME', 'vendor_name_2',
    'G2A_HOMEPASS_ID', 'REGION', 'In Out Bound', 'Overlap HP Exis',
    'Potensi HP Dummy', 'id fat',
]

# Nilai yang dianggap kosong
EMPTY_VALUES = {'-', '--', 'n/a', 'N/A', 'null', 'NULL', 'none', 'NONE', ''}
# ────────────────────────────────────────────────────────────────────────────


def clean_value(val):
    """Bersihkan nilai dash / placeholder → None."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s in EMPTY_VALUES:
        return None
    return s


def generate_id_nw(row: pd.Series) -> str:
    """
    Generate ID NW dari kombinasi:
    PROJECT_NAME + '_' + OLT_NAME + '_' + FDT_CODE + '_' + FAT_CODE
    """
    parts = [
        str(row.get('PROJECT_NAME', '') or '').strip(),
        str(row.get('OLT_NAME', '') or '').strip(),
        str(row.get('FDT_CODE', '') or '').strip(),
        str(row.get('FAT_CODE', '') or '').strip(),
    ]
    # Skip bagian yang kosong atau '-'
    parts = [p for p in parts if p and p not in EMPTY_VALUES]
    return '_'.join(parts) if parts else ''


def convert(input_path: str, output_path: str) -> None:
    print(f"[INFO] Membaca: {os.path.basename(input_path)}")
    df_orig = pd.read_excel(input_path, engine='openpyxl', dtype=str)
    print(f"[INFO] Total rows: {len(df_orig):,} | Total cols: {len(df_orig.columns)}")

    # 1. Bersihkan nilai dash di seluruh dataframe
    df_orig = df_orig.map(clean_value)

    # 2. Rename kolom sesuai mapping
    df_orig = df_orig.rename(columns=COL_MAPPING)

    # 3. Buat dataframe kosong dengan kolom Analyzed
    df_out = pd.DataFrame(index=df_orig.index, columns=ANALYZED_COLS)

    # 4. Copy kolom yang ada
    for col in ANALYZED_COLS:
        if col in df_orig.columns:
            df_out[col] = df_orig[col]

    # 5. Generate ID NW
    print("[INFO] Generate ID NW...")
    df_out['ID NW'] = df_orig.apply(generate_id_nw, axis=1)

    # Verifikasi sample ID NW
    sample_idnw = df_out['ID NW'].dropna().head(2).tolist()
    for s in sample_idnw:
        print(f"       Sample: {s}")

    # 6. Kolom yang by-design kosong (diisi fill_analyzed.py nanti)
    empty_cols = [c for c in ANALYZED_COLS if df_out[c].isna().all()]
    print(f"[INFO] {len(empty_cols)} kolom kosong → akan diisi oleh fill_analyzed.py")

    # 7. Simpan
    df_out.to_excel(output_path, index=False, engine='openpyxl')

    # Summary
    print("\n" + "=" * 55)
    print("  SUMMARY KONVERSI")
    print("=" * 55)
    print(f"  Total rows     : {len(df_out):,}")
    print(f"  Total cols     : {len(df_out.columns)}")
    filled_cols = [c for c in ANALYZED_COLS if df_out[c].notna().any()]
    print(f"  Kolom terisi   : {len(filled_cols)}")
    print(f"  Kolom kosong   : {len(empty_cols)} (siap untuk fill_analyzed.py)")
    print(f"\n  Output: {output_path}")
    print("=" * 55)
    print("\n  LANGKAH BERIKUTNYA:")
    print(f"  python fill_analyzed.py --input \"{output_path}\"")


def main():
    parser = argparse.ArgumentParser(description="Konversi format original → format Analyzed")
    parser.add_argument("--input", required=True, help="Path file original .xlsx")
    parser.add_argument("--output", help="Path output (default: input_analyzed.xlsx)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERROR] File tidak ditemukan: {args.input}")
        sys.exit(1)

    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(args.input)
        output_path = f"{base}_analyzed{ext}"

    start = datetime.now()
    print("=" * 55)
    print("  CONVERT TO ANALYZED FORMAT")
    print(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    try:
        convert(args.input, output_path)
        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n[DONE] Selesai dalam {elapsed:.1f} detik")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        raise


if __name__ == "__main__":
    main()
