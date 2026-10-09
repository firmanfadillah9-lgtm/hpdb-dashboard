"""
export_coords.py
----------------
Export subset HPDB ke hpdb_coords.parquet untuk dipakai di dashboard cloud.
Kolom yang diekspor diperluas untuk mendukung fitur Bulk Check.
"""
import os
import duckdb

HPDB_FILE    = r"data\hpdb.duckdb"
OUTPUT_FILE  = "hpdb_coords.parquet"

print("Mengekspor koordinat HPID dari HPDB...")

con = duckdb.connect(HPDB_FILE, read_only=True)

# Cek total HPID
total = con.execute("SELECT COUNT(*) FROM hpdb").fetchone()[0]
total_aktif = con.execute(
    "SELECT COUNT(*) FROM hpdb WHERE HOMEPASS_STATUS IN ('ACTIVE','ASSIGNED')"
).fetchone()[0]
print(f"Total HPID di HPDB       : {total:,}")
print(f"Total ACTIVE/ASSIGNED    : {total_aktif:,}")

# Export semua HPID dengan kolom yang diperlukan
# Termasuk koordinat FAT, vendor, FAT code, alamat untuk fitur Bulk Check
con.execute(f"""
    COPY (
        SELECT
            HOMEPASS_ID,
            HOMEPASS_STATUS,
            BUILDING_LATITUDE,
            BUILDING_LONGITUDE,
            FAT_LATITUDE,
            FAT_LONGITUDE,
            FAT_CODE,
            VENDOR_NAME,
            NETWORK_ID,
            CLUSTER_NAME,
            FULL_ADDRESS,
            SOURCE_FILE
        FROM hpdb
        WHERE BUILDING_LATITUDE IS NOT NULL
          AND BUILDING_LATITUDE NOT IN ('-', '', 'None')
          AND BUILDING_LONGITUDE IS NOT NULL
          AND BUILDING_LONGITUDE NOT IN ('-', '', 'None')
    ) TO '{OUTPUT_FILE}' (FORMAT PARQUET, COMPRESSION ZSTD)
""")
con.close()

size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
print(f"\n✅ Selesai!")
print(f"   File    : {OUTPUT_FILE}")
print(f"   Ukuran  : {size_mb:.2f} MB")
