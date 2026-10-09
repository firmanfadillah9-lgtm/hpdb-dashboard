"""
cek_dummy_masuk.py — Cek apakah HPID yang SUCCESS di merge log
                     benar-benar sudah ada di HPDB aktual.

Butuh:
  - dummy_success_ids.csv  (daftar HPID SUCCESS, taruh di C:\hpdb\)
  - C:\hpdb\addhp.duckdb    (HPDB aktual)

Jalankan:
    python cek_dummy_masuk.py
"""
import os
import duckdb
import pandas as pd

DB_PATH  = r"C:\hpdb\addhp.duckdb"
IDS_CSV  = r"C:\hpdb\dummy_success_ids.csv"

if not os.path.exists(IDS_CSV):
    print(f"[ERROR] {IDS_CSV} tidak ada. Download dummy_success_ids.csv dari chat, taruh di C:\\hpdb\\")
    raise SystemExit(1)

ids_df = pd.read_csv(IDS_CSV, dtype=str)
ids_df["HOMEPASS_ID"] = ids_df["HOMEPASS_ID"].str.strip()
total_succ = ids_df["HOMEPASS_ID"].nunique()

con = duckdb.connect(DB_PATH, read_only=True)
con.register("succ_ids", ids_df)

print("=" * 60)
print("  CEK HPID SUCCESS vs HPDB AKTUAL")
print("=" * 60)
print(f"Total HPID SUCCESS (dari merge log): {total_succ:,}")

# Berapa yang benar-benar ada di HPDB
ada = con.execute("""
    SELECT COUNT(DISTINCT s.HOMEPASS_ID)
    FROM succ_ids s
    JOIN hpdb h ON UPPER(TRIM(h.HOMEPASS_ID)) = UPPER(TRIM(s.HOMEPASS_ID))
""").fetchone()[0]

tidak_ada = total_succ - ada
print(f"✅ Sudah ADA di HPDB   : {ada:,} ({ada/total_succ*100:.1f}%)")
print(f"❌ TIDAK ada di HPDB   : {tidak_ada:,} ({tidak_ada/total_succ*100:.1f}%)")

# Breakdown status HPID yang ada
print("\nStatus HPID yang sudah masuk HPDB:")
print(con.execute("""
    SELECT h.HOMEPASS_STATUS, COUNT(DISTINCT h.HOMEPASS_ID) AS jml
    FROM succ_ids s
    JOIN hpdb h ON UPPER(TRIM(h.HOMEPASS_ID)) = UPPER(TRIM(s.HOMEPASS_ID))
    GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string())

# Breakdown vendor
print("\nVendor HPID yang sudah masuk HPDB:")
print(con.execute("""
    SELECT h.VENDOR_NAME, COUNT(DISTINCT h.HOMEPASS_ID) AS jml
    FROM succ_ids s
    JOIN hpdb h ON UPPER(TRIM(h.HOMEPASS_ID)) = UPPER(TRIM(s.HOMEPASS_ID))
    GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string())

# Sample yang SUCCESS tapi TIDAK ada di HPDB (kalau ada)
if tidak_ada > 0:
    print(f"\nContoh 20 HPID SUCCESS tapi belum ada di HPDB:")
    missing = con.execute("""
        SELECT s.HOMEPASS_ID
        FROM succ_ids s
        LEFT JOIN hpdb h ON UPPER(TRIM(h.HOMEPASS_ID)) = UPPER(TRIM(s.HOMEPASS_ID))
        WHERE h.HOMEPASS_ID IS NULL
        LIMIT 20
    """).fetchdf()
    print(missing.to_string())
    # Simpan daftar lengkap yang belum masuk
    all_missing = con.execute("""
        SELECT s.HOMEPASS_ID
        FROM succ_ids s
        LEFT JOIN hpdb h ON UPPER(TRIM(h.HOMEPASS_ID)) = UPPER(TRIM(s.HOMEPASS_ID))
        WHERE h.HOMEPASS_ID IS NULL
    """).fetchdf()
    all_missing.to_csv(r"C:\hpdb\dummy_success_belum_masuk.csv", index=False)
    print(f"\n[INFO] Daftar lengkap {len(all_missing):,} HPID belum masuk disimpan ke:")
    print(r"       C:\hpdb\dummy_success_belum_masuk.csv")

con.close()
print("\n[DONE]")
