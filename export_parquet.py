"""
export_parquet.py
-------------------
Export tabel 'hpdb' dari DuckDB ke Parquet, untuk cek ukuran hasil kompresi
dan sebagai kandidat file yang akan di-upload ke GitHub Release.

Cara pakai:
    python export_parquet.py
"""
import os
import time
import duckdb

# PENTING: sumber yang benar adalah addhp.duckdb di root folder (hasil sync_hpdb.py).
# data/hpdb.duckdb adalah sisa lama (Juni) dan kurang ~1,8 juta baris.
DUCKDB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addhp.duckdb")
PARQUET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hpdb.parquet")

con = duckdb.connect(DUCKDB_PATH, read_only=True)

print("Mengekspor tabel 'hpdb' ke Parquet (compression=zstd)...")
start = time.time()
con.execute(f"""
    COPY hpdb TO '{PARQUET_PATH}'
    (FORMAT PARQUET, COMPRESSION ZSTD)
""")
elapsed = time.time() - start

duckdb_size = os.path.getsize(DUCKDB_PATH) / (1024*1024)
parquet_size = os.path.getsize(PARQUET_PATH) / (1024*1024)

print(f"\n✅ Selesai dalam {elapsed:.1f}s")
print(f"   DuckDB  : {duckdb_size:.1f} MB")
print(f"   Parquet : {parquet_size:.1f} MB")
print(f"   Rasio   : {parquet_size/duckdb_size*100:.1f}%")

con.close()
