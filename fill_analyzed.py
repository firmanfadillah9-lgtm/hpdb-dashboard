"""
fill_analyzed.py
----------------
Mengisi field kosong pada file Analyzed_*.xlsx menggunakan data HPDB
yang sudah tersimpan di addhp.duckdb.

Strategi lookup (bulk JOIN — jauh lebih cepat dari row-by-row):
  1. via FAT_CODE  → JOIN ke HPDB, ambil 1 referensi per FAT unik
  2. via near_HOMEPASS_ID → fallback untuk row yang FAT-nya tidak ditemukan

HOUSE_NUMBER diisi otomatis format "?-1", "?-2", dst — reset per ID NW.

Cara pakai:
    python fill_analyzed.py --input "C:\\path\\Analyzed_1.xlsx"
    python fill_analyzed.py --input "C:\\path\\Analyzed_1.xlsx" --output "C:\\path\\out.xlsx"
"""

import os
import sys
import argparse
import duckdb
import pandas as pd
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────────
DB_PATH = r"C:\hpdb\addhp.duckdb"
TABLE   = "hpdb"

# Field yang diisi dari HPDB (HOUSE_NUMBER dihandle terpisah)
FIELDS_TO_FILL = [
    "ACQUISITION_CLASS", "ACQUISITION_TIER", "COMPETITION", "BUILDING_TYPE",
    "CITY_CODE", "PROJECT_ID", "RESIDENCE_NAME", "CLUSTER_CODE",
    "PREFIX_ADDRESS", "STREET_NAME", "BLOCK", "FLOOR",
    "RT", "RW", "DISTRICT", "SUB_DISTRICT", "ZIP_CODE",
    "OLT_LOCATION", "OLT_LOCATION_CODE", "OLT_DEVICE_CODE",
    "FDT_LONGITUDE", "FDT_LATITUDE", "FAT_LONGITUDE", "FAT_LATITUDE",
    "NETWORK_ID", "FRAME", "SLOT", "PORT",
    "IP_DEVICE", "VLAN_SERVICE",
    "MOBILE_REGION", "MOBILE_CLUSTER",
    "CITY_GROUP", "BUILDING_NAME", "COUNTER",
    "RFS_DATE", "PARTNER_RFS_DATE", "REMARKS",
]

# Field yang sudah ada di Analyzed — tidak di-overwrite
DO_NOT_OVERWRITE = [
    "HOMEPASS_ID", "HOMEPASS_STATUS",
    "PROJECT_NAME", "CLUSTER_NAME", "OLT_NAME",
    "FDT_CODE", "FAT_CODE",
    "VENDOR_NAME", "REGION", "CITY", "OWNERSHIP",
    "BUILDING_LATITUDE", "BUILDING_LONGITUDE",
]
# ────────────────────────────────────────────────────────────────────────────


def check_db(db_path: str) -> None:
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"DB tidak ditemukan: {db_path}\n"
            f"Jalankan dulu: python sync_hpdb.py"
        )
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


def build_ref_table(con: duckdb.DuckDBPyConnection, key_col: str, keys: list[str]) -> pd.DataFrame:
    """
    Buat tabel referensi: 1 row per unique key_col dari HPDB.
    Menggunakan DISTINCT ON / ROW_NUMBER untuk ambil 1 referensi per key.
    """
    if not keys:
        return pd.DataFrame()

    cols_select = ", ".join([f'h."{f}"' for f in FIELDS_TO_FILL])

    # Register keys sebagai tabel temp
    keys_df = pd.DataFrame({key_col: keys})
    con.register("_keys", keys_df)

    ref = con.execute(f"""
        SELECT k."{key_col}", {cols_select}
        FROM _keys k
        JOIN (
            SELECT {key_col}, {", ".join(FIELDS_TO_FILL)},
                   ROW_NUMBER() OVER (PARTITION BY {key_col} ORDER BY HOMEPASS_ID) AS rn
            FROM {TABLE}
            WHERE HOMEPASS_ID IS NOT NULL
              AND HOMEPASS_ID != ''
              AND {key_col} IS NOT NULL
              AND {key_col} != ''
        ) h ON k."{key_col}" = h.{key_col} AND h.rn = 1
    """).df()

    con.unregister("_keys")
    return ref


def merge_fill(df: pd.DataFrame, ref: pd.DataFrame, join_key: str,
               filled_mask: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """
    Merge df dengan ref berdasarkan join_key.
    Hanya mengisi field yang kosong DAN belum diisi sebelumnya (filled_mask=False).
    Returns: (df yang sudah diupdate, mask baris yang berhasil diisi)
    """
    # Hanya proses baris yang belum filled
    to_fill = df[~filled_mask].copy()
    if to_fill.empty or ref.empty:
        return df, filled_mask

    # Rename kolom ref agar tidak clash
    ref_renamed = ref.rename(columns={f: f"_ref_{f}" for f in FIELDS_TO_FILL})

    merged = to_fill.merge(ref_renamed, on=join_key, how="left")
    matched = merged[f"_ref_{FIELDS_TO_FILL[0]}"].notna()

    for field in FIELDS_TO_FILL:
        if field not in df.columns:
            continue
        ref_col = f"_ref_{field}"
        if ref_col not in merged.columns:
            continue

        # Isi hanya jika: (1) kolom kosong di original, (2) ada nilai di ref
        orig_empty = merged[field].isna() | (merged[field].astype(str).str.strip().isin(["", "None", "nan"]))
        ref_has_val = merged[ref_col].notna() & (~merged[ref_col].astype(str).str.strip().isin(["", "None", "nan"]))

        should_fill = orig_empty & ref_has_val
        merged.loc[should_fill, field] = merged.loc[should_fill, ref_col]

    # Drop ref columns
    ref_cols = [c for c in merged.columns if c.startswith("_ref_")]
    merged = merged.drop(columns=ref_cols)

    # Update baris yang matched kembali ke df utama
    new_filled = filled_mask.copy()
    matched_idx = to_fill.index[matched.values]
    df.loc[matched_idx] = merged.loc[matched.values].values
    new_filled.loc[matched_idx] = True

    return df, new_filled


def assign_house_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Isi HOUSE_NUMBER dengan format '?-N' — reset counter per ID NW.
    Hanya mengisi row yang HOUSE_NUMBER-nya masih kosong.
    """
    if "HOUSE_NUMBER" not in df.columns:
        return df

    # Force ke object dtype agar bisa menampung string "?-N"
    df["HOUSE_NUMBER"] = df["HOUSE_NUMBER"].astype(object)

    # Tentukan baris yang perlu diisi (kosong / NaN / None)
    empty_mask = df["HOUSE_NUMBER"].isna() | (
        df["HOUSE_NUMBER"].astype(str).str.strip().isin(["", "None", "nan", "<NA>"])
    )

    if not empty_mask.any():
        print("[INFO] HOUSE_NUMBER sudah terisi semua, tidak ada yang perlu di-assign.")
        return df

    # Gunakan ID NW sebagai grup, fallback ke FAT_CODE
    group_key = df["ID NW"].fillna("").str.strip()
    if "FAT_CODE" in df.columns:
        group_key = group_key.where(group_key != "", df["FAT_CODE"].fillna("").str.strip())

    # Assign nomor urut per grup hanya untuk baris kosong
    counters = {}
    idnw_summary = {}

    for idx in df[empty_mask].index:
        key = group_key.at[idx]
        if not key:
            continue
        counters[key] = counters.get(key, 0) + 1
        df.at[idx, "HOUSE_NUMBER"] = f"?-{counters[key]:03d}"
        idnw_summary[key] = counters[key]

    # Log summary (ringkas — max 20 baris)
    print(f"[INFO] HOUSE_NUMBER assigned untuk {len(idnw_summary)} ID NW unik:")
    items = sorted(idnw_summary.items(), key=lambda x: -x[1])[:20]
    for idnw, count in items:
        label = idnw.split("_")[-1] if "_" in idnw else idnw
        print(f"       ...{label} → ?-1 s/d ?-{count}")
    if len(idnw_summary) > 20:
        print(f"       ... dan {len(idnw_summary)-20} ID NW lainnya")

    return df


def process_analyzed(input_path: str, output_path: str) -> None:
    """Main process menggunakan bulk JOIN — jauh lebih cepat dari row-by-row."""

    # 1. Baca input
    print(f"[INFO] Membaca: {os.path.basename(input_path)}")
    df = pd.read_excel(input_path, engine="openpyxl", dtype=str)
    df = df.where(df.notna(), other=None)
    total = len(df)
    print(f"[INFO] Total rows: {total:,} | Total cols: {len(df.columns)}")

    con = duckdb.connect(DB_PATH, read_only=True)

    # Track baris mana yang sudah berhasil diisi
    filled_mask = pd.Series(False, index=df.index)

    # ── PASS 1: Lookup via FAT_CODE ─────────────────────────────────────────
    print("[INFO] Pass 1: Lookup via FAT_CODE...")
    fat_keys = df["FAT_CODE"].dropna().str.strip().unique().tolist()
    fat_keys = [k for k in fat_keys if k]
    print(f"       {len(fat_keys):,} FAT unik ditemukan")

    if fat_keys:
        ref_fat = build_ref_table(con, "FAT_CODE", fat_keys)
        print(f"       {len(ref_fat):,} FAT matched di HPDB")
        df, filled_mask = merge_fill(df, ref_fat, "FAT_CODE", filled_mask)
        print(f"       {filled_mask.sum():,} rows berhasil diisi via FAT_CODE")

    # ── PASS 2: Fallback via near_HOMEPASS_ID ───────────────────────────────
    still_empty = ~filled_mask
    if still_empty.any() and "near_HOMEPASS_ID" in df.columns:
        print(f"[INFO] Pass 2: Lookup via near_HOMEPASS_ID ({still_empty.sum():,} rows belum terisi)...")
        hpid_keys = df.loc[still_empty, "near_HOMEPASS_ID"].dropna().str.strip().unique().tolist()
        hpid_keys = [k for k in hpid_keys if k]
        print(f"       {len(hpid_keys):,} HOMEPASS_ID unik")

        if hpid_keys:
            ref_hpid = build_ref_table(con, "HOMEPASS_ID", hpid_keys)
            # Rename join key agar bisa merge
            ref_hpid = ref_hpid.rename(columns={"HOMEPASS_ID": "near_HOMEPASS_ID"})
            df, filled_mask_hpid = merge_fill(df, ref_hpid, "near_HOMEPASS_ID", ~filled_mask)
            newly_filled = filled_mask_hpid & ~filled_mask
            filled_mask = filled_mask | newly_filled
            print(f"       {newly_filled.sum():,} rows berhasil diisi via near_HOMEPASS_ID")

    con.close()

    not_found = (~filled_mask).sum()
    print(f"[INFO] {not_found:,} rows tidak ditemukan di HPDB")

    # ── PASS 3: Assign HOUSE_NUMBER ─────────────────────────────────────────
    print()
    df = assign_house_numbers(df)

    # ── Simpan output ────────────────────────────────────────────────────────
    print(f"\n[INFO] Menyimpan output...")
    df.to_excel(output_path, index=False, engine="openpyxl")

    # Summary
    print("\n" + "=" * 55)
    print("  SUMMARY")
    print("=" * 55)
    print(f"  Total rows diproses  : {total:,}")
    print(f"  Filled via FAT_CODE  : {filled_mask.sum() - (filled_mask.sum() - filled_mask.sum()):,}")
    print(f"  Tidak ditemukan      : {not_found:,}")
    print(f"\n  Output: {output_path}")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(description="Fill Analyzed xlsx dari HPDB (addhp.duckdb)")
    parser.add_argument("--input", required=True, help="Path file Analyzed_*.xlsx input")
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
    print("  FILL ANALYZED — from HPDB (optimized)")
    print(f"  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    try:
        check_db(DB_PATH)
        process_analyzed(args.input, output_path)
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
