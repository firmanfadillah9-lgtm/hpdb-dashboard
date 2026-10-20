"""
pulihkan_hpdb.py - Pulihkan tabel 'hpdb' di addhp.duckdb dari data/hpdb.parquet
===============================================================================

Dipakai kalau tabel hpdb hilang (mis. sync_hpdb.py versi lama gagal di tengah setelah DROP TABLE).
data/hpdb.parquet = salinan persis tabel hpdb dari export_parquet.py terakhir.

    python pulihkan_hpdb.py           # hanya kalau tabel hpdb TIDAK ada
    python pulihkan_hpdb.py --paksa   # timpa tabel hpdb yang ada dengan isi parquet
"""
import os
import sys
import time
from datetime import datetime

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "addhp.duckdb")
PARQUET = os.path.join(HERE, "data", "hpdb.parquet")


def main():
    if not os.path.exists(PARQUET):
        print(f"[GAGAL] {PARQUET} tidak ada")
        return 1
    try:
        con = duckdb.connect(DB_PATH)
    except duckdb.IOException as e:
        print(f"[GAGAL] addhp.duckdb sedang dipakai program lain (tutup dashboard HPDB lokal / tunggu sync): {e}")
        return 1
    ada = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'hpdb'").fetchone()[0]
    if ada and "--paksa" not in sys.argv:
        n = con.execute("SELECT count(*) FROM hpdb").fetchone()[0]
        print(f"[OK] Tabel hpdb masih ada ({n:,} baris) - tidak perlu dipulihkan.")
        return 0
    tgl = datetime.fromtimestamp(os.path.getmtime(PARQUET))
    print(f"[INFO] Memulihkan tabel hpdb dari data/hpdb.parquet (export {tgl:%d %b %Y %H:%M})...")
    t = time.time()
    con.execute("BEGIN TRANSACTION")
    con.execute("DROP TABLE IF EXISTS hpdb")
    con.execute(f"CREATE TABLE hpdb AS SELECT * FROM read_parquet('{PARQUET}')")
    con.execute("COMMIT")
    for nama, kolom in (("idx_fat", "FAT_CODE"), ("idx_hpid", "HOMEPASS_ID"), ("idx_fdt", "FDT_CODE")):
        try:
            con.execute(f"CREATE INDEX IF NOT EXISTS {nama} ON hpdb ({kolom})")
        except Exception as e:
            print(f"       [WARN] index {nama}: {str(e)[:80]}")
    n = con.execute("SELECT count(*) FROM hpdb").fetchone()[0]
    con.close()
    print(f"[OK] Tabel hpdb pulih: {n:,} baris ({time.time() - t:.0f} detik). Data per {tgl:%d %b %Y}.")
    print("     Jalankan /update_hpdb untuk memperbarui ke data terbaru.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
